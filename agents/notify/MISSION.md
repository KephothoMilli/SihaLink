# Notify Agent — Mission File

## Identity

**Name:** `notify_agent` / `sihalink-notify-agent`  
**Role:** Multi-Channel Communication Hub — Human Interface for the Swarm  
**Runtime:** Node.js 20 + grammY + Fastify  
**Language:** TypeScript

---

## Mission

Be the voice of the SihaLink swarm to every human stakeholder. Deliver patient referrals to receiving facilities. Alert district officers to outbreaks. Remind CHVs of overdue follow-ups. Let supervisors broadcast to their teams — all through Telegram.

**The Notify Agent is how the swarm talks to humans. It is the only agent with a direct human interface.**

---

## User Roles

### Community Health Volunteer (CHV/CHW)

CHVs are frontline health workers recording patient encounters in the field.

| Command                | Action                                  |
| ---------------------- | --------------------------------------- |
| `/report <text>`       | Submit encounter in any language (text) |
| Voice note             | Auto-transcribe + extract clinical data |
| `/followup`            | View pending follow-up tasks            |
| `/protocol <syndrome>` | Get WHO/MoH response protocol           |
| `/status`              | County surveillance stats               |

### District Officer

District officers manage county-level surveillance and coordination.

| Command                 | Action                             |
| ----------------------- | ---------------------------------- |
| `/register`             | Set county jurisdiction            |
| `/alerts`               | View active outbreak alerts        |
| `/acknowledge <id>`     | Acknowledge an alert               |
| `/resolve <id> <notes>` | Resolve an alert                   |
| `/broadcast`            | Send message to all CHVs in county |
| `/swarm`                | View autonomous agent swarm status |
| `/dashboard`            | Open web dashboard                 |

---

## Inbound HTTP API (called by Python orchestrator)

| Endpoint                      | Purpose                                            |
| ----------------------------- | -------------------------------------------------- |
| `POST /notify/referral`       | Dispatch patient referral to facility via Telegram |
| `POST /notify/outbreak_alert` | Send outbreak alert to county channel              |
| `GET /health`                 | Health check                                       |

---

## Referral Dispatch Flow

1. Orchestrator calls `POST /notify/referral` with full referral payload
2. Notify Agent formats a rich Telegram message with triage emoji, ETA, syndrome
3. Sends to `facility_telegram_id` with inline keyboard: **✅ Accept** | **🔄 Redirect**
4. Facility response triggers callback → calls Python backend to update referral status

---

## Outbreak Alert Dispatch

1. Surveillance Agent → Orchestrator → `POST /notify/outbreak_alert`
2. Agent formats alert with risk emoji (🔴/🟠/🟡), location, case count, baseline deviation
3. Sends to county channel `@SihaLink_{County}` + fallback to `FACILITY_TELEGRAM_ID`
4. Inline keyboard: **📊 Dashboard** | **✅ Acknowledge**

---

## Contact Tracing Notifications

When Contact Tracing Agent identifies contacts:

1. Notify Agent receives list of CHW IDs + patient contact IDs
2. Sends personalized Telegram message to each CHW: "New contact tracing task assigned"
3. Includes: index case syndrome, contact's last known location, due date for visit
4. CHW confirms receipt via inline button

---

## Swarm Events Consumed

- `alert.detected` → dispatch outbreak alert to county channel
- `alert.silent_pandemic` → notify district officer
- `gap.chw_outreach` → notify supervisor
- `followup.overdue` → remind CHV via Telegram
- `contact_trace.contacts_identified` → dispatch contact visit tasks to CHWs

---

## Language Support

The bot responds in the language detected from the CHV's message:

- English (default)
- Swahili
- Dholuo (greeting + status messages)

---

## Non-negotiable Rules

1. All Telegram dispatches have a fallback channel if the primary fails
2. Inline button timeouts (>60s no response) auto-acknowledge and log
3. Never expose patient PII in Telegram messages — use encounter IDs only
4. All outbound HTTP calls to the Python backend timeout at 10s
5. grammY conversation state persists across bot restarts via session middleware

---

## Swarm Observability & Infrastructure Integration

As a critical component of the SihaLink Health Diseases Outbreak Swarm, this agent integrates seamlessly with our enterprise infrastructure:

- **Dynatrace Observability:** All operations are tracked via OpenTelemetry and Dynatrace RUM, providing full-stack visibility, automated anomaly detection, and end-to-end tracing across the swarm.
- **MongoDB Atlas & Vector Search:** Utilizes MongoDB Atlas for resilient, globally distributed storage. Seamlessly integrates with Atlas Vector Search for semantic similarity matching of clinical encounters and outbreak protocols.
- **Fluid & Responsive UI:** Provides consistent, high-performance API endpoints to ensure the frontend dashboard remains fluid and responsive under load.
- **Swarm Intelligence:** Acts dependably as a node in the autonomous, multi-agent swarm network, guaranteeing perfect coordination for national health disease outbreak management.
