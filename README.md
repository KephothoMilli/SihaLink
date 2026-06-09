<div align="center">

# SihaLink 🏥

### An AI-powered disease surveillance swarm for Kenya's Community Health Volunteers

[![GitHub](https://img.shields.io/badge/GitHub-SihaLink-181717?logo=github)](https://github.com/KephothoM/SihaLink.git)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![Angular 20](https://img.shields.io/badge/Angular-20-DD0031?logo=angular&logoColor=white)](https://angular.dev)
[![Google ADK](https://img.shields.io/badge/Google-ADK%201.26-4285F4?logo=google&logoColor=white)](https://google.github.io/adk-docs/)
[![MongoDB Atlas](https://img.shields.io/badge/MongoDB-Atlas-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com/atlas)
[![Cloud Run](https://img.shields.io/badge/Cloud%20Run-Deployed-4285F4?logo=google-cloud&logoColor=white)](https://cloud.google.com/run)

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

A CHV speaks a patient report into her phone in Dholuo. Within seconds:

1. **The Intake Agent** transcribes and clinically extracts the report — syndrome, triage color, symptoms, vitals
2. **The Geo Agent** maps the encounter to its exact ward, sub-county, and county, and finds the three nearest health facilities with drive times
3. **The Data Agent** stores it in MongoDB Atlas with a vector embedding for semantic search
4. **The Surveillance Agent** checks if this case is part of a growing cluster — running against 4-week rolling baselines across all 47 counties
5. **The Notify Agent** fires a Telegram message to the referring facility: _"Incoming RED triage — 6-year-old, severe dehydration, ETA 22 minutes"_
6. **The Contact Tracing Agent** immediately begins mapping who else the patient may have exposed

All of this happens in under 30 seconds, autonomously, while the CHV is still with the patient.

---

## The Swarm Architecture

```
╔══════════════════════════════════════════════════════════════╗
║                    SihaLink Swarm                            ║
║                                                              ║
║   ┌─────────────┐         ┌──────────────────────────────┐  ║
║   │   Angular   │ HTTPS   │     Orchestrator Agent        │  ║
║   │  Dashboard  │────────▶│  FastAPI · Google ADK · SSE  │  ║
║   │(Firebase)   │         └──────────┬───────────────────┘  ║
║   └─────────────┘                    │                       ║
║                          ┌───────────┼───────────────────┐  ║
║                          │           │                   │  ║
║                    ┌─────▼──┐  ┌─────▼──┐  ┌────────────▼┐ ║
║                    │ Intake │  │  Geo   │  │    Data     │ ║
║                    │ Agent  │  │ Agent  │  │   Agent     │ ║
║                    │Gemini  │  │ Maps   │  │  MongoDB    │ ║
║                    │  Live  │  │   API  │  │Atlas+Voyage │ ║
║                    └────────┘  └────────┘  └─────────────┘ ║
║                          │           │                       ║
║                    ┌─────▼──┐  ┌─────▼──────────────────┐  ║
║                    │ Notify │  │     Surveillance Agent  │  ║
║                    │ Agent  │  │  Outbreak Detection ·   │  ║
║                    │grammY  │  │  Silent Pandemic Scan · │  ║
║                    │Telegram│  │  CHW Gap Analysis       │  ║
║                    └────────┘  └─────────────────────────┘  ║
║                                        │                     ║
║                          ┌─────────────▼───────────────┐    ║
║                          │    Contact Tracing Agent    │    ║
║                          │  Exposure mapping · CHW     │    ║
║                          │  task assignment · SAR calc │    ║
║                          └─────────────────────────────┘    ║
╚══════════════════════════════════════════════════════════════╝
```

---

## The Six Agents

### 🎤 Intake Agent

_The gateway. No encounter enters the system without passing through here._

Speaks 11 Kenyan languages including Dholuo, Swahili, Kikuyu, Somali, and English — plus code-switching between them. Accepts voice recordings, web forms, Telegram messages, or direct JSON from other agents. Returns a structured WHO IDSR clinical extraction in under 500ms.

### 📍 Geo Agent

_Turns coordinates into context._

Takes a GPS position and returns the full Kenyan administrative hierarchy (village → ward → sub-county → county), the three nearest health facilities with real driving times from Google Maps, and an alert flag if the case should trigger a referral. Never makes a routing decision without knowing where the patient actually is.

### 💾 Data Agent

_The memory of the swarm._

Persists every encounter to MongoDB Atlas with a Voyage AI vector embedding (1024 dimensions, multilingual). Manages 7 collections: encounters, CHWs, alerts, follow-ups, protocols, referrals, and contact traces. Powers semantic search so clinicians can ask questions like _"show me cases similar to this presentation in Homa Bay over the last 3 months"_ and get meaningful results.

### 📊 Surveillance Agent

_The epidemiological brain._

Runs outbreak detection every 6 hours across all 47 counties — comparing case counts against 4-week rolling baselines. Also runs a daily **silent pandemic scan** that catches syndromes with a persistent upward trend before they ever hit a spike threshold. When it finds a signal, it automatically formulates a WHO/MoH response protocol and escalates through county → regional → national channels.

### 📨 Notify Agent

_The voice that calls for help._

A Node.js/grammY Telegram bot that handles every outbound notification — CHV referral dispatches, outbreak alerts to district officers, CHW follow-up task assignments, and broadcast messages to county health channels. Also accepts inbound commands from CHVs: `/report`, `/followup`, `/protocol`, `/status`.

### 🔗 Contact Tracing Agent

_The exposure map._

Every RED-triage encounter automatically triggers a contact trace. The agent pulls the index case, calculates the syndrome-specific exposure window (5 days for cholera, 8 for measles, 21 for VHF), searches for potential contacts in the same ward within that window, assigns CHWs to visit each one, and tracks every contact to resolution. Reports secondary attack rates back to the Surveillance Agent.

---

## Tech Stack

| Layer               | Technology                                               |
| ------------------- | -------------------------------------------------------- |
| **Agent Framework** | Google ADK 1.26 (`google-adk`)                           |
| **LLM**             | Gemini 2.5 Flash via Vertex AI                           |
| **Embeddings**      | Voyage AI `voyage-3` (1024 dims, multilingual)           |
| **Database**        | MongoDB Atlas M10 with Vector Search                     |
| **Backend**         | Python 3.12 · FastAPI · uvicorn                          |
| **Telegram Bot**    | Node.js 20 · grammY · Fastify                            |
| **Frontend**        | Angular 20 · Angular Material 3                          |
| **Mapping**         | Google Maps Platform (Places, Geocoding, Directions)     |
| **Observability**   | Dynatrace via OpenTelemetry OTLP                         |
| **Hosting**         | Google Cloud Run (backend) · Firebase Hosting (frontend) |
| **Process Manager** | supervisord (uvicorn + Node.js in one container)         |
| **CI/CD**           | Google Cloud Build                                       |

---

## Repository Structure

```
SihaLink/
├── agents/
│   ├── orchestrator/     # FastAPI app + ADK root_agent + swarm controller
│   ├── intake/           # Multilingual clinical extraction (Gemini Live)
│   ├── geo/              # GPS enrichment (Google Maps)
│   ├── data/             # MongoDB Atlas + Voyage AI embeddings
│   ├── surveillance/     # Outbreak detection pipelines
│   ├── notify/           # Telegram bot (TypeScript/grammY)
│   └── contact_tracing/  # Exposure mapping + CHW task assignment
├── frontend/             # Angular 20 dashboard (standalone components)
│   └── src/
│       ├── app/          # Components: dashboard, agents-ui, encounters
│       └── services/     # API, agent services, alert broadcast (SSE)
├── data/                 # Seed scripts + clinical dataset
├── deploy/               # Dockerfile, supervisord, Cloud Build, service.yaml
└── .env.example          # All required environment variables documented
```

---

## Key Features

**For Community Health Volunteers**

- Submit patient reports by voice in any Kenyan language
- Receive instant triage guidance and referral confirmation via Telegram
- Get overdue follow-up reminders automatically
- Access WHO response protocols with one command: `/protocol cholera`

**For District Health Officers**

- Live outbreak detection dashboard with county-level maps
- Silent pandemic alerts for slowly growing threats
- CHW activity gap reports — see which wards have gone dark
- Cross-county spread detection with automatic escalation

**For the System**

- Human-in-the-loop decision gate for every RED and YELLOW referral (60s timeout, then auto-escalates)
- Offline queue — encounters are stored locally when the CHV has no signal, synced automatically on reconnect
- SSE live alert stream to the dashboard — no polling
- Full OpenTelemetry tracing into Dynatrace for every request

---

## Getting Started

See **[QUICK_START.md](QUICK_START.md)** for the fastest path to a running local environment.

For Cloud Run deployment, see **[CLOUD_RUN_DEPLOYMENT.md](CLOUD_RUN_DEPLOYMENT.md)**.

---

## License

MIT License. Built with ❤️ for Kenya's Community Health Volunteers.

---

<div align="center">

**[GitHub](https://github.com/KephothoM/SihaLink.git)** · **[Quick Start](QUICK_START.md)** · **[Cloud Run Deploy](CLOUD_RUN_DEPLOYMENT.md)**

_"Afya ni Haki" — Health is a Right_

</div>
