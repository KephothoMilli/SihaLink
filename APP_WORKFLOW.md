# SihaLink — How the Agents Actually Work

This document explains the real runtime behavior of the SihaLink swarm — how the agents are wired together, what triggers what, and what happens autonomously vs. what waits for a human.

---

## The Big Picture

There are two completely separate things happening at once:

1. **Encounter pipeline** — a CHV submits a patient report and the system processes it in real time, end to end, in under 30 seconds.
2. **Background swarm cycles** — completely autonomous loops running on timers, scanning all 47 counties for outbreak signals, sending reminders, syncing offline data — whether anyone is using the app or not.

These two things share the same event bus. An encounter processed by the pipeline can trigger the background swarm. An alert detected by the swarm can trigger a Telegram notification and a contact trace. Everything talks to everything through events.

---

## Part 1 — The Encounter Pipeline

This is what happens the moment a CHV submits a patient report.

```
CHV submits report (voice / web form / Telegram message)
          │
          ▼
    ┌─────────────┐
    │   LISTENING  │  session created, payload received
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐
    │  EXTRACTING  │  Intake Agent → Gemini 2.5 Flash
    └──────┬──────┘  returns: syndrome, triage, symptoms, vitals, language, confidence
           │
           │  clarification_needed? ──────────────────────────────────────────┐
           │  (up to 2 rounds)                                                 │
           │                                                              CLARIFICATION
           │◀─────────────────────────────────────────────────────────── GATE (60s)
           │
           ▼
    ┌─────────────┐
    │  GEOCODING   │  Geo Agent → Google Maps
    └──────┬──────┘  returns: county, ward, sub-county, village, 3 nearest facilities + ETAs
           │
           ▼
    ┌─────────────┐
    │   STORING    │  Data Agent → MongoDB Atlas
    └──────┬──────┘  inserts encounter + Voyage AI embedding (1024 dims)
           │         schedules follow-up tasks (non-fatal if it fails)
           │
           │  triage = GREEN? ──────────────────────────────────────────────────────┐
           │                                                                        │
           ▼ (RED or YELLOW only)                                                   │
    ┌─────────────┐                                                                 │
    │  ALERTING    │  Data Agent writes referral record to MongoDB                  │
    └──────┬──────┘                                                                 │
           │                                                                        │
           ▼                                                                        │
    ┌─────────────────┐                                                             │
    │  DECISION_GATE  │  ← human pause                                             │
    └──────┬──────────┘                                                             │
           │  CHV confirms via Telegram inline button or web dashboard             │
           │                                                                        │
           │  60s timeout:                                                          │
           │    RED    → auto-escalate (proceed anyway)                             │
           │    YELLOW → auto-queue (stop, notify district officer)                 │
           │                                                                        │
           │  CHV declines → mark COMPLETE with outcome = "declined_by_chv"        │
           │                                                                        │
           ▼ (confirmed)                                                            │
    ┌─────────────┐                                                                 │
    │  NOTIFYING   │  Notify Agent → Telegram referral to facility                 │
    └──────┬──────┘                                                                 │
           │                                                                        │
           ▼                                                                        │
    ┌─────────────┐ ◀──────────────────────────────────────────────────────────────┘
    │   COMPLETE   │
    └─────────────┘
           │
           └──► event published: "encounter.stored"
                    │
                    └──► Swarm picks this up and runs immediate
                         outbreak detection for that county
```

### Retry behavior

Every state transition has automatic retry with exponential backoff — 3 attempts, delays of 1s, 2s, 4s. If all 3 fail, the session goes to `FAILED` and the CHV gets a Telegram message explaining what went wrong.

### Offline path

If the CHV has no signal, the encounter goes to `OFFLINE_QUEUED` in memory. The swarm checks every 30 minutes — when connectivity returns, the queue drains automatically and each encounter runs through the full pipeline.

---

## Part 2 — The Autonomous Swarm

The swarm runs independently of any user action. It starts when the server starts and keeps going until the server stops. These are the scheduled cycles:

| Cycle                | Interval         | What it does                                                                                                                     |
| -------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Outbreak detection   | Every 6 hours    | Runs across all 20 active counties. Compares case counts against 4-week rolling baselines. Fires `alert.detected` for any spike. |
| Silent pandemic scan | Every 24 hours   | Looks for syndromes with a steady upward trend over 3+ weeks — even if they never hit the spike threshold. The slow burns.       |
| Baseline update      | Every 24 hours   | Recalculates the 4-week rolling baselines for every county.                                                                      |
| Follow-up reminders  | Every hour       | Finds overdue follow-up tasks in MongoDB and fires `followup.overdue` for each one.                                              |
| CHW gap check        | Daily            | Finds wards with zero encounter submissions in the past 7 days. Fires `gap.chw_outreach`.                                        |
| Contact trace scan   | Daily            | Finds contacts in active traces whose visit is overdue (24h past due date) and escalates.                                        |
| Offline queue sync   | Every 30 minutes | Attempts to drain the offline queue if connectivity is available.                                                                |

The scheduler checks every 10 seconds whether any task is due. It's not a cron daemon — it's a simple async loop inside the FastAPI process.

---

## Part 3 — The Event Bus

This is what makes the agents feel like a swarm rather than a pipeline. Every meaningful thing that happens publishes an event. Other parts of the system subscribe and react.

```
"encounter.stored"
    └──► Swarm: run immediate outbreak check for that county
    └──► Swarm: if triage = RED, initiate contact trace

"alert.detected"
    └──► Surveillance Agent: formulate response protocol
    └──► Notify Agent: send Telegram alert to district officer
    └──► Contact Tracing Agent: trace all encounters in the outbreak cluster

"alert.silent_pandemic"
    └──► Notify Agent: escalate to district officer

"alert.cross_county_spread"
    └──► Swarm: national escalation notification

"gap.chw_outreach"
    └──► Notify Agent: supervisor alert

"followup.overdue"
    └──► Notify Agent: reminder to the assigned CHW

"contact_trace.contact_confirmed"
    └──► Contact Tracing Agent: initiate secondary trace from the new case

"surveillance.escalation_needed"    (from the reflection step)
    └──► National alert broadcast

"task.*.complete" / "task.*.error"  (from scheduler)
    └──► SSE stream → Angular dashboard live toast
```

The wildcard `*` subscriber logs every single event to the swarm audit trail — visible in the dashboard at `/swarm/events`.

---

## Part 4 — The Contact Tracing Agent

This agent runs entirely off events — it never polls and never needs to be called directly in normal operation.

When a RED encounter is stored, the swarm fires `encounter.stored`. The swarm's event handler checks the triage color, and if it's RED, calls `contact_tracing_agent.initiate_trace(encounter_id)` directly.

When an outbreak alert fires, the swarm calls `contact_tracing_agent.trace_cluster(alert_id)` — which traces all encounters in the whole cluster at once.

What initiating a trace actually does:

1. Pulls the index case from MongoDB
2. Calculates the syndrome-specific exposure window (5 days for cholera, 8 for measles, 21 for VHF, etc.)
3. Searches the `encounters` collection for anyone in the same ward within that window
4. For high-priority syndromes (cholera, measles, VHF, meningitis), always adds at least one presumptive household contact
5. Assigns a CHW to each contact — preferring the CHW already linked to their encounter, falling back to round-robin
6. Creates a `follow_up` task in MongoDB for each contact
7. Persists the full trace document to the `contact_traces` collection

If a CHW later reports a contact is a confirmed new case, the agent automatically initiates a secondary trace from that new case. This is how contact chains grow: each confirmed contact spawns its own trace.

---

## Part 5 — The Reflection Layer (IBM Agentic Workflow)

After each major operation, the system evaluates what just happened and adjusts its next move. This isn't LLM reasoning — it's deterministic code that scores outcomes and logs decisions.

**After each encounter pipeline:**

The `PipelineReflection.evaluate_encounter()` method scores the result on a 100-point scale:

- Syndrome not identified → -20 points
- Confidence below 70% → -10 points
- Triage color missing → -15 points
- County not resolved → -10 points
- No facilities found → -5 points
- Storage failed → -30 points
- Triage-syndrome mismatch (e.g., Ebola classified as YELLOW) → -15 points

Scores 90+ = EXCELLENT, 70-89 = GOOD, 50-69 = FAIR, below 50 = POOR. This gets logged with the workflow state so you can see exactly why a pipeline run went sideways.

**After each surveillance cycle:**

The `PipelineReflection.evaluate_surveillance_cycle()` method looks across all county results and identifies:

- Which syndromes reached RED/HIGH risk
- Which syndromes appeared in 2+ counties (cross-county spread)
- Which counties failed detection (will be prioritized next cycle)
- Whether the spread threshold (3+ counties, same syndrome) was hit — if so, fires national escalation

This is the `ReAct` loop from the IBM agentic framework: Reason (what do we know?) → Act (run detection) → Observe (what came back?) → Reflect (what does it mean for next time?).

---

## Part 6 — Workflow State Persistence

Every encounter's full state machine history is written to MongoDB's `workflow_states` collection in real time. This means:

- If the server crashes mid-pipeline, the incomplete workflow is recoverable
- The `GET /encounter/{session_id}/workflow` endpoint shows every state transition with timestamps
- The `GET /workflows/incomplete` endpoint finds any encounter stuck in a non-terminal state for more than 30 minutes — useful for ops monitoring

Each workflow document records:

- Every state transition with timestamp and note
- All accumulated pipeline data (extraction, enrichment, storage IDs)
- Non-fatal errors that were worked around
- Per-step retry counts

---

## Part 7 — Agent Memory

The `AgentMemory` class gives the Telegram bot cross-turn context. When a CHW sends `/followup`, the bot knows their registered county and CHW ID from previous interactions — it doesn't ask again. When a CHV is mid-way through a clarification gate, the session state persists across Telegram messages.

Memory entries expire after 72 hours of inactivity. The `remember()` / `recall()` / `forget()` interface is simple by design — it's just MongoDB upserts with a TTL.

---

## How it all fits together — a complete example

A CHW in Homa Bay opens Telegram and sends:

> `/report Mtoto miaka 3, homa kali, kuhara maji, hawezi kunywa`

Here's exactly what happens:

1. **Notify Agent** (Node.js) receives the Telegram message, identifies it as a `/report` command, and POSTs to `http://localhost:8000/intake/telegram` with the message text, CHW ID, and GPS coordinates from the device.

2. **Orchestrator** creates a new session `tg-{chat_id}-{timestamp}`, transitions to `LISTENING`, then calls the **Intake Agent** with the Swahili text.

3. **Intake Agent** sends the text to Gemini 2.5 Flash with the WHO IDSR extraction prompt. Returns: `syndrome: acute_watery_diarrhea`, `triage: RED`, `symptoms: [high fever, watery diarrhea, unable to drink]`, `age: 3 years`, `confidence: 0.94`.

4. **Orchestrator** transitions to `GEOCODING` and calls the **Geo Agent** with the CHW's GPS coordinates.

5. **Geo Agent** calls Google Maps Geocoding API, gets `ward: East Karachuonyo, sub_county: Karachuonyo, county: Homa Bay`. Calls Places API for nearby health facilities. Returns top 3 with drive times.

6. **Orchestrator** transitions to `STORING`, calls the **Data Agent** to insert the enriched encounter. Data Agent generates a Voyage AI embedding and inserts to MongoDB. Returns `encounter_id: "enc-abc123"`.

7. **Data Agent** auto-schedules follow-up tasks: day 1, 3, 7, 14 for a RED case.

8. **Orchestrator** transitions to `ALERTING`, creates a referral record in MongoDB.

9. **Orchestrator** transitions to `DECISION_GATE`. The **Notify Agent** sends the CHW an inline Telegram message with ✅ Confirm Referral / ❌ Decline buttons. The Future waits up to 60 seconds.

10. The CHW taps ✅. The Future resolves with `confirmed = True`.

11. **Orchestrator** transitions to `NOTIFYING`. **Notify Agent** fires a formatted Telegram message to the facility (`FACILITY_TELEGRAM_ID`): _"🔴 URGENT — 3yr RED, acute watery diarrhea, ETA 22min from East Karachuonyo. CHW: CHW-0042."_

12. **Orchestrator** transitions to `COMPLETE`. Sends the CHW a confirmation message.

13. The `encounter.stored` event fires on the swarm bus.

14. **Swarm Controller** receives the event. Runs an immediate outbreak check for Homa Bay. This case tips a running cholera cluster over the alert threshold.

15. **Swarm** publishes `alert.detected` with the cluster data.

16. **Surveillance Agent** formulates and stores a cholera response protocol for Homa Bay.

17. **Notify Agent** broadcasts the outbreak alert to the Homa Bay county health Telegram channel.

18. **Contact Tracing Agent** initiates a trace for `enc-abc123`. Finds 2 encounters in the same ward within the 5-day cholera exposure window. Creates follow-up tasks for 2 CHWs. Adds a presumptive household contact. Stores the trace as `CT-A3F7B21C`.

19. The `contact_trace.initiated` event fires on the bus. The Angular dashboard's SSE stream receives it and shows a toast: _"🔗 Contact Trace: 3 contacts — CT-A3F7B21C initiated for acute watery diarrhea."_

Total elapsed time from the CHW hitting send to the facility receiving the referral: **under 30 seconds**.

---

## Active counties

The swarm monitors 20 counties by default at startup:

Homa Bay · Kisumu · Siaya · Migori · Kisii · Garissa · Wajir · Mandera · Turkana · Nairobi · Mombasa · Nakuru · Kilifi · Kwale · Bungoma · Kakamega · Marsabit · Isiolo · Tana River · Lamu

Add more at runtime:

```bash
curl -X POST http://localhost:8000/swarm/counties/add \
  -H "Content-Type: application/json" \
  -d '{"county": "Kirinyaga", "lat": -0.5597, "lng": 37.3490}'
```

---

## Human involvement — when and only when

The system is designed to do as much as possible without asking. Here are the only moments it stops and waits for a human:

| Trigger              | Who is asked                  | Wait time                   | What happens on timeout                    |
| -------------------- | ----------------------------- | --------------------------- | ------------------------------------------ |
| RED encounter        | CHV via Telegram or web       | 60 seconds                  | Auto-escalate — referral dispatched anyway |
| YELLOW encounter     | CHV via Telegram or web       | 60 seconds                  | Auto-queue — defer to next check-in        |
| Clarification needed | CHV via Telegram or web       | 60 seconds                  | Continue with best-effort extraction       |
| CRITICAL alert       | District officer via Telegram | No gate — just notification | N/A                                        |
| National escalation  | Broadcast to all channels     | No gate — just notification | N/A                                        |

Everything else — outbreak detection, protocol formulation, contact tracing, follow-up scheduling, baseline updates, gap analysis — happens without asking anyone.
