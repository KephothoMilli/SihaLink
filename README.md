# AfyaVoice — Sauti ya Afya

This workspace contains the AfyaVoice multi-agent swarm prototype for the Google Cloud Rapid Agent Hackathon (MongoDB track).

Quick start (local development):

1. Create a Python virtualenv and install dependencies (FastAPI, uvicorn, pymongo, google-generative-ai):

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install fastapi uvicorn pymongo google-generative-ai googlemaps
```

1. Set environment variables (example):

```powershell
$env:GEMINI_API_KEY = "your_gemini_key"
$env:GOOGLE_MAPS_API_KEY = "your_maps_key"
$env:MONGODB_ATLAS_URI = "your_mongodb_uri"
```

1. Run the Orchestrator service (development):

```bash
uvicorn agents.orchestrator.agent:app --reload --port 8000
```

1. Use the `/test/run` endpoint to run a simple pipeline.

## Google Cloud Agent Builder Tool Support

The orchestrator exposes Google ADK-compatible tooling via `agents/orchestrator/tool_manifest.json`. The primary tool endpoints are documented in `agents/orchestrator/README.md`.

## Deployment

### Google Agent Runtime + Firebase Hosting

This project uses:
- **Backend**: Google Agent Runtime (instead of Cloud Run)
- **Frontend**: Firebase Hosting (CDN, SPA routing, built-in auth support)

#### Quick Deploy (One Command)

**Linux/macOS:**
```bash
./deploy.sh prod YOUR_PROJECT_ID
```

**Windows (PowerShell):**
```powershell
.\deploy.ps1 -Environment prod -ProjectId YOUR_PROJECT_ID
```

The deployment script handles:
1. ✅ Frontend build & Firebase Hosting deployment
2. ✅ Secret Manager configuration
3. ✅ Service account creation & IAM setup
4. ✅ Container image build & push to GCR
5. ✅ Agent Runtime deployment
6. ✅ Endpoint verification

#### Manual Deployment Steps

**Step 1: Deploy Frontend**
```bash
cd frontend && npm install && npm run build
firebase deploy --only hosting
# Result: https://YOUR_PROJECT_ID.web.app
```

**Step 2: Setup Secrets**
```bash
echo "your-gemini-key" | gcloud secrets create GEMINI_API_KEY --data-file=-
echo "your-maps-key" | gcloud secrets create GOOGLE_MAPS_API_KEY --data-file=-
echo "your-mongodb-uri" | gcloud secrets create MONGODB_ATLAS_URI --data-file=-
```

**Step 3: Build & Push Container**
```bash
gcloud auth configure-docker gcr.io
docker build -t gcr.io/$PROJECT_ID/afyavoice-agent .
docker push gcr.io/$PROJECT_ID/afyavoice-agent
```

**Step 4: Deploy Agent Runtime**
```bash
gcloud agent runtime deploy afya-voice-orchestrator \
  --image gcr.io/$PROJECT_ID/afyavoice-agent \
  --region us-central1 \
  --agent-yaml .google/agent.yaml
```

#### Monitor Deployment

```bash
# View logs
gcloud agent runtime logs read afya-voice-orchestrator --region us-central1 --follow

# Check status
gcloud agent runtime describe afya-voice-orchestrator --region us-central1

# View metrics
gcloud monitoring dashboards list
```

### Legacy Cloud Run Deployment

If you need to deploy to Cloud Run instead:

```bash
gcloud run deploy afya-voice-orchestrator \
  --source . \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --port 8000 \
  --set-env-vars "GEMINI_API_KEY=$GEMINI_API_KEY,GOOGLE_MAPS_API_KEY=$GOOGLE_MAPS_API_KEY,MONGODB_ATLAS_URI=$MONGODB_ATLAS_URI"
```

## Development

### Frontend Development

The repository includes an Angular + Vite frontend under `frontend/`.

```bash
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

### Backend Development

Start the orchestrator service locally:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn agents.orchestrator.agent:app --reload --port 8000
```

### Integration Testing

```bash
# Test the orchestrator endpoint
curl -X POST http://localhost:8000/tool/start_encounter \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test-001",
    "audio_base64": "...",
    "latitude": -1.2864,
    "longitude": 36.8172
  }'
```

## Architecture

```
┌─────────────────────────────────────────────┐
│     Firebase Hosting (CDN)                  │
│     https://YOUR_PROJECT_ID.web.app        │
└────────────────┬────────────────────────────┘
                 │ API calls
┌────────────────▼────────────────────────────┐
│  Google Agent Runtime                       │
│  - Multi-agent orchestrator                 │
│  - Tool manifest exposed                    │
│  - Auto-scaling                             │
└────────────────┬────────────────────────────┘
                 │
        ┌────────┼────────┬──────────┐
        │        │        │          │
  ┌─────▼──┐  ┌─▼─────┐ ┌▼────┐  ┌─▼────┐
  │ Intake │  │ Geo   │ │Data │  │Notify│
  │ Agent  │  │ Agent │ │Agent│  │Agent │
  └─────┬──┘  └─┬─────┘ └┬────┘  └──────┘
        │       │       │
        └───────┼───────┤
                │       │
           ┌────▼───────▼────┐
           │   MongoDB Atlas  │
           │   (Encounters)   │
           └──────────────────┘
```

## Notes

- The Telegram notify bot is implemented in `agents/notify/bot.ts` (Node/grammY). For local end-to-end testing, run it separately and implement the webhook integration.
- This prototype emphasizes state-changing operations (MongoDB writes, index creation, facility lookups). It is intentionally not a conversational chatbot.
- For full Angular CLI support, see `DEPLOYMENT_PLAN.md` for migration guidance.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Agent Runtime not responding | Check logs: `gcloud agent runtime logs read afya-voice-orchestrator` |
| Secrets not found | Verify with: `gcloud secrets list` |
| Firebase deployment fails | Run: `firebase init hosting` and check `firebase.json` |
| Container push fails | Ensure Docker is running and authenticated: `docker ps` |

For detailed deployment architecture, see [DEPLOYMENT_PLAN.md](DEPLOYMENT_PLAN.md).
