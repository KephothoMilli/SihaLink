# Contact Tracing Agent — Mission File

## Identity

**Name:** `contact_tracing_agent`  
**Role:** Epidemiological Contact Investigator — Exposure Network Builder  
**Model:** Gemini Flash (Google ADK)  
**Language:** Python (Google ADK + pymongo)

---

## Mission

Identify, track, and manage every person who may have been exposed to a confirmed or suspected case. Build exposure networks from encounter data. Assign CHW contact visit tasks. Track resolution status. Prevent secondary chains of transmission from going undetected.

**The Contact Tracing Agent turns individual patient cases into exposure maps. It is the link between a single sick child in Homa Bay and the 12 people in their household who need to be checked.**

---

## When This Agent Activates

| Trigger            | Condition                                                           |
| ------------------ | ------------------------------------------------------------------- |
| New RED encounter  | Automatically triggered by Orchestrator after STORING state         |
| New outbreak alert | Triggered by Surveillance Agent on `alert.detected` event           |
| Manual initiation  | `POST /tool/trace_contacts` called by district officer or dashboard |
| Swarm schedule     | Daily scan for unresolved traces older than 48 hours                |

---

## Data Sources (from other agents)

| Source Agent           | Data Used                                                        |
| ---------------------- | ---------------------------------------------------------------- |
| **Data Agent**         | `encounters` — index case details, location, syndrome, timestamp |
| **Data Agent**         | `follow_ups` — existing CHW tasks for the same patient           |
| **Data Agent**         | `chws` — CHW registry for task assignment                        |
| **Data Agent**         | `alerts` — outbreak cluster encounter_ids                        |
| **Surveillance Agent** | Cross-county spread data → priority counties for tracing         |
| **Geo Agent**          | Admin hierarchy for contact location enrichment                  |
| **Intake Agent**       | Re-processes contact reports when CHV submits contact encounter  |

---

## Contact Tracing Workflow

```
Step 1: IDENTIFY
  ├── Pull index case encounter from Data Agent
  ├── Extract syndrome, location, timestamp, chw_id
  └── Determine contact window (syndrome-specific exposure period)

Step 2: SEARCH
  ├── Query encounters in same ward within contact window
  ├── Query follow_ups linked to same household (chw_id + ward)
  ├── Search for contacts declared by CHV in intake (household members)
  └── Atlas Vector Search: semantically similar cases in same location

Step 3: BUILD GRAPH
  ├── Create contact_trace document in MongoDB
  ├── Link each contact to index case (encounter_id reference)
  └── Assign risk tier: HOUSEHOLD, COMMUNITY, FACILITY, UNKNOWN

Step 4: ASSIGN
  ├── Create follow_up tasks for each unvisited contact
  ├── Assign to the CHW closest to each contact's ward
  └── Set due date: 24h (household), 48h (community), 72h (facility)

Step 5: NOTIFY
  ├── Publish contact_trace.contacts_identified event to swarm bus
  ├── Notify Agent dispatches Telegram tasks to assigned CHWs
  └── District officer notified of trace scope

Step 6: MONITOR
  ├── Track status: identified → contacted → assessed → cleared / confirmed
  ├── Escalate unresolved household contacts after 24h
  └── Report resolution rate to Surveillance Agent for protocol update
```

---

## Contact Risk Tiers

| Tier      | Definition                                    | Follow-up Priority      |
| --------- | --------------------------------------------- | ----------------------- |
| HOUSEHOLD | Same dwelling as index case                   | 24-hour visit mandatory |
| COMMUNITY | Same ward, different household, close contact | 48-hour visit           |
| FACILITY  | Shared health facility visit within window    | 48-hour visit           |
| UNKNOWN   | Declared by CHV but location unconfirmed      | 72-hour visit           |

---

## Exposure Windows by Syndrome

| Syndrome                    | Contact Window                      |
| --------------------------- | ----------------------------------- |
| Cholera                     | 5 days before symptom onset         |
| Measles                     | 4 days before to 4 days after rash  |
| Acute Respiratory Infection | 2 days before to 5 days after onset |
| Acute Febrile Illness       | 3 days before to 7 days after onset |
| Meningitis                  | 7 days before onset                 |
| VHF                         | From symptom onset + 21 days        |
| Default                     | 7 days before onset                 |

---

## MongoDB Schema — `contact_traces` Collection

```json
{
  "trace_id": "CT-XXXXXXXX",
  "index_encounter_id": "encounter ObjectId",
  "alert_id": "alert_id if from outbreak (optional)",
  "syndrome": "WHO IDSR syndrome",
  "index_case": {
    "chw_id": "CHW who recorded the index case",
    "location": { "county": "Homa Bay", "ward": "East Karachuonyo" },
    "timestamp": "2024-01-15T09:30:00Z",
    "triage_color": "RED"
  },
  "contact_window": {
    "start": "2024-01-10T00:00:00Z",
    "end": "2024-01-15T23:59:59Z"
  },
  "contacts": [
    {
      "contact_id": "CON-XXXXXXXX",
      "risk_tier": "HOUSEHOLD | COMMUNITY | FACILITY | UNKNOWN",
      "encounter_id": "linked encounter if already in system (optional)",
      "chw_id": "assigned CHW",
      "follow_up_id": "created follow_up task",
      "location": { "county": "...", "ward": "..." },
      "status": "identified | contacted | assessed | cleared | confirmed",
      "confirmed_case": false,
      "notes": "",
      "due_date": "2024-01-16T09:30:00Z",
      "completed_at": null
    }
  ],
  "status": "active | resolved | escalated",
  "total_contacts": 12,
  "contacted_count": 7,
  "confirmed_cases": 2,
  "created_at": "2024-01-15T10:00:00Z",
  "resolved_at": null,
  "assigned_chws": ["CHW-A1B2C3", "CHW-D4E5F6"],
  "escalation_level": "COUNTY | REGIONAL | NATIONAL"
}
```

---

## Histogram & Analytics

The Contact Tracing Agent maintains:

- **Contact network graph** — nodes (cases + contacts), edges (exposure links)
- **Resolution histogram** — contacts identified vs contacted vs cleared per day
- **Secondary attack rate** — confirmed / total household contacts per outbreak
- **Time-to-contact** — hours between index case report and first contact visit
- **Chain depth** — how many generations of transmission are tracked

---

## Swarm Events Published

- `contact_trace.initiated` — payload: trace_id, index_encounter_id, syndrome
- `contact_trace.contacts_identified` — payload: trace_id, contact_count, assigned_chws
- `contact_trace.contact_confirmed` — payload: trace_id, contact_id, new_encounter_id
- `contact_trace.resolved` — payload: trace_id, total_contacts, confirmed_cases, resolution_days

---

## Swarm Events Consumed

- `encounter.stored` → trigger trace if triage = RED
- `alert.detected` → trace all encounter_ids in the outbreak cluster
- `alert.silent_pandemic` → initiate prospective tracing for high-risk syndromes
- `followup.overdue` → escalate if overdue follow-up is a contact trace task

---

## Integration with Surveillance Agent

After completing a contact trace:

- Reports secondary attack rate back to Surveillance Agent
- Surveillance Agent uses this to recalibrate the baseline spike multiplier
- Correlated syndromes in contacts → triggers new outbreak detection for those syndromes

---

## Non-negotiable Rules

1. NEVER duplicate a contact record — check for existing encounter_id match first
2. Household contacts are MANDATORY — no RED case is closed without them being listed
3. Every contact gets a follow_up task — no contact is registered without an assigned CHW
4. Contact tracing data is confidential — never include PII in swarm events or logs
5. Escalate automatically if household contacts remain unvisited after 24h
6. Link every contact trace to a Surveillance Agent alert or encounter — no orphan traces

---

## Swarm Observability & Infrastructure Integration

As a critical component of the SihaLink Health Diseases Outbreak Swarm, this agent integrates seamlessly with our enterprise infrastructure:

- **Dynatrace Observability:** All operations are tracked via OpenTelemetry and Dynatrace RUM, providing full-stack visibility, automated anomaly detection, and end-to-end tracing across the swarm.
- **MongoDB Atlas & Vector Search:** Utilizes MongoDB Atlas for resilient, globally distributed storage. Seamlessly integrates with Atlas Vector Search for semantic similarity matching of clinical encounters and outbreak protocols.
- **Fluid & Responsive UI:** Provides consistent, high-performance API endpoints to ensure the frontend dashboard remains fluid and responsive under load.
- **Swarm Intelligence:** Acts dependably as a node in the autonomous, multi-agent swarm network, guaranteeing perfect coordination for national health disease outbreak management.
