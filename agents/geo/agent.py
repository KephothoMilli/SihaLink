"""
Geo Agent — SihaLink (Google ADK)
Location enrichment: GPS → admin hierarchy + nearest health facilities + ETAs.

ADK pattern:
  - root_agent: LlmAgent with function tools
  - Model: gemini-flash-latest (text, no streaming needed for geo enrichment)
  - Tools wrap Google Maps API calls
"""

import os
import logging
from typing import Any, Dict, List

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from .maps_client import GeoAgent as _GeoClient

logger = logging.getLogger("SihaLink-Geo")

# Singleton Maps client (initialized lazily)
_geo_client: _GeoClient | None = None


def _get_client() -> _GeoClient:
    global _geo_client
    if _geo_client is None:
        _geo_client = _GeoClient()
    return _geo_client


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def get_admin_hierarchy(latitude: float, longitude: float) -> dict:
    """
    Reverse-geocode GPS coordinates to Kenya's administrative hierarchy.
    Returns village, ward, sub-county, and county.

    Args:
        latitude: GPS latitude (e.g., -1.2864).
        longitude: GPS longitude (e.g., 36.8172).

    Returns:
        dict with keys: village, ward, sub_county, county.
    """
    try:
        return _get_client()._get_admin_hierarchy(latitude, longitude)
    except Exception as exc:
        logger.error("Admin hierarchy lookup failed: %s", exc)
        return {"village": "Unknown", "ward": "Unknown",
                "sub_county": "Unknown", "county": "Unknown"}


def find_nearest_facilities(latitude: float, longitude: float) -> list:
    """
    Find the nearest health facilities within 50km of the given GPS coordinates.
    Returns up to 5 facilities with name, address, distance, ETA, and open status.

    Args:
        latitude: GPS latitude.
        longitude: GPS longitude.

    Returns:
        List of facility dicts with keys: place_id, name, address,
        distance_km, eta_minutes, open_now, has_emergency.
    """
    try:
        facilities = _get_client()._find_nearby_facilities(latitude, longitude)
        if facilities:
            facilities = _get_client()._add_etas(latitude, longitude, facilities[:5])
        return facilities
    except Exception as exc:
        logger.error("Facility search failed: %s", exc)
        return []


def enrich_encounter_location(
    encounter_json: dict, latitude: float, longitude: float
) -> dict:
    """
    Fully enrich an encounter with location data: admin hierarchy + facilities + ETAs.
    This is the primary tool called by the Orchestrator after clinical extraction.

    Args:
        encounter_json: The extracted clinical JSON from the Intake Agent.
        latitude: GPS latitude from the CHV device.
        longitude: GPS longitude from the CHV device.

    Returns:
        The encounter_json enriched with location, admin_hierarchy,
        nearest_facilities, and location_confidence fields.
    """
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    _get_client().enrich_location(
                        encounter_json, {"lat": latitude, "lng": longitude}
                    )
                )
                return future.result(timeout=15)
        else:
            return loop.run_until_complete(
                _get_client().enrich_location(
                    encounter_json, {"lat": latitude, "lng": longitude}
                )
            )
    except Exception as exc:
        logger.error("Location enrichment failed: %s", exc)
        encounter_json["location_confidence"] = "low"
        encounter_json["location"] = {
            "type": "Point", "coordinates": [longitude, latitude]
        }
        return encounter_json


# ---------------------------------------------------------------------------
# ADK root_agent
# ---------------------------------------------------------------------------

root_agent = LlmAgent(
    name="geo_agent",
    model="gemini-flash-latest",
    description=(
        "Location enrichment agent for SihaLink. "
        "Converts GPS coordinates to Kenya administrative hierarchy "
        "(village → ward → sub-county → county) and finds the nearest "
        "health facilities with real-time ETAs."
    ),
    instruction="""You are the SihaLink Geo Agent.

YOUR ROLE:
- Enrich clinical encounter data with precise location information
- Convert GPS coordinates to Kenya's administrative hierarchy
- Find the nearest health facilities and calculate driving ETAs

WORKFLOW:
1. Call enrich_encounter_location with the encounter JSON and GPS coordinates
2. If enrichment fails (location_confidence = 'low'), still return the encounter
   with whatever location data is available — never block the pipeline
3. Report the top facility name and ETA in your response

IMPORTANT:
- Always prioritize facilities with has_emergency=true for RED triage cases
- If no facilities found within 50km, note this clearly
- Location data is critical for outbreak surveillance — always capture it
""",
    tools=[get_admin_hierarchy, find_nearest_facilities, enrich_encounter_location],
    generate_content_config=genai_types.GenerateContentConfig(
        temperature=0.0,  # Deterministic for geo lookups
        max_output_tokens=256,
    ),
)

# ---------------------------------------------------------------------------
# Runner setup (for adk run / Agent Runtime)
# ---------------------------------------------------------------------------

APP_NAME = "sihalink_geo"
_session_service = InMemorySessionService()
_runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=_session_service,
)
