"""
Surveillance Agent — SihaLink (Google ADK)
Silent pandemic detection, outbreak monitoring, protocol formulation,
CHW outreach gap analysis, and cross-county spread tracking.

Collections used: encounters, alerts, baselines, protocols, chws
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types
from pymongo import MongoClient, GEOSPHERE
from pymongo.errors import OperationFailure

from .pipelines import (
    get_outbreak_pipeline,
    get_silent_pandemic_pipeline,
    get_cross_county_spread_pipeline,
    get_underreporting_pipeline,
    get_chw_performance_pipeline,
)
from .pipelines_1 import get_geospatial_cluster_pipeline, get_vector_similarity_pipeline

logger = logging.getLogger("SihaLink-Surveillance")

# ── Thresholds ────────────────────────────────────────────────────────────────
OUTBREAK_CASE_THRESHOLD = 5
BASELINE_SPIKE_MULTIPLIER = 2.0
SILENT_TREND_WEEKS = 4          # weeks of consistent rise = silent pandemic signal
UNDERREPORTING_DAYS = 7         # days window for CHW activity check

CORRELATED_SYNDROMES = {
    frozenset({"acute_watery_diarrhea", "acute_febrile_illness"}): "cholera",
    frozenset({"acute_rash_with_fever", "acute_febrile_illness"}): "measles",
    frozenset({"acute_respiratory_infection", "acute_febrile_illness"}): "influenza",
    frozenset({"malnutrition_severe", "acute_watery_diarrhea"}): "severe_acute_malnutrition",
}

# ── WHO/MoH Kenya response protocol templates ─────────────────────────────────
PROTOCOL_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "cholera": {
        "syndrome": "cholera",
        "alert_level": "RED",
        "immediate_actions": [
            "Activate county cholera task force within 2 hours",
            "Deploy oral rehydration solution (ORS) to affected wards",
            "Establish cholera treatment centres (CTCs) within 24 hours",
            "Conduct rapid water quality testing in affected area",
            "Issue boil-water advisory via Telegram broadcast",
        ],
        "chw_actions": [
            "Conduct household visits in affected ward — identify all symptomatic contacts",
            "Distribute ORS sachets and hygiene kits",
            "Record all cases using SihaLink intake",
            "Follow up all cases at 24h, 48h, and 7 days",
        ],
        "follow_up_days": [1, 2, 7],
        "reporting_threshold": 1,   # single case triggers protocol
        "who_idsr_code": "CHL",
    },
    "measles": {
        "syndrome": "measles",
        "alert_level": "YELLOW",
        "immediate_actions": [
            "Verify diagnosis with rapid antigen test",
            "Activate supplementary immunisation activity (SIA) planning",
            "Identify unvaccinated children in affected ward",
            "Notify county immunisation coordinator",
        ],
        "chw_actions": [
            "Map all unvaccinated children under 5 in the ward",
            "Conduct door-to-door vaccination campaign",
            "Record all suspected cases via SihaLink",
            "Follow up confirmed cases at 7 and 14 days",
        ],
        "follow_up_days": [7, 14],
        "reporting_threshold": 1,
        "who_idsr_code": "MEA",
    },
    "acute_watery_diarrhea": {
        "syndrome": "acute_watery_diarrhea",
        "alert_level": "YELLOW",
        "immediate_actions": [
            "Assess water and sanitation conditions in affected area",
            "Distribute ORS to households with children under 5",
            "Refer severe dehydration cases immediately",
        ],
        "chw_actions": [
            "Conduct WASH assessment in affected households",
            "Distribute ORS and zinc supplements",
            "Follow up all cases under 5 at 48 hours",
        ],
        "follow_up_days": [2, 5],
        "reporting_threshold": 5,
        "who_idsr_code": "AWD",
    },
    "acute_respiratory_infection": {
        "syndrome": "acute_respiratory_infection",
        "alert_level": "YELLOW",
        "immediate_actions": [
            "Identify high-risk groups (elderly, immunocompromised, under 5)",
            "Ensure adequate stock of amoxicillin at health facilities",
            "Issue community advisory on respiratory hygiene",
        ],
        "chw_actions": [
            "Screen all household contacts of confirmed cases",
            "Refer severe cases (fast breathing, chest indrawing) immediately",
            "Follow up at 3 and 7 days",
        ],
        "follow_up_days": [3, 7],
        "reporting_threshold": 10,
        "who_idsr_code": "ARI",
    },
    "malnutrition_severe": {
        "syndrome": "malnutrition_severe",
        "alert_level": "RED",
        "immediate_actions": [
            "Activate community-based management of acute malnutrition (CMAM)",
            "Ensure RUTF (ready-to-use therapeutic food) supply",
            "Identify all SAM cases for inpatient stabilisation",
        ],
        "chw_actions": [
            "Conduct MUAC screening in all households with children under 5",
            "Enrol SAM cases in outpatient therapeutic programme (OTP)",
            "Weekly follow-up for all enrolled cases",
        ],
        "follow_up_days": [7, 14, 21, 28],
        "reporting_threshold": 3,
        "who_idsr_code": "SAM",
    },
    "default": {
        "syndrome": "unknown",
        "alert_level": "YELLOW",
        "immediate_actions": [
            "Verify diagnosis and confirm case definition",
            "Notify county health officer",
            "Increase surveillance frequency to every 6 hours",
        ],
        "chw_actions": [
            "Record all suspected cases via SihaLink",
            "Follow up at 48 hours",
        ],
        "follow_up_days": [2],
        "reporting_threshold": 5,
        "who_idsr_code": "UNK",
    },
}

# ── MongoDB singleton ─────────────────────────────────────────────────────────
_mongo_client: MongoClient | None = None
_db = None


def _get_db():
    global _mongo_client, _db
    if _mongo_client is None:
        uri = os.getenv("MONGODB_ATLAS_URI")
        if not uri:
            raise RuntimeError("MONGODB_ATLAS_URI not set")
        _mongo_client = MongoClient(uri, appname="sihalink")
        _db = _mongo_client.sihalink
        _ensure_indexes(_db)
    return _db


def _ensure_indexes(db):
    try:
        db.encounters.create_index([("location", GEOSPHERE)])
        db.encounters.create_index([("extracted.syndrome", 1), ("timestamp", -1)])
        db.encounters.create_index([("admin_hierarchy.county", 1), ("timestamp", -1)])
        db.encounters.create_index([("chw_id", 1), ("timestamp", -1)])
        db.baselines.create_index([("county", 1), ("syndrome", 1)], unique=True)
        db.alerts.create_index([("location.county", 1), ("status", 1), ("timestamp", -1)])
        db.protocols.create_index([("syndrome", 1)], unique=True)
        db.chws.create_index([("chw_id", 1)], unique=True)
        db.chws.create_index([("county", 1), ("ward", 1)])
        db.follow_ups.create_index([("encounter_id", 1)])
        db.follow_ups.create_index([("chw_id", 1), ("status", 1), ("due_date", 1)])
        db.follow_ups.create_index([("county", 1), ("status", 1), ("due_date", 1)])
        logger.info("✅ Surveillance indexes verified")
    except OperationFailure as exc:
        logger.warning("Index creation warning: %s", exc)


# ═════════════════════════════════════════════════════════════════════════════
# TOOL FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

def run_outbreak_detection(county: str, lat: float, lng: float, hours: int = 6) -> dict:
    """
    Run geospatial outbreak detection for a county using MongoDB aggregation.
    Compares case counts against 4-week rolling baselines to detect spikes.
    Also checks for correlated syndrome pairs (cholera, measles, influenza, SAM).

    Args:
        county: Kenya county name (e.g., 'Homa Bay', 'Kisumu').
        lat: Latitude of the county center.
        lng: Longitude of the county center.
        hours: Time window for case counting (default 6).

    Returns:
        dict with alerts_detected (int) and alerts (list).
    """
    db = _get_db()
    pipeline = get_geospatial_cluster_pipeline(county, hours)
    try:
        results = list(db.encounters.aggregate(pipeline))
    except Exception as exc:
        logger.error("Outbreak pipeline failed: %s", exc)
        return {"alerts_detected": 0, "alerts": [], "error": str(exc)}

    alerts = []
    detected_syndromes = set()

    for row in results:
        syndrome = row["_id"]["syndrome"]
        ward = row["_id"].get("ward", "Unknown")
        count = row["count"]
        detected_syndromes.add(syndrome)

        baseline_doc = db.baselines.find_one({"county": county, "syndrome": syndrome})
        baseline = baseline_doc.get("weekly_avg") if baseline_doc else None
        pct_above = 0

        if baseline and baseline > 0:
            pct_above = round(((count - baseline) / baseline) * 100, 1)
            if count < baseline * BASELINE_SPIKE_MULTIPLIER:
                continue

        alert = {
            "alert_id": f"{county}-{syndrome}-{ward}-{datetime.utcnow().strftime('%Y%m%d%H')}",
            "syndrome": syndrome,
            "alert_type": "spike",
            "location": {"county": county, "ward": ward},
            "count": count,
            "baseline": baseline,
            "percent_above_baseline": pct_above,
            "encounter_ids": row.get("encounter_ids", []),
            "detected_at": datetime.utcnow().isoformat(),
            "status": "active",
        }
        alerts.append(alert)
        db.alerts.update_one({"alert_id": alert["alert_id"]}, {"$set": alert}, upsert=True)

    for pair, disease in CORRELATED_SYNDROMES.items():
        if pair.issubset(detected_syndromes):
            corr = {
                "alert_id": f"{county}-{disease}-corr-{datetime.utcnow().strftime('%Y%m%d%H')}",
                "syndrome": disease,
                "alert_type": "correlation",
                "contributing_syndromes": list(pair),
                "location": {"county": county, "ward": "Multiple"},
                "count": 0,
                "percent_above_baseline": 0,
                "detected_at": datetime.utcnow().isoformat(),
                "status": "active",
                "priority": "HIGH",
            }
            alerts.append(corr)
            db.alerts.update_one({"alert_id": corr["alert_id"]}, {"$set": corr}, upsert=True)

    return {"county": county, "alerts_detected": len(alerts), "alerts": alerts}


def detect_silent_pandemic(county: str, weeks: int = 4) -> dict:
    """
    Detect silent pandemics — syndromes with a persistent upward trend over
    multiple weeks that never trigger a single-week spike threshold.
    These are the most dangerous: they grow unnoticed until they explode.

    Uses a week-over-week slope analysis across the past N weeks.
    Flags any syndrome with a positive trend_delta across ≥3 weeks.

    Args:
        county: Kenya county name.
        weeks: Number of weeks to analyse (default 4).

    Returns:
        dict with silent_signals (list) — each with syndrome, trend_delta,
        weekly_counts, weekly_avg, and a generated protocol recommendation.
    """
    db = _get_db()
    pipeline = get_silent_pandemic_pipeline(county, weeks)
    try:
        results = list(db.encounters.aggregate(pipeline))
    except Exception as exc:
        logger.error("Silent pandemic pipeline failed: %s", exc)
        return {"silent_signals": [], "error": str(exc)}

    signals = []
    for row in results:
        syndrome = row.get("syndrome") or row.get("_id", "unknown")
        signal = {
            "syndrome": syndrome,
            "county": county,
            "trend_delta": row.get("trend_delta", 0),
            "weekly_counts": row.get("weekly_counts", []),
            "weekly_avg": round(row.get("weekly_avg", 0), 2),
            "weeks_observed": row.get("weeks_observed", 0),
            "total_cases": row.get("total_cases", 0),
            "signal_type": "silent_pandemic",
            "detected_at": datetime.utcnow().isoformat(),
            "risk_level": (
                "HIGH" if row.get("trend_delta", 0) > 5
                else "MEDIUM" if row.get("trend_delta", 0) > 2
                else "LOW"
            ),
        }
        # Persist as a special alert type
        alert_id = f"{county}-{syndrome}-silent-{datetime.utcnow().strftime('%Y%m%d')}"
        db.alerts.update_one(
            {"alert_id": alert_id},
            {"$set": {**signal, "alert_id": alert_id, "status": "active",
                      "alert_type": "silent_pandemic"}},
            upsert=True,
        )
        signals.append(signal)

    return {
        "county": county,
        "weeks_analysed": weeks,
        "silent_signals": signals,
        "signals_detected": len(signals),
    }


def detect_cross_county_spread(syndrome: str, hours: int = 48) -> dict:
    """
    Detect whether a syndrome is simultaneously rising in multiple counties,
    indicating cross-county spread or a common-source outbreak (e.g., contaminated
    water supply, mass gathering).

    Args:
        syndrome: WHO IDSR syndrome category to track.
        hours: Time window in hours (default 48).

    Returns:
        dict with counties_affected (list), spread_detected (bool),
        and recommended escalation level.
    """
    db = _get_db()
    pipeline = get_cross_county_spread_pipeline(syndrome, hours)
    try:
        results = list(db.encounters.aggregate(pipeline))
    except Exception as exc:
        logger.error("Cross-county spread pipeline failed: %s", exc)
        return {"spread_detected": False, "error": str(exc)}

    counties_affected = [
        {
            "county": r.get("county") or r.get("_id"),
            "count": r.get("count", 0),
            "wards_affected": r.get("wards_affected_count", 0),
            "latest_case": r.get("latest_case", ""),
        }
        for r in results
    ]

    spread_detected = len(counties_affected) >= 2
    escalation = "NATIONAL" if len(counties_affected) >= 3 else "REGIONAL" if spread_detected else "LOCAL"

    if spread_detected:
        alert_id = f"spread-{syndrome}-{datetime.utcnow().strftime('%Y%m%d%H')}"
        db.alerts.update_one(
            {"alert_id": alert_id},
            {"$set": {
                "alert_id": alert_id,
                "syndrome": syndrome,
                "alert_type": "cross_county_spread",
                "counties_affected": counties_affected,
                "escalation_level": escalation,
                "detected_at": datetime.utcnow().isoformat(),
                "status": "active",
                "priority": "HIGH",
            }},
            upsert=True,
        )

    return {
        "syndrome": syndrome,
        "spread_detected": spread_detected,
        "counties_affected": counties_affected,
        "counties_count": len(counties_affected),
        "escalation_level": escalation,
    }


def formulate_response_protocol(syndrome: str, county: str, alert_level: str = "YELLOW") -> dict:
    """
    Generate and persist a structured response protocol for a detected syndrome.
    Combines WHO IDSR guidelines with Kenya MoH protocols and local context.
    Protocols are stored in MongoDB for CHW retrieval via Telegram /protocol command.

    Args:
        syndrome: WHO IDSR syndrome category.
        county: Affected county (for localisation).
        alert_level: RED, YELLOW, or GREEN.

    Returns:
        dict with protocol_id, immediate_actions, chw_actions,
        follow_up_days, and reporting_threshold.
    """
    db = _get_db()
    template = PROTOCOL_TEMPLATES.get(syndrome, PROTOCOL_TEMPLATES["default"]).copy()
    template["alert_level"] = alert_level

    protocol_doc = {
        "protocol_id": f"PROTO-{syndrome.upper()[:6]}-{county[:3].upper()}-{datetime.utcnow().strftime('%Y%m%d')}",
        "syndrome": syndrome,
        "county": county,
        "alert_level": alert_level,
        "immediate_actions": template["immediate_actions"],
        "chw_actions": template["chw_actions"],
        "follow_up_days": template["follow_up_days"],
        "reporting_threshold": template["reporting_threshold"],
        "who_idsr_code": template.get("who_idsr_code", "UNK"),
        "created_at": datetime.utcnow().isoformat(),
        "status": "active",
        "version": 1,
    }

    db.protocols.update_one(
        {"syndrome": syndrome, "county": county},
        {"$set": protocol_doc, "$inc": {"version": 0}},
        upsert=True,
    )
    logger.info("Protocol formulated: %s for %s", syndrome, county)
    return protocol_doc


def get_protocol(syndrome: str, county: Optional[str] = None) -> dict:
    """
    Retrieve the active response protocol for a syndrome, optionally county-specific.
    Used by CHWs via the Telegram /protocol command.

    Args:
        syndrome: WHO IDSR syndrome category.
        county: Optional county for localised protocol.

    Returns:
        dict with the full protocol document, or the default template if none stored.
    """
    db = _get_db()
    query: Dict[str, Any] = {"syndrome": syndrome, "status": "active"}
    if county:
        query["county"] = county

    doc = db.protocols.find_one(query, {"_id": 0}, sort=[("created_at", -1)])
    if doc:
        return doc

    # Fall back to template
    template = PROTOCOL_TEMPLATES.get(syndrome, PROTOCOL_TEMPLATES["default"]).copy()
    template["syndrome"] = syndrome
    template["county"] = county or "all"
    template["source"] = "template"
    return template


def run_vector_similarity_search(query_vector: list, lat: float, lng: float, top_k: int = 10) -> dict:
    """
    Use Atlas Vector Search to find semantically similar clinical cases.
    Requires the vector_index on encounters.embedding.

    Args:
        query_vector: 768-dim embedding from text-embedding-004.
        lat: Latitude for geospatial context.
        lng: Longitude for geospatial context.
        top_k: Number of similar cases to return (default 10).

    Returns:
        dict with similar_cases (list) and count (int).
    """
    db = _get_db()
    pipeline = get_vector_similarity_pipeline(query_vector, lat, lng)
    try:
        results = list(db.encounters.aggregate(pipeline))
        return {"similar_cases": results[:top_k], "count": len(results)}
    except Exception as exc:
        logger.error("Vector similarity search failed: %s", exc)
        return {"similar_cases": [], "count": 0, "error": str(exc)}


def update_baselines(county: Optional[str] = None) -> dict:
    """
    Recalculate 4-week rolling baselines for each syndrome per county.
    Stores results in the baselines collection for spike detection.

    Args:
        county: Optional county to update. If None, updates all counties.

    Returns:
        dict with baselines_updated count and county scope.
    """
    db = _get_db()
    four_weeks_ago = datetime.utcnow() - timedelta(weeks=4)
    match_stage: Dict[str, Any] = {"timestamp": {"$gte": four_weeks_ago}}
    if county:
        match_stage["admin_hierarchy.county"] = county

    pipeline = [
        {"$match": match_stage},
        {"$group": {
            "_id": {"county": "$admin_hierarchy.county", "syndrome": "$extracted.syndrome"},
            "total_cases": {"$sum": 1},
            "weeks_with_data": {"$addToSet": {"$week": "$timestamp"}},
        }},
        {"$project": {
            "county": "$_id.county",
            "syndrome": "$_id.syndrome",
            "weekly_avg": {"$divide": ["$total_cases", {"$max": [{"$size": "$weeks_with_data"}, 1]}]},
            "total_cases": 1,
            "weeks_with_data": {"$size": "$weeks_with_data"},
        }},
    ]
    try:
        rows = list(db.encounters.aggregate(pipeline))
        updated = 0
        for row in rows:
            db.baselines.update_one(
                {"county": row["county"], "syndrome": row["syndrome"]},
                {"$set": {
                    "weekly_avg": row["weekly_avg"],
                    "total_cases": row["total_cases"],
                    "weeks_with_data": row["weeks_with_data"],
                    "updated_at": datetime.utcnow(),
                    "sufficient_data": row["weeks_with_data"] >= 4,
                }},
                upsert=True,
            )
            updated += 1
        return {"baselines_updated": updated, "county": county or "all"}
    except Exception as exc:
        logger.error("update_baselines failed: %s", exc)
        return {"baselines_updated": 0, "error": str(exc)}


def get_county_stats(county: str) -> dict:
    """
    Get quick surveillance statistics for a county.
    Used by the Telegram /status command and the dashboard.

    Args:
        county: Kenya county name.

    Returns:
        dict with encounters_today, active_alerts, pending_followups, active_chws.
    """
    db = _get_db()
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        encounters_today = db.encounters.count_documents(
            {"admin_hierarchy.county": county, "timestamp": {"$gte": today}}
        )
        active_alerts = db.alerts.count_documents(
            {"location.county": county, "status": "active"}
        )
        pending_followups = db.follow_ups.count_documents(
            {"county": county, "status": "pending"}
        )
        active_chws = db.chws.count_documents(
            {"county": county, "status": "active"}
        )
        return {
            "encounters_today": encounters_today,
            "active_alerts": active_alerts,
            "pending_followups": pending_followups,
            "active_chws": active_chws,
        }
    except Exception as exc:
        logger.error("get_county_stats failed: %s", exc)
        return {"encounters_today": 0, "active_alerts": 0, "error": str(exc)}


def detect_chw_outreach_gaps(county: str, days: int = 7) -> dict:
    """
    Identify wards with low or zero CHW encounter submissions — a proxy for
    outreach coverage gaps. Returns wards needing supervisor follow-up and
    suggests targeted deployment of additional CHWs.

    Args:
        county: Kenya county name.
        days: Time window for activity check (default 7 days).

    Returns:
        dict with gap_wards (list), total_gap_wards, and recommended_actions.
    """
    db = _get_db()
    pipeline = get_underreporting_pipeline(county, days)
    try:
        results = list(db.encounters.aggregate(pipeline))
    except Exception as exc:
        logger.error("Underreporting pipeline failed: %s", exc)
        return {"gap_wards": [], "error": str(exc)}

    gap_wards = []
    for row in results:
        ward = row.get("ward") or row.get("_id", "Unknown")
        gap_wards.append({
            "ward": ward,
            "county": county,
            "encounter_count": row.get("encounter_count", 0),
            "active_chws": row.get("active_chws", 0),
            "days_since_last_submission": round(row.get("days_since_last", 0), 1),
            "gap_severity": (
                "CRITICAL" if row.get("encounter_count", 0) == 0
                else "HIGH" if row.get("encounter_count", 0) < 2
                else "MEDIUM"
            ),
        })

    recommended_actions = []
    if gap_wards:
        critical = [w for w in gap_wards if w["gap_severity"] == "CRITICAL"]
        if critical:
            recommended_actions.append(
                f"URGENT: {len(critical)} wards with zero submissions — "
                f"deploy supervisor to: {', '.join(w['ward'] for w in critical[:3])}"
            )
        recommended_actions.append(
            f"Send motivational broadcast to CHWs in {county} via Telegram"
        )
        recommended_actions.append(
            "Schedule refresher training for low-performing wards"
        )

    return {
        "county": county,
        "days_analysed": days,
        "total_gap_wards": len(gap_wards),
        "gap_wards": gap_wards,
        "recommended_actions": recommended_actions,
    }


def get_chw_performance(county: str, weeks: int = 4) -> dict:
    """
    Analyse CHW performance metrics: encounters submitted, RED/YELLOW cases
    identified, and weeks active. Identifies top performers and those needing support.

    Args:
        county: Kenya county name.
        weeks: Number of weeks to analyse (default 4).

    Returns:
        dict with chw_stats (list), top_performers, needs_support.
    """
    db = _get_db()
    pipeline = get_chw_performance_pipeline(county, weeks)
    try:
        results = list(db.encounters.aggregate(pipeline))
    except Exception as exc:
        logger.error("CHW performance pipeline failed: %s", exc)
        return {"chw_stats": [], "error": str(exc)}

    chw_stats = []
    for row in results:
        chw_id = row.get("_id", "unknown")
        chw_doc = db.chws.find_one({"chw_id": chw_id}, {"_id": 0, "name": 1, "ward": 1})
        chw_stats.append({
            "chw_id": chw_id,
            "name": chw_doc.get("name", "Unknown") if chw_doc else "Unknown",
            "ward": chw_doc.get("ward", "Unknown") if chw_doc else "Unknown",
            "total_encounters": row.get("total_encounters", 0),
            "total_red": row.get("total_red", 0),
            "total_yellow": row.get("total_yellow", 0),
            "weeks_active": row.get("weeks_active", 0),
            "avg_per_week": round(row.get("avg_per_week", 0), 1),
        })

    avg_encounters = (
        sum(c["total_encounters"] for c in chw_stats) / len(chw_stats)
        if chw_stats else 0
    )
    top_performers = [c for c in chw_stats if c["total_encounters"] >= avg_encounters * 1.5]
    needs_support = [c for c in chw_stats if c["total_encounters"] < avg_encounters * 0.5]

    return {
        "county": county,
        "weeks_analysed": weeks,
        "total_chws": len(chw_stats),
        "chw_stats": chw_stats,
        "top_performers": top_performers,
        "needs_support": needs_support,
        "county_avg_per_week": round(avg_encounters / max(weeks, 1), 1),
    }


# ═════════════════════════════════════════════════════════════════════════════
# ADK root_agent
# ═════════════════════════════════════════════════════════════════════════════

root_agent = LlmAgent(
    name="surveillance_agent",
    model="gemini-flash-latest",
    description=(
        "SihaLink Surveillance Agent. Detects outbreaks, silent pandemics, and "
        "cross-county spread using MongoDB aggregation pipelines and Atlas Vector Search. "
        "Formulates WHO/MoH response protocols. Identifies CHW outreach gaps. "
        "Runs every 6 hours or on-demand."
    ),
    instruction="""You are the SihaLink Surveillance Agent — the epidemiological intelligence brain.

YOUR FOUR MISSIONS:

1. OUTBREAK DETECTION (every 6 hours)
   - Call run_outbreak_detection for each active county
   - Compare against 4-week baselines; alert on ≥2× spike
   - Check correlated syndrome pairs (cholera, measles, influenza, SAM)

2. SILENT PANDEMIC DETECTION (weekly)
   - Call detect_silent_pandemic for each county
   - Flag syndromes with consistent upward trend over ≥3 weeks
   - Even if counts are below spike threshold — these are the most dangerous
   - Classify risk: HIGH (delta>5), MEDIUM (delta>2), LOW
   - Call detect_cross_county_spread for any HIGH-risk syndrome

3. PROTOCOL FORMULATION (on any alert)
   - Call formulate_response_protocol immediately for every new alert
   - Protocols are stored in MongoDB and retrievable by CHWs via /protocol
   - Include: immediate actions, CHW field actions, follow-up schedule

4. CHW OUTREACH IMPROVEMENT (daily)
   - Call detect_chw_outreach_gaps to find silent wards
   - Call get_chw_performance to identify who needs support
   - Generate targeted recommendations for supervisors

DECISION RULES:
- Silent pandemic signal → formulate protocol + notify district officer
- Cross-county spread (≥2 counties) → escalate to REGIONAL level
- Cross-county spread (≥3 counties) → escalate to NATIONAL level
- CHW gap ward (0 submissions in 7 days) → CRITICAL — supervisor deployment

ALWAYS: Persist all findings to MongoDB. Report with: syndrome, location,
evidence (counts/trend), risk level, and specific recommended actions.
""",
    tools=[
        run_outbreak_detection,
        detect_silent_pandemic,
        detect_cross_county_spread,
        formulate_response_protocol,
        get_protocol,
        run_vector_similarity_search,
        update_baselines,
        get_county_stats,
        detect_chw_outreach_gaps,
        get_chw_performance,
    ],
    generate_content_config=genai_types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=1024,
    ),
)

APP_NAME = "sihalink_surveillance"
_session_service = InMemorySessionService()
_runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=_session_service)


# ── Backward-compatible class wrapper ────────────────────────────────────────

class SurveillanceAgent:
    """Thin wrapper for Orchestrator state machine compatibility."""

    async def run_outbreak_detection(self, county: str, lat: float, lng: float, hours: int = 6) -> List[Dict[str, Any]]:
        return run_outbreak_detection(county, lat, lng, hours).get("alerts", [])

    async def detect_silent_pandemic(self, county: str, weeks: int = 4) -> Dict[str, Any]:
        return detect_silent_pandemic(county, weeks)

    async def detect_cross_county_spread(self, syndrome: str, hours: int = 48) -> Dict[str, Any]:
        return detect_cross_county_spread(syndrome, hours)

    async def formulate_response_protocol(self, syndrome: str, county: str, alert_level: str = "YELLOW") -> Dict[str, Any]:
        return formulate_response_protocol(syndrome, county, alert_level)

    async def get_protocol(self, syndrome: str, county: Optional[str] = None) -> Dict[str, Any]:
        return get_protocol(syndrome, county)

    async def run_vector_similarity_search(self, query_vector: List[float], lat: float, lng: float) -> List[Dict[str, Any]]:
        return run_vector_similarity_search(query_vector, lat, lng).get("similar_cases", [])

    async def update_baselines(self, county: Optional[str] = None) -> Dict[str, Any]:
        return update_baselines(county)

    async def get_county_stats(self, county: str) -> Dict[str, Any]:
        return get_county_stats(county)

    async def detect_chw_outreach_gaps(self, county: str, days: int = 7) -> Dict[str, Any]:
        return detect_chw_outreach_gaps(county, days)

    async def get_chw_performance(self, county: str, weeks: int = 4) -> Dict[str, Any]:
        return get_chw_performance(county, weeks)
