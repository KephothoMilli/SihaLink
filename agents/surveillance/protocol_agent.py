"""
SihaLink Protocol Research Agent
=================================
A fully agentic Google ADK agent that formulates evidence-based clinical
response protocols by searching WHO, CDC, ECDC, Kenya MoH, and other
authoritative public health sources in real time.

Architecture
------------
  ProtocolResearchAgent — LlmAgent (Gemini 2.0 Flash)
    Tools:
      - google_search       (ADK built-in — searches WHO, CDC, MoH, ECDC)
      - save_protocol       (persists the researched protocol to MongoDB)
      - get_existing_protocol  (retrieves an existing protocol to update)
      - get_kenya_context   (pulls Kenya-specific incidence data from MongoDB)

The agent:
  1. Receives a syndrome + county + alert_level
  2. Searches WHO IDSR, CDC, and Kenya MOH guidelines for that syndrome
  3. Synthesises immediate actions, CHW field tasks, follow-up schedule
  4. Saves the structured protocol to MongoDB with source citations
  5. Returns the protocol + sources used
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import google_search  # ADK built-in search tool
from google.genai import types as genai_types

logger = logging.getLogger("SihaLink-ProtocolResearch")

# ── Source authority priority ─────────────────────────────────────────────────
# The agent is instructed to prioritise these domains when researching
AUTHORITATIVE_SOURCES = [
    "who.int",           # WHO — primary authority
    "cdc.gov",           # US CDC
    "ecdc.europa.eu",    # ECDC (European)
    "health.go.ke",      # Kenya MOH
    "afro.who.int",      # WHO Africa regional
    "unicef.org",        # UNICEF (nutrition/childhood)
    "msf.org",           # MSF field protocols
    "ncdc.gov.ng",       # Africa CDC reference
    "africacdc.org",     # Africa CDC
]


# ── Tool: save a researched protocol to MongoDB ───────────────────────────────

def save_protocol(
    syndrome: str,
    county: str,
    alert_level: str,
    source_authority: str,
    immediate_actions: List[str],
    chw_actions: List[str],
    follow_up_days: List[int],
    reporting_threshold: int,
    who_idsr_code: str,
    sources_consulted: List[str],
    research_summary: str,
    version_notes: str = "",
) -> dict:
    """
    Persist an AI-researched response protocol to MongoDB.
    Called by the Protocol Research Agent after synthesising guidance.

    Args:
        syndrome:             WHO IDSR syndrome category.
        county:               Affected county (use 'all' for national).
        alert_level:          RED | YELLOW | GREEN.
        source_authority:     Primary authority (WHO | CDC | MOH_KENYA | ECDC | etc.).
        immediate_actions:    List of ≤8 immediate response actions.
        chw_actions:          List of ≤6 CHW/CHV field tasks.
        follow_up_days:       Day offsets for patient follow-up.
        reporting_threshold:  Minimum cases before protocol activates.
        who_idsr_code:        3-letter WHO IDSR code.
        sources_consulted:    URLs/titles of sources used.
        research_summary:     Brief summary of research findings.
        version_notes:        What changed vs previous version.

    Returns:
        dict with protocol_id, syndrome, county, status.
    """
    try:
        from pymongo import MongoClient
        uri = os.getenv("MONGODB_ATLAS_URI")
        if not uri:
            return {"error": "MONGODB_ATLAS_URI not set"}

        client = MongoClient(uri, appname="sihalink-protocol-agent")
        db = client.sihalink
        now = datetime.utcnow()

        protocol_id = f"PROTO-{syndrome.upper()[:6]}-{county[:3].upper()}-{now.strftime('%Y%m%d')}"

        protocol_doc = {
            "protocol_id":          protocol_id,
            "syndrome":             syndrome,
            "county":               county,
            "alert_level":          alert_level,
            "source_authority":     source_authority,
            "immediate_actions":    immediate_actions,
            "chw_actions":          chw_actions,
            "follow_up_days":       follow_up_days,
            "reporting_threshold":  reporting_threshold,
            "who_idsr_code":        who_idsr_code,
            "sources_consulted":    sources_consulted,
            "research_summary":     research_summary,
            "version_notes":        version_notes,
            "formulated_by":        "protocol_research_agent",
            "created_at":           now.isoformat(),
            "updated_at":           now.isoformat(),
            "status":               "active",
        }

        db.protocols.update_one(
            {"syndrome": syndrome, "county": county},
            {
                "$set": protocol_doc,
                "$inc": {"version": 1},
                "$setOnInsert": {"first_created": now.isoformat()},
            },
            upsert=True,
        )
        client.close()
        logger.info("✅ Protocol saved: %s / %s (authority: %s)", syndrome, county, source_authority)
        return {
            "protocol_id":      protocol_id,
            "syndrome":         syndrome,
            "county":           county,
            "source_authority": source_authority,
            "status":           "saved",
            "sources_count":    len(sources_consulted),
        }
    except Exception as exc:
        logger.error("save_protocol failed: %s", exc)
        return {"error": str(exc)}


def get_existing_protocol(syndrome: str, county: Optional[str] = None) -> dict:
    """
    Retrieve an existing protocol from MongoDB before updating.
    The agent uses this to see what's already stored and decide if it
    needs to update or create fresh.

    Args:
        syndrome: WHO IDSR syndrome.
        county:   Optional county filter.

    Returns:
        Existing protocol dict or {"found": false}.
    """
    try:
        from pymongo import MongoClient
        uri = os.getenv("MONGODB_ATLAS_URI")
        if not uri:
            return {"found": False, "reason": "no_db"}

        client = MongoClient(uri, appname="sihalink-protocol-agent")
        db = client.sihalink
        query: Dict[str, Any] = {"syndrome": syndrome, "status": "active"}
        if county:
            query["county"] = county

        doc = db.protocols.find_one(query, {"_id": 0}, sort=[("updated_at", -1)])
        client.close()

        if doc:
            return {**doc, "found": True}
        return {"found": False}
    except Exception as exc:
        return {"found": False, "error": str(exc)}


def get_kenya_context(syndrome: str, county: str) -> dict:
    """
    Pull Kenya-specific incidence data for a syndrome to contextualise the
    protocol — recent case counts, affected wards, age/sex distribution.
    This gives the agent real-world local data to incorporate in the protocol.

    Args:
        syndrome: Syndrome to query.
        county:   Kenya county.

    Returns:
        dict with recent_cases, top_wards, demographics, alert_history.
    """
    try:
        from pymongo import MongoClient, DESCENDING
        uri = os.getenv("MONGODB_ATLAS_URI")
        if not uri:
            return {"county": county, "syndrome": syndrome, "recent_cases": 0}

        client = MongoClient(uri, appname="sihalink-protocol-agent")
        db = client.sihalink
        cutoff = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        # Recent case count (last 30 days)
        thirty_days_ago = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        from datetime import timedelta
        thirty_days_ago = thirty_days_ago - timedelta(days=30)

        recent_cases = db.encounters.count_documents({
            "admin_hierarchy.county": county,
            "extracted.syndrome":     syndrome,
            "timestamp":              {"$gte": thirty_days_ago},
        })

        # Top wards
        ward_pipeline = [
            {"$match": {
                "admin_hierarchy.county": county,
                "extracted.syndrome": syndrome,
                "timestamp": {"$gte": thirty_days_ago},
            }},
            {"$group": {"_id": "$admin_hierarchy.ward", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 5},
        ]
        top_wards = [
            {"ward": r["_id"], "cases": r["count"]}
            for r in db.encounters.aggregate(ward_pipeline)
        ]

        # Alert history
        alert_history = list(db.alerts.find(
            {"syndrome": syndrome, "location.county": county},
            {"_id": 0, "alert_id": 1, "count": 1, "detected_at": 1, "status": 1},
        ).sort("detected_at", DESCENDING).limit(5))

        client.close()
        return {
            "county":         county,
            "syndrome":       syndrome,
            "recent_cases":   recent_cases,
            "top_wards":      top_wards,
            "alert_history":  alert_history,
            "period_days":    30,
        }
    except Exception as exc:
        logger.warning("get_kenya_context failed: %s", exc)
        return {"county": county, "syndrome": syndrome, "recent_cases": 0}


# ═════════════════════════════════════════════════════════════════════════════
# Protocol Research Agent — the agentic core
# ═════════════════════════════════════════════════════════════════════════════

protocol_research_agent = LlmAgent(
    name="protocol_research_agent",
    model="gemini-2.0-flash",   # Gemini 2.0 Flash for grounded search + reasoning
    description=(
        "Agentic protocol formulation specialist. Researches WHO, CDC, ECDC, "
        "and Kenya MOH guidelines in real time using Google Search, then "
        "synthesises structured response protocols tailored to the Kenya context."
    ),
    instruction="""You are the SihaLink Protocol Research Agent — an epidemiological intelligence
specialist that formulates evidence-based clinical response protocols.

YOUR MISSION:
When given a syndrome, county, and alert level, you must:
1. RESEARCH current WHO, CDC, Kenya MOH, and ECDC guidelines using google_search
2. CONTEXTUALISE with local Kenya data using get_kenya_context
3. CHECK if a protocol already exists using get_existing_protocol
4. SYNTHESISE a structured protocol that is:
   - Evidence-based (cite your sources)
   - Kenya-contextualised (reference local incidence, infrastructure, CHW cadre)
   - Actionable (specific, time-bound actions — not vague advice)
5. SAVE the protocol using save_protocol

RESEARCH STRATEGY:
Search for each syndrome using these query patterns:
  - "[syndrome] WHO IDSR response protocol 2024"
  - "[syndrome] Kenya MOH treatment guidelines"
  - "[syndrome] CDC clinical guidance [year]"
  - "[syndrome] outbreak response Africa field guide"

Prioritise sources in this order:
  1. WHO (who.int, afro.who.int) — global standard
  2. Kenya MoH (health.go.ke) — local authority
  3. CDC (cdc.gov) — clinical depth
  4. ECDC (ecdc.europa.eu) — surveillance methodology
  5. Africa CDC (africacdc.org) — regional context
  6. MSF (msf.org) — field implementation

PROTOCOL STRUCTURE REQUIREMENTS:
immediate_actions (≤8 items):
  - Must be actionable within the FIRST 24 HOURS
  - Include specific thresholds and timeframes ("within 2 hours", "within 24 hours")
  - Reference specific supplies (ORS, PPE level, specific drugs)
  - Name responsible actors (county health officer, rapid response team)

chw_actions (≤6 items):
  - Specific to Community Health Volunteers in Kenya
  - Reference SihaLink tools where relevant ("record via SihaLink intake")
  - Include contact tracing instructions for high-risk syndromes
  - Specify follow-up intervals precisely

follow_up_days: Day offsets from first encounter (e.g., [1, 3, 7, 14])
reporting_threshold: Cases before this protocol fires (1 for VHF/Ebola, 5+ for ARI)

KENYA CONTEXT RULES:
- Kenya has 47 counties; name specific county interventions when relevant
- Reference Kenya National Health Sector Strategic Plan where applicable
- Consider CHV (Community Health Volunteer) capacity — they have basic training
- Include mobile money (M-PESA) or SMS-based tools when relevant
- Reference Kenya IDSR Technical Guidelines (4th edition) as baseline

SOURCE CITATION FORMAT:
sources_consulted: ["WHO: title (url)", "CDC: title (url)", "MOH Kenya: title (url)"]

ALWAYS:
- Search before synthesising — never rely only on training data
- If WHO guidelines conflict with Kenya MOH — note both and defer to MOH Kenya
- Include the research_summary field explaining what you found
- Set version_notes if updating an existing protocol
""",
    tools=[
        google_search,          # ADK built-in: real-time WHO/CDC/MOH research
        save_protocol,          # persist to MongoDB
        get_existing_protocol,  # check for existing protocol
        get_kenya_context,      # pull local incidence data
    ],
    generate_content_config=genai_types.GenerateContentConfig(
        temperature=0.2,        # slightly higher than 0.1 for synthesis creativity
        max_output_tokens=2048,
    ),
)

# ── Runner ────────────────────────────────────────────────────────────────────
_proto_session_service = InMemorySessionService()
_proto_runner = Runner(
    agent=protocol_research_agent,
    app_name="sihalink_protocol_research",
    session_service=_proto_session_service,
)


# ── Public API called by surveillance agent ───────────────────────────────────

async def research_and_formulate_protocol(
    syndrome: str,
    county: str,
    alert_level: str = "YELLOW",
    force_refresh: bool = False,
) -> dict:
    """
    Run the Protocol Research Agent to produce an evidence-based protocol.
    This is the agentic path — Gemini searches WHO/CDC/MOH in real time.

    Args:
        syndrome:      WHO IDSR syndrome category.
        county:        Kenya county name.
        alert_level:   RED | YELLOW | GREEN.
        force_refresh: If True, re-research even if protocol exists.

    Returns:
        Protocol dict with source_authority, sources_consulted, research_summary.
    """
    import uuid
    session_id = f"proto-{syndrome}-{county}-{uuid.uuid4().hex[:8]}"

    user_message = (
        f"Formulate a response protocol for {syndrome.upper()} "
        f"in {county} County, Kenya. Alert level: {alert_level}. "
        f"{'Force-refresh the protocol even if it exists.' if force_refresh else ''}"
        f"Search WHO, CDC, and Kenya MOH guidelines, then save the protocol."
    )

    try:
        session = await _proto_session_service.create_session(
            app_name="sihalink_protocol_research",
            user_id="surveillance_agent",
            session_id=session_id,
        )

        final_response = None
        async for event in _proto_runner.run_async(
            user_id="surveillance_agent",
            session_id=session_id,
            new_message=genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=user_message)],
            ),
        ):
            if event.is_final_response() and event.content:
                parts = event.content.parts or []
                final_response = " ".join(
                    p.text for p in parts if hasattr(p, "text") and p.text
                )

        logger.info(
            "✅ Protocol research complete for %s/%s: %s",
            syndrome, county,
            final_response[:120] if final_response else "no response",
        )

        # Retrieve the saved protocol
        from pymongo import MongoClient
        uri = os.getenv("MONGODB_ATLAS_URI")
        if uri:
            client = MongoClient(uri, appname="sihalink")
            doc = client.sihalink.protocols.find_one(
                {"syndrome": syndrome, "county": county, "status": "active"},
                {"_id": 0},
                sort=[("updated_at", -1)],
            )
            client.close()
            if doc:
                return doc

        return {
            "syndrome":     syndrome,
            "county":       county,
            "alert_level":  alert_level,
            "status":       "researched",
            "agent_output": final_response,
        }

    except Exception as exc:
        logger.error("Protocol research agent failed: %s", exc)
        return {"syndrome": syndrome, "county": county, "error": str(exc)}


def research_and_formulate_protocol_sync(
    syndrome: str,
    county: str,
    alert_level: str = "YELLOW",
    force_refresh: bool = False,
) -> dict:
    """Synchronous wrapper for research_and_formulate_protocol."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            asyncio.run,
            research_and_formulate_protocol(syndrome, county, alert_level, force_refresh),
        )
        try:
            return future.result(timeout=60)
        except Exception as exc:
            logger.error("Protocol research sync wrapper failed: %s", exc)
            return {"syndrome": syndrome, "county": county, "error": str(exc)}
