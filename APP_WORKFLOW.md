# SihaLink — Application Workflow

How the swarm processes a clinical encounter from first report to referral dispatch, surveillance cycle to protocol formulation, and contact trace to resolution.

---

## 1. Encounter Pipeline

A CHW submits a patient report. This is what happens:

```
CHW Device
    │
    ▼
POST /encounter/start
    │
    ▼
Orchestrator (FastAPI)
    │  session_id, audio_base64|form_data|telegram_payload, lat/lng, chw_id
    │
    ├──► Background Task: run_lifecycle()
    │        │
    │        ▼
    │   EXTRACTING ──► Intake Agent
    │        │         • Gemini 2.5 Flash (Vertex AI)
    │        │         • 11 Kenyan languages + code-switching
    │        │         • Returns: syndrome, triage_color, symptoms, vitals,
    │        │                    chief_complaint, confidence, detected_language
    │        │         • Applies disease reference correction
    │        │
    │        ▼
    │   CLARIFICATION_GATE (if confidence < 0.7)
    │        │         • Frontend polls and shows question modal
    │        │         • CHW types answer → POST /encounter/{id}/clarify
    │        │         • Backend resolves asyncio.Future, extraction reruns
    │        │
    │        ▼
    │   GEOCODING ──► Geo Agent
    │        │        • Google Maps Geocoding + Places APIs
    │        │        • GPS coords → village/ward/sub-county/county
    │        │        • Returns 3 nearest health facilities with ETAs
    │        │        • Falls back to county name if GPS is 0,0
    │        │
    │        ▼
    │   STORING ──► Data Agent (MongoDB Atlas)
    │        │      • Inserts encounter doc with Voyage AI embedding
    │        │      • Publishes encounter.stored to SwarmEventBus
    │        │        → triggers immediate surveillance check
    │        │        → triggers contact trace if RED triage
    │        │
    │        ▼
    │   FOLLOW_UP_SCHEDULED ──► Data Agent
    │        │      • RED:    follow-ups at day 1, 3, 7, 14
    │        │      • YELLOW: follow-ups at day 2, 7, 14
    │        │      • GREEN:  follow-up at day 7
    │        │
    │        ▼
    │   ALERTING (RED/YELLOW only) ──► Data Agent
    │        │      • Creates referral record in `referrals` collection
    │        │      • Stores encounter_id, facility info, triage, patient details
    │        │
    │        ▼
    │   DECISION_GATE (RED/YELLOW only)
    │        │      • Sets asyncio.Future in _pending_gates
    │        │      • Frontend polls → shows Clinical Gate Authorization modal
    │        │      • Modal shows: triage, syndrome, chief complaint, symptoms, location
    │        │      • Buttons: Approve & Dispatch | Decline | Share via WhatsApp
    │        │      • Timeout: 5 minutes
    │        │        RED timeout → auto-escalate (confirmed=True)
    │        │        YELLOW timeout → auto-queue (confirmed=False)
    │        │      • CHW confirms → POST /encounter/{id}/confirm
    │        │
    │        ▼
    │   NOTIFYING (confirmed only) ──► Notify Agent
    │        │      • Telegram message to facility with patient details + ETA
    │        │      • grammY bot sends with Accept/Redirect inline keyboard
    │        │
    │        ▼
    │   COMPLETE
    │
    ▼
Frontend poll (/encounter/{id}/status every 2s)
    │  maps state → UI pipeline log progress bar
    │  maps gate_data → gate modal content
    └──► session reaches COMPLETE → result step shown
```

---

## 2. Swarm Event Bus

After an encounter is stored, the `SwarmEventBus` propagates it autonomously:

```
encounter.stored
    │
    ├──► Surveillance Agent
    │        run_outbreak_detection(county, hours=1)
    │        if alert found → publish alert.detected
    │
    └──► Contact Tracing Agent (RED triage only)
             initiate_trace(encounter_id)
             calculates exposure window by syndrome
             searches contacts in same ward
             assigns CHW visit tasks

alert.detected
    │
    ├──► Surveillance Agent
    │        formulate_response_protocol(syndrome, county)
    │        stores in protocols collection
    │
    ├──► Notify Agent
    │        dispatch_outbreak_alert(alert)
    │        Telegram to district officer
    │
    └──► Contact Tracing Agent
             trace_cluster(alert_id)
             maps all encounters in the cluster
```

---

## 3. Scheduled Swarm Cycles

The `SwarmScheduler` runs background tasks on fixed intervals:

| Task                   | Interval       | Description                                              |
| ---------------------- | -------------- | -------------------------------------------------------- |
| `outbreak_detection`   | Every 6 hours  | Run detection across all 47 counties vs 4-week baselines |
| `silent_pandemic_scan` | Every 24 hours | Detect slow-growing trends (no spike threshold)          |
| `baseline_update`      | Every 24 hours | Recalculate rolling baselines for all counties           |
| `followup_reminders`   | Every 1 hour   | Find overdue follow-ups, publish `followup.overdue`      |
| `offline_queue_sync`   | Every 30 min   | Retry any queued-offline encounters                      |
| `chw_outreach_gaps`    | Every 24 hours | Find wards with zero CHW submissions in 7 days           |
| `contact_trace_scan`   | Every 24 hours | Find contacts overdue for CHW visit                      |

Each scheduled task uses the IBM agentic **ReAct** pattern:

- **Reason**: why am I running, what do I expect?
- **Act**: call the agent
- **Observe**: what came back, are there anomalies?
- **Reflect**: escalate? retry? adjust next cycle priority?

---

## 4. Surveillance Pipeline Detail

```
run_outbreak_detection(county, lat, lng, hours=6)
    │
    ├── Query encounters in the past {hours}h for this county
    ├── Group by syndrome
    ├── Compare each syndrome count to 4-week rolling baseline
    ├── If count > (baseline × 1.5) AND count ≥ 3:
    │       create alert in MongoDB `alerts` collection
    │       publish alert.detected to SwarmEventBus
    │
    └── Return {alerts_detected, alerts[]}

detect_silent_pandemic(county, weeks=4)
    │
    ├── Pull weekly syndrome counts for the past {weeks} weeks
    ├── For each syndrome: calculate week-over-week trend_delta
    ├── If trend_delta > 2.0 consistently across 3+ weeks:
    │       signal classified as "silent pandemic"
    │       risk_level = HIGH
    │       publish alert.silent_pandemic
    │
    └── Return {silent_signals[]}

formulate_response_protocol(syndrome, county, alert_level)
    │
    ├── Check protocols collection for existing (syndrome, county) entry
    ├── If not found or stale:
    │       Gemini 2.5 Flash generates protocol from WHO/MoH guidelines
    │       Includes: immediate_actions, chw_actions, follow_up_days,
    │                 reporting_requirements, source_authority
    │       Upsert into protocols collection
    │
    └── Return protocol dict
```

---

## 5. Contact Tracing Workflow

```
RED encounter stored
    │
    ▼
initiate_trace(encounter_id)
    │
    ├── Pull index case from encounters collection
    ├── Determine exposure_window_days by syndrome:
    │       cholera: 5 days
    │       measles: 8 days (4 before + 4 after)
    │       tuberculosis: 90 days
    │       viral_hemorrhagic_fever: 21 days
    │       default: 14 days
    │
    ├── Search contacts:
    │       same ward + same time window
    │       patient_contacts field from intake form
    │       previous encounters by the same CHW
    │
    ├── Create trace record in `contact_traces` collection
    ├── Create CHW visit tasks for each contact
    │
    └── Return trace_id, contacts_identified

update_contact_status(trace_id, contact_id, status)
    │
    ├── Status flow: identified → contacted → assessed → cleared | confirmed
    ├── If status = confirmed → create new encounter for that contact
    ├── Calculate Secondary Attack Rate (SAR):
    │       SAR = confirmed_cases / total_contacts × 100
    │
    └── Report SAR back to Surveillance Agent
```

---

## 6. Human Gate Design

The DECISION_GATE is the only mandatory human checkpoint in the pipeline. Everything else is autonomous.

```
Gate fires (RED or YELLOW triage)
    │
    ▼
Backend:
    asyncio.Future stored in _pending_gates[session_id]
    session.gate_data = {triage_color, syndrome, summary, symptoms, encounter_id}
    timeout = 300 seconds (5 minutes)

Frontend polls every 2 seconds:
    GET /encounter/{id}/status
    → state: DECISION_GATE
    → gate_data populated from backend session

Gate modal shows:
    • Triage color (RED/YELLOW badge)
    • Syndrome
    • Chief complaint
    • Symptoms list
    • Location (ward, county)
    • Buttons: Approve & Dispatch | Decline | Share via WhatsApp

CHW clicks Approve:
    POST /encounter/{id}/confirm {confirmed: true}
    → Future.set_result(True)
    → pipeline continues to NOTIFYING

CHW clicks Decline:
    POST /encounter/{id}/confirm {confirmed: false}
    → Future.set_result(False)
    → session marked COMPLETE, outcome=declined_by_chv

Timeout:
    RED  → auto-escalate (confirmed=True) — referral dispatched anyway
    YELLOW → auto-queue (confirmed=False) — logged for district review

If gate already resolved (double-click, timeout, etc.):
    Backend returns {status: "already_resolved"} — never 404
    Frontend shows "Gate timed out — auto-processed" toast
```

---

## 7. Offline Queue

When the CHW device has no connectivity:

```
POST /encounter/start fails (network error)
    │
    ▼
Frontend: session.state = OFFLINE_QUEUED
    Encounter stored in localStorage via OfflineSyncService

window.addEventListener('online')
    │
    ▼
syncOfflineQueue()
    For each queued encounter:
        POST /encounter/start (retry)
        Remove from queue on success

Backend side:
    orchestrator.offline_queue (in-memory list)
    SwarmScheduler runs process_offline_queue() every 30 min
    Each queued encounter runs through full lifecycle
```

---

## 8. SSE Live Alert Stream

The frontend subscribes to `GET /swarm/stream` on startup:

```
Backend: SwarmEventBus publishes to _sse_swarm_subscriber on every event
    │
    ▼
SSE stream → AlertBroadcastService (Angular)
    │
    ▼
alertBroadcast.alerts$ (Observable)
    │
    ├──► AppComponent: showSwarmAlert() → toast notification
    │        Critical/Warning toasts include WhatsApp share link
    │
    └──► Dashboard: updates encounter counts, active alert list
```

SSE reconnects with exponential backoff (5s → 10s → 20s → 40s → 60s, stops after 5 failures).

---

## 9. Frontend Architecture

```
AppComponent (root shell)
    ├── Sidebar nav (routerLink)
    ├── Agent health bar (SSE + 30s health polls)
    ├── Gate modals (DECISION_GATE, CLARIFICATION_GATE)
    ├── Toast stack (swarm alerts + agent status changes)
    └── router-outlet
          ├── /dashboard         → DashboardComponent
          ├── /agents/intake     → IntakeAgentComponent (5-step Material Stepper)
          ├── /agents/geo        → GeoAgentComponent
          ├── /agents/data       → DataAgentComponent (SihaLink Data Management Portal)
          ├── /agents/notify     → NotifyAgentComponent (Alert Notification Portal)
          ├── /agents/surveillance → SurveillanceAgentComponent
          ├── /agents/contact-tracing → ContactTracingAgentComponent
          └── /encounters        → EncountersComponent (Material Table, server-side pagination)

Services:
    RootAgentService      — startEncounter(), confirmEncounterDecision(), poll loop
    ApiService            — all HTTP calls to backend (base: VITE_API_URL)
    AlertBroadcastService — SSE connection, exponential backoff, alerts$ Observable
    OfflineSyncService    — localStorage queue for offline encounters
    IntakeAgentService    — normalizeExtraction(), clarifyExtraction()
    DataAgentService      — searchEncounters(), getCountyStats()
    ContactTracingAgentService — getActiveTraces(), traceContacts()
```

---

## 10. Deployment Architecture

```
Google Cloud Run (backend)
    Container: supervisord managing two processes
    ├── uvicorn agents.orchestrator.agent:app --port 8080
    │       Handles all API routes, SSE, ADK runner
    └── node agents/notify/dist/bot.js --port 3001
            Telegram bot (internal, not externally routed)

    Environment variables from Secret Manager:
        GEMINI_API_KEY, GOOGLE_MAPS_API_KEY, MONGODB_ATLAS_URI,
        TELEGRAM_BOT_TOKEN, FACILITY_TELEGRAM_ID, VOYAGE_API_KEY

    Cloud Run config:
        Memory: 2Gi | CPU: 2 | Min instances: 1
        Timeout: 3600s | Concurrency: 80
        Execution: gen2 | No CPU throttling

Firebase Hosting (frontend)
    Angular SPA built with ng build --configuration production
    VITE_API_URL set to Cloud Run service URL at build time
    All routes rewrite to index.html (SPA routing)
    Static assets cached for 1 year (immutable)
    public dir: frontend/dist/frontend/browser

CI/CD: Google Cloud Build (deploy/cloudbuild.yaml)
    Trigger: push to main
    Steps: test-python → build → push → deploy-cloudrun → build-frontend → deploy-firebase → smoke-test
```
