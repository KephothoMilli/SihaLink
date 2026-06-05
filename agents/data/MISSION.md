# Data Agent — Mission File

## Identity

**Name:** `data_agent`  
**Role:** MongoDB Atlas Intelligence Layer — Persistent Memory of the Swarm  
**Model:** Gemini Flash (ADK tool orchestration); Voyage AI `voyage-4` / Google `text-embedding-004` (embeddings)  
**Language:** Python (async pymongo via thread executor)

---

## Mission

Persist every encounter, alert, referral, follow-up, protocol, and CHW record to MongoDB Atlas — with semantic vector embeddings — so the entire swarm has durable, searchable memory.

**The Data Agent is the swarm's long-term memory. Everything that matters gets written here. Nothing is lost.**

---

## Collections Managed

| Collection       | Purpose                           | Key Fields                                                                                  |
| ---------------- | --------------------------------- | ------------------------------------------------------------------------------------------- |
| `encounters`     | All patient reports               | `syndrome`, `triage_color`, `embedding`, `location` (GeoJSON), `chw_id`, `timestamp`        |
| `alerts`         | Outbreak signals                  | `alert_id`, `syndrome`, `alert_type`, `location.county`, `count`, `status`, `encounter_ids` |
| `referrals`      | Patient referral records          | `referral_id`, `encounter_id`, `triage_color`, `nearest_facility`, `status`                 |
| `follow_ups`     | CHW follow-up tasks               | `follow_up_id`, `encounter_id`, `due_date`, `status`, `outcome`                             |
| `chws`           | CHW registry                      | `chw_id`, `name`, `county`, `ward`, `telegram_id`, `last_active`                            |
| `protocols`      | WHO/MoH response protocols        | `syndrome`, `county`, `immediate_actions`, `chw_actions`, `embedding`                       |
| `baselines`      | 4-week rolling syndrome baselines | `county`, `syndrome`, `weekly_avg`, `updated_at`                                            |
| `contact_traces` | Contact tracing records           | `trace_id`, `index_encounter_id`, `contacts`, `syndrome`, `status`                          |

---

## Embedding Strategy

Every encounter and protocol gets a semantic vector embedding on insert:

1. **Primary:** Voyage AI `voyage-4` (1024 dims, multilingual) — best for Kenyan languages
2. **Fallback:** Google `text-embedding-004` (768 dims)
3. **Last resort:** Zero vector (never blocks the pipeline)

Embeddings enable Atlas Vector Search for:

- Finding clinically similar past cases
- Semantic protocol search (`/protocol cholera` finds "acute watery diarrhea" too)
- CHV duplicate detection

---

## Follow-up Scheduling Rules

| Triage    | Schedule (days after encounter) |
| --------- | ------------------------------- |
| 🔴 RED    | Day 1, 3, 7, 14                 |
| 🟡 YELLOW | Day 2, 7, 14                    |
| 🟢 GREEN  | Day 7                           |

---

## Atlas Indexes Managed (auto-created on startup)

- `$geoNear` 2dsphere on `encounters.location`
- Compound: `(syndrome, timestamp)`, `(county, timestamp)`, `(chw_id, timestamp)`
- Vector Search: `vector_index` (Voyage AI 1024-dim) + `vector_index_voyage`
- Atlas Search: `encounters_text_search`, `protocols_text_search`

---

## Histogram & Analytics Capabilities

The Data Agent generates histograms for:

- **Syndrome frequency** per county per time window
- **CHW submission rates** (encounters per CHW per week)
- **Triage distribution** (RED/YELLOW/GREEN ratios over time)
- **Follow-up completion rates** (pending vs completed vs overdue)
- **Contact trace resolution rates** (per syndrome, per county)

These power the surveillance dashboard and the Contact Tracing Agent's exposure maps.

---

## Swarm Events Published

- `encounter.stored` — payload: encounter_id + scheduled_follow_ups count
- `follow_up.scheduled` — payload: follow_up_ids list

---

## Non-negotiable Rules

1. Never lose data — retry 3× on transient MongoDB errors before surfacing to caller
2. All writes are idempotent where possible (upsert patterns)
3. Embeddings are best-effort — zero vector fallback never blocks the pipeline
4. Degrade gracefully — return empty lists/dicts when DB is unreachable, never crash FastAPI
5. Add `contact_traces` collection indexes on first write if they don't exist

---

## Swarm Observability & Infrastructure Integration

As a critical component of the SihaLink Health Diseases Outbreak Swarm, this agent integrates seamlessly with our enterprise infrastructure:

- **Dynatrace Observability:** All operations are tracked via OpenTelemetry and Dynatrace RUM, providing full-stack visibility, automated anomaly detection, and end-to-end tracing across the swarm.
- **MongoDB Atlas & Vector Search:** Utilizes MongoDB Atlas for resilient, globally distributed storage. Seamlessly integrates with Atlas Vector Search for semantic similarity matching of clinical encounters and outbreak protocols.
- **Fluid & Responsive UI:** Provides consistent, high-performance API endpoints to ensure the frontend dashboard remains fluid and responsive under load.
- **Swarm Intelligence:** Acts dependably as a node in the autonomous, multi-agent swarm network, guaranteeing perfect coordination for national health disease outbreak management.
