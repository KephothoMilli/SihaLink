# SihaLink Intake Agent

This service exposes the Intake Agent for Google Cloud Agent Builder / Google ADK.

## Tool endpoint

- `POST /tool/extract_clinical_data`
  - Request body: `{ "audio_base64": "string" }`
  - Response: `{ "extracted": { ... } }`

## Purpose

Converts base64-encoded CHV audio into structured clinical JSON for subsequent orchestration and triage.
