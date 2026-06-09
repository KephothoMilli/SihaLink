"""
Data Agent — SihaLink (Google ADK)
MongoDB MCP superpower layer exposed as ADK FunctionTools.

Collections covered:
  encounters  — insert, batch, sync, vector search index
  alerts      — query, acknowledge, resolve
  referrals   — insert, update status, query
  follow_ups  — schedule, list pending, complete, reschedule, summary
  chws        — register, get, list, update activity
  protocols   — upsert, get, full-text search, list

ADK pattern:
  - root_agent: LlmAgent with 20 function tools
  - Model: gemini-3.5-flash
  - All tools are plain sync functions; async DataAgent calls run in
    a ThreadPoolExecutor so the ADK event loop stays healthy.
"""

import asyncio
import concurrent.futures
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import uuid

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from .mcp_client import DataAgent as _DataClient

logger = logging.getLogger("SihaLink-Data")

# ── Singleton DataAgent (lazy — requires MONGODB_ATLAS_URI at runtime) ────────
_data_client: Optional[_DataClient] = None


def _get_client() -> _DataClient:
    global _data_client
    if _data_client is None:
        _data_client = _DataClient()
    return _data_client


# ── Helper: run an async coroutine from a sync ADK tool function ──────────────
def _run(coro):
    """
    Execute an async DataAgent method from a synchronous ADK tool.
    Uses a fresh event loop in a ThreadPoolExecutor to avoid conflicts
    with the ADK runner's own event loop.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result(timeout=30)


# ═════════════════════════════════════════════════════════════════════════════
# TOOL GROUP 1 — ENCOUNTERS
# ═════════════════════════════════════════════════════════════════════════════


def insert_encounter(enriched_encounter: Dict[str, Any]) -> Dict[str, Any]:
    """
    Insert a geo-enriched clinical encounter into MongoDB.
    Automatically generates a semantic vector embedding (Voyage AI voyage-3
    or Google text-embedding-004) and attaches it for Atlas Vector Search.
    Also schedules patient follow-up tasks based on triage color.

    Args:
        enriched_encounter: Fully enriched encounter JSON from the Geo Agent.
            Must include: extracted (syndrome, triage_color, symptoms),
            admin_hierarchy (county, ward), location (GeoJSON Point),
            nearest_facilities, chw_id, session_id.

    Returns:
        dict with inserted_id (str), status, and scheduled_follow_ups count.
    """
    try:
        client = _get_client()
        inserted_id = _run(client.insert_encounter(enriched_encounter))
        enriched_encounter["encounter_id"] = inserted_id

        # Auto-schedule follow-ups after every encounter
        fu_result = _run(client.schedule_follow_ups(enriched_encounter))

        return {
            "inserted_id": inserted_id,
            "status": "stored",
            "scheduled_follow_ups": fu_result.get("scheduled_count", 0),
        }
    except Exception as exc:
        logger.error("insert_encounter failed: %s", exc)
        return {"error": str(exc), "status": "failed"}


def sync_offline_encounters(encounters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Batch-insert encounters queued while the CHV device was offline.
    Processes in batches of 50. Generates embeddings for each.
    Schedules follow-ups for each synced encounter.

    Args:
        encounters: List of encounter dicts from the offline queue.
            Each must have session_id, audio_base64 (optional),
            extracted, admin_hierarchy, location.

    Returns:
        dict with total, synced, errors counts.
    """
    try:
        return _run(_get_client().sync_offline_encounters(encounters))
    except Exception as exc:
        logger.error("sync_offline_encounters failed: %s", exc)
        return {"total": len(encounters), "synced": 0, "errors": len(encounters)}


def create_vector_search_index() -> Dict[str, Any]:
    """
    Idempotently create the Atlas Vector Search index on encounters.embedding.
    Uses pymongo 4.6+ SearchIndexModel API. Requires MongoDB Atlas M10+ cluster.
    Supports both 768-dim (Google) and 1024-dim (Voyage AI) embeddings.
    Safe to call on every startup — will not recreate if already exists.

    Returns:
        dict with created (bool), index name, and dimension used.
    """
    try:
        from .index import IndexManager
        from .embedding_service import get_embedding_dim

        mgr = IndexManager(_get_client().db)
        dim = get_embedding_dim()
        result = mgr.ensure_all_indexes(embedding_dim=dim)
        return {"status": "ok", "embedding_dim": dim, "details": result}
    except Exception as exc:
        logger.error("create_vector_search_index failed: %s", exc)
        return {"created": False, "error": str(exc)}


# ═════════════════════════════════════════════════════════════════════════════
# TOOL GROUP 2 — ALERTS
# ═════════════════════════════════════════════════════════════════════════════


def query_active_alerts(county: Optional[str] = None) -> Dict[str, Any]:
    """
    Query active outbreak alerts from MongoDB, optionally filtered by county.
    Returns the 20 most recent active alerts sorted by timestamp descending.
    Includes spike alerts, silent pandemic signals, and cross-county spread alerts.

    Args:
        county: Optional Kenya county name (e.g., 'Homa Bay', 'Kisumu').
                If omitted, returns alerts from all counties.

    Returns:
        dict with alerts (list of alert dicts) and count (int).
    """
    try:
        alerts = _get_client().query_active_alerts(county)
        return {"alerts": alerts, "count": len(alerts)}
    except Exception as exc:
        logger.error("query_active_alerts failed: %s", exc)
        return {"alerts": [], "count": 0, "error": str(exc)}


def update_alert_status(
    alert_id: str, status: str, user_id: str = "system"
) -> Dict[str, Any]:
    """
    Update the status of an outbreak alert.
    Used by district officers to acknowledge alerts via Telegram or dashboard.

    Args:
        alert_id: MongoDB ObjectId string of the alert document.
        status:   New status — 'acknowledged' or 'resolved'.
        user_id:  Telegram username or system ID (for audit trail).

    Returns:
        dict with matched_count and modified_count.
    """
    try:
        return _run(_get_client().update_alert_status(alert_id, status, user_id))
    except Exception as exc:
        logger.error("update_alert_status failed: %s", exc)
        return {"error": str(exc)}


def resolve_alert(
    alert_id: str, notes: str = "", user_id: str = "system"
) -> Dict[str, Any]:
    """
    Mark an outbreak alert as resolved with optional resolution notes.
    Records who resolved it and when for the audit trail.

    Args:
        alert_id: MongoDB ObjectId string of the alert.
        notes:    Optional resolution notes from the district officer.
        user_id:  Telegram username or system ID.

    Returns:
        dict with matched_count and modified_count.
    """
    try:
        return _run(_get_client().resolve_alert(alert_id, notes, user_id))
    except Exception as exc:
        logger.error("resolve_alert failed: %s", exc)
        return {"error": str(exc)}


# ═════════════════════════════════════════════════════════════════════════════
# TOOL GROUP 3 — REFERRALS
# ═════════════════════════════════════════════════════════════════════════════


def insert_referral(encounter_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a patient referral record in the dedicated `referrals` collection.
    Called for every RED or YELLOW triage encounter after CHV confirmation.
    Includes nearest facility, ETA, patient demographics, and CHW identity.

    Args:
        encounter_doc: Enriched encounter with encounter_id set.
            Must include: extracted (triage_color, syndrome, age, sex),
            admin_hierarchy, nearest_facilities, chw_id.

    Returns:
        dict with referral_id (str) and status.
    """
    try:
        referral_id = _run(_get_client().insert_referral(encounter_doc))
        return {"referral_id": referral_id, "status": "stored"}
    except Exception as exc:
        logger.error("insert_referral failed: %s", exc)
        return {"error": str(exc), "status": "failed"}


def update_referral_status(
    referral_id: str, status: str, notes: str = ""
) -> Dict[str, Any]:
    """
    Update the status of a patient referral.
    Called by the receiving facility via Telegram inline keyboard.

    Args:
        referral_id: The REF-XXXXXXXX string from the referral document.
        status:      'accepted' | 'redirected' | 'completed' | 'cancelled'.
        notes:       Optional notes from the facility (e.g., redirect reason).

    Returns:
        dict with matched_count and modified_count.
    """
    try:
        return _run(_get_client().update_referral_status(referral_id, status, notes))
    except Exception as exc:
        logger.error("update_referral_status failed: %s", exc)
        return {"error": str(exc)}


def query_referrals(
    county: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Query patient referrals with optional county and status filters.
    Used by the dashboard and Telegram /referrals command.

    Args:
        county: Optional county filter.
        status: Optional status filter — 'pending' | 'accepted' | 'completed'.
        limit:  Max results to return (default 20).

    Returns:
        dict with referrals (list) and count (int).
    """
    try:
        referrals = _get_client().query_referrals(county, status, limit)
        return {"referrals": referrals, "count": len(referrals)}
    except Exception as exc:
        logger.error("query_referrals failed: %s", exc)
        return {"referrals": [], "count": 0, "error": str(exc)}


# ═════════════════════════════════════════════════════════════════════════════
# TOOL GROUP 4 — FOLLOW-UPS
# ═════════════════════════════════════════════════════════════════════════════


def schedule_follow_ups(encounter_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Auto-schedule patient follow-up tasks for the CHW based on triage color.
    Creates individual follow-up documents in MongoDB with due dates.

    Schedule (days after encounter):
      RED    → day 1, 3, 7, 14  (daily monitoring then weekly)
      YELLOW → day 2, 7, 14     (48h check then weekly)
      GREEN  → day 7            (single routine check)

    Args:
        encounter_doc: Enriched encounter with encounter_id, chw_id,
                       extracted.triage_color, admin_hierarchy.

    Returns:
        dict with scheduled_count (int) and follow_up_ids (list of str).
    """
    try:
        return _run(_get_client().schedule_follow_ups(encounter_doc))
    except Exception as exc:
        logger.error("schedule_follow_ups failed: %s", exc)
        return {"scheduled_count": 0, "error": str(exc)}


def get_pending_follow_ups(
    chw_id: Optional[str] = None,
    county: Optional[str] = None,
    overdue_only: bool = False,
) -> Dict[str, Any]:
    """
    Retrieve pending follow-up tasks for a CHW or county.
    Used by the Telegram /followup command to show a CHW their task list.

    Args:
        chw_id:       Filter by specific CHW ID (e.g., 'CHW-A1B2C3').
        county:       Filter by county name.
        overdue_only: If True, return only tasks past their due_date.

    Returns:
        dict with follow_ups (list) and count (int).
    """
    try:
        tasks = _get_client().get_pending_follow_ups(chw_id, county, overdue_only)
        return {"follow_ups": tasks, "count": len(tasks)}
    except Exception as exc:
        logger.error("get_pending_follow_ups failed: %s", exc)
        return {"follow_ups": [], "count": 0, "error": str(exc)}


def complete_follow_up(
    follow_up_id: str,
    outcome: str,
    notes: str = "",
    chw_id: str = "unknown",
) -> Dict[str, Any]:
    """
    Mark a patient follow-up as completed with clinical outcome.
    Called by the CHV after visiting the patient.

    Args:
        follow_up_id: The FU-XXXXXXXX string from the follow-up document.
        outcome:      Patient outcome — one of:
                      'improved' | 'stable' | 'deteriorated' | 'referred' | 'deceased'
        notes:        Free-text CHV notes (voice-transcribed or typed).
        chw_id:       CHW who completed the follow-up.

    Returns:
        dict with matched_count and modified_count.
    """
    try:
        return _run(
            _get_client().complete_follow_up(follow_up_id, outcome, notes, chw_id)
        )
    except Exception as exc:
        logger.error("complete_follow_up failed: %s", exc)
        return {"error": str(exc)}


def reschedule_follow_up(
    follow_up_id: str,
    days_from_now: int,
    reason: str = "",
) -> Dict[str, Any]:
    """
    Reschedule a follow-up task to a new date.
    Used when the patient was unavailable or the CHW needs more time.

    Args:
        follow_up_id:  The FU-XXXXXXXX string.
        days_from_now: Number of days from today for the new due date.
        reason:        Optional reason for rescheduling.

    Returns:
        dict with matched_count and modified_count.
    """
    try:
        from datetime import timedelta

        new_due = datetime.now(timezone.utc) + timedelta(days=days_from_now)
        return _run(_get_client().reschedule_follow_up(follow_up_id, new_due, reason))
    except Exception as exc:
        logger.error("reschedule_follow_up failed: %s", exc)
        return {"error": str(exc)}


def get_follow_up_summary(county: str) -> Dict[str, Any]:
    """
    Get follow-up completion statistics for a county.
    Used by the Telegram /status command and the supervisor dashboard.

    Args:
        county: Kenya county name.

    Returns:
        dict with county, pending (int), completed (int), overdue (int).
    """
    try:
        return _get_client().get_follow_up_summary(county)
    except Exception as exc:
        logger.error("get_follow_up_summary failed: %s", exc)
        return {
            "county": county,
            "pending": 0,
            "completed": 0,
            "overdue": 0,
            "error": str(exc),
        }


# ═════════════════════════════════════════════════════════════════════════════
# TOOL GROUP 5 — CHWs
# ═════════════════════════════════════════════════════════════════════════════


def register_chw(chw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Register or update a Community Health Worker in the MongoDB registry.
    Called when a CHW first uses the Telegram bot (/register command).
    Idempotent — safe to call multiple times for the same CHW.

    Args:
        chw_data: dict with fields:
            chw_id (optional — auto-generated if absent),
            name (str), county (str), ward (str),
            telegram_id (int), phone (str, optional),
            supervisor_id (str, optional),
            languages (list[str], optional — defaults to ['Swahili', 'English']).

    Returns:
        dict with chw_id (str), upserted (bool), modified (int).
    """
    try:
        return _run(_get_client().register_chw(chw_data))
    except Exception as exc:
        logger.error("register_chw failed: %s", exc)
        return {"error": str(exc)}


def get_chw(chw_id: str) -> Dict[str, Any]:
    """
    Retrieve a CHW record by their CHW ID.

    Args:
        chw_id: The CHW-XXXXXX identifier string.

    Returns:
        CHW document dict, or dict with error key if not found.
    """
    try:
        doc = _get_client().get_chw(chw_id)
        return doc if doc else {"error": "CHW not found", "chw_id": chw_id}
    except Exception as exc:
        logger.error("get_chw failed: %s", exc)
        return {"error": str(exc)}


def list_chws(
    county: Optional[str] = None,
    ward: Optional[str] = None,
    status: str = "active",
) -> Dict[str, Any]:
    """
    List Community Health Workers filtered by county, ward, and status.
    Used by supervisors to see their team and identify inactive CHWs.

    Args:
        county: Optional county filter.
        ward:   Optional ward filter.
        status: 'active' | 'inactive' | 'suspended' (default 'active').

    Returns:
        dict with chws (list) and count (int).
    """
    try:
        chws = _get_client().list_chws(county, ward, status)
        return {"chws": chws, "count": len(chws)}
    except Exception as exc:
        logger.error("list_chws failed: %s", exc)
        return {"chws": [], "count": 0, "error": str(exc)}


# ═════════════════════════════════════════════════════════════════════════════
# TOOL GROUP 6 — PROTOCOLS
# ═════════════════════════════════════════════════════════════════════════════


def upsert_protocol(protocol_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Store or update a WHO/MoH response protocol in MongoDB.
    Called by the Surveillance Agent after formulating a protocol.
    Embeds the protocol text for semantic search.
    Keyed by (syndrome, county) — use county='all' for national protocols.

    Args:
        protocol_doc: Full protocol dict with fields:
            syndrome (str), county (str), alert_level (str),
            immediate_actions (list[str]), chw_actions (list[str]),
            follow_up_days (list[int]), reporting_threshold (int),
            who_idsr_code (str).

    Returns:
        dict with protocol_id (str), upserted (bool), modified (int).
    """
    try:
        return _run(_get_client().upsert_protocol(protocol_doc))
    except Exception as exc:
        logger.error("upsert_protocol failed: %s", exc)
        return {"error": str(exc)}


def get_protocol(syndrome: str, county: Optional[str] = None) -> Dict[str, Any]:
    """
    Retrieve the active response protocol for a syndrome.
    Prefers county-specific protocol; falls back to national ('all').
    Used by CHWs via the Telegram /protocol command.

    Args:
        syndrome: WHO IDSR syndrome category (e.g., 'cholera', 'measles').
        county:   Optional county for localised protocol.

    Returns:
        Protocol document dict, or dict with error if not found.
    """
    try:
        doc = _get_client().get_protocol(syndrome, county)
        return doc if doc else {"error": "Protocol not found", "syndrome": syndrome}
    except Exception as exc:
        logger.error("get_protocol failed: %s", exc)
        return {"error": str(exc)}


def search_protocols(query: str, limit: int = 5) -> Dict[str, Any]:
    """
    Full-text search across all protocols using Atlas Search.
    Enables CHWs to find protocols by keyword (e.g., 'ORS', 'dehydration').
    Falls back to regex search if Atlas Search index is not available.

    Args:
        query: Free-text search string (e.g., 'cholera treatment ORS').
        limit: Max results to return (default 5).

    Returns:
        dict with protocols (list) and count (int).
    """
    try:
        results = _get_client().search_protocols_fulltext(query, limit)
        return {"protocols": results, "count": len(results)}
    except Exception as exc:
        logger.error("search_protocols failed: %s", exc)
        return {"protocols": [], "count": 0, "error": str(exc)}


def list_protocols(county: Optional[str] = None) -> Dict[str, Any]:
    """
    List all active response protocols, optionally filtered by county.
    Returns both county-specific and national ('all') protocols.

    Args:
        county: Optional county filter. If None, returns all protocols.

    Returns:
        dict with protocols (list) and count (int).
    """
    try:
        results = _get_client().list_protocols(county)
        return {"protocols": results, "count": len(results)}
    except Exception as exc:
        logger.error("list_protocols failed: %s", exc)
        return {"protocols": [], "count": 0, "error": str(exc)}


# ═════════════════════════════════════════════════════════════════════════════
# TOOL GROUP 7 — AGENT LOGS
# ═════════════════════════════════════════════════════════════════════════════


def insert_agent_log(
    agent_name: str, step: str, detail: str, level: str, session_id: str
) -> Dict[str, Any]:
    """
    Insert a vectorized agent decision log.
    """
    try:
        inserted_id = _run(
            _get_client().insert_agent_log(agent_name, step, detail, level, session_id)
        )
        return {"inserted_id": inserted_id, "status": "stored"}
    except Exception as exc:
        logger.error("insert_agent_log failed: %s", exc)
        return {"error": str(exc), "status": "failed"}


def query_agent_logs(
    session_id: Optional[str] = None, limit: int = 50
) -> Dict[str, Any]:
    """Fetch recent agent logs."""
    try:
        results = _get_client().query_agent_logs(session_id, limit)
        return {"logs": results, "count": len(results)}
    except Exception as exc:
        logger.error("query_agent_logs failed: %s", exc)
        return {"logs": [], "count": 0, "error": str(exc)}


def search_agent_logs(query: str, limit: int = 10) -> Dict[str, Any]:
    """Semantic search over agent logs."""
    try:
        results = _get_client().search_agent_logs(query, limit)
        return {"logs": results, "count": len(results)}
    except Exception as exc:
        logger.error("search_agent_logs failed: %s", exc)
        return {"logs": [], "count": 0, "error": str(exc)}


def search_encounters(
    query: str, county: Optional[str] = None, limit: int = 20
) -> list:
    """Atlas Search full-text search across encounter records."""
    try:
        return _run(_get_client().search_encounters(query, county, limit))
    except Exception as exc:
        logger.error("search_encounters failed: %s", exc)
        return []


def search_alerts(
    query: str, county: Optional[str] = None, status: str = "active", limit: int = 20
) -> list:
    """Atlas Search full-text search across outbreak alerts."""
    try:
        return _run(_get_client().search_alerts(query, county, status, limit))
    except Exception as exc:
        logger.error("search_alerts failed: %s", exc)
        return []


def vector_search_protocols(query: str, limit: int = 5) -> list:
    """Semantic vector search across protocols."""
    try:
        return _run(_get_client().vector_search_protocols(query, limit))
    except Exception as exc:
        logger.error("vector_search_protocols failed: %s", exc)
        return []


# ═════════════════════════════════════════════════════════════════════════════
# DISEASE REFERENCE DATABASE (comprehensive disease information for data correction)
# ═════════════════════════════════════════════════════════════════════════════


def upsert_disease_reference(
    disease: str, disease_info: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Upsert comprehensive disease reference data to MongoDB.
    Used by Intake Agent for data correction and validation.

    Args:
        disease: Disease name (key from disease database)
        disease_info: Dictionary with clinical information, symptoms, management, etc.

    Returns:
        dict with upserted_id, status, and timestamp.
    """
    try:
        from agents.data.disease_reference import get_disease_info

        info = disease_info or get_disease_info(disease)
        if not info:
            return {"status": "error", "message": f"Disease '{disease}' not found"}

        doc = {
            "disease": disease.lower(),
            "name": info.get("name", disease),
            "category": info.get("category", ""),
            "synonyms": info.get("synonyms", []),
            "case_definition": info.get("case_definition", {}),
            "clinical_features": info.get("clinical_features", {}),
            "triage": info.get("triage", {}),
            "management": info.get("management", {}),
            "risk_factors": info.get("risk_factors", []),
            "transmission": info.get("transmission", ""),
            "kenya_context": info.get("kenya_context", {}),
            "updated_at": datetime.now(timezone.utc),
        }

        result = _run(
            _get_client().db.disease_reference.update_one(
                {"disease": disease.lower()}, {"$set": doc}, upsert=True
            )
        )

        return {
            "status": "success",
            "disease": disease,
            "upserted_id": str(result.upserted_id) if result.upserted_id else None,
            "modified_count": result.modified_count,
            "timestamp": doc["updated_at"].isoformat(),
        }
    except Exception as exc:
        logger.error("upsert_disease_reference failed for %s: %s", disease, exc)
        return {"status": "error", "disease": disease, "details": str(exc)}


def get_disease_reference(disease: str) -> Dict[str, Any]:
    """
    Retrieve disease reference information from MongoDB.

    Args:
        disease: Disease name

    Returns:
        dict with disease information or empty dict if not found.
    """
    try:
        result = _run(
            _get_client().db.disease_reference.find_one({"disease": disease.lower()})
        )
        if result:
            result["_id"] = str(result["_id"])
        return result or {}
    except Exception as exc:
        logger.error("get_disease_reference failed for %s: %s", disease, exc)
        return {}


def load_disease_references() -> Dict[str, Any]:
    """
    Load all disease references from the disease_reference module into MongoDB.
    Called during system initialization to seed the database.

    Returns:
        dict with count of diseases loaded and status.
    """
    try:
        from agents.data.disease_reference import DISEASE_DATABASE

        count = 0
        errors = []

        for disease_key, disease_data in DISEASE_DATABASE.items():
            try:
                result = upsert_disease_reference(disease_key, disease_data)
                if result.get("status") == "success":
                    count += 1
                else:
                    errors.append(
                        f"{disease_key}: {result.get('details', result.get('message'))}"
                    )
            except Exception as e:
                errors.append(f"{disease_key}: {str(e)}")

        logger.info("✅ Loaded %d disease references into MongoDB", count)

        return {
            "status": "success" if not errors else "partial",
            "diseases_loaded": count,
            "errors": errors if errors else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error("load_disease_references failed: %s", exc)
        return {"status": "error", "details": str(exc)}


def search_diseases_by_symptom(symptom: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Find diseases matching a specific symptom.
    Used by Intake Agent for syndrome suggestion and data correction.

    Args:
        symptom: Symptom keyword or phrase
        limit: Max results to return

    Returns:
        list of matching disease documents.
    """
    try:
        results = _run(
            _get_client()
            .db.disease_reference.find(
                {
                    "$or": [
                        {
                            "clinical_features": {
                                "$elemMatch": {"$regex": symptom, "$options": "i"}
                            }
                        },
                        {
                            "synonyms": {
                                "$elemMatch": {"$regex": symptom, "$options": "i"}
                            }
                        },
                        {"name": {"$regex": symptom, "$options": "i"}},
                    ]
                }
            )
            .limit(limit)
        )

        for r in results:
            r["_id"] = str(r["_id"])

        return results
    except Exception as exc:
        logger.error("search_diseases_by_symptom failed for '%s': %s", symptom, exc)
        return []


def record_data_correction(
    session_id: str,
    original_extraction: Dict[str, Any],
    corrected_extraction: Dict[str, Any],
    correction_reason: str,
) -> Dict[str, Any]:
    """
    Record when Intake Agent corrects extracted data.
    Used for quality assurance and model improvement.

    Args:
        session_id: Encounter session ID
        original_extraction: Original extracted data
        corrected_extraction: Corrected extracted data
        correction_reason: Reason for correction (e.g., "syndrome mismatch", "triage adjustment")

    Returns:
        dict with correction_id and status.
    """
    try:
        doc = {
            "session_id": session_id,
            "original_extraction": original_extraction,
            "corrected_extraction": corrected_extraction,
            "correction_reason": correction_reason,
            "timestamp": datetime.now(timezone.utc),
            "corrected_by": "intake_agent_auto",
        }

        result = _run(_get_client().db.data_corrections.insert_one(doc))

        return {
            "status": "recorded",
            "correction_id": str(result.inserted_id),
            "session_id": session_id,
        }
    except Exception as exc:
        logger.error("record_data_correction failed: %s", exc)
        return {"status": "error", "details": str(exc)}


def get_data_correction_stats(days: int = 7) -> Dict[str, Any]:
    """
    Get statistics on data corrections made by Intake Agent.

    Args:
        days: Number of days to look back

    Returns:
        dict with correction statistics.
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        stats = _run(
            _get_client().db.data_corrections.aggregate(
                [
                    {"$match": {"timestamp": {"$gte": cutoff}}},
                    {
                        "$group": {
                            "_id": "$correction_reason",
                            "count": {"$sum": 1},
                        }
                    },
                    {"$sort": {"count": -1}},
                ]
            )
        )

        return {
            "status": "success",
            "period_days": days,
            "corrections_by_reason": list(stats),
        }
    except Exception as exc:
        logger.error("get_data_correction_stats failed: %s", exc)
        return {"status": "error", "details": str(exc)}


# ═════════════════════════════════════════════════════════════════════════════
# CLINICAL DATASET SEEDING — Voyage AI Embeddings
# ═════════════════════════════════════════════════════════════════════════════


def seed_clinical_dataset() -> Dict[str, Any]:
    """
    Load the clinical intake dataset (15 realistic Kenya health scenarios) into
    MongoDB with Voyage AI embeddings for semantic search.

    Called during system startup (orchestrator _lifespan).

    Returns:
        dict with status, count of encounters loaded, and timestamp.
    """
    try:
        from agents.data.clinical_intake_dataset import (
            get_clinical_intake_dataset,
            get_dataset_embeddings_text,
        )
        from agents.data.embedding_service import EmbeddingService

        embedding_svc = EmbeddingService()
        dataset = get_clinical_intake_dataset()
        embeddings_text = get_dataset_embeddings_text()

        client = _get_client()
        count = 0
        errors = []

        for encounter in dataset:
            try:
                encounter_id = encounter["encounter_id"]

                # Generate Voyage AI embedding (1024 dims, document type)
                embedding_text = embeddings_text.get(encounter_id, "")
                if embedding_text:
                    vec = embedding_svc.generate_encounter_embedding(
                        {
                            "encounter_id": encounter_id,
                            "text_for_embedding": embedding_text,
                        }
                    )
                    encounter["embedding"] = vec

                # Insert into encounters collection
                _run(client.insert_encounter(encounter))
                count += 1
            except Exception as e:
                errors.append(f"Encounter {encounter_id}: {str(e)}")

        logger.info("✅ Seeded %d clinical encounters with Voyage AI embeddings", count)

        return {
            "status": "success" if not errors else "partial",
            "encounters_loaded": count,
            "errors": errors if errors else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error("seed_clinical_dataset failed: %s", exc)
        return {"status": "error", "details": str(exc)}


def query_encounters_by_syndrome(syndrome: str, limit: int = 20) -> Dict[str, Any]:
    """
    Query encounters by syndrome (e.g., 'malaria', 'pneumonia').
    Used for case history and pattern analysis.

    Args:
        syndrome: Syndrome name (malaria, pneumonia, etc.)
        limit: Max results to return

    Returns:
        dict with matching encounters and count.
    """
    try:
        client = _get_client()
        results = _run(
            client.db.encounters.find(
                {"extracted.syndrome": syndrome},
                {"embedding": 0},  # Exclude embeddings from response
            )
            .limit(limit)
            .to_list(limit)
        )

        return {
            "status": "success",
            "syndrome": syndrome,
            "count": len(results),
            "encounters": results,
        }
    except Exception as exc:
        logger.error("query_encounters_by_syndrome failed: %s", exc)
        return {"status": "error", "details": str(exc)}


def semantic_search_encounters(query_text: str, limit: int = 5) -> Dict[str, Any]:
    """
    Semantic search for encounters using Voyage AI vector embeddings.
    Searches the encounters collection with MongoDB $vectorSearch.

    Args:
        query_text: Natural language query (e.g., 'child with fever and cough')
        limit: Max results to return

    Returns:
        dict with similar encounters sorted by relevance (similarity score).
    """
    try:
        from agents.data.embedding_service import EmbeddingService

        embedding_svc = EmbeddingService()

        # Generate query embedding (1024 dims, query input type)
        query_vec = embedding_svc.generate_query_embedding(query_text)

        # Perform MongoDB vector search
        client = _get_client()
        results = _run(
            client.db.encounters.aggregate(
                [
                    {
                        "$search": {
                            "cosmosSearch": {
                                "vector": query_vec,
                                "k": limit,
                            },
                            "returnStoredSource": True,
                        }
                    },
                    {
                        "$project": {
                            "encounter_id": 1,
                            "chw_id": 1,
                            "chw_name": 1,
                            "patient_details": 1,
                            "extracted": 1,
                            "admin_hierarchy": 1,
                            "similarity_score": {"$meta": "searchScore"},
                        }
                    },
                    {"$limit": limit},
                ]
            ).to_list(limit)
        )

        logger.info(
            "Semantic search found %d similar encounters for query: %s",
            len(results),
            query_text[:50],
        )

        return {
            "status": "success",
            "query": query_text,
            "count": len(results),
            "encounters": results,
        }
    except Exception as exc:
        logger.error("semantic_search_encounters failed: %s", exc)
        return {"status": "error", "details": str(exc)}


# ═════════════════════════════════════════════════════════════════════════════
# ADK root_agent
# ═════════════════════════════════════════════════════════════════════════════

root_agent = LlmAgent(
    name="data_agent",
    model="gemini-3.5-flash",
    description=(
        "SihaLink MongoDB data agent. Handles all persistent storage across "
        "7 collections: encounters (with Voyage AI / Google vector embeddings), "
        "alerts, referrals, follow_ups, chws, protocols, and baselines. "
        "Autonomous Atlas Vector Search and full-text index management. "
        "This is the MongoDB MCP superpower layer."
    ),
    instruction="""You are the SihaLink Data Agent — the MongoDB Atlas intelligence layer.

YOUR COLLECTIONS AND RESPONSIBILITIES:

ENCOUNTERS (insert_encounter, sync_offline_encounters)
- Every encounter gets a semantic vector embedding (Voyage AI voyage-3 preferred,
  Google text-embedding-004 fallback) for Atlas Vector Search
- insert_encounter also auto-schedules follow-ups based on triage color
- sync_offline_encounters handles batches from offline CHV devices

ALERTS (query_active_alerts, update_alert_status, resolve_alert)
- Outbreak signals written by the Surveillance Agent
- District officers acknowledge and resolve via Telegram

REFERRALS (insert_referral, update_referral_status, query_referrals)
- Patient referral records — separate from outbreak alerts
- Facilities accept/redirect via Telegram inline keyboards

FOLLOW-UPS (schedule_follow_ups, get_pending_follow_ups, complete_follow_up,
            reschedule_follow_up, get_follow_up_summary)
- Auto-scheduled per triage: RED→[1,3,7,14d], YELLOW→[2,7,14d], GREEN→[7d]
- CHWs complete follow-ups via Telegram /followup command
- Supervisors monitor overdue tasks via get_follow_up_summary

CHWs (register_chw, get_chw, list_chws)
- Registry of all Community Health Workers
- Linked to encounters, follow-ups, and Telegram IDs

PROTOCOLS (upsert_protocol, get_protocol, search_protocols, list_protocols)
- WHO/MoH response protocols written by the Surveillance Agent
- Embedded for semantic search — CHWs find them via /protocol command
- County-specific protocols override national ones

INDEXES (create_vector_search_index)
- Call on startup to ensure Atlas Vector Search + full-text indexes exist
- Supports both 768-dim (Google) and 1024-dim (Voyage AI) embeddings

WORKFLOW FOR NEW ENCOUNTER:
1. insert_encounter → returns inserted_id + scheduled_follow_ups count
2. If RED/YELLOW: insert_referral → returns referral_id
3. Orchestrator routes referral_id to Notify Agent for Telegram dispatch

CRITICAL RULES:
- Never lose data — if insert fails, return error clearly for Orchestrator retry
- All writes are idempotent where possible (upsert patterns)
- Embeddings are best-effort — zero vector fallback never blocks the pipeline
- Always call create_vector_search_index on startup
""",
    tools=[
        # Encounters
        insert_encounter,
        sync_offline_encounters,
        create_vector_search_index,
        # Alerts
        query_active_alerts,
        update_alert_status,
        resolve_alert,
        # Referrals
        insert_referral,
        update_referral_status,
        query_referrals,
        # Follow-ups
        schedule_follow_ups,
        get_pending_follow_ups,
        complete_follow_up,
        reschedule_follow_up,
        get_follow_up_summary,
        # CHWs
        register_chw,
        get_chw,
        list_chws,
        # Protocols
        upsert_protocol,
        get_protocol,
        search_protocols,
        list_protocols,
        # Agent Logs
        insert_agent_log,
        query_agent_logs,
        search_agent_logs,
    ],
    generate_content_config=genai_types.GenerateContentConfig(
        temperature=0.0,  # Deterministic — this is a data layer, not creative
        max_output_tokens=512,
    ),
)

# ── Runner setup ──────────────────────────────────────────────────────────────
APP_NAME = "sihalink_data"
_session_service = InMemorySessionService()
_runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=_session_service,
)
