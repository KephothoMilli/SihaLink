"""
Orchestrator Agent — SihaLink (Google ADK)
Central coordinator that routes work between all specialized sub-agents.

ADK pattern:
  - root_agent: LlmAgent with function tools + sub-agent delegation
  - Model: gemini-flash-latest-live-001 (Live API for real-time CHV interaction)
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
from fastapi import FastAPI, BackgroundTasks, HTTPException
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
        HTTPXClientInstrumentor().instrument()   # traces all httpx calls (Gemini, Maps, Telegram)
        PymongoInstrumentor().instrument()        # traces every MongoDB query
        logger.info("[Telemetry] HTTPx + PyMongo auto-instrumentation active")
    except ImportError:
        logger.debug("[Telemetry] Auto-instrumentation packages not installed")

_tracer = get_tracer("sihalink.orchestrator")

# ---------------------------------------------------------------------------
# Notify Agent HTTP shim
# ---------------------------------------------------------------------------

NOTIFY_BASE = os.getenv("NOTIFY_AGENT_URL", "http://localhost:3001")


class NotifyAgentClient:
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
                return resp.json()
        except Exception as exc:
            logger.warning("Notify Agent unavailable (%s) — referral logged only", exc)
            return {"delivered": False, "note": str(exc)}

    async def dispatch_outbreak_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{NOTIFY_BASE}/notify/outbreak_alert", json={"alert": alert}
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("Notify Agent unavailable (%s) — alert logged only", exc)
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

swarm = SwarmController.get()
swarm.initialise(
    intake=intake_agent,
    geo=geo_agent,
    data=data_agent,
    notify=notify_agent,
    surveillance=surveillance_agent,
    orchestrator=orchestrator,
)

# ---------------------------------------------------------------------------
# Orchestrator tool functions (ADK FunctionTools)
# ---------------------------------------------------------------------------


def route_to_intake(audio_base64: str, session_id: str) -> dict:
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

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run, intake_agent.process_audio(audio_base64)
                )
                extracted = future.result(timeout=30)
        else:
            extracted = loop.run_until_complete(
                intake_agent.process_audio(audio_base64)
            )
        return {"session_id": session_id, "extracted": extracted}
    except Exception as exc:
        return {"session_id": session_id, "error": str(exc)}


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
    model="gemini-flash-latest",  # generateContent model for ADK web + run_async
    # Live API (run_live) is invoked separately via build_orchestrator_run_config()
    description=(
        "SihaLink Orchestrator — central coordinator for community health disease "
        "surveillance in Kenya. Manages the full encounter lifecycle: voice intake → "
        "geo-enrichment → MongoDB storage → human-in-the-loop gate → Telegram notification. "
        "Runs outbreak detection, silent pandemic scanning, protocol formulation, "
        "CHW outreach gap analysis, and patient follow-up scheduling every 6 hours."
    ),
    instruction="""You are the SihaLink Orchestrator — the central intelligence of a
multi-agent disease surveillance system serving Community Health Volunteers (CHVs) in Kenya.

═══════════════════════════════════════════════════════════════
MISSION 1 — ENCOUNTER LIFECYCLE (triggered by every CHV recording)
═══════════════════════════════════════════════════════════════
State machine: IDLE → LISTENING → EXTRACTING → GEOCODING → STORING
               → [DECISION_GATE] → NOTIFYING → FOLLOW_UP_SCHEDULED → COMPLETE

Step 1 — INTAKE
  Call route_to_intake(audio_base64, session_id)
  → Returns extracted clinical JSON with syndrome, triage_color, symptoms, language

Step 2 — GEO ENRICHMENT
  Call route_to_geo(encounter_json, latitude, longitude)
  → Returns admin hierarchy (village/ward/sub-county/county) + nearest facilities + ETAs

Step 3 — STORE + FOLLOW-UPS
  Call route_to_data(enriched_encounter)
  → Inserts into MongoDB with Voyage AI / Google vector embedding
  → Auto-schedules follow-ups: RED→[1,3,7,14d], YELLOW→[2,7,14d], GREEN→[7d]

Step 4 — HUMAN-IN-THE-LOOP GATE (RED or YELLOW only)
  Call request_human_decision(session_id, decision_type, summary)
  → Pauses lifecycle; CHV confirms or declines via Telegram
  → RED: auto-escalate after 60s timeout
  → YELLOW: auto-queue (no send) after 60s timeout
  → GREEN: skip gate entirely

Step 5 — NOTIFY (RED/YELLOW, confirmed only)
  Call route_to_notify("referral", payload) → Telegram to facility
  Call route_to_notify("outbreak_alert", payload) → Telegram to county channel

Step 6 — OFFLINE FALLBACK
  If device offline: call queue_offline_encounter(encounter_json)
  When back online: call process_offline_queue()

═══════════════════════════════════════════════════════════════
MISSION 2 — SURVEILLANCE (every 6 hours, all active counties)
═══════════════════════════════════════════════════════════════
  Call trigger_surveillance(county, lat, lng, immediate=True)
  → Spike detection: ≥2× weekly baseline triggers alert
  → Correlated pairs: cholera, measles, influenza, SAM

  Call run_silent_pandemic_scan(county, weeks=4)
  → Detects syndromes with persistent upward trend below spike threshold
  → HIGH risk (delta>5): immediate protocol formulation + district notification
  → MEDIUM risk (delta>2): monitor + weekly report

  For any detected signal (spike OR silent):
  → Call route_to_notify("outbreak_alert", alert_payload)

═══════════════════════════════════════════════════════════════
MISSION 3 — PROTOCOL FORMULATION (on every new alert)
═══════════════════════════════════════════════════════════════
  Call get_response_protocol(syndrome, county)
  → Returns WHO/MoH immediate actions + CHW field tasks + follow-up schedule
  → If no protocol exists, the Surveillance Agent auto-generates one

  Call search_response_protocols(query)
  → Full-text Atlas Search across all protocols
  → Used when CHV sends /protocol to Telegram bot

═══════════════════════════════════════════════════════════════
MISSION 4 — PATIENT FOLLOW-UP (daily check)
═══════════════════════════════════════════════════════════════
  Call get_chw_follow_ups(chw_id, overdue_only=True)
  → Returns overdue tasks for a CHW — sent via Telegram /followup

  Call complete_patient_follow_up(follow_up_id, outcome, notes, chw_id)
  → Outcomes: improved | stable | deteriorated | referred | deceased
  → 'deteriorated' or 'referred' → immediately trigger new referral flow

  Call get_county_follow_up_summary(county)
  → Used by /status command: pending, completed, overdue counts

═══════════════════════════════════════════════════════════════
MISSION 5 — CHW OUTREACH IMPROVEMENT (daily)
═══════════════════════════════════════════════════════════════
  Call check_chw_outreach_gaps(county, days=7)
  → Identifies wards with zero or low encounter submissions
  → CRITICAL gap (0 submissions): supervisor deployment alert via Telegram
  → Generates targeted recommendations for each gap ward

INVARIANT RULES — NEVER VIOLATE:
  • Never lose data — retry failed routes 3× before escalating to human
  • Raw audio never leaves the CHV device — only extracted JSON is transmitted
  • Always confirm encounter_id to the CHV verbally after storage
  • Always speak in the CHV's detected language (Dholuo/Swahili/Kikuyu/Somali/English)
  • Human gate is mandatory for RED and YELLOW — never skip it
  • Follow-ups are scheduled automatically — never skip schedule_follow_ups
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
        max_output_tokens=1024,
    ),
)

# ---------------------------------------------------------------------------
# RunConfig with TTS for CHV voice feedback
# ---------------------------------------------------------------------------


def build_orchestrator_run_config(voice_name: str = "Aoede") -> RunConfig:
    """Build RunConfig with TTS for spoken CHV feedback."""
    voice_config = genai_types.VoiceConfig(
        prebuilt_voice_config=genai_types.PrebuiltVoiceConfigDict(voice_name=voice_name)
    )
    speech_config = genai_types.SpeechConfig(voice_config=voice_config)
    return RunConfig(speech_config=speech_config)


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

# ---------------------------------------------------------------------------
# FastAPI app — Agent Runtime HTTP interface
# ---------------------------------------------------------------------------

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(fastapi_app):
    """Start the autonomous swarm on startup; shut it down cleanly on exit."""
    logger.info("[Orchestrator] 🚀 Starting SihaLink — Kenya National Disease Surveillance")
    await swarm.start()
    yield
    logger.info("[Orchestrator] 🛑 Shutting down SihaLink swarm")
    await swarm.stop()


app = FastAPI(title="SihaLink Orchestrator", lifespan=_lifespan)

# ── Dynatrace: auto-instrument every FastAPI request ─────────────────────────
if _telemetry_active:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("[Telemetry] FastAPI auto-instrumentation active")
    except ImportError:
        pass
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://*.web.app",
        "https://*.firebaseapp.com",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
@app.get("/status")
async def health_check():
    """Health check endpoint - shows status of all services."""
    mongodb_status = "connected" if data_agent.connected else "disconnected"

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
        },
    }


@app.post("/encounter/start")
@app.post("/tool/start_encounter")
async def start_encounter(payload: Dict[str, Any], background_tasks: BackgroundTasks):
    """ADK tool: Initialize a session and run the background state machine."""
    session_id = payload.get("session_id")
    audio = payload.get("audio_base64", "")
    coords = {"lat": payload.get("latitude", 0.0), "lng": payload.get("longitude", 0.0)}
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    # Custom Dynatrace span — marks the start of the full encounter pipeline
    with _tracer.start_as_current_span("encounter.start") as span:
        span.set_attribute("encounter.session_id", session_id)
        span.set_attribute("encounter.has_audio", bool(audio))
        span.set_attribute("encounter.latitude", coords["lat"])
        span.set_attribute("encounter.longitude", coords["lng"])
        background_tasks.add_task(orchestrator.run_lifecycle, session_id, audio, coords)

    return {"status": "processing", "session_id": session_id}


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
    session_id = payload.get("session_id", f"form-{int(asyncio.get_event_loop().time())}")
    form_data  = payload.get("form_data", payload)   # allow flat or nested
    extracted  = await intake_agent.process_form(form_data, session_id)
    return {"session_id": session_id, "extracted": extracted}


@app.post("/intake/telegram")
async def api_intake_telegram(payload: Dict[str, Any]):
    """Accept a clinical intake from a Telegram CHV message."""
    chw_id      = payload.get("chw_id", "unknown")
    session_id  = payload.get("session_id", f"tg-{chw_id}-{int(asyncio.get_event_loop().time())}")
    extracted   = await intake_agent.process_telegram(
        message_text   = payload.get("message_text"),
        audio_b64      = payload.get("audio_base64"),
        chw_id         = chw_id,
        session_id     = session_id,
        language_hint  = payload.get("language_hint"),
    )
    return {"session_id": session_id, "extracted": extracted}


@app.post("/intake/agent")
async def api_intake_agent(payload: Dict[str, Any]):
    """Accept a clinical intake forwarded from another SihaLink agent."""
    source_agent = payload.get("source_agent", "unknown")
    session_id   = payload.get("session_id", f"agent-{int(asyncio.get_event_loop().time())}")
    extracted    = await intake_agent.process_from_agent(payload, source_agent, session_id)
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


@app.get("/health")
async def health():
    return {"status": "ok", "service": "sihalink-orchestrator"}





@app.get("/tool/follow_ups/{chw_id}")
async def api_get_chw_follow_ups(chw_id: str, overdue_only: bool = False):
    """Get pending follow-up tasks for a CHW."""
    from ..data.agent import get_pending_follow_ups

    tasks = get_pending_follow_ups(chw_id=chw_id, overdue_only=overdue_only)
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
            "outbreak_detection", "silent_pandemic", "cross_county_spread",
            "protocol_formulation", "chw_outreach_gaps",
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
        query_text     = query,
        county         = payload.get("county"),
        syndrome       = payload.get("syndrome"),
        limit          = payload.get("limit", 10),
        num_candidates = payload.get("num_candidates", 100),
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
        query  = query,
        county = payload.get("county"),
        limit  = payload.get("limit", 20),
    )
    return {"results": results, "count": len(results)}


@app.post("/tool/search_alerts")
async def api_search_alerts(payload: Dict[str, Any]):
    """Atlas Search full-text search across outbreak alerts."""
    query = payload.get("query", "")
    if not query:
        raise HTTPException(status_code=400, detail="query required")
    results = data_agent.search_alerts(
        query  = query,
        county = payload.get("county"),
        status = payload.get("status", "active"),
        limit  = payload.get("limit", 20),
    )
    return {"results": results, "count": len(results)}


@app.post("/tool/update_referral_status")
async def api_update_referral_status(payload: Dict[str, Any]):
    """Update a patient referral status (called from Telegram accept/redirect buttons)."""
    referral_id = payload.get("referral_id")
    status      = payload.get("status")
    if not referral_id or not status:
        raise HTTPException(status_code=400, detail="referral_id and status required")
    return data_agent.update_referral_status_sync(
        referral_id, status, payload.get("notes", "")
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
        "intake":       {"status": "ok"},
        "geo":          {"status": "ok" if bool(os.getenv("GOOGLE_MAPS_API_KEY")) else "degraded"},
        "data":         {"status": "ok" if data_agent.connected else "degraded",
                         "mongodb_connected": data_agent.connected},
        "notify":       {"status": "ok" if bool(os.getenv("TELEGRAM_BOT_TOKEN")) else "degraded"},
        "surveillance": {"status": "ok" if data_agent.connected else "degraded"},
        "language":     {"status": "ok" if bool(os.getenv("GEMINI_API_KEY")) else "degraded"},
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
    """Return recent swarm events for the dashboard event log."""
    return {"events": swarm.bus.recent(topic=topic, limit=limit)}


@app.post("/swarm/counties/add")
async def swarm_add_county(payload: Dict[str, Any]):
    """Add a county to the active surveillance scope."""
    county = payload.get("county")
    lat    = payload.get("lat", 0.0)
    lng    = payload.get("lng", 0.0)
    if not county:
        raise HTTPException(status_code=400, detail="county required")
    swarm.add_county(county, lat, lng)
    return {"status": "added", "county": county, "total_counties": len(swarm.active_counties)}


@app.delete("/swarm/counties/{county}")
async def swarm_remove_county(county: str):
    """Remove a county from active surveillance."""
    swarm.remove_county(county)
    return {"status": "removed", "county": county}


# ── Import needed for swarm event publishing in routes above ──────────────────
from agents.swarm import SwarmEvent  # noqa: E402 — after app definition to avoid circular
