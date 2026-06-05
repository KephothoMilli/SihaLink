"""
Contact Tracing Agent — SihaLink (Google ADK)
==============================================
Identifies, tracks, and manages exposed contacts for every RED-triage
encounter and outbreak cluster.

Data flows IN from:
  - Data Agent     (encounters, follow_ups, chws, alerts)
  - Surveillance Agent (outbreak cluster encounter_ids)
  - Geo Agent      (admin hierarchy for contact location enrichment)

Data flows OUT to:
  - Data Agent     (writes contact_traces collection + follow_up tasks)
  - Notify Agent   (Telegram contact visit tasks to CHWs)
  - Surveillance Agent (secondary attack rate, chain depth)

Collections used:
  contact_traces  — master trace document per index case
  encounters      — queried for geospatial/temporal contact search
  follow_ups      — written for each identified contact
  chws            — queried to assign nearest CHW to each contact
  alerts          — queried for outbreak cluster encounter_ids
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pymongo import MongoClient, ASCENDING, DESCENDING, GEOSPHERE
from pymongo.errors import OperationFailure

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

logger = logging.getLogger("SihaLink-ContactTracing")

# ── Exposure windows by syndrome (days BEFORE symptom onset) ──────────────────
EXPOSURE_WINDOWS: Dict[str, int] = {
    "cholera":                   5,
    "measles":                   8,   # 4 before + 4 after rash onset
    "acute_respiratory_infection": 7,
    "acute_febrile_illness":     10,
    "meningitis":                7,
    "viral_hemorrhagic_fever":   21,
    "acute_watery_diarrhea":     5,
    "acute_bloody_diarrhea":     5,
    "malnutrition_severe":       14,
    "default":                   7,
}

# ── Follow-up due days by contact risk tier ───────────────────────────────────
CONTACT_DUE_DAYS: Dict[str, int] = {
    "HOUSEHOLD":  1,
    "COMMUNITY":  2,
    "FACILITY":   2,
    "UNKNOWN":    3,
}

# ── Syndromes that always trigger household contact tracing ───────────────────
HIGH_PRIORITY_SYNDROMES = {
    "cholera", "measles", "viral_hemorrhagic_fever",
    "meningitis", "acute_bloody_diarrhea",
}

# ── MongoDB singleton ─────────────────────────────────────────────────────────
_client: MongoClient | None = None
_db = None


def _get_db():
    global _client, _db
    if _client is None:
        uri = os.getenv("MONGODB_ATLAS_URI")
        if not uri:
            raise RuntimeError("MONGODB_ATLAS_URI not set")
        _client = MongoClient(uri, appname="sihalink-contact-tracing")
        _db = _client.sihalink
        _ensure_indexes(_db)
    return _db


def _ensure_indexes(db):
    """Idempotent index creation for the contact_traces collection."""
    try:
        db.contact_traces.create_index(
            [("index_encounter_id", ASCENDING)], unique=True, sparse=True
        )
        db.contact_traces.create_index([("trace_id", ASCENDING)], unique=True)
        db.contact_traces.create_index([("syndrome", ASCENDING), ("status", ASCENDING)])
        db.contact_traces.create_index(
            [("index_case.location.county", ASCENDING), ("created_at", DESCENDING)]
        )
        db.contact_traces.create_index([("alert_id", ASCENDING)], sparse=True)
        db.contact_traces.create_index(
            [("contacts.contact_id", ASCENDING)], sparse=True
        )
        logger.info("✅ Contact tracing indexes verified")
    except OperationFailure as exc:
        logger.warning("Index creation warning: %s", exc)


# =============================================================================
# TOOL FUNCTIONS
# =============================================================================

def initiate_contact_trace(
    encounter_id: str,
    alert_id: Optional[str] = None,
    initiated_by: str = "system",
) -> dict:
    """
    Initiate a contact trace for a RED-triage encounter or outbreak cluster.

    Pulls the index case from the encounters collection, determines the
    syndrome-specific exposure window, searches for contacts in the same
    ward within that window, creates follow_up tasks for each contact,
    and persists the full trace to the contact_traces collection.

    Args:
        encounter_id: MongoDB encounter_id of the index case.
        alert_id:     Optional outbreak alert_id this trace is linked to.
        initiated_by: 'system' | CHW ID | district officer ID.

    Returns:
        dict with trace_id, contacts_identified, assigned_chws, status.
    """
    db = _get_db()

    # 1. Pull index case
    from bson import ObjectId
    try:
        index_case = db.encounters.find_one(
            {"$or": [
                {"encounter_id": encounter_id},
                {"_id": ObjectId(encounter_id) if len(encounter_id) == 24 else None},
            ]},
            {"_id": 0},
        )
    except Exception:
        index_case = db.encounters.find_one({"encounter_id": encounter_id}, {"_id": 0})

    if not index_case:
        logger.warning("Contact trace: encounter %s not found", encounter_id)
        return {"error": f"Encounter {encounter_id} not found", "trace_id": None}

    extracted   = index_case.get("extracted", {})
    syndrome    = extracted.get("syndrome", "unknown")
    triage      = extracted.get("triage_color", "GREEN")
    admin       = index_case.get("admin_hierarchy", {})
    county      = admin.get("county", "Unknown")
    ward        = admin.get("ward", "Unknown")
    timestamp   = index_case.get("timestamp", datetime.utcnow())
    chw_id      = index_case.get("chw_id", "unknown")

    # 2. Check if trace already exists
    existing = db.contact_traces.find_one(
        {"index_encounter_id": encounter_id}, {"trace_id": 1}
    )
    if existing:
        logger.info("Contact trace already exists for encounter %s", encounter_id)
        return {
            "trace_id":            existing["trace_id"],
            "status":              "already_exists",
            "contacts_identified": 0,
        }

    # 3. Build exposure window
    window_days = EXPOSURE_WINDOWS.get(syndrome, EXPOSURE_WINDOWS["default"])
    window_start = timestamp - timedelta(days=window_days)
    window_end   = timestamp + timedelta(days=2)  # 2 days post-onset

    # 4. Search for contacts in same ward within window
    contacts = _find_contacts(
        db, syndrome, county, ward, window_start, window_end, encounter_id
    )

    # 5. Assign CHWs to contacts
    available_chws = list(
        db.chws.find(
            {"county": county, "status": "active"},
            {"_id": 0, "chw_id": 1, "ward": 1, "name": 1, "telegram_id": 1},
        ).limit(10)
    )
    contacts_with_tasks = _assign_chws_and_schedule(
        db, contacts, available_chws, encounter_id, syndrome, timestamp
    )

    # 6. Create and persist the trace document
    trace_id = f"CT-{uuid4().hex[:8].upper()}"
    assigned_chw_ids = list({c.get("assigned_chw") for c in contacts_with_tasks if c.get("assigned_chw")})

    trace_doc = {
        "trace_id":            trace_id,
        "index_encounter_id":  encounter_id,
        "alert_id":            alert_id,
        "syndrome":            syndrome,
        "index_case": {
            "chw_id":       chw_id,
            "triage_color": triage,
            "location":     {"county": county, "ward": ward},
            "timestamp":    timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp,
        },
        "contact_window": {
            "start": window_start.isoformat(),
            "end":   window_end.isoformat(),
            "days":  window_days,
        },
        "contacts":         contacts_with_tasks,
        "status":           "active",
        "total_contacts":   len(contacts_with_tasks),
        "contacted_count":  0,
        "confirmed_cases":  0,
        "assigned_chws":    assigned_chw_ids,
        "escalation_level": "COUNTY",
        "initiated_by":     initiated_by,
        "created_at":       datetime.utcnow().isoformat(),
        "resolved_at":      None,
        "history": [
            {
                "event":     "trace_initiated",
                "timestamp": datetime.utcnow().isoformat(),
                "by":        initiated_by,
                "detail":    f"{len(contacts_with_tasks)} contacts identified in {ward}, {county}",
            }
        ],
    }

    db.contact_traces.insert_one(trace_doc)
    logger.info(
        "✅ Contact trace %s: %d contacts for %s in %s/%s",
        trace_id, len(contacts_with_tasks), syndrome, ward, county,
    )

    return {
        "trace_id":            trace_id,
        "syndrome":            syndrome,
        "county":              county,
        "ward":                ward,
        "contacts_identified": len(contacts_with_tasks),
        "assigned_chws":       assigned_chw_ids,
        "status":              "active",
    }


def trace_outbreak_cluster(
    alert_id: str,
    max_encounters: int = 50,
) -> dict:
    """
    Initiate contact traces for all encounters in an outbreak cluster.

    Pulls the alert, extracts its encounter_ids, and calls
    initiate_contact_trace for each one. Returns aggregate results.

    Args:
        alert_id:       The outbreak alert_id from the alerts collection.
        max_encounters: Cap on encounters to trace (default 50).

    Returns:
        dict with traces_created, total_contacts, alert_id, syndrome.
    """
    db = _get_db()

    alert = db.alerts.find_one(
        {"alert_id": alert_id}, {"_id": 0}
    )
    if not alert:
        return {"error": f"Alert {alert_id} not found"}

    syndrome      = alert.get("syndrome", "unknown")
    encounter_ids = alert.get("encounter_ids", [])[:max_encounters]

    if not encounter_ids:
        logger.warning("Alert %s has no encounter_ids — skipping cluster trace", alert_id)
        return {
            "alert_id":      alert_id,
            "syndrome":      syndrome,
            "traces_created": 0,
            "total_contacts": 0,
            "note":          "No encounter_ids in alert",
        }

    traces_created = 0
    total_contacts = 0

    for enc_id in encounter_ids:
        result = initiate_contact_trace(enc_id, alert_id=alert_id, initiated_by="surveillance_agent")
        if result.get("trace_id") and result.get("status") != "already_exists":
            traces_created += 1
            total_contacts += result.get("contacts_identified", 0)

    logger.info(
        "Cluster trace for alert %s: %d traces, %d contacts",
        alert_id, traces_created, total_contacts,
    )
    return {
        "alert_id":       alert_id,
        "syndrome":       syndrome,
        "traces_created": traces_created,
        "total_contacts": total_contacts,
        "status":         "active",
    }


def update_contact_status(
    trace_id: str,
    contact_id: str,
    status: str,
    new_encounter_id: Optional[str] = None,
    notes: str = "",
    chw_id: str = "unknown",
) -> dict:
    """
    Update the status of an individual contact within a trace.

    Called when a CHW visits a contact and submits their assessment.

    Args:
        trace_id:         The CT-XXXXXXXX trace identifier.
        contact_id:       The CON-XXXXXXXX contact identifier.
        status:           contacted | assessed | cleared | confirmed
        new_encounter_id: If contact became a case, the new encounter_id.
        notes:            CHW assessment notes.
        chw_id:           CHW completing the contact visit.

    Returns:
        dict with matched_count, modified_count, escalation_triggered.
    """
    db = _get_db()
    now = datetime.utcnow()

    update_fields: Dict[str, Any] = {
        "contacts.$.status":       status,
        "contacts.$.completed_at": now.isoformat(),
        "contacts.$.notes":        notes,
        "contacts.$.completed_by": chw_id,
    }
    if new_encounter_id:
        update_fields["contacts.$.confirmed_case"]  = True
        update_fields["contacts.$.encounter_id"]    = new_encounter_id

    result = db.contact_traces.update_one(
        {"trace_id": trace_id, "contacts.contact_id": contact_id},
        {
            "$set":  update_fields,
            "$push": {
                "history": {
                    "event":     f"contact_{status}",
                    "timestamp": now.isoformat(),
                    "by":        chw_id,
                    "contact_id": contact_id,
                    "detail":    notes[:200] if notes else "",
                }
            },
        },
    )

    # Recount contacted and confirmed cases
    trace = db.contact_traces.find_one({"trace_id": trace_id}, {"contacts": 1, "syndrome": 1})
    if trace:
        contacts        = trace.get("contacts", [])
        contacted_count = sum(1 for c in contacts if c.get("status") not in ("identified",))
        confirmed_cases = sum(1 for c in contacts if c.get("confirmed_case"))
        db.contact_traces.update_one(
            {"trace_id": trace_id},
            {"$set": {
                "contacted_count": contacted_count,
                "confirmed_cases": confirmed_cases,
            }},
        )

    # Auto-escalate if confirmed case detected
    escalation_triggered = False
    if new_encounter_id and status == "confirmed":
        escalation_triggered = True
        logger.warning(
            "⚠️  Contact %s confirmed as new case — initiating secondary trace",
            contact_id,
        )
        initiate_contact_trace(
            new_encounter_id,
            initiated_by=f"contact_trace_{trace_id}",
        )

    return {
        "matched_count":       result.matched_count,
        "modified_count":      result.modified_count,
        "escalation_triggered": escalation_triggered,
    }


def get_trace_status(trace_id: str) -> dict:
    """
    Retrieve the full status of a contact trace including all contacts,
    resolution histogram, and secondary attack rate.

    Args:
        trace_id: The CT-XXXXXXXX trace identifier.

    Returns:
        Full trace document with computed analytics.
    """
    db = _get_db()
    trace = db.contact_traces.find_one({"trace_id": trace_id}, {"_id": 0})
    if not trace:
        return {"error": f"Trace {trace_id} not found"}

    contacts        = trace.get("contacts", [])
    total           = len(contacts)
    contacted       = sum(1 for c in contacts if c.get("status") not in ("identified",))
    cleared         = sum(1 for c in contacts if c.get("status") == "cleared")
    confirmed       = sum(1 for c in contacts if c.get("confirmed_case"))
    overdue         = sum(
        1 for c in contacts
        if c.get("status") == "identified"
        and c.get("due_date")
        and c["due_date"] < datetime.utcnow().isoformat()
    )

    # Secondary attack rate
    household_total    = sum(1 for c in contacts if c.get("risk_tier") == "HOUSEHOLD")
    household_confirmed = sum(
        1 for c in contacts
        if c.get("risk_tier") == "HOUSEHOLD" and c.get("confirmed_case")
    )
    secondary_attack_rate = (
        round(household_confirmed / household_total * 100, 1)
        if household_total > 0 else 0.0
    )

    # Histogram: contacts by status
    status_histogram = {
        "identified": total - contacted,
        "contacted":  contacted - cleared - confirmed,
        "cleared":    cleared,
        "confirmed":  confirmed,
        "overdue":    overdue,
    }

    # Histogram: contacts by risk tier
    tier_histogram = {}
    for tier in ("HOUSEHOLD", "COMMUNITY", "FACILITY", "UNKNOWN"):
        tier_histogram[tier] = sum(1 for c in contacts if c.get("risk_tier") == tier)

    return {
        **trace,
        "analytics": {
            "total_contacts":         total,
            "contacted":              contacted,
            "cleared":                cleared,
            "confirmed_cases":        confirmed,
            "overdue":                overdue,
            "completion_rate_pct":    round(contacted / total * 100, 1) if total > 0 else 0,
            "secondary_attack_rate":  secondary_attack_rate,
            "status_histogram":       status_histogram,
            "tier_histogram":         tier_histogram,
        },
    }


def get_active_traces(
    county: Optional[str] = None,
    syndrome: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """
    List active contact traces with summary statistics.

    Args:
        county:  Filter by county.
        syndrome: Filter by syndrome.
        limit:   Max results (default 20).

    Returns:
        dict with traces list and summary counts.
    """
    db = _get_db()
    query: Dict[str, Any] = {"status": "active"}
    if county:
        query["index_case.location.county"] = county
    if syndrome:
        query["syndrome"] = syndrome

    traces = list(
        db.contact_traces.find(query, {
            "_id":              0,
            "trace_id":         1,
            "syndrome":         1,
            "index_case":       1,
            "total_contacts":   1,
            "contacted_count":  1,
            "confirmed_cases":  1,
            "status":           1,
            "escalation_level": 1,
            "created_at":       1,
            "assigned_chws":    1,
        })
        .sort("created_at", DESCENDING)
        .limit(limit)
    )

    return {
        "traces": traces,
        "count":  len(traces),
        "filters": {"county": county, "syndrome": syndrome},
    }


def resolve_trace(
    trace_id: str,
    resolved_by: str = "system",
    resolution_notes: str = "",
) -> dict:
    """
    Mark a contact trace as resolved when all contacts are cleared or confirmed.

    Args:
        trace_id:         The CT-XXXXXXXX identifier.
        resolved_by:      User ID or 'system'.
        resolution_notes: Summary notes from district officer.

    Returns:
        dict with matched_count and trace summary.
    """
    db = _get_db()
    now = datetime.utcnow()

    result = db.contact_traces.update_one(
        {"trace_id": trace_id},
        {
            "$set": {
                "status":           "resolved",
                "resolved_at":      now.isoformat(),
                "resolved_by":      resolved_by,
                "resolution_notes": resolution_notes,
            },
            "$push": {
                "history": {
                    "event":     "trace_resolved",
                    "timestamp": now.isoformat(),
                    "by":        resolved_by,
                    "detail":    resolution_notes,
                }
            },
        },
    )

    summary = get_trace_status(trace_id)
    analytics = summary.get("analytics", {})
    logger.info(
        "✅ Trace %s resolved — %d contacts, %d confirmed, %.1f%% SAR",
        trace_id,
        analytics.get("total_contacts", 0),
        analytics.get("confirmed_cases", 0),
        analytics.get("secondary_attack_rate", 0.0),
    )
    return {
        "matched_count":      result.matched_count,
        "trace_id":           trace_id,
        "total_contacts":     analytics.get("total_contacts", 0),
        "confirmed_cases":    analytics.get("confirmed_cases", 0),
        "secondary_attack_rate": analytics.get("secondary_attack_rate", 0.0),
    }


def scan_overdue_contacts(hours_overdue: int = 24) -> dict:
    """
    Scan all active traces for contacts whose visit is overdue.
    Called daily by the swarm scheduler. Escalates and re-notifies CHWs.

    Args:
        hours_overdue: Number of hours past due_date before escalation (default 24).

    Returns:
        dict with escalated_count and trace_ids affected.
    """
    db = _get_db()
    threshold = (datetime.utcnow() - timedelta(hours=hours_overdue)).isoformat()

    overdue_traces = list(
        db.contact_traces.find(
            {
                "status": "active",
                "contacts": {
                    "$elemMatch": {
                        "status":   "identified",
                        "due_date": {"$lt": threshold},
                    }
                },
            },
            {"trace_id": 1, "syndrome": 1, "index_case.location.county": 1, "contacts": 1},
        )
    )

    escalated = 0
    trace_ids = []

    for trace in overdue_traces:
        trace_ids.append(trace["trace_id"])
        overdue_contacts = [
            c for c in trace.get("contacts", [])
            if c.get("status") == "identified"
            and c.get("due_date", "") < threshold
        ]

        if overdue_contacts:
            escalated += len(overdue_contacts)
            db.contact_traces.update_one(
                {"trace_id": trace["trace_id"]},
                {
                    "$push": {
                        "history": {
                            "event":     "contacts_overdue_escalated",
                            "timestamp": datetime.utcnow().isoformat(),
                            "by":        "system",
                            "detail":    f"{len(overdue_contacts)} contacts overdue by {hours_overdue}h",
                        }
                    }
                },
            )
            logger.warning(
                "[ContactTrace] %d overdue contacts in trace %s (%s)",
                len(overdue_contacts), trace["trace_id"], trace.get("syndrome"),
            )

    return {
        "escalated_count": escalated,
        "traces_affected":  len(trace_ids),
        "trace_ids":        trace_ids,
        "threshold_hours":  hours_overdue,
    }


# =============================================================================
# PRIVATE HELPERS
# =============================================================================

def _find_contacts(
    db,
    syndrome: str,
    county: str,
    ward: str,
    window_start: datetime,
    window_end: datetime,
    exclude_encounter_id: str,
) -> List[Dict[str, Any]]:
    """
    Search for potential contacts in the same ward within the exposure window.
    Returns contact dicts ready for assignment.
    """
    contacts = []

    # Search encounters in same ward within window
    raw = list(
        db.encounters.find(
            {
                "admin_hierarchy.county": county,
                "admin_hierarchy.ward":   ward,
                "timestamp": {"$gte": window_start, "$lte": window_end},
                "encounter_id": {"$ne": exclude_encounter_id},
            },
            {
                "_id":             0,
                "encounter_id":    1,
                "chw_id":          1,
                "admin_hierarchy": 1,
                "extracted.syndrome": 1,
                "extracted.triage_color": 1,
            },
        ).limit(100)
    )

    seen_encounters = set()
    for enc in raw:
        enc_id = enc.get("encounter_id", "")
        if enc_id in seen_encounters:
            continue
        seen_encounters.add(enc_id)

        # Same syndrome = higher risk tier
        enc_syndrome = enc.get("extracted", {}).get("syndrome", "")
        tier = "COMMUNITY"
        if enc_syndrome == syndrome:
            tier = "HOUSEHOLD"  # same syndrome in same ward = treat as household

        contacts.append({
            "contact_id":     f"CON-{uuid4().hex[:8].upper()}",
            "risk_tier":      tier,
            "encounter_id":   enc_id,
            "source":         "encounter_search",
            "location":       {
                "county": enc.get("admin_hierarchy", {}).get("county", county),
                "ward":   enc.get("admin_hierarchy", {}).get("ward", ward),
            },
            "status":         "identified",
            "confirmed_case": False,
            "notes":          "",
            "assigned_chw":   enc.get("chw_id"),   # tentative — may be overridden
        })

    # For high-priority syndromes, always add at least a placeholder household tier
    if syndrome in HIGH_PRIORITY_SYNDROMES and not any(
        c["risk_tier"] == "HOUSEHOLD" for c in contacts
    ):
        contacts.append({
            "contact_id":     f"CON-{uuid4().hex[:8].upper()}",
            "risk_tier":      "HOUSEHOLD",
            "encounter_id":   None,
            "source":         "presumptive_household",
            "location":       {"county": county, "ward": ward},
            "status":         "identified",
            "confirmed_case": False,
            "notes":          "Presumptive household contact — CHW to verify on visit",
            "assigned_chw":   None,
        })

    logger.info(
        "Found %d contacts for %s in %s/%s (window: %s → %s)",
        len(contacts), syndrome, ward, county,
        window_start.strftime("%Y-%m-%d"), window_end.strftime("%Y-%m-%d"),
    )
    return contacts


def _assign_chws_and_schedule(
    db,
    contacts: List[Dict[str, Any]],
    available_chws: List[Dict[str, Any]],
    encounter_id: str,
    syndrome: str,
    base_timestamp: datetime,
) -> List[Dict[str, Any]]:
    """
    Assign a CHW to each contact and create a follow_up task in MongoDB.
    Prefers the CHW already associated with the contact's encounter.
    Falls back to round-robin across available CHWs.
    """
    chw_pool = list(available_chws) or [{"chw_id": "unassigned", "ward": "unknown"}]
    chw_index = 0
    now = datetime.utcnow()

    enriched = []
    for contact in contacts:
        tier     = contact.get("risk_tier", "COMMUNITY")
        due_days = CONTACT_DUE_DAYS.get(tier, 3)
        due_date = now + timedelta(days=due_days)

        # Prefer the CHW already linked to the contact's encounter
        assigned_chw = contact.get("assigned_chw")
        if not assigned_chw or assigned_chw == "unknown":
            assigned_chw = chw_pool[chw_index % len(chw_pool)]["chw_id"]
            chw_index += 1

        # Create a follow_up task
        follow_up_id = f"FU-CT-{uuid4().hex[:8].upper()}"
        try:
            db.follow_ups.insert_one({
                "follow_up_id":   follow_up_id,
                "encounter_id":   encounter_id,
                "contact_id":     contact["contact_id"],
                "trace_type":     "contact_tracing",
                "chw_id":         assigned_chw,
                "county":         contact["location"].get("county", "Unknown"),
                "ward":           contact["location"].get("ward", "Unknown"),
                "due_date":       due_date,
                "status":         "pending",
                "triage_color":   "YELLOW",
                "syndrome":       syndrome,
                "risk_tier":      tier,
                "chief_complaint": f"Contact trace visit — {tier} contact for {syndrome}",
                "created_at":     now,
                "notes":          contact.get("notes", ""),
            })
        except Exception as exc:
            logger.warning("Could not create follow_up for contact %s: %s",
                          contact.get("contact_id"), exc)
            follow_up_id = None

        enriched.append({
            **contact,
            "assigned_chw":  assigned_chw,
            "follow_up_id":  follow_up_id,
            "due_date":      due_date.isoformat(),
        })

    return enriched


# =============================================================================
# ADK root_agent
# =============================================================================

root_agent = LlmAgent(
    name="contact_tracing_agent",
    model="gemini-flash-latest",
    description=(
        "SihaLink Contact Tracing Agent. Identifies and tracks all persons exposed to "
        "confirmed or suspected disease cases. Pulls encounter, alert, CHW, and follow-up "
        "data from the Data Agent. Builds exposure networks. Assigns CHW contact visit tasks. "
        "Monitors resolution status. Reports secondary attack rates back to the Surveillance Agent."
    ),
    instruction="""You are the SihaLink Contact Tracing Agent.

YOUR MISSION:
Every RED-triage encounter and every outbreak alert triggers a contact trace.
You identify who was exposed, assign CHWs to visit them, track every contact to resolution,
and report secondary attack rates back to the Surveillance Agent.

WORKFLOW FOR A SINGLE CASE:
1. INITIATE: Call initiate_contact_trace(encounter_id) for each RED encounter
2. CLUSTER:  Call trace_outbreak_cluster(alert_id) when an outbreak alert fires
3. MONITOR:  Call scan_overdue_contacts(hours_overdue=24) daily
4. UPDATE:   Call update_contact_status() when CHV reports back on a contact visit
5. RESOLVE:  Call resolve_trace() when all contacts are cleared or confirmed

ESCALATION RULES:
- A confirmed contact (new_encounter_id set) triggers a NEW trace automatically
- Household contacts unvisited after 24h → escalate to district officer via Notify Agent
- If confirmed_cases > 2 in a single trace → elevate escalation_level to REGIONAL
- If traces span ≥ 3 counties for same syndrome → elevate to NATIONAL

ANALYTICS TO REPORT:
- Secondary attack rate per trace (confirmed household / total household)
- Time-to-contact (hours between index case report and first contact visit)
- Contact chain depth (generations of secondary cases)
- Resolution rate per county per syndrome

ALWAYS:
- Never duplicate a contact trace for the same encounter
- Always create a follow_up task for every identified contact
- Report completion status to the Surveillance Agent when a trace resolves
- Log every state transition in the trace history array
""",
    tools=[
        initiate_contact_trace,
        trace_outbreak_cluster,
        update_contact_status,
        get_trace_status,
        get_active_traces,
        resolve_trace,
        scan_overdue_contacts,
    ],
    generate_content_config=genai_types.GenerateContentConfig(
        temperature=0.0,
        max_output_tokens=1024,
    ),
)

# ── Runner setup ──────────────────────────────────────────────────────────────
APP_NAME = "sihalink_contact_tracing"
_session_service = InMemorySessionService()
_runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=_session_service,
)


# ── Thin class wrapper for Orchestrator/Swarm compatibility ───────────────────
class ContactTracingAgent:
    """Thin wrapper so the swarm can call agent methods directly."""

    def initiate_trace(self, encounter_id: str, alert_id: Optional[str] = None) -> dict:
        return initiate_contact_trace(encounter_id, alert_id=alert_id)

    def trace_cluster(self, alert_id: str) -> dict:
        return trace_outbreak_cluster(alert_id)

    def scan_overdue(self, hours: int = 24) -> dict:
        return scan_overdue_contacts(hours)

    def get_status(self, trace_id: str) -> dict:
        return get_trace_status(trace_id)
