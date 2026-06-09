# SihaLink — Google Cloud Run Deployment Guide

## Architecture

```
Firebase Hosting (Angular SPA)
         │  HTTPS
         ▼
Google Cloud Run  ←──── Cloud Build CI/CD (on push to main)
  sihalink-orchestrator
  ├── uvicorn :8080  (FastAPI orchestrator  — primary Cloud Run port)
  └── node    :3001  (Notify Agent / grammY — internal Telegram bot)
         │
         ├── Vertex AI / Gemini 2.5 Flash
         ├── Google Maps Platform
         ├── MongoDB Atlas (Vector Search)
         └── Dynatrace OTLP (traces/metrics/logs)
```

## Prerequisites

```bash
# Install tools
gcloud auth login
gcloud auth application-default login
gcloud config set project kephothoagenticai

# Docker must be running
docker info

# Firebase CLI (for hosting deploy)
npm install -g firebase-tools
firebase login
```

## First-Time Setup (run once)

### 1. Push secrets to Secret Manager

```bash
chmod +x deploy/setup-secrets.sh
./deploy/setup-secrets.sh kephothoagenticai .env
```

This reads your local `.env` and creates each secret in Google Secret Manager.

### 2. Manual secrets not in `.env`

If `VOYAGE_API_KEY` is not set:

```bash
echo "YOUR_VOYAGE_KEY" | gcloud secrets create VOYAGE_API_KEY --data-file=-
```

### 3. Enable required APIs (auto-handled by deploy.sh)

```bash
gcloud services enable \
  run.googleapis.com \
  secretmanager.googleapis.com \
  containerregistry.googleapis.com \
  aiplatform.googleapis.com
```

---

## Deploy

```bash
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

The script does:

1. Authenticates with GCP
2. Enables required APIs
3. Creates/verifies service account + IAM roles
4. Verifies all secrets exist in Secret Manager
5. Builds the multi-stage Docker image (Node build → Angular build → Python runtime)
6. Pushes to GCR
7. Deploys to Cloud Run with secrets injected
8. Rebuilds Angular frontend with the real Cloud Run URL as `VITE_API_URL`
9. Deploys frontend to Firebase Hosting
10. Runs a `/health` smoke test

---

## Cloud Build CI/CD (automatic)

Set up a trigger in Cloud Build to run on every push to `main`:

```bash
gcloud builds triggers create github \
  --repo-name=SihaLink \
  --repo-owner=YOUR_GITHUB_USERNAME \
  --branch-pattern="^main$" \
  --build-config=deploy/cloudbuild.yaml \
  --project=kephothoagenticai
```

Add required substitution variables in the trigger:
| Variable | Value |
|---|---|
| `_PROJECT_ID` | `kephothoagenticai` |
| `_REGION` | `us-central1` |
| `_SERVICE_NAME` | `sihalink-orchestrator` |
| `_SERVICE_URL` | Set after first manual deploy |
| `_FIREBASE_PROJECT` | `kephothoagenticai` |

---

## Key Cloud Run configuration decisions

### Why `--min-instances=1`

CHVs are in the field at unpredictable times. Cold starts of 15-30s are unacceptable for emergency clinical encounters. One warm instance keeps the API responsive 24/7.

### Why `--no-cpu-throttling`

Cloud Run normally throttles CPU to near zero between requests. This breaks:

- The supervisord process manager (uvicorn + Node.js both need CPU)
- SSE `/swarm/stream` keepalive coroutines (they run between requests)
- Background surveillance scheduler tasks

### Why `--timeout=3600`

The SSE endpoint `/swarm/stream` keeps connections open for the lifetime of the browser tab. Cloud Run's default 300s timeout would disconnect the live alert stream.

### Why `gen2` execution environment

- Full Linux kernel (required by some Python packages)
- Faster startup (50ms vs 250ms)
- Better concurrent request handling
- Supports larger memory (up to 32Gi)

### Why supervisord (two processes in one container)

The Notify Agent (Node.js/grammY) and Orchestrator (Python/FastAPI) communicate on `localhost:3001`. Cloud Run runs one container per instance, so both must coexist. Supervisord is the standard process manager for this pattern — it also restarts either process if it crashes.

An alternative is separate Cloud Run services with VPC connector, but that adds cost and latency for what is effectively a sidecar.

---

## Secrets management

All secrets are stored in Google Secret Manager and injected as environment variables at deploy time. **No secrets are baked into the image.**

| Secret                 | Used by                                            |
| ---------------------- | -------------------------------------------------- |
| `GEMINI_API_KEY`       | Vertex AI / Gemini (fallback if ADC not available) |
| `GOOGLE_MAPS_API_KEY`  | Geo Agent (Places, Geocoding, Directions)          |
| `MONGODB_ATLAS_URI`    | Data Agent (Atlas Vector Search)                   |
| `TELEGRAM_BOT_TOKEN`   | Notify Agent (grammY bot)                          |
| `FACILITY_TELEGRAM_ID` | Notify Agent (referral dispatch)                   |
| `VOYAGE_API_KEY`       | Data Agent (embeddings)                            |
| `DYNATRACE_API_TOKEN`  | Telemetry (OTel traces/metrics)                    |

Update a secret:

```bash
echo "NEW_VALUE" | gcloud secrets versions add SECRET_NAME --data-file=-
# Then redeploy:
gcloud run deploy sihalink-orchestrator --image gcr.io/kephothoagenticai/sihalink-orchestrator:latest --region us-central1
```

---

## Useful commands

```bash
# Stream logs in real time
gcloud run services logs read sihalink-orchestrator --region us-central1 --follow

# Check current revision
gcloud run revisions list --service sihalink-orchestrator --region us-central1

# Roll back to previous revision
gcloud run services update-traffic sihalink-orchestrator \
  --to-revisions=PREV=100 --region us-central1

# Scale to zero (cost saving)
gcloud run services update sihalink-orchestrator \
  --min-instances=0 --region us-central1

# Test locally before deploying
docker build -t sihalink-local .
docker run -p 8080:8080 --env-file .env sihalink-local

# Check health
curl https://YOUR_SERVICE_URL/health | python3 -m json.tool

# Check swarm status
curl https://YOUR_SERVICE_URL/swarm/status | python3 -m json.tool
```

---

## Troubleshooting

### Container fails to start

```bash
gcloud run services logs read sihalink-orchestrator --region us-central1 --limit 50
```

Common causes:

- Missing secret (`KeyError` / `RuntimeError: MONGODB_ATLAS_URI not set`)
- MongoDB Atlas IP not allowing Cloud Run egress IPs — add `0.0.0.0/0` in Atlas Network Access

### 422 on `/swarm/stream`

Fixed in the orchestrator: `Request` was a forward-reference string. Now properly imported from `fastapi`.

### SSE disconnects after 5 minutes

Ensure `--timeout=3600` and `--no-cpu-throttling` are set. Cloud Run default timeout is 300s.

### MongoDB connection timeout in Cloud Run

Atlas firewall blocks unknown IPs. Add Cloud Run's egress IP range or allow `0.0.0.0/0` in Atlas Network Access (dev/staging only — use VPC peering in prod).

### Telegram bot not responding

The Notify Agent starts on `:3001` via supervisord. Check:

```bash
# In container logs look for:
# "✅ Notify Agent HTTP server on port 3001"
# "Bot polling started"
```
