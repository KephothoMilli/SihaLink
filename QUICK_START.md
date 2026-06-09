# Quick Start Guide — SihaLink

> Clone it, configure it, and have the full swarm running locally in about 15 minutes.
> No Kubernetes. No cloud account required for dev. Just Python, Node, and a free MongoDB Atlas cluster.

**Repo:** https://github.com/KephothoM/SihaLink.git

---

## What you'll have running by the end

- The Python orchestrator and all 5 sub-agents at `http://localhost:8000`
- The Telegram notify bot at `http://localhost:3001`
- The Angular dashboard at `http://localhost:4200` with live SSE alerts
- 120 seeded patient encounters, 12 contact traces, and 18 outbreak alerts in MongoDB

---

## Prerequisites

You need these installed before you start. Nothing exotic.

| Tool    | Version | Get it                                          |
| ------- | ------- | ----------------------------------------------- |
| Python  | 3.12+   | [python.org](https://www.python.org/downloads/) |
| Node.js | 20+     | [nodejs.org](https://nodejs.org/)               |
| Git     | any     | [git-scm.com](https://git-scm.com/)             |

You'll also need accounts for:

- **MongoDB Atlas** — free M0 cluster works for dev (upgrade to M10 for Vector Search)
- **Google Cloud** — free tier is fine; you need a Gemini API key
- **Telegram** — create a bot via [@BotFather](https://t.me/BotFather) (takes 2 minutes)
- **Google Maps** — for the Geo Agent (free $200/month credit covers dev usage)

---

## Step 1 — Clone the repo

```bash
git clone https://github.com/KephothoM/SihaLink.git
cd SihaLink
```

---

## Step 2 — Python environment

```bash
# Create a virtual environment
python -m venv SihaLinkEnv

# Activate it
# On Windows:
SihaLinkEnv\Scripts\activate
# On macOS/Linux:
source SihaLinkEnv/bin/activate

# Install all Python dependencies
pip install -r requirements.txt
```

This installs FastAPI, Google ADK, pymongo, Voyage AI, httpx, and the OpenTelemetry packages. Should take about 2 minutes.

---

## Step 3 — Environment variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

Open `.env` and set these — the rest are optional for local dev:

```bash
# Required — the swarm won't start without these four
GEMINI_API_KEY=your_key_here
GOOGLE_MAPS_API_KEY=your_key_here
MONGODB_ATLAS_URI=mongodb+srv://user:pass@cluster.mongodb.net/
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Set to TRUE to use Vertex AI billing (recommended — avoids free tier quota)
# Requires: gcloud auth application-default login
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=your_gcp_project_id
GOOGLE_CLOUD_LOCATION=us-central1

# The Telegram chat ID that receives referral notifications
FACILITY_TELEGRAM_ID=your_telegram_chat_id
```

**Getting your MongoDB URI:** Sign up at [mongodb.com/atlas](https://www.mongodb.com/atlas), create a free cluster, click "Connect" → "Drivers", and copy the connection string. Replace `<password>` with your actual password.

**Getting your Gemini API key:** Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey) and create a new key.

**Getting your Maps API key:** Go to [console.cloud.google.com](https://console.cloud.google.com), enable the Maps JavaScript API, Geocoding API, Places API, and Directions API, then create a credential.

---

## Step 4 — MongoDB Atlas Network Access

Before the swarm can connect to Atlas, you need to allow your IP:

1. Go to your Atlas cluster → **Network Access** → **Add IP Address**
2. For local dev: click **Add Current IP Address**
3. For Cloud Run deployment later: add `0.0.0.0/0` (restrict this in production)

---

## Step 5 — Start the Python backend

```bash
# From the project root, with your virtualenv active
uvicorn agents.orchestrator.agent:app --reload --port 8000
```

You should see something like this in the console:

```
INFO:     Started server process
[Orchestrator] 🚀 Starting SihaLink — Kenya National Disease Surveillance
[Orchestrator] Vector Index Status: {'status': 'exists'}
[Orchestrator] Disease Reference Load: 9 diseases loaded
[Orchestrator] Clinical Dataset Seeded: 15 encounters with Voyage AI embeddings
[Orchestrator] 📡 SSE broadcast channel active (/swarm/stream)
INFO:     Uvicorn running on http://127.0.0.1:8000
```

If you see `MongoDB not connected — running in degraded mode`, go back and check your Atlas URI and network access settings.

---

## Step 6 — Seed the test data

Open a second terminal (with the virtualenv still active) and run:

```bash
python data/seed_test_data.py
```

This creates realistic test data across all 7 MongoDB collections:

- 24 CHWs across Nairobi, Kisumu, Mombasa, Nakuru, and Kisii
- 120 patient encounters with Voyage AI embeddings
- 18 outbreak alerts with encounter clusters
- 12 active contact traces (96 individual contacts with "View Details" data)
- 63 follow-up tasks
- 18 WHO/MoH response protocols
- 25 referrals
- 200 agent decision logs

Takes about 2-3 minutes. You'll see progress as each collection is seeded.

---

## Step 7 — Start the Telegram Notify Agent

Open a third terminal:

```bash
cd agents/notify
npm install
npm run dev
```

You should see:

```
✅ Notify Agent HTTP server on port 3001
✅ Backend target: http://localhost:8000
Bot is polling for updates...
```

If the bot token is valid, you can now message your bot on Telegram and it will respond.

---

## Step 8 — Start the Angular frontend

Open a fourth terminal:

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
```

Open `http://localhost:4200` in your browser.

You should see the SihaLink dashboard with:

- The Swarm Health bar showing all 6 agent pills (they'll turn green once the backend is connected)
- The 📡 LIVE indicator in the header showing the SSE stream is connected
- The dashboard showing "6 Active Agents" and the status cards

---

## Verify everything is working

Open a fifth terminal and run a quick health check:

```bash
curl http://localhost:8000/health
```

You should get back something like:

```json
{
  "status": "ok",
  "services": {
    "mongodb": { "status": "connected" },
    "orchestrator": "ready",
    "gemini": { "status": "configured" },
    "maps": { "status": "configured" }
  }
}
```

Check the swarm is running with your seeded data:

```bash
curl http://localhost:8000/swarm/status
```

---

## Try it out

### Submit a test encounter via the dashboard

1. Go to `http://localhost:4200/agents/intake`
2. Fill in the clinical form with some symptoms
3. Submit and watch the pipeline run through the state machine in real time

### Submit via Telegram

Send your bot a message like:

```
/report Mtoto miaka 3, homa kali, kuhara maji, hawezi kunywa
```

_(Swahili: "3-year-old child, high fever, watery diarrhea, unable to drink")_

The bot will extract clinical data, triage the case, and ask for confirmation before routing to the nearest facility.

### Check the live alert stream

Go to the Surveillance tab and trigger an outbreak detection run. Watch the toast notifications appear in real time as alerts are published to the SSE stream.

### Explore contact traces

Go to `http://localhost:4200/agents/contact-tracing` — you should see 12 active contact traces from the seed data. Click "View Detail" on any trace to see the inline panel with contacts, status histogram, and trace history.

### Browse case encounters

Go to `http://localhost:4200/encounters` — you should see all 120 seeded encounters. Click "View Details" on any card to see the full clinical data, vitals, geo enrichment, and nearest facilities.

---

## Common issues

**`ModuleNotFoundError: No module named 'agents'`**
You're running the command from the wrong directory. Always run from the project root (`/SihaLink`), not from inside a subdirectory.

**`MongoDB not connected — running in degraded mode`**
Either your `MONGODB_ATLAS_URI` is wrong, or your IP isn't whitelisted in Atlas Network Access. Check both.

**`Notify Agent unavailable (All connection attempts failed)`**
The Python backend can't reach the Telegram bot. Make sure Step 7 is running. This warning appears once then goes quiet — it won't spam your logs.

**`ECONNREFUSED` in the Vite console**
The Python backend isn't running. Start it in Step 5 first.

**SSE shows "⏳ connecting…" forever**
The `/swarm/stream` endpoint needs the backend running. Once it's up, the badge will flip to "📡 LIVE" within a few seconds.

**Voyage AI embeddings failing**
Set your `VOYAGE_API_KEY` in `.env`. Get a free key at [voyageai.com](https://www.voyageai.com/). The seeder falls back to Google text-embedding-004 if Voyage isn't configured, but the quality is better with Voyage.

---

## Project structure at a glance

```
SihaLink/
├── agents/                  # All Python agents
│   ├── orchestrator/        # The conductor — FastAPI + ADK
│   ├── intake/              # Multilingual clinical extraction
│   ├── geo/                 # GPS → admin hierarchy + facilities
│   ├── data/                # MongoDB + Voyage AI embeddings
│   ├── surveillance/        # Outbreak detection pipelines
│   ├── notify/              # Telegram bot (TypeScript)
│   └── contact_tracing/     # Exposure mapping
├── frontend/                # Angular 20 dashboard
├── data/                    # Seed scripts
│   ├── seed_test_data.py    # ← Run this in Step 6
│   └── clinical_intake_dataset.py
├── deploy/                  # Cloud Run deployment files
│   ├── deploy.sh            # One-command deploy
│   ├── cloudbuild.yaml      # CI/CD pipeline
│   ├── supervisord.conf     # Process manager config
│   └── validate.py          # Pre-deploy validation
├── .env.example             # All env vars documented
└── QUICK_START.md           # ← You are here
```

---

## What's next

Once you have the local environment running, you have a few options:

**Deploy to Cloud Run** — follow [CLOUD_RUN_DEPLOYMENT.md](CLOUD_RUN_DEPLOYMENT.md). The `deploy/deploy.sh` script handles everything in one command.

**Add a county to the surveillance scope** — call the swarm API:

```bash
curl -X POST http://localhost:8000/swarm/counties/add \
  -H "Content-Type: application/json" \
  -d '{"county": "Kakamega", "lat": 0.2827, "lng": 34.7519}'
```

**Explore the ADK agent** — run the ADK web UI:

```bash
adk web
```

Then go to `http://localhost:8080` and chat directly with the orchestrator agent.

**Run the dataset integration tests:**

```bash
python data/test_dataset_integration.py
```

---

## Getting help

- **GitHub Issues:** [github.com/KephothoM/SihaLink/issues](https://github.com/KephothoM/SihaLink/issues)
- **Check the logs:** The orchestrator logs everything. Watch the terminal where uvicorn is running.
- **Health endpoint:** `curl http://localhost:8000/health` always tells you what's connected and what's not.

---

_"Pole pole ndio mwendo" — Step by step is the way to go._
