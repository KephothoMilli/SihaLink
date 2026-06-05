# Orchestrator Agent — Mission File

## Identity

**Name:** `orchestrator_agent`  
**Role:** Central Coordinator — State Machine Director  
**Model:** Gemini Flash (ADK generateContent); Gemini Flash Live (real-time voice TTS)  
**Language:** Python (FastAPI + Google ADK)

---

## Mission

Coordinate the entire SihaLink swarm. Route every patient encounter through the full lifecycle. Manage human-in-the-loop decision gates. Own the offline queue. Start and stop the autonomous swarm. Expose the FastAPI HTTP interface for all frontend and external calls.

**The Orchestrator is the conductor. Every other agent plays their part — the Orchestrator decides when, what, and in what order.**

---

## Encounter Lifecycle State Machine

```
IDLE → LISTENING → EXTRACTING → GEOCODING → STORING
     → [DECISION_GATE] → NOTIFYING → TRACING → COMPLETE
```

| State         | Action                                  | Agent Responsible     |
| ------------- | --------------------------------------- | --------------------- |
| IDLE          | Session created                         | Orchestrator          |
| LISTENING     | Audio/text received                     | Intake Agent          |
| EXTRACTING    | Clinical data extracted                 | Intake Agent          |
| GEOCODING     | GPS → admin hierarchy + facilities      | Geo Agent             |
| STORING       | MongoDB insert + follow-up scheduling   | Data Agent            |
| DECISION_GATE | CHV confirms referral (RED/YELLOW only) | Human (60s timeout)   |
| NOTIFYING     | Telegram referral dispatch              | Notify Agent          |
| TRACING       | Contact tracing initiated for RED cases | Contact Tracing Agent |
| COMPLETE      | Encounter fully processed               | Orchestrator          |

---

## Human Gate Policy

| Triage    | Gate Required | Timeout     | Auto-action                              |
| --------- | ------------- | ----------- | ---------------------------------------- |
| 🔴 RED    | Yes           | 60 seconds  | Auto-escalate → send referral regardless |
| 🟡 YELLOW | Yes           | 120 seconds | Auto-queue → defer to next CHV check-in  |
| 🟢 GREEN  | No            | —           | No gate — store and schedule follow-up   |

---

## HTTP Endpoints Exposed

### Encounter Lifecycle

- `POST /encounter/start` — initiate full pipeline
- `GET /encounter/{id}/status` — poll state machine state
- `POST /encounter/{id}/confirm` — resolve human gate

### Intake (all 4 channels)

- `POST /tool/route_to_intake` — audio base64
- `POST /intake/form` — web form
- `POST /intake/telegram` — Telegram CHV message
- `POST /intake/agent` — agent-to-agent

### Geo / Data / Notify

- `POST /tool/route_to_geo`, `/tool/route_to_data`, `/tool/route_to_notify`

### Surveillance

- `POST /tool/trigger_surveillance`, `/tool/silent_pandemic_scan`
- `POST /tool/chw_outreach_gaps`, `/tool/cross_county_spread`

### Contact Tracing

- `POST /tool/trace_contacts` — initiate trace from encounter/alert
- `GET /tool/trace_status/{trace_id}` — trace progress
- `POST /tool/update_contact_status` — mark contact as found/notified

### Follow-ups & Protocols & CHWs

- Full CRUD endpoints for all 7 MongoDB collections

### Swarm Control

- `GET /swarm/status`, `POST /swarm/trigger/outbreak`
- `GET /swarm/events` — audit event log

---

## Offline Queue

When the CHV device is offline:

1. Encounters are queued in memory via `POST /tool/queue_offline_encounter`
2. When connectivity returns, `POST /tool/process_offline_queue` drains the queue
3. Every 30 minutes the swarm auto-attempts queue drain

---

## Swarm Integration

The Orchestrator owns the `SwarmController` singleton and:

- Calls `swarm.start()` on FastAPI lifespan startup
- Calls `swarm.stop()` on shutdown
- Passes its own instance to `swarm.initialise()` so the swarm can call `process_offline_queue()`

---

## Telemetry

All HTTP requests are auto-instrumented via `FastAPIInstrumentor` → Dynatrace OTel.  
Custom spans wrapping the encounter lifecycle (`encounter.start`, state transitions).

---

## Non-negotiable Rules

1. NEVER skip the human gate for RED or YELLOW encounters
2. NEVER lose encounter data — always queue offline, always retry
3. All endpoints must return within 30 seconds — use background tasks for slow work
4. The state machine is the single source of truth for encounter status
5. Contact Tracing Agent is called automatically for every RED encounter

---

## Swarm Observability & Infrastructure Integration

As a critical component of the SihaLink Health Diseases Outbreak Swarm, this agent integrates seamlessly with our enterprise infrastructure:

- **Dynatrace Observability:** All operations are tracked via OpenTelemetry and Dynatrace RUM, providing full-stack visibility, automated anomaly detection, and end-to-end tracing across the swarm.
- **MongoDB Atlas & Vector Search:** Utilizes MongoDB Atlas for resilient, globally distributed storage. Seamlessly integrates with Atlas Vector Search for semantic similarity matching of clinical encounters and outbreak protocols.
- **Fluid & Responsive UI:** Provides consistent, high-performance API endpoints to ensure the frontend dashboard remains fluid and responsive under load.
- **Swarm Intelligence:** Acts dependably as a node in the autonomous, multi-agent swarm network, guaranteeing perfect coordination for national health disease outbreak management.
