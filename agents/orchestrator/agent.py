"""
Orchestrator Agent — SihaLink (Google ADK)
Central coordinator that routes work between all specialized sub-agents.

ADK pattern:
  - root_agent: LlmAgent with function tools + sub-agent delegation
  - Model: gemini-3.5-flash (run_async); gemini-live-2.5-flash-preview (run_live voice sessions)
  - RunConfig with SpeechConfig for TTS feedback to CHVs
  - State machine lifecycle: IDLE → LISTENING → EXTRACTING → GEOCODING
    → STORING → [DECISION_GATE] → NOTIFYING → COMPLETE
  - Human-in-the-loop gate via asyncio.Future
  - Offline queue with automatic sync on reconnect

Also exposes a FastAPI app for the Agent Runtime HTTP interface.
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("SihaLink-Orchestrator")

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents.run_config import RunConfig
from google.adk.agents.live_request_queue import LiveRequestQueue, LiveRequest
from google.genai import types as genai_types

load_dotenv()

from .state_machine import Orchestrator, EncounterState
from agents.intake.agent import IntakeAgent, build_run_config as intake_run_config
from agents.geo.maps_client import GeoAgent
from agents.data.mcp_client import DataAgent
from agents.surveillance.agent import SurveillanceAgent

# ── Dynatrace / OpenTelemetry bootstrap ──────────────────────────────────────
# Must run before agent/db instantiation so instrumentation patches apply first.
from .telemetry import init_telemetry, get_tracer

_telemetry_active = init_telemetry()

if _telemetry_active:
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.pymongo import PymongoInstrumentor

        HTTPXClientInstrumentor().instrument()  # traces all httpx calls (Gemini, Maps, Telegram)
        PymongoInstrumentor().instrument()  # traces every MongoDB query
        logger.info("[Telemetry] HTTPx + PyMongo auto-instrumentation active")
    except ImportError:
        logger.debug("[Telemetry] Auto-instrumentation packages not installed")

_tracer = get_tracer("sihalink.orchestrator")

# ---------------------------------------------------------------------------
# Notify Agent HTTP shim
# ---------------------------------------------------------------------------

NOTIFY_BASE = os.getenv("NOTIFY_AGENT_URL", "http://localhost:3001")


class NotifyAgentClient:
    """HTTP shim for the Node.js Notify Agent (grammY/Fastify bot).

    Uses a circuit-breaker pattern: after the first connection failure the
    error is logged at WARNING level exactly once, then demoted to DEBUG
    until a successful call resets the breaker.
    """

    def __init__(self) -> None:
        self._notify_down = False  # True after first failure — suppresses repeat warnings

    def _log_unavailable(self, exc: Exception, context: str) -> None:
        if not self._notify_down:
            logger.warning("Notify Agent unavailable (%s) — %s", exc, context)
            self._notify_down = True
        else:
            logger.debug("Notify Agent still unavailable: %s", exc)

    async def dispatch_referral(self, enriched_json: Dict[str, Any]) -> Dict[str, Any]:
        extracted = enriched_json.get("extracted", {})
        facilities = enriched_json.get("nearest_facilities", [{}])
        top_facility = facilities[0] if facilities else {}
        payload = {
            "referral": {
                "encounter_id": enriched_json.get("encounter_id", ""),
                "referral_id": enriched_json.get("referral_id", ""),
                "syndrome": extracted.get("syndrome", "unknown"),
                "triage_color": extracted.get("triage_color", "YELLOW"),
                "eta_minutes": top_facility.get("eta_minutes", 0),
                "facility_telegram_id": os.getenv("FACILITY_TELEGRAM_ID", "0"),
                "nearest_facility": top_facility.get("name", ""),
                "age": extracted.get("age"),
                "sex": extracted.get("sex"),
                "chief_complaint": extracted.get("chief_complaint", ""),
            }
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{NOTIFY_BASE}/notify/referral", json=payload)
                resp.raise_for_status()
                self._notify_down = False  # reset breaker on success
                return resp.json()
        except Exception as exc:
            self._log_unavailable(exc, "referral logged only")
            return {"delivered": False, "note": str(exc)}

    async def dispatch_outbreak_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import json

            payload_str = json.dumps({"alert": alert}, default=str)
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{NOTIFY_BASE}/notify/outbreak_alert",
                    content=payload_str,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                self._notify_down = False  # reset breaker on success
                return resp.json()
        except Exception as exc:
            self._log_unavailable(exc, "alert logged only")
            return {"delivered": False, "note": str(exc)}


# ---------------------------------------------------------------------------
# Agent instances
# ---------------------------------------------------------------------------

intake_agent = IntakeAgent()
geo_agent = GeoAgent()
data_agent = DataAgent()
notify_agent = NotifyAgentClient()
surveillance_agent = SurveillanceAgent()
orchestrator = Orchestrator(intake_agent, geo_agent, data_agent, notify_agent)

# ---------------------------------------------------------------------------
# Swarm controller — wires all agents into autonomous coordination
# ---------------------------------------------------------------------------
from agents.swarm import SwarmController

from agents.contact_tracing.agent import ContactTracingAgent
from agents.workflows import (
    agent_registry,
    get_workflow_state,
    get_agent_memory,
    pipeline_reflect,
    ReActStep,
)

swarm = SwarmController.get()
contact_tracing_agent = ContactTracingAgent()
swarm.initialise(
    intake=intake_agent,
    geo=geo_agent,
    data=data_agent,
    notify=notify_agent,
    surveillance=surveillance_agent,
    orchestrator=orchestrator,
    contact_tracing=contact_tracing_agent,
)

# ── Register all agents in the AgentRegistry ─────────────────────────────────
agent_registry.register("intake", intake_agent)
agent_registry.register("geo", geo_agent)
agent_registry.register("data", data_agent)
agent_registry.register("notify", notify_agent)
agent_registry.register("surveillance", surveillance_agent)
agent_registry.register("contact_tracing", contact_tracing_agent)
agent_registry.register("orchestrator", orchestrator)

# ── Workflow state + memory bound to the data agent's DB ─────────────────────
_workflow_state = get_workflow_state(data_agent.db if data_agent.connected else None)
_agent_memory = get_agent_memory(data_agent.db if data_agent.connected else None)

# ---------------------------------------------------------------------------
# Orchestrator tool functions (ADK FunctionTools)
# ---------------------------------------------------------------------------


def route_to_intake(audio_base64: str, session_id: str) -> Dict[str, Any]:
    """
    Send a CHV audio recording to the Intake Agent for multilingual clinical extraction.
    Supports Dholuo, Swahili, Kikuyu, Somali, and English (including code-switching).

    Args:
        audio_base64: Base64-encoded WAV or WebM audio from the CHV device.
        session_id: Unique encounter session identifier.

    Returns:
        dict with session_id and extracted clinical JSON.
    """
    import asyncio
    import concurrent.futures

    try:
        # Try to use existing event loop if available
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Event loop already running — use thread executor
                def _run_async():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return new_loop.run_until_complete(
                            intake_agent.process_audio(audio_base64)
                        )
                    finally:
                        new_loop.close()

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(_run_async)
                    extracted = future.result(timeout=30)
            else:
                # Event loop exists but not running
                extracted = loop.run_until_complete(
                    intake_agent.process_audio(audio_base64)
                )
        except RuntimeError:
            # No event loop in this thread
            extracted = asyncio.run(intake_agent.process_audio(audio_base64))

        return {"session_id": session_id, "extracted": extracted}
    except Exception as exc:
        logger.error("route_to_intake failed: %s", exc, exc_info=True)
        return {
            "session_id": session_id,
            "extracted": {
                "error": "intake_processing_failed",
                "details": str(exc),
                "syndrome": "unknown",
                "triage_color": "YELLOW",
            },
        }


def route_to_geo(encounter_json: dict, latitude: float, longitude: float) -> dict:
    """
    Send an extracted encounter with GPS coordinates to the Geo Agent for location enrichment.
    Adds admin hierarchy (village/ward/sub-county/county) and nearest facilities with ETAs.

    Args:
        encounter_json: Clinical JSON from the Intake Agent.
        latitude: GPS latitude from the CHV device.
        longitude: GPS longitude from the CHV device.

    Returns:
        dict with encounter_id and enriched_encounter.
    """
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    geo_agent.enrich_location(
                        encounter_json, {"lat": latitude, "lng": longitude}
                    ),
                )
                enriched = future.result(timeout=15)
        else:
            enriched = loop.run_until_complete(
                geo_agent.enrich_location(
                    encounter_json, {"lat": latitude, "lng": longitude}
                )
            )
        return {
            "encounter_id": encounter_json.get("session_id"),
            "enriched_encounter": enriched,
        }
    except Exception as exc:
        return {"error": str(exc)}


def route_to_data(enriched_encounter: dict) -> dict:
    """
    Send a geo-enriched encounter to the Data Agent for MongoDB storage.
    Automatically generates a vector embedding and creates indexes if needed.

    Args:
        enriched_encounter: The fully enriched encounter from the Geo Agent.

    Returns:
        dict with inserted_id.
    """
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run, data_agent.insert_encounter(enriched_encounter)
                )
                inserted_id = future.result(timeout=15)
        else:
            inserted_id = loop.run_until_complete(
                data_agent.insert_encounter(enriched_encounter)
            )
        return {"inserted_id": inserted_id}
    except Exception as exc:
        return {"error": str(exc)}


def request_human_decision(
    session_id: str, decision_type: str, summary: str, timeout_seconds: int = 60
) -> dict:
    """
    Pause the encounter lifecycle and wait for CHV confirmation before sending a referral.
    This is the human-in-the-loop gate for RED and YELLOW triage cases.

    Args:
        session_id: The encounter session to pause.
        decision_type: 'referral' or 'alert'.
        summary: Human-readable summary of what the CHV is confirming.
        timeout_seconds: How long to wait before auto-escalating (default 60s).

    Returns:
        dict with confirmed (bool) and session_id.
    """
    # Sets the session state to DECISION_GATE — the frontend polls this
    session = orchestrator.sessions.get(session_id, {})
    session["state"] = EncounterState.DECISION_GATE
    session["gate_data"] = {
        "decision_type": decision_type,
        "summary": summary,
        "timeout_seconds": timeout_seconds,
    }
    orchestrator.sessions[session_id] = session
    return {
        "session_id": session_id,
        "state": "DECISION_GATE",
        "message": f"Waiting for CHV confirmation: {summary}",
    }


def route_to_notify(notification_type: str, payload: dict) -> dict:
    """
    Send an alert or referral to the Notify Agent for Telegram delivery.

    Args:
        notification_type: 'referral', 'outbreak_alert', or 'broadcast'.
        payload: The notification payload (referral or alert dict).

    Returns:
        dict with status and delivery result.
    """
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                if notification_type == "referral":
                    future = pool.submit(
                        asyncio.run, notify_agent.dispatch_referral(payload)
                    )
                elif notification_type == "outbreak_alert":
                    future = pool.submit(
                        asyncio.run, notify_agent.dispatch_outbreak_alert(payload)
                    )
                else:
                    return {
                        "delivered": False,
                        "note": f"Unknown type: {notification_type}",
                    }
                result = future.result(timeout=15)
        else:
            if notification_type == "referral":
                result = loop.run_until_complete(
                    notify_agent.dispatch_referral(payload)
                )
            else:
                result = loop.run_until_complete(
                    notify_agent.dispatch_outbreak_alert(payload)
                )
        return {"status": "notified", "result": result}
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


def trigger_surveillance(
    county: str,
    lat: float = 0.0,
    lng: float = 0.0,
    immediate: bool = False,
    hours: int = 6,
) -> dict:
    """
    Trigger outbreak detection for a county. If immediate=True, runs synchronously.
    Otherwise schedules as a background task.

    Args:
        county: Kenya county name.
        lat: County center latitude.
        lng: County center longitude.
        immediate: If True, run now and return results. If False, schedule.
        hours: Time window for case counting (default 6).

    Returns:
        dict with status, county, alerts_detected, and alerts list.
    """
    from agents.surveillance.agent import run_outbreak_detection

    if immediate and county:
        return run_outbreak_detection(county, lat, lng, hours)
    return {"status": "scheduled", "county": county}


def queue_offline_encounter(encounter_json: dict) -> dict:
    """
    Store an encounter locally when the CHV device is offline.
    The encounter will be synced automatically when connectivity returns.

    Args:
        encounter_json: The encounter to queue (audio_base64 + GPS + session_id).

    Returns:
        dict with status and queue_size.
    """
    queue_size = orchestrator.queue_offline_encounter(encounter_json)
    return {"status": "queued", "queue_size": queue_size}


def process_offline_queue() -> dict:
    """
    Pull all unsynced encounters from the offline queue and route them through
    the full pipeline (intake → geo → data → notify).
    Called automatically when the device comes back online.

    Returns:
        dict with total, processed, and errors counts.
    """
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, orchestrator.process_offline_queue())
                return future.result(timeout=120)
        else:
            return loop.run_until_complete(orchestrator.process_offline_queue())
    except Exception as exc:
        return {"total": 0, "processed": 0, "errors": 1, "error": str(exc)}


# ---------------------------------------------------------------------------
# Follow-up bridge tools — delegate to Data Agent
# ---------------------------------------------------------------------------


def get_chw_follow_ups(chw_id: str, overdue_only: bool = False) -> dict:
    """
    Retrieve pending follow-up tasks for a specific CHW.
    Called when a CHW sends /followup to the Telegram bot.

    Args:
        chw_id:       The CHW-XXXXXX identifier.
        overdue_only: If True, return only tasks past their due date.

    Returns:
        dict with follow_ups (list) and count (int).
    """
    from ..data.agent import get_pending_follow_ups

    return get_pending_follow_ups(chw_id=chw_id, overdue_only=overdue_only)


def complete_patient_follow_up(
    follow_up_id: str, outcome: str, notes: str = "", chw_id: str = "unknown"
) -> dict:
    """
    Mark a patient follow-up as completed with clinical outcome.
    Called after a CHV visits the patient and reports back via Telegram.

    Args:
        follow_up_id: The FU-XXXXXXXX string.
        outcome:      'improved' | 'stable' | 'deteriorated' | 'referred' | 'deceased'
        notes:        CHV's voice-transcribed or typed notes.
        chw_id:       CHW who completed the visit.

    Returns:
        dict with matched_count and modified_count.
    """
    from ..data.agent import complete_follow_up

    return complete_follow_up(follow_up_id, outcome, notes, chw_id)


def get_county_follow_up_summary(county: str) -> dict:
    """
    Get follow-up completion statistics for a county.
    Used by supervisors and the /status Telegram command.

    Args:
        county: Kenya county name.

    Returns:
        dict with pending, completed, and overdue counts.
    """
    from ..data.agent import get_follow_up_summary

    return get_follow_up_summary(county)


# ---------------------------------------------------------------------------
# Protocol bridge tools — delegate to Surveillance + Data Agents
# ---------------------------------------------------------------------------


def get_response_protocol(syndrome: str, county: Optional[str] = None) -> dict:
    """
    Retrieve the active WHO/MoH response protocol for a syndrome.
    Called when a CHV or district officer sends /protocol to the Telegram bot.
    Returns immediate actions, CHW field tasks, and follow-up schedule.

    Args:
        syndrome: WHO IDSR syndrome category (e.g., 'cholera', 'measles').
        county:   Optional county for localised protocol.

    Returns:
        Full protocol dict with immediate_actions, chw_actions, follow_up_days.
    """
    from ..data.agent import get_protocol

    return get_protocol(syndrome, county)


def search_response_protocols(query: str) -> dict:
    """
    Full-text search across all stored protocols using Atlas Search.
    Enables CHWs to find protocols by keyword (e.g., 'ORS', 'dehydration').

    Args:
        query: Free-text search string.

    Returns:
        dict with protocols (list) and count (int).
    """
    from ..data.agent import search_protocols

    return search_protocols(query)


# ---------------------------------------------------------------------------
# CHW outreach bridge tools — delegate to Surveillance Agent
# ---------------------------------------------------------------------------


def check_chw_outreach_gaps(county: str, days: int = 7) -> dict:
    """
    Identify wards with low or zero CHW encounter submissions.
    Used by supervisors to target outreach support and training.

    Args:
        county: Kenya county name.
        days:   Time window for activity check (default 7 days).

    Returns:
        dict with gap_wards (list), total_gap_wards, recommended_actions.
    """
    from agents.surveillance.agent import detect_chw_outreach_gaps

    return detect_chw_outreach_gaps(county, days)


def run_silent_pandemic_scan(county: str, weeks: int = 4) -> dict:
    """
    Scan for silent pandemic signals — syndromes with a persistent upward
    trend over multiple weeks that never trigger a single-week spike.
    These are the most dangerous: they grow unnoticed until they explode.

    Args:
        county: Kenya county name.
        weeks:  Number of weeks to analyse (default 4).

    Returns:
        dict with silent_signals (list), signals_detected (int).
    """
    from agents.surveillance.agent import detect_silent_pandemic

    return detect_silent_pandemic(county, weeks)


# ---------------------------------------------------------------------------
# ADK root_agent — the entry point for `adk run` and Agent Runtime
# ---------------------------------------------------------------------------

root_agent = LlmAgent(
    name="orchestrator_agent",
    model="gemini-3.5-flash",  # Vertex AI — confirmed in Google Cloud ADK quickstart
    description=(
        "SihaLink Orchestrator — agentic coordinator for community health disease "
        "surveillance in Kenya. Implements ReAct (Reason→Act→Observe) loops, "
        "self-reflection after each pipeline stage, and direct agent delegation. "
        "Manages the full encounter lifecycle, outbreak detection, protocol "
        "formulation, CHW outreach, and patient follow-up."
    ),
    instruction="""You are the SihaLink Orchestrator — the central intelligence of a
multi-agent disease surveillance system serving Community Health Volunteers (CHVs) in Kenya.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AGENTIC WORKFLOW PRINCIPLES (IBM Framework)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You operate using four core agentic patterns:

1. ReAct (Reason → Act → Observe → Reflect)
   Before EVERY tool call, state:
     REASON: Why am I calling this tool? What do I expect?
     ACT:    Call the tool with specific arguments.
     OBSERVE: What did the tool return? Was it complete and correct?
     REFLECT: Should I proceed, retry, or take a different path?

2. Chain-of-Thought Planning
   For multi-step tasks, explicitly lay out your plan first:
     "To process this encounter I need to: (1) extract clinical data,
      (2) enrich with location, (3) store with embeddings,
      (4) check triage color, (5) initiate contact trace if RED,
      (6) request human gate if RED/YELLOW, (7) dispatch Telegram notification."
   Then execute step-by-step, checking each result before proceeding.

3. Self-Reflection After Each Stage
   After completing a pipeline stage, evaluate:
     - Is the data complete? (syndrome extracted? location enriched?)
     - Are there anomalies? (unusual triage for reported symptoms?)
     - Should I escalate to a specialist agent or continue?
   If data is incomplete: retry with clarification_question tool.
   If anomaly detected: log it AND continue — do not block the pipeline.

4. Multi-Agent Delegation
   You delegate to specialist agents when their expertise is needed:
     - route_to_intake    → Intake Agent  (clinical extraction)
     - route_to_geo       → Geo Agent     (location enrichment)
     - route_to_data      → Data Agent    (MongoDB persistence)
     - route_to_notify    → Notify Agent  (Telegram delivery)
     - trigger_surveillance → Surveillance Agent (outbreak detection)
     - get_response_protocol → Protocol Research Agent (WHO/CDC guidelines)
   Each agent is autonomous. Your role is coordination, not execution.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MISSION 1 — ENCOUNTER LIFECYCLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
State: IDLE → LISTENING → EXTRACTING → GEOCODING → STORING
       → [CONTACT_TRACING] → [DECISION_GATE] → NOTIFYING → COMPLETE

PLAN before executing:
  Step 1 — INTAKE (delegate to Intake Agent)
    REASON: Extract syndrome, triage, symptoms, language from CHV input.
    ACT: Call route_to_intake(audio_base64, session_id)
    OBSERVE: Check syndrome is a valid WHO IDSR category. Check confidence ≥ 0.7.
    REFLECT: If confidence < 0.7 or syndrome = 'unknown', note it but continue.
             Do NOT block the pipeline for low confidence.

  Step 2 — GEO ENRICHMENT (delegate to Geo Agent)
    REASON: Admin hierarchy + nearest facilities needed for referral routing.
    ACT: Call route_to_geo(encounter_json, latitude, longitude)
    OBSERVE: Verify county and ward are populated. Verify ≥1 facility returned.
    REFLECT: If location unavailable (0,0 coords), set county = 'Unknown' and continue.

  Step 3 — PERSIST (delegate to Data Agent)
    REASON: Encounter must be stored before gate — so data is never lost.
    ACT: Call route_to_data(enriched_encounter)
    OBSERVE: Confirm inserted_id returned.
    REFLECT: If error, retry ONCE. If still failing, queue_offline_encounter.

  Step 4 — CONTACT TRACING (if RED triage — delegate to Contact Tracing Agent)
    REASON: RED cases need immediate exposure mapping.
    Note: Contact tracing is triggered automatically by the swarm event bus.
    This step is informational — the swarm handles it.

  Step 5 — HUMAN GATE (RED or YELLOW only)
    REASON: Human confirmation before irreversible referral dispatch.
    ACT: Call request_human_decision(session_id, "referral", summary, timeout=60)
    OBSERVE: Wait for confirmed=True/False or timeout.
    REFLECT: On timeout, apply HumanGatePolicy (RED → escalate, YELLOW → queue).
    IMPORTANT: Never skip this gate for RED/YELLOW.

  Step 6 — NOTIFY (delegate to Notify Agent)
    REASON: Facility must receive referral via Telegram before patient arrives.
    ACT: Call route_to_notify("referral", referral_payload)
    OBSERVE: Check delivered=True.
    REFLECT: If delivery fails, log and continue — Notify Agent handles retries.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MISSION 2 — SURVEILLANCE (every 6 hours)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PLAN: For each active county:
  REASON: Detect outbreak spikes vs 4-week rolling baselines.
  ACT: trigger_surveillance(county, lat, lng, immediate=True)
  OBSERVE: Count alerts_detected. For each alert, note syndrome + risk_level.
  REFLECT: HIGH risk → immediately formulate protocol via get_response_protocol.
           Cross-county spread ≥3 → escalate to NATIONAL level.
  ACT: run_silent_pandemic_scan(county, weeks=4)
  OBSERVE: Any trend_delta > 2 signals a silent pandemic.
  REFLECT: Silent pandemic is MORE dangerous than spike. Always notify + formulate.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MISSION 3 — PROTOCOL FORMULATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REASON: Every alert needs a response protocol before CHWs are notified.
ACT: get_response_protocol(syndrome, county)
OBSERVE: Check source_authority. If source = "TEMPLATE", the protocol
         was not AI-researched. That is acceptable — templates are WHO-based.
REFLECT: If no protocol found, call search_response_protocols(syndrome)
         to find a similar one. Never leave an alert without a protocol.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MISSION 4 — PATIENT FOLLOW-UP (daily)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REASON: Overdue follow-ups mean patients lost to follow-up — preventable deaths.
ACT: get_chw_follow_ups(chw_id, overdue_only=True)
OBSERVE: Count overdue tasks. For each, check outcome if completed.
REFLECT: outcome = 'deteriorated' → immediately trigger new referral.
         outcome = 'deceased' → log for district officer, no referral.
         outcome = 'improved' → mark complete.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONVERSATIONAL INTELLIGENCE (Telegram + Web)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When a CHV sends a text message through Telegram:
  REASON: Understand the intent — is this a report, a question, a follow-up?
  THINK: Parse the message. Identify: syndrome clues, urgency words,
         location mentions, patient details (age, sex, symptoms).
  RESPOND in the CHV's language (Dholuo/Swahili/Kikuyu/Somali/English).
  ACT accordingly:
    - Symptom report → start encounter lifecycle
    - Protocol question → get_response_protocol
    - Follow-up report → complete_patient_follow_up
    - Status question → get_county_follow_up_summary

RESPONSE FORMAT for CHVs (always):
  ✅/❌/⚠️ Status indicator
  Brief plain-language explanation (1-3 sentences)
  Next action if any (e.g., "Patient referred. Confirm receipt at facility.")
  Session ID for tracking (e.g., "Session: tg-12345")

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INVARIANT RULES — NEVER VIOLATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Retry every failed tool call ONCE before giving up
• Never lose encounter data — always queue_offline_encounter on failure
• Human gate is mandatory for RED and YELLOW — never skip
• Always speak in the CHV's detected language
• Always include session_id in every response to CHV
• Contact tracing is automatic for RED — the swarm handles it
""",
    tools=[
        # ── Encounter lifecycle ───────────────────────────────────────────────
        route_to_intake,
        route_to_geo,
        route_to_data,
        request_human_decision,
        route_to_notify,
        # ── Offline queue ─────────────────────────────────────────────────────
        queue_offline_encounter,
        process_offline_queue,
        # ── Surveillance ──────────────────────────────────────────────────────
        trigger_surveillance,
        run_silent_pandemic_scan,
        # ── Protocols ─────────────────────────────────────────────────────────
        get_response_protocol,
        search_response_protocols,
        # ── Patient follow-up ─────────────────────────────────────────────────
        get_chw_follow_ups,
        complete_patient_follow_up,
        get_county_follow_up_summary,
        # ── CHW outreach ──────────────────────────────────────────────────────
        check_chw_outreach_gaps,
    ],
    generate_content_config=genai_types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=2048,  # increased for ReAct reasoning chains
    ),
)

# ---------------------------------------------------------------------------
# RunConfig with TTS for CHV voice feedback
# ---------------------------------------------------------------------------


def build_orchestrator_run_config(voice_name: str = "Aoede") -> RunConfig:
    """
    Build RunConfig with TTS for spoken CHV feedback via Gemini Live API.
    response_modalities=["AUDIO"] tells the Live session to speak responses
    rather than return text — the CHV hears the AI's reply directly.
    """
    voice_config = genai_types.VoiceConfig(
        prebuilt_voice_config=genai_types.PrebuiltVoiceConfigDict(voice_name=voice_name)
    )
    speech_config = genai_types.SpeechConfig(voice_config=voice_config)
    return RunConfig(
        speech_config=speech_config,
        response_modalities=["AUDIO"],
    )


# ---------------------------------------------------------------------------
# Runner setup
# ---------------------------------------------------------------------------

APP_NAME = "sihalink_orchestrator"
_session_service = InMemorySessionService()
_runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=_session_service,
)

# ── Agentic message handler ───────────────────────────────────────────────────
# Per-user persistent sessions so Gemini maintains conversation context
# across multiple Telegram messages from the same CHW.


async def run_agentic_message(
    user_id: str,
    message: str,
    session_id: Optional[str] = None,
) -> str:
    """
    Route a user message through the ADK orchestrator runner.
    Gemini decides which tools to call, chains them autonomously,
    and returns a natural language response.

    Used by:
      - POST /encounter/respond  (Telegram text relay)
      - POST /adk/run            (direct ADK invocation)
    """
    sid = session_id or f"tg-{user_id}"

    # Ensure session exists — create if first message from this user
    try:
        await _session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=sid
        )
    except Exception:
        await _session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=sid
        )

    final_text = ""
    async for event in _runner.run_async(
        user_id=user_id,
        session_id=sid,
        new_message=genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=message)],
        ),
    ):
        if event.is_final_response() and event.content:
            parts = event.content.parts or []
            final_text = " ".join(
                p.text for p in parts if hasattr(p, "text") and p.text
            )

    return final_text or "✅ Request processed."


# ---------------------------------------------------------------------------
# FastAPI app — Agent Runtime HTTP interface
# ---------------------------------------------------------------------------

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(fastapi_app):
    """Start the autonomous swarm on startup; shut it down cleanly on exit."""
    logger.info(
        "[Orchestrator] 🚀 Starting SihaLink — Kenya National Disease Surveillance"
    )
    try:
        from agents.data.agent import (
            create_vector_search_index,
            load_disease_references,
            seed_clinical_dataset,
        )

        idx_res = create_vector_search_index()
        logger.info(f"[Orchestrator] Vector Index Status: {idx_res}")

        # Load disease reference database on startup
        disease_res = load_disease_references()
        logger.info(
            f"[Orchestrator] Disease Reference Load: {disease_res.get('diseases_loaded', 0)} diseases loaded"
        )
        if disease_res.get("errors"):
            logger.warning(
                f"[Orchestrator] Disease load errors: {disease_res['errors']}"
            )

        # Seed clinical dataset with Voyage AI embeddings
        dataset_res = seed_clinical_dataset()
        logger.info(
            f"[Orchestrator] Clinical Dataset Seeded: {dataset_res.get('encounters_loaded', 0)} encounters with Voyage AI embeddings"
        )
        if dataset_res.get("errors"):
            logger.warning(
                f"[Orchestrator] Dataset seed errors: {dataset_res['errors']}"
            )
    except Exception as e:
        logger.error(f"[Orchestrator] Startup Error: {e}")
    await swarm.start()
    # Register SSE broadcaster — relay every swarm bus event to connected browsers
    swarm.bus.subscribe("*", _sse_swarm_subscriber)
    logger.info("[Orchestrator] 📡 SSE broadcast channel active (/swarm/stream)")
    yield
    logger.info("[Orchestrator] 🛑 Shutting down SihaLink swarm")
    await swarm.stop()

    # Flush and shut down OTel providers to prevent
    # "Task was destroyed but it is pending!" from aiohttp/genai client
    from .telemetry import graceful_shutdown as _telemetry_shutdown
    _telemetry_shutdown()

    # Give any lingering aiohttp connections a moment to close gracefully
    await asyncio.sleep(0.25)


app = FastAPI(title="SihaLink Orchestrator", lifespan=_lifespan)

# ── Dynatrace: auto-instrument every FastAPI request ─────────────────────────
if _telemetry_active:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        logger.info("[Telemetry] FastAPI auto-instrumentation active")
    except ImportError:
        pass

# ── CORS ─────────────────────────────────────────────────────────────────────
# In production (Cloud Run), the Angular app is served from Firebase Hosting
# (*.web.app / *.firebaseapp.com) and makes requests to this service.
# The wildcard "*" is kept for dev convenience; restrict in prod via
# ALLOWED_ORIGINS env var if needed.
_ALLOWED_ORIGINS = [o.strip() for o in os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:4200,http://localhost:5173,http://localhost:3000,"
    "https://*.web.app,https://*.firebaseapp.com",
).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.(web\.app|firebaseapp\.com|run\.app)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Serve Angular static files in production ──────────────────────────────────
# When the container includes frontend/dist/frontend/browser (built in Docker
# Stage 2) we serve the Angular SPA from /static.
# API routes take precedence; the SPA catch-all is registered last.
import pathlib as _pathlib
_STATIC_DIR = _pathlib.Path("/app/static")
if _STATIC_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles
    # Mount at a non-conflicting prefix first; the catch-all is added after
    # all API routes are registered (see bottom of file).
    logger.info("[Orchestrator] Serving Angular SPA from /app/static")


@app.get("/health")
@app.get("/status")
async def health_check():
    """Health check endpoint - shows status of all services."""
    mongodb_status = "connected" if data_agent.connected else "disconnected"
    gemini_key_set = bool(os.getenv("GEMINI_API_KEY"))
    maps_key_set = bool(os.getenv("GOOGLE_MAPS_API_KEY"))

    return {
        "status": "ok",
        "services": {
            "mongodb": {
                "status": mongodb_status,
                "warning": (
                    "MongoDB not connected - running in degraded mode"
                    if not data_agent.connected
                    else None
                ),
            },
            "orchestrator": "ready",
            "api": "online",
            "gemini": {
                "status": "configured" if gemini_key_set else "not_configured",
                "warning": (
                    "GEMINI_API_KEY not set - audio extraction will use mock data"
                    if not gemini_key_set
                    else None
                ),
            },
            "maps": {
                "status": "configured" if maps_key_set else "not_configured",
                "warning": (
                    "GOOGLE_MAPS_API_KEY not set - location enrichment disabled"
                    if not maps_key_set
                    else None
                ),
            },
        },
    }


@app.post("/encounter/start")
@app.post("/tool/start_encounter")
async def start_encounter(payload: Dict[str, Any], background_tasks: BackgroundTasks):
    """
    Unified encounter start — accepts audio, web-form, or Telegram payloads.
    Kicks off the full state-machine lifecycle as a background task.
    Uses WorkflowState (MongoDB-persistent) and ReAct pipeline pattern.

    Body:
        session_id       — required
        audio_base64     — raw audio for voice intake
        form_data        — structured clinical form (web UI)
        telegram_payload — {chw_id, message_text, audio_base64, language_hint}
        latitude / longitude — GPS coordinates
    """
    session_id = payload.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    audio = payload.get("audio_base64", "")
    coords = {"lat": payload.get("latitude", 0.0), "lng": payload.get("longitude", 0.0)}
    form_data = payload.get("form_data")
    telegram_payload = payload.get("telegram_payload")
    chw_id = (telegram_payload or {}).get("chw_id", payload.get("chw_id", "unknown"))

    source = "audio"
    if form_data:
        source = "form"
    elif telegram_payload:
        source = "telegram"

    # ── IBM Agentic Pattern: Workflow State Persistence ───────────────────────
    # Create durable state in MongoDB — survives server restarts mid-pipeline
    _workflow_state.create(
        session_id=session_id,
        source=source,
        chw_id=chw_id,
        county=(telegram_payload or {}).get("county", "Unknown"),
    )
    _workflow_state.transition(
        session_id, "INTAKE", note=f"Encounter started via {source}"
    )

    with _tracer.start_as_current_span("encounter.start") as span:
        span.set_attribute("encounter.session_id", session_id)
        span.set_attribute("encounter.source", source)
        span.set_attribute("encounter.has_audio", bool(audio))
        span.set_attribute("encounter.latitude", coords["lat"])
        span.set_attribute("encounter.longitude", coords["lng"])
        background_tasks.add_task(
            orchestrator.run_lifecycle,
            session_id,
            audio,
            coords,
            form_data=form_data,
            telegram_payload=telegram_payload,
        )

    return {"status": "processing", "session_id": session_id, "source": source}


@app.get("/encounters")
async def list_encounters(
    county:  Optional[str] = None,
    syndrome: Optional[str] = None,
    triage:  Optional[str] = None,
    limit:   int = 50,
    skip:    int = 0,
):
    """
    List persisted encounters from MongoDB with optional filters.
    Used by the Angular Encounters component to show seeded/live data.

    Query params:
      county   — filter by admin_hierarchy.county
      syndrome — filter by extracted.syndrome
      triage   — filter by extracted.triage_color (RED|YELLOW|GREEN)
      limit    — max results (default 50)
      skip     — pagination offset
    """
    if not data_agent.connected:
        return {"encounters": [], "count": 0, "status": "degraded"}

    from pymongo import DESCENDING as _DESC
    query: Dict[str, Any] = {}
    if county:
        query["admin_hierarchy.county"] = county
    if syndrome:
        query["extracted.syndrome"] = syndrome
    if triage:
        query["extracted.triage_color"] = triage.upper()

    try:
        docs = list(
            data_agent.db.encounters.find(query, {"_id": 0, "embedding": 0})
            .sort("timestamp", _DESC)
            .skip(skip)
            .limit(limit)
        )
        total = data_agent.db.encounters.count_documents(query)
        # Convert datetime to ISO string for JSON serialisation
        for doc in docs:
            if hasattr(doc.get("timestamp"), "isoformat"):
                doc["timestamp"] = doc["timestamp"].isoformat()
        return {"encounters": docs, "count": total, "limit": limit, "skip": skip}
    except Exception as exc:
        logger.error("GET /encounters failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/encounters/{encounter_id}")
async def get_encounter(encounter_id: str):
    """
    Get a single encounter by encounter_id.
    Used by the Angular Encounters component View Details panel.
    """
    if not data_agent.connected:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        doc = data_agent.db.encounters.find_one(
            {"encounter_id": encounter_id}, {"_id": 0, "embedding": 0}
        )
        if not doc:
            raise HTTPException(status_code=404, detail=f"Encounter {encounter_id} not found")
        if hasattr(doc.get("timestamp"), "isoformat"):
            doc["timestamp"] = doc["timestamp"].isoformat()
        return doc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("GET /encounters/%s failed: %s", encounter_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/encounter/{session_id}/workflow")
async def get_workflow_state_endpoint(session_id: str):
    """
    Get the persistent workflow state for an encounter including ReAct history.
    Shows each pipeline stage, reflection scores, and any errors.
    """
    state = _workflow_state.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Workflow {session_id} not found")
    return state


@app.get("/workflows/incomplete")
async def list_incomplete_workflows(older_than_minutes: int = 30):
    """
    List workflows stuck in non-terminal states — for monitoring and recovery.
    Useful to find encounters that need manual intervention.
    """
    return {
        "incomplete": _workflow_state.list_incomplete(older_than_minutes),
        "older_than_minutes": older_than_minutes,
    }


@app.get("/encounter/{session_id}/status")
async def get_encounter_status(session_id: str):
    """Poll the current state of an encounter session."""
    session = orchestrator.sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    state = session.get("state")
    return {
        "session_id": session_id,
        "state": state.value if hasattr(state, "value") else str(state),
        "data": {k: v for k, v in session.items() if k != "state"},
    }


@app.post("/encounter/{session_id}/confirm")
async def confirm_encounter(session_id: str, payload: Dict[str, Any]):
    """CHV taps Confirm or Decline — resolves the asyncio.Future gate."""
    confirmed = payload.get("confirmed", False)
    success = orchestrator.resolve_human_gate(session_id, confirmed)
    if not success:
        raise HTTPException(status_code=404, detail="No pending gate for this session")
    return {"session_id": session_id, "confirmed": confirmed}


@app.post("/encounter/{session_id}/clarify")
async def clarify_encounter(session_id: str, payload: Dict[str, Any]):
    """
    Submit a clarification answer for an encounter in CLARIFICATION_GATE state.
    The lifecycle coroutine is paused and waiting for this to resolve its Future.
    """
    answer = payload.get("answer", "").strip()
    if not answer:
        raise HTTPException(status_code=400, detail="answer is required")
    future = orchestrator._pending_gates.get(session_id)
    if not future or future.done():
        raise HTTPException(
            status_code=404,
            detail="No active clarification gate for this session",
        )
    future.set_result(answer)
    return {"session_id": session_id, "status": "resolved", "gate": "clarification"}


@app.post("/encounter/gate/respond")
async def respond_to_gate(payload: Dict[str, Any]):
    """
    Gate-resolution endpoint for Telegram bot text responses.
    Resolves an active CLARIFICATION or DECISION gate keyed by chat_id.

    Body:
        chat_id  — Telegram chat ID
        text     — CHV's free-text answer (for CLARIFICATION)
        confirm  — Boolean (for DECISION_GATE)
    """
    from .state_machine import EncounterState

    chat_id = str(payload.get("chat_id", ""))
    text = payload.get("text", "").strip()
    confirm = payload.get("confirm")  # None means text-only / clarification

    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id is required")

    # Find the most recent tg- session for this chat_id that has an active gate
    matching_sid: Optional[str] = None
    for sid, future in orchestrator._pending_gates.items():
        if not future.done() and sid.startswith(f"tg-{chat_id}-"):
            matching_sid = sid
            break

    if not matching_sid:
        return {"status": "no_gate", "message": "No active gate found for this chat"}

    session = orchestrator.sessions.get(matching_sid, {})
    state = session.get("state")
    future = orchestrator._pending_gates[matching_sid]

    if state == EncounterState.CLARIFICATION_GATE:
        if not text:
            return {
                "status": "error",
                "message": "Text answer required for clarification gate",
            }
        future.set_result(text)
        return {
            "status": "resolved",
            "session_id": matching_sid,
            "gate": "clarification",
        }

    elif state == EncounterState.DECISION_GATE:
        if confirm is None:
            return {
                "status": "error",
                "message": "confirm (bool) required for decision gate",
            }
        future.set_result(bool(confirm))
        return {
            "status": "resolved",
            "session_id": matching_sid,
            "gate": "decision",
            "confirmed": bool(confirm),
        }

    else:
        return {
            "status": "no_gate",
            "message": f"Session {matching_sid} is in state {state}, no active gate",
        }


@app.post("/tool/route_to_intake")
async def api_route_to_intake(payload: Dict[str, Any]):
    session_id = payload.get("session_id")
    audio = payload.get("audio_base64")
    if not session_id or not audio:
        raise HTTPException(
            status_code=400, detail="session_id and audio_base64 required"
        )
    clarification_answers = payload.get("clarification_answers")
    extracted = await intake_agent.process_with_clarification(
        audio, clarification_answers, session_id
    )
    return {"session_id": session_id, "extracted": extracted}


@app.post("/intake/form")
async def api_intake_form(payload: Dict[str, Any]):
    """Accept a clinical intake from the Angular web form."""
    session_id = payload.get(
        "session_id", f"form-{int(asyncio.get_event_loop().time())}"
    )
    form_data = payload.get("form_data", payload)  # allow flat or nested
    extracted = await intake_agent.process_form(form_data, session_id)
    return {"session_id": session_id, "extracted": extracted}


@app.post("/intake/telegram")
async def api_intake_telegram(payload: Dict[str, Any]):
    """Accept a clinical intake from a Telegram CHV message."""
    chw_id = payload.get("chw_id", "unknown")
    session_id = payload.get(
        "session_id", f"tg-{chw_id}-{int(asyncio.get_event_loop().time())}"
    )
    extracted = await intake_agent.process_telegram(
        message_text=payload.get("message_text"),
        audio_b64=payload.get("audio_base64"),
        chw_id=chw_id,
        session_id=session_id,
        language_hint=payload.get("language_hint"),
    )
    return {"session_id": session_id, "extracted": extracted}


@app.post("/intake/agent")
async def api_intake_agent(payload: Dict[str, Any]):
    """Accept a clinical intake forwarded from another SihaLink agent."""
    source_agent = payload.get("source_agent", "unknown")
    session_id = payload.get(
        "session_id", f"agent-{int(asyncio.get_event_loop().time())}"
    )
    extracted = await intake_agent.process_from_agent(payload, source_agent, session_id)
    return {"session_id": session_id, "extracted": extracted}


@app.post("/tool/route_to_geo")
async def api_route_to_geo(payload: Dict[str, Any]):
    encounter = payload.get("encounter_json")
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    if encounter is None or latitude is None or longitude is None:
        raise HTTPException(
            status_code=400, detail="encounter_json, latitude, longitude required"
        )
    enriched = await geo_agent.enrich_location(
        encounter, {"lat": latitude, "lng": longitude}
    )
    return {"encounter_id": encounter.get("session_id"), "enriched_encounter": enriched}


@app.post("/tool/route_to_data")
async def api_route_to_data(payload: Dict[str, Any]):
    enriched_encounter = payload.get("enriched_encounter")
    if enriched_encounter is None:
        raise HTTPException(status_code=400, detail="enriched_encounter required")
    inserted_id = await data_agent.insert_encounter(enriched_encounter)
    return {"inserted_id": inserted_id}


@app.post("/tool/route_to_notify")
async def api_route_to_notify(payload: Dict[str, Any]):
    notification_type = payload.get("notification_type")
    notify_payload = payload.get("payload")
    if not notification_type or notify_payload is None:
        raise HTTPException(
            status_code=400, detail="notification_type and payload required"
        )
    if notification_type == "referral":
        result = await notify_agent.dispatch_referral(notify_payload)
    elif notification_type == "outbreak_alert":
        result = await notify_agent.dispatch_outbreak_alert(notify_payload)
    else:
        result = {"delivered": False, "note": f"Unknown type: {notification_type}"}
    return {"status": "notified", "result": result}


# --- Mock Notification Endpoints for UI ---
@app.get("/notifications/recipients")
async def get_recipients():
    return []


@app.post("/tool/register_recipient")
async def api_register_recipient(payload: Dict[str, Any]):
    return {"status": "ok", "recipient": payload}


@app.get("/notifications/encounter/{encounter_id}")
async def get_notification_history(encounter_id: str):
    return {"history": []}


@app.get("/notifications/{notification_id}")
async def get_notification_status(notification_id: str):
    return {"status": "delivered"}


@app.post("/tool/trigger_surveillance")
async def api_trigger_surveillance(
    payload: Dict[str, Any], background_tasks: BackgroundTasks
):
    from agents.surveillance.agent import run_outbreak_detection

    county = payload.get("county", "")
    immediate = payload.get("immediate", False)
    lat = payload.get("lat", 0.0)
    lng = payload.get("lng", 0.0)
    hours = payload.get("hours", 6)
    if immediate and county:
        result = run_outbreak_detection(county, lat, lng, hours)
        for alert in result.get("alerts", []):
            background_tasks.add_task(notify_agent.dispatch_outbreak_alert, alert)
        return result
    if county:
        background_tasks.add_task(_run_surveillance_bg, county, lat, lng, hours)
    return {"status": "scheduled", "county": county}


async def _run_surveillance_bg(county: str, lat: float, lng: float, hours: int):
    from agents.surveillance.agent import run_outbreak_detection

    try:
        result = run_outbreak_detection(county, lat, lng, hours)
        for alert in result.get("alerts", []):
            await notify_agent.dispatch_outbreak_alert(alert)
        logger.info(
            "Surveillance complete for %s: %d alerts",
            county,
            result.get("alerts_detected", 0),
        )
    except Exception as exc:
        logger.error("Surveillance background task failed: %s", exc)


@app.post("/tool/sync_offline_encounters")
async def api_sync_offline_encounters(payload: Dict[str, Any]):
    encounters = payload.get("encounters", [])
    if not encounters:
        raise HTTPException(status_code=400, detail="encounters list required")
    return await data_agent.sync_offline_encounters(encounters)


@app.post("/tool/query_active_alerts")
async def api_query_active_alerts(payload: Dict[str, Any] = {}):
    county = payload.get("county")
    alerts = data_agent.query_active_alerts(county)
    return {"alerts": alerts, "count": len(alerts)}


@app.post("/tool/update_alert_status")
async def api_update_alert_status(payload: Dict[str, Any]):
    alert_id = payload.get("alert_id")
    status = payload.get("status")
    user_id = payload.get("user_id", "system")
    if not alert_id or not status:
        raise HTTPException(status_code=400, detail="alert_id and status required")
    return await data_agent.update_alert_status(alert_id, status, user_id)


@app.post("/tool/resolve_alert")
async def api_resolve_alert(payload: Dict[str, Any]):
    alert_id = payload.get("alert_id")
    if not alert_id:
        raise HTTPException(status_code=400, detail="alert_id required")
    return await data_agent.resolve_alert(
        alert_id, payload.get("notes", ""), payload.get("user_id", "system")
    )


@app.post("/tool/clarify_extraction")
async def api_clarify_extraction(payload: Dict[str, Any]):
    original = payload.get("original_extraction")
    answer = payload.get("clarification_answer")
    if not original or not answer:
        raise HTTPException(
            status_code=400,
            detail="original_extraction and clarification_answer required",
        )
    updated = await intake_agent.clarify(original, answer)
    return {"extracted": updated}


@app.post("/tool/get_county_stats")
async def api_get_county_stats(payload: Dict[str, Any]):
    from agents.surveillance.agent import get_county_stats

    county = payload.get("county")
    if not county:
        raise HTTPException(status_code=400, detail="county required")
    stats = get_county_stats(county)
    return {"county": county, **stats}


@app.post("/tool/update_baselines")
async def api_update_baselines(payload: Dict[str, Any] = {}):
    from agents.surveillance.agent import update_baselines

    return update_baselines(payload.get("county"))


@app.post("/tool/queue_offline_encounter")
async def api_queue_offline_encounter(payload: Dict[str, Any]):
    encounter = payload.get("encounter_json")
    if encounter is None:
        raise HTTPException(status_code=400, detail="encounter_json required")
    queue_size = orchestrator.queue_offline_encounter(encounter)
    return {"status": "queued", "queue_size": queue_size}


@app.post("/tool/process_offline_queue")
async def api_process_offline_queue():
    return await orchestrator.process_offline_queue()


@app.get("/tool/follow_ups/{chw_id}")
async def api_get_chw_follow_ups(chw_id: str, overdue_only: bool = False):
    """Get pending follow-up tasks for a CHW."""
    from ..data.agent import get_pending_follow_ups

    tasks = get_pending_follow_ups(chw_id=chw_id, overdue_only=overdue_only)
    return {"follow_ups": tasks, "count": len(tasks)}


@app.post("/tool/get_pending_follow_ups")
async def api_get_pending_follow_ups(payload: Dict[str, Any] = {}):
    """Get all pending follow-ups for a county (supervisor view)."""
    from ..data.agent import get_pending_follow_ups

    tasks = get_pending_follow_ups(
        county=payload.get("county"), overdue_only=payload.get("overdue_only", False)
    )
    return {"follow_ups": tasks, "count": len(tasks)}


@app.post("/tool/complete_follow_up")
async def api_complete_follow_up(payload: Dict[str, Any]):
    """Mark a follow-up as completed with outcome."""
    follow_up_id = payload.get("follow_up_id")
    outcome = payload.get("outcome")
    if not follow_up_id or not outcome:
        raise HTTPException(status_code=400, detail="follow_up_id and outcome required")
    from ..data.agent import complete_follow_up

    result = complete_follow_up(
        follow_up_id,
        outcome,
        payload.get("notes", ""),
        payload.get("chw_id", "unknown"),
    )
    # If patient deteriorated, trigger a new referral flow
    if outcome == "deteriorated":
        logger.warning(
            "Follow-up %s: patient deteriorated — supervisor notified", follow_up_id
        )
    return result


@app.post("/tool/reschedule_follow_up")
async def api_reschedule_follow_up(payload: Dict[str, Any]):
    """Reschedule a follow-up to a new date."""
    follow_up_id = payload.get("follow_up_id")
    days = payload.get("days_from_now", 1)
    if not follow_up_id:
        raise HTTPException(status_code=400, detail="follow_up_id required")
    from ..data.agent import reschedule_follow_up

    return reschedule_follow_up(follow_up_id, days, payload.get("reason", ""))


@app.get("/tool/follow_up_summary/{county}")
async def api_follow_up_summary(county: str):
    """Get follow-up completion stats for a county."""
    from ..data.agent import get_follow_up_summary

    return get_follow_up_summary(county)


# ── Protocol endpoints ────────────────────────────────────────────────────────


@app.get("/tool/protocol/{syndrome}")
async def api_get_protocol(syndrome: str, county: Optional[str] = None):
    """Retrieve the active response protocol for a syndrome."""
    from ..data.agent import get_protocol

    doc = get_protocol(syndrome, county)
    if not doc:
        raise HTTPException(status_code=404, detail=f"No protocol found for {syndrome}")
    return doc


@app.post("/tool/search_protocols")
async def api_search_protocols(payload: Dict[str, Any]):
    """Full-text Atlas Search across protocols."""
    query = payload.get("query", "")
    if not query:
        raise HTTPException(status_code=400, detail="query required")
    from ..data.agent import search_protocols

    return search_protocols(query, payload.get("limit", 5))


@app.post("/tool/list_protocols")
async def api_list_protocols(payload: Dict[str, Any] = {}):
    """List all active protocols, optionally filtered by county."""
    from ..data.agent import list_protocols

    return list_protocols(county=payload.get("county"))


@app.post("/tool/upsert_protocol")
async def api_upsert_protocol(payload: Dict[str, Any]):
    """Store or update a response protocol."""
    if not payload.get("syndrome"):
        raise HTTPException(status_code=400, detail="syndrome required")
    from ..data.agent import upsert_protocol

    return upsert_protocol(payload)


# ── CHW registry endpoints ────────────────────────────────────────────────────


@app.post("/tool/register_chw")
async def api_register_chw(payload: Dict[str, Any]):
    """Register or update a CHW in the registry."""
    if not payload.get("county"):
        raise HTTPException(status_code=400, detail="county required")
    from ..data.agent import register_chw

    return register_chw(payload)


@app.get("/tool/chws/{county}")
async def api_list_chws(county: str, ward: Optional[str] = None):
    """List active CHWs in a county."""
    from ..data.agent import list_chws

    return list_chws(county=county, ward=ward)


# ── Surveillance endpoints ────────────────────────────────────────────────────


@app.post("/tool/silent_pandemic_scan")
async def api_silent_pandemic_scan(payload: Dict[str, Any]):
    """Scan for silent pandemic signals in a county."""
    county = payload.get("county")
    if not county:
        raise HTTPException(status_code=400, detail="county required")
    from agents.surveillance.agent import detect_silent_pandemic

    return detect_silent_pandemic(county, payload.get("weeks", 4))


@app.post("/tool/chw_outreach_gaps")
async def api_chw_outreach_gaps(payload: Dict[str, Any]):
    """Identify wards with low CHW encounter submissions."""
    county = payload.get("county")
    if not county:
        raise HTTPException(status_code=400, detail="county required")
    from agents.surveillance.agent import detect_chw_outreach_gaps

    return detect_chw_outreach_gaps(county, payload.get("days", 7))


@app.post("/tool/cross_county_spread")
async def api_cross_county_spread(payload: Dict[str, Any]):
    """Detect cross-county spread of a syndrome."""
    syndrome = payload.get("syndrome")
    if not syndrome:
        raise HTTPException(status_code=400, detail="syndrome required")
    from agents.surveillance.agent import detect_cross_county_spread

    return detect_cross_county_spread(syndrome, payload.get("hours", 48))


# ── Per-agent health checks ───────────────────────────────────────────────────


@app.get("/health/intake")
async def health_intake():
    """Health check for the Intake Agent (Gemini Live API / clinical extraction)."""
    gemini_key = bool(os.getenv("GEMINI_API_KEY"))
    return {
        "status": "ok" if gemini_key else "degraded",
        "agent": "intake",
        "gemini_api_key_set": gemini_key,
        "capabilities": ["audio_extraction", "clarification", "triage"],
    }


@app.get("/health/geo")
async def health_geo():
    """Health check for the Geo Agent (Google Maps)."""
    maps_key = bool(os.getenv("GOOGLE_MAPS_API_KEY"))
    return {
        "status": "ok" if maps_key else "degraded",
        "agent": "geo",
        "google_maps_key_set": maps_key,
        "capabilities": ["admin_hierarchy", "facility_search", "eta"],
    }


@app.get("/health/data")
async def health_data():
    """Health check for the Data Agent (MongoDB Atlas)."""
    return {
        "status": "ok" if data_agent.connected else "degraded",
        "agent": "data",
        "mongodb_connected": data_agent.connected,
        "capabilities": ["encounters", "alerts", "follow_ups", "protocols", "chws"],
    }


@app.get("/health/notify")
async def health_notify():
    """Health check for the Notify Agent (Telegram bot)."""
    bot_token = bool(os.getenv("TELEGRAM_BOT_TOKEN"))
    return {
        "status": "ok" if bot_token else "degraded",
        "agent": "notify",
        "telegram_token_set": bot_token,
        "capabilities": ["referral_dispatch", "outbreak_alert", "protocol_broadcast"],
    }


@app.get("/health/surveillance")
async def health_surveillance():
    """Health check for the Surveillance Agent (MongoDB pipelines + ADK)."""
    mongodb_ok = data_agent.connected
    return {
        "status": "ok" if mongodb_ok else "degraded",
        "agent": "surveillance",
        "mongodb_connected": mongodb_ok,
        "capabilities": [
            "outbreak_detection",
            "silent_pandemic",
            "cross_county_spread",
            "protocol_formulation",
            "chw_outreach_gaps",
        ],
    }


# ── Geo tool endpoints ────────────────────────────────────────────────────────


@app.post("/tool/find_nearest_facilities")
async def api_find_nearest_facilities(payload: Dict[str, Any]):
    """Find the nearest health facilities for given GPS coordinates."""
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    if latitude is None or longitude is None:
        raise HTTPException(status_code=400, detail="latitude and longitude required")
    from agents.geo.agent import find_nearest_facilities

    facilities = find_nearest_facilities(float(latitude), float(longitude))
    return {"facilities": facilities, "count": len(facilities)}


@app.post("/tool/get_admin_hierarchy")
async def api_get_admin_hierarchy(payload: Dict[str, Any]):
    """Reverse-geocode GPS coordinates to Kenya administrative hierarchy."""
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    if latitude is None or longitude is None:
        raise HTTPException(status_code=400, detail="latitude and longitude required")
    from agents.geo.agent import get_admin_hierarchy

    hierarchy = get_admin_hierarchy(float(latitude), float(longitude))
    return hierarchy


# ── Surveillance dashboard ────────────────────────────────────────────────────


@app.get("/surveillance/dashboard")
async def surveillance_dashboard(county: Optional[str] = None):
    """
    Aggregate surveillance dashboard data for the frontend.
    Returns active alerts, recent encounters, and per-county stats.
    """
    if not data_agent.connected:
        return {
            "status": "degraded",
            "message": "MongoDB not connected",
            "active_alerts": [],
            "county_stats": {},
            "recent_encounters": [],
        }

    if county:
        return data_agent.get_county_dashboard(county)

    return data_agent.get_national_dashboard()


@app.post("/tool/vector_search")
async def api_vector_search(payload: Dict[str, Any]):
    """
    Atlas Vector Search — find semantically similar clinical encounters.
    Uses query embedding (voyage-4 query path) for best recall.
    """
    query = payload.get("query", "")
    if not query:
        raise HTTPException(status_code=400, detail="query required")
    results = data_agent.vector_search_encounters(
        query_text=query,
        county=payload.get("county"),
        syndrome=payload.get("syndrome"),
        limit=payload.get("limit", 10),
        num_candidates=payload.get("num_candidates", 100),
    )
    return {"results": results, "count": len(results), "query": query}


@app.post("/tool/vector_search_protocols")
async def api_vector_search_protocols(payload: Dict[str, Any]):
    """Semantic search across WHO/MoH response protocols."""
    query = payload.get("query", "")
    if not query:
        raise HTTPException(status_code=400, detail="query required")
    results = data_agent.vector_search_protocols(query, limit=payload.get("limit", 5))
    return {"results": results, "count": len(results)}


@app.post("/tool/search_encounters")
async def api_search_encounters(payload: Dict[str, Any]):
    """Atlas Search full-text search across encounter records."""
    query = payload.get("query", "")
    if not query:
        raise HTTPException(status_code=400, detail="query required")
    results = data_agent.search_encounters(
        query=query,
        county=payload.get("county"),
        limit=payload.get("limit", 20),
    )
    return {"results": results, "count": len(results)}


@app.post("/tool/search_alerts")
async def api_search_alerts(payload: Dict[str, Any]):
    """Atlas Search full-text search across outbreak alerts."""
    query = payload.get("query", "")
    if not query:
        raise HTTPException(status_code=400, detail="query required")
    results = data_agent.search_alerts(
        query=query,
        county=payload.get("county"),
        status=payload.get("status", "active"),
        limit=payload.get("limit", 20),
    )
    return {"results": results, "count": len(results)}


@app.post("/tool/update_referral_status")
async def api_update_referral_status(payload: Dict[str, Any]):
    """Update a patient referral status (called from Telegram accept/redirect buttons)."""
    referral_id = payload.get("referral_id")
    status = payload.get("status")
    if not referral_id or not status:
        raise HTTPException(status_code=400, detail="referral_id and status required")
    return data_agent.update_referral_status_sync(
        referral_id, status, payload.get("notes", "")
    )


@app.post("/tool/query_referrals")
async def api_query_referrals(payload: Dict[str, Any] = {}):
    """Query referrals."""
    from ..data.agent import query_referrals

    return query_referrals(
        county=payload.get("county"),
        status=payload.get("status"),
        limit=payload.get("limit", 20),
    )


# ── Swarm control & status routes ─────────────────────────────────────────────


@app.get("/swarm/status")
async def swarm_status():
    """
    Full swarm health snapshot for the web dashboard and Telegram /status command.
    Returns scheduler task status, recent events, agent health, and county coverage.
    """
    base = swarm.get_swarm_status()
    base["agents"] = {
        "intake": {"status": "ok"},
        "geo": {
            "status": "ok" if bool(os.getenv("GOOGLE_MAPS_API_KEY")) else "degraded"
        },
        "data": {
            "status": "ok" if data_agent.connected else "degraded",
            "mongodb_connected": data_agent.connected,
        },
        "notify": {
            "status": "ok" if bool(os.getenv("TELEGRAM_BOT_TOKEN")) else "degraded"
        },
        "surveillance": {"status": "ok" if data_agent.connected else "degraded"},
        "contact_tracing": {
            "status": "ok" if data_agent.connected else "degraded"
        },
    }
    return base


@app.post("/swarm/trigger/outbreak")
async def swarm_trigger_outbreak(payload: Dict[str, Any] = {}):
    """
    Manually trigger an outbreak detection cycle.
    If county is specified, runs for that county only.
    """
    county = payload.get("county")
    if county:
        from agents.surveillance.agent import run_outbreak_detection

        coords = swarm.active_counties.get(county, {"lat": 0.0, "lng": 0.0})
        result = run_outbreak_detection(county, coords["lat"], coords["lng"])
        for alert in result.get("alerts", []):
            await swarm.bus.publish(
                SwarmEvent("alert.detected", alert, source="manual_trigger")
            )
        return result
    # All counties
    await swarm._run_outbreak_cycle()
    return {"status": "triggered", "scope": "all_counties"}


@app.post("/swarm/trigger/silent_pandemic")
async def swarm_trigger_silent_pandemic(payload: Dict[str, Any] = {}):
    """Manually trigger the silent pandemic scan."""
    await swarm._run_silent_pandemic_cycle()
    return {"status": "triggered", "scope": payload.get("county", "all_counties")}


@app.post("/swarm/trigger/baselines")
async def swarm_trigger_baselines(payload: Dict[str, Any] = {}):
    """Manually trigger a baseline recalculation."""
    await swarm._run_baseline_update()
    return {"status": "triggered"}


@app.post("/swarm/trigger/offline_sync")
async def swarm_trigger_offline_sync():
    """Manually trigger offline queue sync."""
    await swarm._run_offline_sync()
    return {"status": "triggered", "queue_size": len(orchestrator.offline_queue)}


@app.get("/swarm/events")
async def swarm_events(topic: Optional[str] = None, limit: int = 50):
    """Return recent swarm events for the dashboard event log (snapshot)."""
    return {"events": swarm.bus.recent(topic=topic, limit=limit)}


# ── SSE broadcast manager ─────────────────────────────────────────────────────
# Holds a set of active SSE client queues. When any swarm event fires, it is
# pushed to every connected browser in real time.

import asyncio
from typing import Set
from fastapi.responses import StreamingResponse


class _SSEBroadcastManager:
    """Fan-out broadcaster: one swarm event → every connected SSE client."""

    def __init__(self):
        self._queues: Set[asyncio.Queue] = set()

    def add_client(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._queues.add(q)
        return q

    def remove_client(self, q: asyncio.Queue):
        self._queues.discard(q)

    async def broadcast(self, event_data: str):
        dead = set()
        for q in list(self._queues):
            try:
                q.put_nowait(event_data)
            except asyncio.QueueFull:
                dead.add(q)
        for q in dead:
            self._queues.discard(q)

    @property
    def client_count(self) -> int:
        return len(self._queues)


_sse_manager = _SSEBroadcastManager()


async def _sse_swarm_subscriber(event) -> None:
    """
    Global swarm bus subscriber — relays every event to:
      1. SSE clients (browser dashboards)
      2. Telegram channels via /notify/broadcast (for significant alerts)
    """
    import json, httpx

    BROADCAST_TOPICS = {
        "alert.detected",
        "alert.silent_pandemic",
        "alert.cross_county_spread",
        "surveillance.escalation_needed",
        "contact_trace.contact_confirmed",
        "gap.chw_outreach",
    }

    skip_topics = {"task.chk_heartbeat"}
    if event.topic in skip_topics:
        return

    # ── Fan out to SSE clients ────────────────────────────────────────────────
    try:
        payload_safe = {}
        if isinstance(event.payload, dict):
            payload_safe = {
                k: v
                for k, v in event.payload.items()
                if isinstance(v, (str, int, float, bool, list, type(None)))
            }
        data = json.dumps(
            {
                "topic": event.topic,
                "source": event.source,
                "ts": event.ts,
                "payload": payload_safe,
            },
            default=str,
        )
        await _sse_manager.broadcast(f"data: {data}\n\n")
    except Exception as exc:
        logger.debug("SSE broadcast error: %s", exc)

    # ── Fan out to Telegram channels for significant events ───────────────────
    if event.topic not in BROADCAST_TOPICS:
        return

    try:
        p = event.payload if isinstance(event.payload, dict) else {}
        syndrome = p.get("syndrome", "")
        county = p.get("county") or (p.get("location") or {}).get("county", "")
        risk = p.get("risk_level") or p.get("alert_level", "")
        escalation = p.get("escalation_level", "")

        topic_titles = {
            "alert.detected": f"🚨 Outbreak Alert: {syndrome.upper() or 'UNKNOWN'}",
            "alert.silent_pandemic": f"🌊 Silent Pandemic: {syndrome.upper() or 'UNKNOWN'}",
            "alert.cross_county_spread": f"🔴 Cross-County Spread: {syndrome.upper() or 'UNKNOWN'}",
            "surveillance.escalation_needed": "🔴 NATIONAL ESCALATION",
            "contact_trace.contact_confirmed": "⚠️ Contact Confirmed as New Case",
            "gap.chw_outreach": f"👥 CHW Outreach Gap: {county}",
        }
        title = topic_titles.get(event.topic, event.topic)

        messages = {
            "alert.detected": f"{county} — {p.get('count','?')} cases. +{p.get('percent_above_baseline',0)}% above baseline.",
            "alert.silent_pandemic": f"{county} — persistent upward trend over {p.get('weeks_observed','?')} weeks.",
            "alert.cross_county_spread": f"{p.get('counties_count','?')} counties affected. Escalation: {escalation or 'REGIONAL'}.",
            "surveillance.escalation_needed": f"Cross-county syndromes: {list((p.get('cross_county_syndromes') or {}).keys())}",
            "contact_trace.contact_confirmed": f"Trace {p.get('trace_id','')} — secondary trace initiated.",
            "gap.chw_outreach": f"{p.get('total_gap_wards','?')} wards with zero submissions.",
        }
        message = messages.get(event.topic, str(p)[:200])

        broadcast_payload = {
            "topic": event.topic,
            "title": title,
            "message": message,
            "county": county or "NATIONAL",
            "syndrome": syndrome,
            "risk_level": risk,
            "escalation_level": escalation,
            "alert_id": p.get("alert_id", ""),
        }

        async with httpx.AsyncClient(timeout=8.0) as client:
            await client.post(
                f"{NOTIFY_BASE}/notify/broadcast",
                json=broadcast_payload,
            )
    except Exception as exc:
        logger.debug("Telegram broadcast from SSE failed (non-fatal): %s", exc)


@app.get("/swarm/stream")
async def swarm_stream(request: Request):
    """
    Server-Sent Events endpoint — pushes ALL swarm events to the browser in real time.

    Connect from Angular with:
        const es = new EventSource('/swarm/stream');
        es.onmessage = (e) => console.log(JSON.parse(e.data));

    Events include: alert.detected, alert.silent_pandemic, encounter.stored,
    contact_trace.initiated, surveillance.escalation_needed, task.*.complete, etc.
    """
    import json

    queue = _sse_manager.add_client()

    async def event_generator():
        # Send a hello ping so the browser knows the connection is live
        yield f"data: {json.dumps({'topic': 'connected', 'source': 'server', 'ts': __import__('datetime').datetime.utcnow().isoformat()})}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield data
                except asyncio.TimeoutError:
                    # Keep-alive ping every 25s to prevent proxy timeouts
                    yield ": keepalive\n\n"
        finally:
            _sse_manager.remove_client(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable Nginx buffering
        },
    )


@app.post("/swarm/counties/add")
async def swarm_add_county(payload: Dict[str, Any]):
    """Add a county to the active surveillance scope."""
    county = payload.get("county")
    lat = payload.get("lat", 0.0)
    lng = payload.get("lng", 0.0)
    if not county:
        raise HTTPException(status_code=400, detail="county required")
    swarm.add_county(county, lat, lng)
    return {
        "status": "added",
        "county": county,
        "total_counties": len(swarm.active_counties),
    }


@app.delete("/swarm/counties/{county}")
async def swarm_remove_county(county: str):
    """Remove a county from active surveillance."""
    swarm.remove_county(county)
    return {"status": "removed", "county": county}


# ── Import needed for swarm event publishing in routes above ──────────────────
from agents.swarm import (
    SwarmEvent,
)  # noqa: E402 — after app definition to avoid circular

# ── Agentic endpoints — ADK runner ────────────────────────────────────────────


@app.post("/encounter/respond")
async def api_encounter_respond(payload: Dict[str, Any]):
    """
    Route a Telegram or web message through the ADK Gemini orchestrator.

    This is the truly agentic endpoint — Gemini reads the message, decides
    which tools to call (intake, geo, data, surveillance, notify), chains them,
    and returns a natural language response the bot sends back to the user.

    Body:
      chat_id  — Telegram chat ID (used as user_id for session persistence)
      text     — The user's message text
      session_id — Optional explicit session (defaults to tg-{chat_id})
    """
    chat_id = str(payload.get("chat_id", "unknown"))
    text = payload.get("text", "").strip()
    session_id = payload.get("session_id")

    if not text:
        return {"status": "ignored", "reason": "empty message"}

    try:
        response = await run_agentic_message(
            user_id=chat_id,
            message=text,
            session_id=session_id,
        )
        return {
            "status": "resolved",
            "session_id": session_id or f"tg-{chat_id}",
            "response": response,
        }
    except Exception as exc:
        logger.error("Agentic message failed for %s: %s", chat_id, exc)
        return {"status": "error", "error": str(exc)}


@app.post("/adk/run")
async def api_adk_run(payload: Dict[str, Any]):
    """
    Direct ADK runner endpoint for arbitrary agentic tasks.
    Accepts any natural language instruction and returns Gemini's response
    after it autonomously calls the appropriate tools.

    Body:
      user_id    — Caller identity (used for session persistence)
      message    — Natural language instruction
      session_id — Optional session ID for conversation continuity
    """
    user_id = payload.get("user_id", "api-user")
    message = payload.get("message", "").strip()
    session_id = payload.get("session_id")

    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    try:
        response = await run_agentic_message(
            user_id=str(user_id),
            message=message,
            session_id=session_id,
        )
        return {
            "status": "ok",
            "session_id": session_id or f"session-{user_id}",
            "response": response,
        }
    except Exception as exc:
        logger.error("ADK run failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/tool/research_protocol")
async def api_research_protocol(payload: Dict[str, Any]):
    """
    Trigger the Protocol Research Agent to formulate an evidence-based protocol
    by searching WHO, CDC, ECDC, and Kenya MoH guidelines in real time.

    Body:
      syndrome      — WHO IDSR syndrome category (required)
      county        — Kenya county name (default: 'all')
      alert_level   — RED | YELLOW | GREEN (default: YELLOW)
      force_refresh — Re-research even if protocol exists (default: false)
    """
    syndrome = payload.get("syndrome")
    county = payload.get("county", "all")
    alert_level = payload.get("alert_level", "YELLOW")
    force_refresh = payload.get("force_refresh", False)

    if not syndrome:
        raise HTTPException(status_code=400, detail="syndrome is required")

    try:
        from agents.surveillance.protocol_agent import (
            research_and_formulate_protocol_sync,
        )

        result = research_and_formulate_protocol_sync(
            syndrome, county, alert_level, force_refresh
        )
        return result
    except Exception as exc:
        logger.error("Protocol research endpoint failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Contact Tracing endpoints ─────────────────────────────────────────────────


@app.post("/tool/trace_contacts")
async def api_trace_contacts(payload: Dict[str, Any]):
    """
    Initiate a contact trace for a single encounter or outbreak cluster.
    Called automatically for RED encounters; also callable manually.

    Body:
      encounter_id  — index case to trace (required unless alert_id given)
      alert_id      — trace the full outbreak cluster (optional)
      initiated_by  — user ID or 'system' (optional)
    """
    encounter_id = payload.get("encounter_id")
    alert_id = payload.get("alert_id")
    initiated_by = payload.get("initiated_by", "api")

    if not encounter_id and not alert_id:
        raise HTTPException(
            status_code=400,
            detail="encounter_id or alert_id is required",
        )

    from agents.contact_tracing.agent import (
        initiate_contact_trace,
        trace_outbreak_cluster,
    )

    if alert_id and not encounter_id:
        result = trace_outbreak_cluster(alert_id)
    else:
        result = initiate_contact_trace(
            encounter_id, alert_id=alert_id, initiated_by=initiated_by
        )

    # Publish event so Notify Agent can dispatch CHW tasks
    if result.get("trace_id") and result.get("contacts_identified", 0) > 0:
        await swarm.bus.publish(
            SwarmEvent(
                "contact_trace.contacts_identified",
                result,
                source="orchestrator",
            )
        )

    return result


@app.get("/tool/trace_status/{trace_id}")
async def api_trace_status(trace_id: str):
    """
    Get the full status of a contact trace including analytics histogram.

    Returns trace document with:
      - All contacts and their current status
      - completion_rate_pct, secondary_attack_rate
      - status_histogram: identified / contacted / cleared / confirmed / overdue
      - tier_histogram: HOUSEHOLD / COMMUNITY / FACILITY / UNKNOWN counts
    """
    from agents.contact_tracing.agent import get_trace_status

    result = get_trace_status(trace_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.post("/tool/update_contact_status")
async def api_update_contact_status(payload: Dict[str, Any]):
    """
    Update the status of a single contact within a trace.
    Called when a CHW completes a contact visit.

    Body:
      trace_id          — CT-XXXXXXXX (required)
      contact_id        — CON-XXXXXXXX (required)
      status            — contacted | assessed | cleared | confirmed (required)
      new_encounter_id  — if contact became a confirmed case (optional)
      notes             — CHW assessment notes (optional)
      chw_id            — CHW completing the visit (optional)
    """
    trace_id = payload.get("trace_id")
    contact_id = payload.get("contact_id")
    status = payload.get("status")

    if not trace_id or not contact_id or not status:
        raise HTTPException(
            status_code=400,
            detail="trace_id, contact_id, and status are required",
        )

    valid_statuses = {"contacted", "assessed", "cleared", "confirmed"}
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of: {valid_statuses}",
        )

    from agents.contact_tracing.agent import update_contact_status

    result = update_contact_status(
        trace_id=trace_id,
        contact_id=contact_id,
        status=status,
        new_encounter_id=payload.get("new_encounter_id"),
        notes=payload.get("notes", ""),
        chw_id=payload.get("chw_id", "unknown"),
    )

    # If a new confirmed case was found, publish event for secondary trace
    if result.get("escalation_triggered") and payload.get("new_encounter_id"):
        await swarm.bus.publish(
            SwarmEvent(
                "contact_trace.contact_confirmed",
                {
                    "trace_id": trace_id,
                    "contact_id": contact_id,
                    "new_encounter_id": payload["new_encounter_id"],
                },
                source="orchestrator",
            )
        )

    return result


@app.get("/tool/active_traces")
async def api_active_traces(
    county: Optional[str] = None,
    syndrome: Optional[str] = None,
    limit: int = 20,
):
    """
    List all active contact traces with summary statistics.
    Optionally filter by county and/or syndrome.
    """
    from agents.contact_tracing.agent import get_active_traces

    return get_active_traces(county=county, syndrome=syndrome, limit=limit)


@app.post("/tool/resolve_trace")
async def api_resolve_trace(payload: Dict[str, Any]):
    """
    Mark a contact trace as resolved.
    Called when all contacts are cleared or confirmed.

    Body:
      trace_id          — CT-XXXXXXXX (required)
      resolved_by       — user ID (optional, default 'system')
      resolution_notes  — summary notes (optional)
    """
    trace_id = payload.get("trace_id")
    if not trace_id:
        raise HTTPException(status_code=400, detail="trace_id is required")

    from agents.contact_tracing.agent import resolve_trace

    result = resolve_trace(
        trace_id=trace_id,
        resolved_by=payload.get("resolved_by", "system"),
        resolution_notes=payload.get("resolution_notes", ""),
    )

    await swarm.bus.publish(
        SwarmEvent(
            "contact_trace.resolved",
            result,
            source="orchestrator",
        )
    )
    return result


@app.get("/health/contact_tracing")
async def health_contact_tracing():
    """Health check for the Contact Tracing Agent."""
    mongodb_ok = data_agent.connected
    return {
        "mongodb_connected": mongodb_ok,
        "capabilities": [
            "initiate_contact_trace",
            "trace_outbreak_cluster",
            "update_contact_status",
            "scan_overdue_contacts",
            "get_trace_status",
            "resolve_trace",
        ],
    }


# ---------------------------------------------------------------------------
# Agent Observability (Logs)
# ---------------------------------------------------------------------------


@app.get("/swarm/agent_logs")
async def api_get_agent_logs(session_id: Optional[str] = None, limit: int = 50):
    """Fetch recent vectorized agent decision-making logs."""
    from agents.data.agent import query_agent_logs

    try:
        result = query_agent_logs(session_id, limit)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/swarm/agent_logs/search")
async def api_search_agent_logs(query: str, limit: int = 10):
    """Semantic Vector Search over agent decision logs."""
    from agents.data.agent import search_agent_logs

    try:
        result = search_agent_logs(query, limit)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

# ── Static file serving + SPA catch-all (production / Cloud Run) ─────────────
# Must be registered AFTER all API routes so API paths are not shadowed.
# The Angular app is built into /app/static by the Docker Stage 2.
if _STATIC_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    # Serve assets (JS, CSS, images) at /assets/* directly
    app.mount("/assets", StaticFiles(directory=str(_STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_catch_all(full_path: str):
        """
        SPA catch-all: serve index.html for any path not matched by an API route.
        Required for Angular client-side routing (History API).
        Skip known API path prefixes to avoid shadowing them.
        """
        _API_PREFIXES = (
            "api/", "health", "status", "tool/", "swarm/", "encounter",
            "intake/", "surveillance/", "geo/", "adk/", "notify/", "workflows",
        )
        if full_path.startswith(_API_PREFIXES):
            from fastapi import HTTPException as _HTTPException
            raise _HTTPException(status_code=404, detail="API route not found")

        index = _STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"error": "Frontend not built into this image"}
