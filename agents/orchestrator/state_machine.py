"""
Orchestrator State Machine — SihaLink
Manages the full encounter lifecycle with retry logic, offline queuing,
and a real asyncio.Future-based human-in-the-loop gate.

State flow (happy path):
  IDLE → LISTENING → EXTRACTING → GEOCODING → STORING
       → FOLLOW_UP_SCHEDULED
       → [ALERTING]            (RED/YELLOW only — writes referral record)
       → [DECISION_GATE]       (RED/YELLOW only — CHV confirms or declines)
       → [NOTIFYING]           (RED/YELLOW, confirmed — Telegram dispatch)
       → COMPLETE

Offline path:
  IDLE → LISTENING → EXTRACTING → OFFLINE_QUEUED → SYNCING → COMPLETE

Follow-up schedule written at FOLLOW_UP_SCHEDULED:
  RED    → day 1, 3, 7, 14
  YELLOW → day 2, 7, 14
  GREEN  → day 7
"""

import asyncio
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger("SihaLink-Orchestrator")


class EncounterState(Enum):
    IDLE               = "IDLE"
    LISTENING          = "LISTENING"
    EXTRACTING         = "EXTRACTING"
    GEOCODING          = "GEOCODING"
    STORING            = "STORING"
    ALERTING           = "ALERTING"
    DECISION_GATE      = "DECISION_GATE"
    CLARIFICATION_GATE = "CLARIFICATION_GATE"
    NOTIFYING          = "NOTIFYING"
    FOLLOW_UP_SCHEDULED = "FOLLOW_UP_SCHEDULED"   # follow-ups written to MongoDB
    COMPLETE           = "COMPLETE"
    OFFLINE_QUEUED     = "OFFLINE_QUEUED"
    SYNCING            = "SYNCING"
    FAILED             = "FAILED"


class Orchestrator:
    def __init__(self, intake_agent, geo_agent, data_agent, notify_agent):
        self.intake = intake_agent
        self.geo = geo_agent
        self.data = data_agent
        self.notify = notify_agent

        # session_id → session dict
        self.sessions: Dict[str, Dict[str, Any]] = {}

        # session_id → asyncio.Future for human-in-the-loop gate
        self._pending_gates: Dict[str, asyncio.Future] = {}

        # In-memory offline queue (persisted to SQLite in production)
        self.offline_queue: list[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Main lifecycle
    # ------------------------------------------------------------------

    async def run_lifecycle(
        self,
        session_id: str,
        audio_payload: str = "",
        coords: Dict[str, float] = None,
        form_data: Optional[Dict] = None,
        telegram_payload: Optional[Dict] = None,
    ):
        """
        Full lifecycle for a single CHV encounter.

        Steps:
          1. EXTRACTING        — audio/text/form → clinical JSON (Gemini Live API)
          1b. CLARIFICATION    — pause and loop up to 2 rounds if clarification needed
          2. GEOCODING         — GPS → admin hierarchy + facilities (Google Maps)
          3. STORING           — insert into MongoDB with vector embedding
          4. FOLLOW_UP_SCHEDULED — auto-schedule follow-up tasks (non-fatal)
          5. ALERTING          — write referral record (RED/YELLOW only)
          6. DECISION_GATE     — pause for CHV confirmation (RED/YELLOW only)
          7. NOTIFYING         — Telegram dispatch (confirmed RED/YELLOW only)
          8. COMPLETE
        """
        if not coords:
            coords = {"lat": 0.0, "lng": 0.0}

        self.sessions[session_id] = {
            "state": EncounterState.LISTENING,
            "started_at": datetime.utcnow().isoformat(),
            "retries": 0,
        }
        logger.info("▶ Session %s started", session_id)

        try:
            # 1. INTAKE — speech/text/form → clinical JSON
            if form_data:
                extracted_json = await self._transition(
                    session_id,
                    EncounterState.EXTRACTING,
                    self.intake.process_form,
                    form_data,
                    session_id,
                )
            elif telegram_payload:
                extracted_json = await self._transition(
                    session_id,
                    EncounterState.EXTRACTING,
                    self.intake.process_telegram,
                    telegram_payload.get("message_text"),
                    telegram_payload.get("audio_base64"),
                    telegram_payload.get("chw_id", "unknown"),
                    session_id,
                    telegram_payload.get("language_hint"),
                )
            else:
                extracted_json = await self._transition(
                    session_id,
                    EncounterState.EXTRACTING,
                    self.intake.process_audio,
                    audio_payload,
                )

            # 1b. CLARIFICATION GATE — pause and ask questions if needed
            rounds = 0
            while extracted_json.get("clarification_needed") and rounds < 2:
                question = extracted_json.get("clarification_question", "Please provide more details.")
                answer = await self._wait_for_clarification_gate(session_id, question)
                if not answer:
                    break
                # Call clarify on intake agent
                extracted_json = await self._transition(
                    session_id,
                    EncounterState.EXTRACTING,
                    self.intake.clarify,
                    extracted_json,
                    answer,
                    session_id,
                )
                rounds += 1

            self.sessions[session_id]["extracted"] = extracted_json

            # Notify CHV of analysis completion if triggered from Telegram
            triage = extracted_json.get("triage_color", "GREEN")
            emoji = "🔴" if triage == "RED" else "🟡" if triage == "YELLOW" else "🟢"
            conf = round(extracted_json.get("confidence", 0) * 100)
            text = (
                f"{emoji} *Encounter Analysis Complete*\n"
                f"━━━━━━━━━━━━━━\n"
                f"*Syndrome:*  {extracted_json.get('syndrome', '—')}\n"
                f"*Triage:*    {triage}\n"
                f"*Complaint:* {extracted_json.get('chief_complaint', '—')}\n"
                f"*Confidence:* {conf}%\n"
                f"*Session:* `{session_id}`"
            )
            if session_id.startswith("tg-"):
                chat_id = session_id.split("-")[1]
                await self.notify.dispatch_message(chat_id, text)

            # 2. GEOCODING — GPS → admin hierarchy + facilities
            enriched_json = await self._transition(
                session_id,
                EncounterState.GEOCODING,
                self.geo.enrich_location,
                extracted_json,
                coords,
            )

            # 3. STORING — insert into MongoDB with embedding
            encounter_id = await self._transition(
                session_id,
                EncounterState.STORING,
                self.data.insert_encounter,
                enriched_json,
            )
            enriched_json["encounter_id"] = encounter_id
            self.sessions[session_id]["encounter_id"] = encounter_id

            # 3b. FOLLOW_UP_SCHEDULED — auto-schedule follow-up tasks
            try:
                fu_result = await self.data.schedule_follow_ups(enriched_json)
                self.sessions[session_id]["state"] = EncounterState.FOLLOW_UP_SCHEDULED
                self.sessions[session_id]["follow_ups_scheduled"] = fu_result.get(
                    "scheduled_count", 0
                )
                logger.info(
                    "Session %s: %d follow-up(s) scheduled",
                    session_id,
                    fu_result.get("scheduled_count", 0),
                )
            except Exception as exc:
                # Follow-up scheduling failure is non-fatal — log and continue
                logger.warning(
                    "Follow-up scheduling failed for %s (non-fatal): %s", session_id, exc
                )

            # 4. ALERTING — create referral/alert record for RED/YELLOW
            if triage in ("RED", "YELLOW"):
                referral_id = await self._transition(
                    session_id,
                    EncounterState.ALERTING,
                    self.data.insert_referral,
                    enriched_json,
                )
                enriched_json["referral_id"] = referral_id
                self.sessions[session_id]["referral_id"] = referral_id

            # 5. DECISION GATE — human-in-the-loop for RED/YELLOW
            if triage in ("RED", "YELLOW"):
                confirmed = await self._wait_for_human_gate(
                    session_id, enriched_json
                )
                if not confirmed:
                    logger.info(
                        "Session %s: CHV declined referral/alert.", session_id
                    )
                    self.sessions[session_id]["state"] = EncounterState.COMPLETE
                    self.sessions[session_id]["outcome"] = "declined_by_chv"
                    return

            # 6. NOTIFYING — Telegram dispatch
            if triage in ("RED", "YELLOW"):
                await self._transition(
                    session_id,
                    EncounterState.NOTIFYING,
                    self.notify.dispatch_referral,
                    enriched_json,
                )

            self.sessions[session_id]["state"] = EncounterState.COMPLETE
            self.sessions[session_id]["completed_at"] = datetime.utcnow().isoformat()
            logger.info("✅ Session %s completed successfully.", session_id)

            if session_id.startswith("tg-"):
                chat_id = session_id.split("-")[1]
                if triage == "RED":
                    await self.notify.dispatch_message(
                        chat_id,
                        "🔴 *URGENT* — referral dispatched automatically to nearest facility."
                    )
                elif triage == "GREEN":
                    await self.notify.dispatch_message(
                        chat_id,
                        "🟢 Logged for routine 7-day follow-up. Thank you."
                    )

        except Exception as exc:
            logger.error("❌ Lifecycle failure for %s: %s", session_id, exc)
            self.sessions[session_id]["state"] = EncounterState.FAILED
            self.sessions[session_id]["error"] = str(exc)
            if session_id.startswith("tg-"):
                chat_id = session_id.split("-")[1]
                await self.notify.dispatch_message(
                    chat_id,
                    f"❌ Encounter processing failed: {str(exc)}\nPlease try again or contact support."
                )

    # ------------------------------------------------------------------
    # Clarification Gate
    # ------------------------------------------------------------------

    async def _wait_for_clarification_gate(self, session_id: str, question: str) -> str:
        """
        Pauses the lifecycle and waits for the CHV to answer the clarification question
        via POST /encounter/{session_id}/clarify.
        """
        self.sessions[session_id]["state"] = EncounterState.CLARIFICATION_GATE
        self.sessions[session_id]["gate_data"] = {
            "question": question,
        }
        logger.info("⏳ Waiting for CHV clarification — session %s", session_id)

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_gates[session_id] = future

        if session_id.startswith("tg-"):
            chat_id = session_id.split("-")[1]
            await self.notify.dispatch_message(chat_id, f"❓ {question}")

        try:
            answer = await asyncio.wait_for(asyncio.shield(future), timeout=60)
            return answer
        except asyncio.TimeoutError:
            logger.warning("Gate timeout for %s (clarification)", session_id)
            return ""
        finally:
            self._pending_gates.pop(session_id, None)

    # ------------------------------------------------------------------
    # State transition helper with retry + exponential backoff
    # ------------------------------------------------------------------

    async def _transition(self, session_id: str, next_state: EncounterState, func, *args):
        """
        Transition to next_state, call func(*args), retry up to 3 times.
        Raises on final failure so the lifecycle can mark the session FAILED.
        """
        self.sessions[session_id]["state"] = next_state
        max_retries = 3

        for attempt in range(max_retries):
            try:
                return await func(*args)
            except Exception as exc:
                logger.warning(
                    "Retry %d/%d for %s in session %s: %s",
                    attempt + 1,
                    max_retries,
                    next_state.value,
                    session_id,
                    exc,
                )
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s

    # ------------------------------------------------------------------
    # Human-in-the-loop gate
    # ------------------------------------------------------------------

    async def _wait_for_human_gate(
        self, session_id: str, data: Dict[str, Any]
    ) -> bool:
        """
        Pauses the lifecycle and waits for the CHV to confirm or decline
        via POST /encounter/{session_id}/confirm.

        Timeout: 60 seconds.
        - RED triage: auto-escalate (return True) on timeout
        - YELLOW triage: auto-queue (return False) on timeout
        """
        self.sessions[session_id]["state"] = EncounterState.DECISION_GATE
        self.sessions[session_id]["gate_data"] = {
            "triage_color": data.get("extracted", {}).get("triage_color", "YELLOW"),
            "summary": data.get("extracted", {}).get("chief_complaint", ""),
            "encounter_id": data.get("encounter_id"),
        }
        logger.info("⏳ Waiting for CHV confirmation — session %s", session_id)

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_gates[session_id] = future

        triage = data.get("extracted", {}).get("triage_color", "YELLOW")
        timeout = 60

        if session_id.startswith("tg-"):
            chat_id = session_id.split("-")[1]
            reply_markup = {
                "inline_keyboard": [[
                    {"text": "✅ Confirm Referral", "callback_data": f"confirm_{session_id}"},
                    {"text": "❌ Decline", "callback_data": f"decline_{session_id}"}
                ]]
            }
            await self.notify.dispatch_message(
                chat_id,
                "Confirm patient referral to nearest facility?",
                reply_markup=reply_markup
            )

        try:
            result = await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
            return result
        except asyncio.TimeoutError:
            if triage == "RED":
                logger.warning(
                    "Gate timeout for %s (RED) — auto-escalating", session_id
                )
                return True  # RED: escalate automatically
            else:
                logger.warning(
                    "Gate timeout for %s (YELLOW) — queuing", session_id
                )
                return False
        finally:
            self._pending_gates.pop(session_id, None)

    def resolve_human_gate(self, session_id: str, confirmed: bool) -> bool:
        """
        Called by POST /encounter/{session_id}/confirm.
        Resolves the pending Future so the lifecycle can continue.
        Returns True if a gate was found and resolved, False otherwise.
        """
        future = self._pending_gates.get(session_id)
        if future and not future.done():
            future.set_result(confirmed)
            logger.info(
                "Gate resolved for session %s: confirmed=%s", session_id, confirmed
            )
            return True
        return False

    # ------------------------------------------------------------------
    # Offline queue
    # ------------------------------------------------------------------

    def queue_offline_encounter(self, encounter_doc: Dict[str, Any]) -> int:
        """Store an encounter locally when offline."""
        encounter_doc["queued_at"] = datetime.utcnow().isoformat()
        encounter_doc["synced"] = False
        self.offline_queue.append(encounter_doc)

        sid = encounter_doc.get("session_id", f"offline-{len(self.offline_queue)}")
        self.sessions[sid] = {
            "state": EncounterState.OFFLINE_QUEUED,
            "queued_at": encounter_doc["queued_at"],
        }
        logger.info(
            "Encounter queued offline. Queue size: %d", len(self.offline_queue)
        )
        return len(self.offline_queue)

    async def process_offline_queue(self) -> Dict[str, Any]:
        """
        Pull all unsynced encounters and route through the full pipeline.
        Called when connectivity returns.
        """
        total = len(self.offline_queue)
        processed = 0
        errors = 0

        while self.offline_queue:
            item = self.offline_queue.pop(0)
            sid = item.get("session_id", f"offline-{processed + 1}")
            self.sessions[sid] = {"state": EncounterState.SYNCING}

            try:
                await self.run_lifecycle(
                    sid,
                    item.get("audio_base64", ""),
                    item.get("coords", {"lat": 0.0, "lng": 0.0}),
                )
                processed += 1
            except Exception as exc:
                logger.error("Offline sync failed for %s: %s", sid, exc)
                errors += 1

        logger.info(
            "Offline queue processed: %d/%d succeeded, %d errors",
            processed,
            total,
            errors,
        )
        return {"total": total, "processed": processed, "errors": errors}
