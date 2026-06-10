# AfyaVoice Orchestrator

This service is the orchestrator layer for the AfyaVoice system. It routes encounter audio through Intake, enriches with Geo, stores data in MongoDB, applies a human-in-the-loop gate for urgent referrals, and dispatches alerts via Notify.

## Google Cloud Agent Builder Compatibility

The orchestrator exposes a set of Google ADK-compatible tool endpoints via FastAPI.

Tool manifest: `agents/orchestrator/tool_manifest.json`

Key tool endpoints:

- `POST /tool/start_encounter` — initialize an encounter session and start the orchestrator lifecycle
- `POST /tool/route_to_intake` — extract clinical JSON from base64 audio
- `POST /tool/route_to_geo` — enrich encounter with admin hierarchy and facility ETAs
- `POST /tool/route_to_data` — insert geo-enriched encounter into MongoDB
- `POST /tool/request_human_decision` — pause and confirm CHV referral or alert
- `POST /tool/route_to_notify` — send a notification payload for Telegram delivery
- `POST /tool/trigger_surveillance` — schedule or trigger surveillance processing
- `POST /tool/queue_offline_encounter` — queue offline encounters for later sync
- `POST /tool/process_offline_queue` — replay queued encounters when connectivity returns

## Recommended environment variables

- `GEMINI_API_KEY`
- `GOOGLE_MAPS_API_KEY`
- `MONGODB_ATLAS_URI`

## Run locally

```bash
uvicorn agents.orchestrator.agent:app --reload --port 8000
```

## Cloud Run deployment path

A Dockerfile is provided at the repository root. Deploy the orchestrator to Cloud Run using the following pattern:

```bash
gcloud run deploy afya-voice-orchestrator \
  --source . \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --port 8000 \
  --set-env-vars "GEMINI_API_KEY=$GEMINI_API_KEY,GOOGLE_MAPS_API_KEY=$GOOGLE_MAPS_API_KEY,MONGODB_ATLAS_URI=$MONGODB_ATLAS_URI"
```

If you want to build a container image manually:

```bash
gcloud builds submit --tag gcr.io/$PROJECT_ID/afyavoice-orchestrator .
```
