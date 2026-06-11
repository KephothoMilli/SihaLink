# SihaLink — Quick Start

Get a fully working local environment in under 10 minutes.

---

## Prerequisites

| Tool             | Version | Install                                                                              |
| ---------------- | ------- | ------------------------------------------------------------------------------------ |
| Python           | 3.12+   | [python.org](https://python.org)                                                     |
| Node.js          | 20+     | [nodejs.org](https://nodejs.org)                                                     |
| Angular CLI      | 20+     | `npm i -g @angular/cli`                                                              |
| Google Cloud CLI | latest  | [cloud.google.com/sdk](https://cloud.google.com/sdk/docs/install)                    |
| Firebase CLI     | latest  | `npm i -g firebase-tools`                                                            |
| Docker           | latest  | [docker.com](https://docs.docker.com/get-docker/) — only needed for Cloud Run deploy |

---

## 1. Clone & configure

```bash
git clone https://github.com/KephothoM/SihaLink.git
cd SihaLink
cp .env.example .env
```

Edit `.env` and fill in at minimum:

```env
GEMINI_API_KEY=...              # From Google AI Studio
GOOGLE_MAPS_API_KEY=...         # Maps Platform key with Places + Geocoding + Directions
MONGODB_ATLAS_URI=...           # Atlas M10+ connection string
TELEGRAM_BOT_TOKEN=...          # From @BotFather
GOOGLE_CLOUD_PROJECT=kephothoagenticai
GOOGLE_GENAI_USE_VERTEXAI=TRUE
```

---

## 2. Python backend

```bash
# Create virtual environment
python -m venv SihaLinkEnv
source SihaLinkEnv/bin/activate     # Windows: SihaLinkEnv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Authenticate with Google (needed for Vertex AI / Gemini)
gcloud auth application-default login
gcloud config set project kephothoagenticai

# Start the orchestrator
uvicorn agents.orchestrator.agent:app --reload --port 8000
```

The backend is now at `http://localhost:8000`. Visit `/health` to confirm.

---

## 3. Telegram Notify Agent

```bash
cd agents/notify
npm install
npm run dev        # uses tsx for hot-reload
```

The bot starts on port `3001`. Check the console for `Notify Agent listening on :3001`.

---

## 4. Angular frontend

```bash
cd frontend
npm install --legacy-peer-deps
ng serve           # starts on http://localhost:4200
```

The dev proxy (`proxy.conf.json`) forwards all API calls to `http://localhost:8000`.

---

## 5. Seed clinical data (optional but recommended)

```bash
python data/seed_test_data.py
```

This seeds 24 CHWs, 120 encounters, 18 alerts, 12 contact traces, protocols and follow-ups — all treated as real clinical records.

---

## 6. Verify everything works

Open `http://localhost:4200` and check:

- **Swarm Health bar** — all six agent pills should turn green within 30 seconds
- **Case Encounters** — 120 records visible with filters working
- **Intake Agent** — complete a form intake through the 5-step stepper
- **Dashboard** — live SSE toasts appear when the swarm detects activity
- **Data Agent** — search "fever" returns matching encounters

---

## Environment variables reference

| Variable                    | Required | Description                                    |
| --------------------------- | -------- | ---------------------------------------------- |
| `GEMINI_API_KEY`            | Yes      | Gemini API key (AI Studio or Vertex AI)        |
| `GOOGLE_GENAI_USE_VERTEXAI` | Yes      | `TRUE` to use Vertex AI, `FALSE` for AI Studio |
| `GOOGLE_CLOUD_PROJECT`      | Yes      | GCP project ID                                 |
| `GOOGLE_CLOUD_LOCATION`     | Yes      | `us-central1`                                  |
| `GOOGLE_MAPS_API_KEY`       | Yes      | Maps Platform key                              |
| `MONGODB_ATLAS_URI`         | Yes      | Atlas M10+ connection string                   |
| `TELEGRAM_BOT_TOKEN`        | Yes      | From @BotFather                                |
| `FACILITY_TELEGRAM_ID`      | Yes      | Telegram chat ID for test facility             |
| `NOTIFY_AGENT_URL`          | Yes      | `http://localhost:3001` (local)                |
| `VITE_API_URL`              | Yes      | `http://localhost:8000` (local)                |
| `DYNATRACE_ENV_ID`          | No       | For OpenTelemetry tracing                      |
| `DYNATRACE_API_TOKEN`       | No       | Scopes: `openpipeline:traces:ingest`           |

---

## Cloud Run + Firebase deployment

Full one-command deploy:

```bash
./deploy/deploy.sh --project kephothoagenticai --region us-central1
```

This script:

1. Enables required GCP APIs
2. Creates service account with correct IAM roles
3. Stores secrets in Secret Manager
4. Builds the multi-stage Docker image (Node → Angular → Python)
5. Pushes to Google Container Registry
6. Deploys to Cloud Run (`--allow-unauthenticated`, port 8080)
7. Builds Angular with the real Cloud Run URL as `VITE_API_URL`
8. Deploys frontend to Firebase Hosting
9. Runs a health check

**Frontend only (after backend is already deployed):**

```bash
cd frontend
VITE_API_URL=https://sihalink-orchestrator-<hash>-uc.a.run.app \
  npm run build:prod
firebase deploy --only hosting --project kephothoagenticai
```

**CI/CD (push to main triggers automatically):**

```bash
gcloud builds submit --config deploy/cloudbuild.yaml .
```

---

## MongoDB Atlas setup checklist

- [ ] Cluster tier: M10 or higher (required for Vector Search)
- [ ] Network Access: add your IP (or `0.0.0.0/0` for Cloud Run)
- [ ] Database user with `readWrite` on `sihalink` database
- [ ] Atlas Search indexes: `encounters_search` on the `encounters` collection
- [ ] Vector Search index: `vector_index` on `encounters.embedding` (1024 dims, cosine)

The Data Agent creates standard indexes automatically on startup. Atlas Search + Vector Search indexes must be created once in the Atlas UI.

---

## Troubleshooting

**`data_agent.connected = False` on startup**
MongoDB couldn't connect during the 5-second startup ping. The backend now has a lazy reconnect — call `POST /health/reconnect` to trigger it, or just make any API call and it will auto-reconnect.

**`GET /encounters` returns `{"status":"degraded"}`**
Same as above. Add your IP to the Atlas Network Access allowlist.

**Telegram bot not receiving messages**
Check `TELEGRAM_BOT_TOKEN` is set and the bot is started (`npm run dev` in `agents/notify/`).

**`GOOGLE_GENAI_USE_VERTEXAI=TRUE` but extraction fails**
Run `gcloud auth application-default login` — the ADC credentials need to be refreshed.

**Angular build fails with `Cannot find module '@analogjs/vite-plugin-angular'`**
Run `npm install --legacy-peer-deps` in the `frontend/` directory.
