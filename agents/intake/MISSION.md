# Intake Agent — Mission File

## Identity

**Name:** `intake_agent`  
**Role:** Clinical Data Intake Specialist — First Point of Contact  
**Model:** Gemini Flash (Live API for real-time voice; generateContent for text/form)  
**Language:** Python (Google ADK)

---

## Mission

Transform raw patient reports — spoken in any Kenyan language, typed via web form, or relayed from Telegram — into structured WHO IDSR clinical data ready for the rest of the swarm.

**The Intake Agent is the gateway. No encounter enters the system without passing through here.**

---

## Supported Input Channels

| Channel          | Path                         | Description                                      |
| ---------------- | ---------------------------- | ------------------------------------------------ |
| Voice recording  | `POST /tool/route_to_intake` | Base64 WAV/WebM audio from CHV device or browser |
| Web form         | `POST /intake/form`          | Structured fields from Angular clinical form     |
| Telegram message | `POST /intake/telegram`      | CHV text/audio relayed from bot                  |
| Agent relay      | `POST /intake/agent`         | JSON from another SihaLink agent                 |

---

## Supported Languages

Dholuo · Swahili · Kikuyu · Somali · Luhya · Kamba · Mijikenda · Meru · Turkana · Kalenjin · English

Handles **code-switching** (sentences that mix two or more languages) and **keyword fallback** when LLM translation is unavailable.

---

## Output Schema (per extraction)

```json
{
  "syndrome": "WHO IDSR category string",
  "triage_color": "RED | YELLOW | GREEN",
  "symptoms": ["list of extracted symptoms"],
  "chief_complaint": "free-text normalised to English",
  "age": { "value": 3, "unit": "years" },
  "sex": "male | female | unknown",
  "vital_signs": {
    "temperature_c": 38.5,
    "respiratory_rate": 28,
    "heart_rate": 110
  },
  "detected_language": "Dholuo",
  "confidence": 0.92,
  "clarification_needed": false,
  "clarification_question": null,
  "processing_ms": 420
}
```

---

## Triage Decision Rules

| Color     | Meaning                                                                  | Auto-action                                             |
| --------- | ------------------------------------------------------------------------ | ------------------------------------------------------- |
| 🔴 RED    | Life-threatening — severe dehydration, respiratory distress, unconscious | Auto-escalate referral after 60s if CHV doesn't confirm |
| 🟡 YELLOW | Moderate — needs facility visit within 24h                               | Queue referral; notify district officer                 |
| 🟢 GREEN  | Mild — home management with 7-day follow-up                              | Log and schedule single follow-up                       |

---

## Swarm Event Published

- `encounter.extracted` — payload: full extraction dict + session_id + source

---

## Protocol Integration

After extraction, the Orchestrator immediately:

1. Routes to **Geo Agent** for location enrichment
2. Routes to **Data Agent** for MongoDB storage + follow-up scheduling
3. Checks if syndrome triggers an existing protocol via **Surveillance Agent**
4. Routes RED/YELLOW to **Notify Agent** for Telegram dispatch
5. Triggers **Contact Tracing Agent** if triage is RED or syndrome is high-priority

---

## Clarification Loop

If `clarification_needed = true`, the agent returns a `clarification_question`.  
The CHV answers via Telegram or web form → `POST /tool/clarify_extraction` → updated extraction.  
Maximum 3 clarification rounds before accepting best-effort extraction.

---

## Non-negotiable Rules

1. Never silently drop data — if extraction fails, return an error with session_id so the Orchestrator can retry
2. Audio never leaves the CHV device unencrypted
3. Always set `detected_language` — even if it's `"unknown"`
4. Always return a triage color — default to YELLOW if uncertain

---

## Swarm Observability & Infrastructure Integration

As a critical component of the SihaLink Health Diseases Outbreak Swarm, this agent integrates seamlessly with our enterprise infrastructure:

- **Dynatrace Observability:** All operations are tracked via OpenTelemetry and Dynatrace RUM, providing full-stack visibility, automated anomaly detection, and end-to-end tracing across the swarm.
- **MongoDB Atlas & Vector Search:** Utilizes MongoDB Atlas for resilient, globally distributed storage. Seamlessly integrates with Atlas Vector Search for semantic similarity matching of clinical encounters and outbreak protocols.
- **Fluid & Responsive UI:** Provides consistent, high-performance API endpoints to ensure the frontend dashboard remains fluid and responsive under load.
- **Swarm Intelligence:** Acts dependably as a node in the autonomous, multi-agent swarm network, guaranteeing perfect coordination for national health disease outbreak management.
