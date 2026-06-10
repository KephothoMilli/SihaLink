# SihaLink Data Agent

This service exposes the Data Agent for Google Cloud Agent Builder / Google ADK.

## Tool endpoints

- `POST /tool/insert_encounter`
  - Request body: `{ "enriched_encounter": { ... } }`
  - Response: `{ "inserted_id": "..." }`

- `POST /tool/query_active_alerts`
  - Request body: `{ "county": "string" }`
  - Response: `[...]`

- `POST /tool/update_alert_status`
  - Request body: `{ "alert_id": "string", "status": "string", "user_id": "string" }`
  - Response: `{ "matched_count": number, "modified_count": number }`

## Purpose

Handles MongoDB persistence and alert/referral operations for encounters and active surveillance.
