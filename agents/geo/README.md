# SihaLink Geo Agent

This service exposes the Geo Agent for Google Cloud Agent Builder / Google ADK.

## Tool endpoint

- `POST /tool/enrich_encounter`
  - Request body: `{ "encounter_json": { ... }, "latitude": float, "longitude": float }`
  - Response: `{ "enriched_encounter": { ... } }`

## Purpose

Enriches encounter records with administrative hierarchy, facility ETAs, and location metadata for routing and surveillance.
