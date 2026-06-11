<div align="center">

# SihaLink 🏥

### AI-powered disease surveillance swarm for Kenya's Community Health Volunteers

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![Angular 20](https://img.shields.io/badge/Angular-20-DD0031?logo=angular&logoColor=white)](https://angular.dev)
[![Google ADK](https://img.shields.io/badge/Google-ADK%201.26-4285F4?logo=google&logoColor=white)](https://google.github.io/adk-docs/)
[![MongoDB Atlas](https://img.shields.io/badge/MongoDB-Atlas-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com/atlas)
[![Cloud Run](https://img.shields.io/badge/Cloud%20Run-Deployed-4285F4?logo=google-cloud&logoColor=white)](https://cloud.google.com/run)
[![Firebase Hosting](https://img.shields.io/badge/Firebase-Hosting-FFCA28?logo=firebase&logoColor=black)](https://firebase.google.com)

---

_Built for the Google Cloud Rapid Agent Hackathon — MongoDB Track_

</div>

---

## The Problem

Every year, disease outbreaks in Kenya kill people who could have been saved — not because the healthcare system lacks knowledge, but because it lacks **speed**. A CHW (Community Health Volunteer) in a remote Kisumu ward notices a cluster of cholera cases. She files a paper report. It travels by hand to the sub-county office. By the time the data reaches Nairobi, three weeks have passed and the outbreak has spread to four other counties.

**SihaLink breaks that chain.**

---

## What It Does

SihaLink is a **multi-agent AI swarm** that gives every one of Kenya's 100,000+ Community Health Volunteers a direct line to an intelligent outbreak detection system — through their phone, in their own language.

A CHW speaks a patient report in Dholuo. Within 30 seconds:

1. **Intake Agent** — transcribes and clinically extracts the report (syndrome, triage, symptoms, vitals) using Gemini 2.5 Flash
2. **Geo Agent** — maps the encounter to ward/sub-county/county and finds the three nearest facilities with real drive times
3. **Data Agent** — stores it in MongoDB Atlas with a Voyage AI vector embedding for semantic search
4. **Surveillance Agent** — checks if this is part of a growing cluster against 4-week rolling baselines across all 47 counties
5. **Notify Agent** — fires a Telegram message to the facility: _"Incoming RED — 6yr, severe dehydration, ETA 22 min"_
6. **Contact Tracing Agent** — maps who else the patient may have exposed, assigns CHW visits

All autonomous. Human confirmation only for RED/YELLOW referral dispatch.

---

## Architecture

```
╔══════════════════════════════════════════════════════════════╗
║                       SihaLink Swarm                         ║
║                                                              ║
║  ┌──────────────────┐  HTTPS   ┌─────────────────────────┐  ║
║  │  Angular 20 SPA  │─────────▶│   Orchestrator Agent    │  ║
║  │ Firebase Hosting │          │  FastAPI · Google ADK   │  ║
║  └──────────────────┘          │  SSE · Cloud Run :8080  │  ║
║                                └────────────┬────────────┘  ║
║                         ┌───────────────────┼────────────┐  ║
║                    ┌────▼───┐  ┌────────┐  ┌▼──────────┐ ║
║                    │Intake  │  │  Geo   │  │   Data    │ ║
║                    │Agent   │  │ Agent  │  │  Agent    │ ║
║                    │Gemini  │  │ Maps   │  │ MongoDB + │ ║
║                    │2.5Flash│  │ API    │  │ Voyage AI │ ║
║                    └────────┘  └────────┘  └───────────┘ ║
║                         │           │                      ║
║                    ┌────▼──┐  ┌─────▼──────────────────┐  ║
║                    │Notify │  │   Surveillance Agent    │  ║
║                    │Agent  │  │ Outbreak · Silent       │  ║
║                    │grammY │  │ Pandemic · CHW Gaps     │  ║
║                    │:3001  │  └─────────────────────────┘  ║
║                    └───────┘          │                     ║
║                               ┌───────▼──────────────┐     ║
║                               │  Contact Tracing     │     ║
║                               │  Agent               │     ║
║                               └──────────────────────┘     ║
╚══════════════════════════════════════════════════════════════╝
```

---

## The Six Agents

### 🎤 Intake Agent

Multilingual clinical extraction from voice, web forms, or Telegram messages. Supports Dholuo, Swahili, Kikuyu, Somali, Luhya, Kamba, English and code-switching. Returns WHO IDSR clinical JSON with triage color in under 500ms.

### 📍 Geo Agent

GPS → full Kenyan admin hierarchy (village → ward → sub-county → county) + nearest facilities with real driving times. Never routes a referral without knowing exactly where the patient is.

### 💾 Data Agent

MongoDB Atlas with Voyage AI multilingual embeddings (1024 dims). Manages 7 collections: encounters, CHWs, alerts, referrals, follow-ups, protocols, contact traces. Powers semantic search across all clinical records.

### 📊 Surveillance Agent

Outbreak detection every 6 hours across 47 counties vs 4-week rolling baselines. Daily **silent pandemic scan** catches slowly growing threats before they spike. Automatically formulates WHO/MoH response protocols on alert.

### 📨 Notify Agent

Node.js/grammY Telegram bot. Handles referral dispatches, outbreak alerts, CHW follow-up reminders, and broadcast messages. CHVs interact via `/report`, `/followup`, `/protocol`, `/status`. Alert modals in the web dashboard include WhatsApp deep-link sharing.

### 🔗 Contact Tracing Agent

Every RED encounter triggers an automatic contact trace. Calculates syndrome-specific exposure windows, maps potential contacts in the same ward, assigns CHW visits, tracks to resolution, reports secondary attack rates.

---

## Tech Stack

| Layer            | Technology                            |
| ---------------- | ------------------------------------- |
| Agent Framework  | Google ADK 1.26                       |
| LLM              | Gemini 2.5 Flash (Vertex AI)          |
| Embeddings       | Voyage AI `voyage-3` (1024 dims)      |
| Database         | MongoDB Atlas M10+ with Vector Search |
| Backend          | Python 3.12 · FastAPI · uvicorn       |
| Telegram Bot     | Node.js 20 · grammY · Fastify         |
| Frontend         | Angular 20 · Angular Material 3       |
| Mapping          | Google Maps Platform                  |
| Observability    | Dynatrace via OpenTelemetry OTLP      |
| Backend Hosting  | Google Cloud Run                      |
| Frontend Hosting | Firebase Hosting                      |
| Process Manager  | supervisord                           |
| CI/CD            | Google Cloud Build                    |

---

## Repository Structure

```
SihaLink/
├── agents/
│   ├── orchestrator/     # FastAPI app + ADK root_agent + swarm event bus
│   ├── intake/           # Multilingual clinical extraction (Gemini Live)
│   ├── geo/              # GPS enrichment (Google Maps)
│   ├── data/             # MongoDB Atlas + Voyage AI embeddings
│   ├── surveillance/     # Outbreak detection + silent pandemic scan
│   ├── notify/           # Telegram bot (TypeScript/grammY)
│   └── contact_tracing/  # Exposure mapping + CHW task assignment
├── frontend/             # Angular 20 SPA
│   └── src/app/
│       ├── agents-ui/    # Per-agent UI panels
│       ├── encounters/   # Case Encounters table (server-side pagination)
│       └── dashboard/    # Live swarm dashboard
├── data/                 # Seed scripts + clinical reference dataset
├── deploy/               # supervisord.conf, deploy.sh, cloudbuild.yaml
├── Dockerfile            # Multi-stage: Node build → Angular build → Python runtime
├── firebase.json         # Firebase Hosting config (SPA rewrites)
└── .env.example          # All environment variables documented
```

---

## Deployment

**Backend — Google Cloud Run:**

```bash
./deploy/deploy.sh --project kephothoagenticai --region us-central1
```

**Frontend — Firebase Hosting:**

```bash
cd frontend && npm run build:prod
firebase deploy --only hosting --project kephothoagenticai
```

**CI/CD — triggers automatically on push to `main`:**

```bash
gcloud builds submit --config deploy/cloudbuild.yaml .
```

See [QUICK_START.md](QUICK_START.md) for local development setup.

---

## License

MIT. Built with ❤️ for Kenya's Community Health Volunteers.

_"Afya ni Haki" — Health is a Right_
