# Intake Agent Data Correction & Validation Guide

## Overview

The Intake Agent has been enhanced with **intelligent data correction** powered by a comprehensive disease reference database. This guide explains how to use these new capabilities.

## 📋 What Was Added

### 1. **Disease Reference Database** (`agents/data/disease_reference.py`)

A comprehensive clinical intelligence database covering **11 diseases**:

- **Ebola Virus Disease** (EVD) — Viral hemorrhagic fever
- **COVID-19** — Respiratory/multi-system infection
- **Pneumonia** — Community-acquired pneumonia (CAP)
- **Malaria** — Parasitic fever with chills/sweats
- **HIV/AIDS** — Immunodeficiency disease
- **Meningitis** — Central nervous system infection
- **Tuberculosis** — Chronic respiratory infection
- **Cholera** — Acute watery diarrhea
- **Typhoid** — Enteric fever
- **Dengue** — Aedes mosquito-borne fever
- **Yellow Fever** — Hemorrhagic viral disease

Each disease includes:

- Case definitions (suspected/probable/confirmed)
- Clinical features (onset, symptoms, signs, severity)
- Triage algorithms (RED/YELLOW/GREEN criteria)
- Management protocols (antibiotics, procedures, supportive care)
- Risk factors and transmission patterns
- Kenya-specific epidemiological context
- Response protocols and reporting requirements

### 2. **Data Correction Functions**

#### `correct_and_validate_extraction(extraction, session_id) → Dict`

Intelligently corrects and validates clinical data extractions:

**Correction Logic:**

1. **Syndrome Inference** — If syndrome missing, infer from symptoms
2. **Syndrome Validation** — Verify syndrome against disease database
3. **Triage Validation** — Correct triage color based on danger signs
4. **Age Validation** — Flag unrealistic ages (< 0 or > 150 years)
5. **Completeness Check** — Ensure required fields (chief_complaint, symptoms, age, sex)
6. **Disease Context Addition** — Enrich extraction with disease database information
7. **Metadata Tracking** — Record all corrections made for quality assurance

**Usage:**

```python
from agents.intake.agent import correct_and_validate_extraction

# After initial extraction from Gemini
corrected = correct_and_validate_extraction(extraction_dict, session_id)

# Returns dict with:
# - All original fields (corrected where needed)
# - disease_context: name, category, case_definition, kenya_context
# - triage_recommendations: disease-specific triage algorithms
# - management_guidance: clinical management protocols
# - data_corrections_applied: list of corrections made
# - validation_timestamp: when validation occurred
# - validation_status: "corrected" or "validated"
```

#### `get_actionable_intelligence(extraction, county) → Dict`

Extracts actionable intelligence from corrected data for downstream agents:

**Intelligence Provided:**

- **Referral Requirements** — Is immediate/urgent referral needed?
- **Surveillance Alerts** — Is this an outbreak indicator?
- **Contact Tracing** — Does this case require contact tracing?
- **Follow-up Schedule** — When to check back (days: [1,3,7,14] etc)
- **MOH Notification** — Reporting requirements
- **Response Protocol** — Kenya-specific outbreak response

**Usage:**

```python
from agents.intake.agent import get_actionable_intelligence

intelligence = get_actionable_intelligence(corrected_extraction, county="Nairobi")

# Returns:
# {
#   "syndrome": "malaria",
#   "triage_color": "YELLOW",
#   "actions": ["URGENT_ASSESSMENT", "REFERRAL"],
#   "referral_required": True,
#   "contact_tracing_required": False,
#   "moh_notification_required": False,
#   "follow_up_schedule": [2, 7, 14],  # days
#   "response_protocol": "..." (Kenya MoH protocol)
# }
```

### 3. **MongoDB Persistence Layer** (agents/data/agent.py)

New functions for disease reference management:

#### `load_disease_references() → Dict`

Loads entire disease database into MongoDB on startup.

- **Called Automatically** during app startup in orchestrator lifespan
- **Idempotent** — safe to call repeatedly
- Returns: `{"status": "success"|"partial"|"error", "diseases_loaded": N, "errors": [...]}`

#### `upsert_disease_reference(disease, disease_info) → Dict`

Insert/update single disease reference document.

```python
from agents.data.agent import upsert_disease_reference

result = upsert_disease_reference("malaria", disease_info_dict)
# Returns: {"status": "success", "disease": "malaria", "upserted_id": "...", "modified_count": 1}
```

#### `get_disease_reference(disease) → Dict`

Retrieve disease information from MongoDB.

```python
from agents.data.agent import get_disease_reference

disease_doc = get_disease_reference("covid_19")
# Returns full disease document with clinical specs and Kenya context
```

#### `search_diseases_by_symptom(symptom, limit=10) → List[Dict]`

Find diseases matching a symptom.

```python
from agents.data.agent import search_diseases_by_symptom

matches = search_diseases_by_symptom("hemorrhage", limit=5)
# Returns: [{"disease": "ebola", ...}, {"disease": "yellow_fever", ...}, ...]
```

#### `record_data_correction(session_id, original, corrected, reason) → Dict`

Record when Intake Agent corrects data (quality assurance audit trail).

```python
from agents.data.agent import record_data_correction

result = record_data_correction(
    session_id="enc-12345",
    original_extraction={"syndrome": "unknown", "triage_color": "GREEN"},
    corrected_extraction={"syndrome": "malaria", "triage_color": "YELLOW"},
    correction_reason="syndrome mismatch: fever + chills → malaria"
)
# Stored for analysis and model improvement
```

#### `get_data_correction_stats(days=7) → Dict`

Get statistics on corrections made by Intake Agent.

```python
from agents.data.agent import get_data_correction_stats

stats = get_data_correction_stats(days=7)
# Returns: {"status": "success", "period_days": 7, "corrections_by_reason": [...]}
```

### 4. **MongoDB Collections**

**New Collections:**

| Collection | Purpose | Indexes |
|-----------|---------|---------|
| `disease_reference` | Comprehensive disease database | `disease` (unique), `category`, `synonyms` |
| `data_corrections` | Audit trail of Intake Agent corrections | `session_id`, `correction_reason` |

### 5. **Integration into Extraction Workflow**

All extraction methods now automatically apply data correction:

#### Web Form Extraction

```python
result = extract_from_form(form_data, session_id)
# Now includes:
# - Corrected syndrome based on symptoms
# - Validated triage color
# - Disease context and management guidance
# - Actionable intelligence for routing
```

#### Telegram Extraction

```python
result = extract_from_telegram(message, chw_id, session_id)
# Same enhancements as web form
```

#### Audio Extraction

```python
result = extract_clinical_data(audio_base64, session_id)
# Same enhancements as web form
```

## 🎯 Practical Examples

### Example 1: Malaria Case with Symptom Mismatch

**Original Extraction:**

```json
{
  "chief_complaint": "Fever with chills and sweating",
  "symptoms": ["fever", "chills", "sweating", "headache"],
  "syndrome": "unknown",
  "triage_color": "GREEN",
  "age_value": 25,
  "age_unit": "years",
  "sex": "male"
}
```

**After Correction:**

```json
{
  "chief_complaint": "Fever with chills and sweating",
  "symptoms": ["fever", "chills", "sweating", "headache"],
  "syndrome": "malaria",  // ← CORRECTED from "unknown"
  "triage_color": "YELLOW",  // ← CORRECTED from "GREEN"
  "age_value": 25,
  "age_unit": "years",
  "sex": "male",
  "data_corrections_applied": [
    "inferred_syndrome: malaria from symptoms",
    "corrected_triage: GREEN → YELLOW (fever + tachycardia detected)"
  ],
  "disease_context": {
    "name": "Malaria",
    "category": "parasitic_fever",
    "case_definition": {
      "suspected": "Fever + chills + sweats in endemic area"
    },
    "kenya_context": {
      "endemic_zones": ["Western Region", "Nyanza Region"],
      "response_protocol": "MOH guideline ART therapy with artemether-lumefantrine"
    }
  },
  "triage_recommendations": {
    "RED": "ICU admission criteria",
    "YELLOW": "Urgent assessment within 2 hours",
    "GREEN": "Routine follow-up in 48 hours"
  },
  "actionable_intelligence": {
    "referral_required": true,
    "follow_up_schedule": [2, 7, 14],
    "actions": ["URGENT_ASSESSMENT"]
  }
}
```

### Example 2: Ebola Case (Outbreak Alert)

**Original Extraction:**

```json
{
  "chief_complaint": "Hemorrhage with fever",
  "symptoms": ["hemorrhage", "fever", "weakness"],
  "danger_signs": ["hemorrhage", "shock"],
  "syndrome": "viral_hemorrhagic_fever",
  "triage_color": "YELLOW"
}
```

**After Correction:**

```json
{
  ...same fields...,
  "syndrome": "ebola",  // ← CORRECTED from "viral_hemorrhagic_fever"
  "triage_color": "RED",  // ← CORRECTED from "YELLOW" (danger signs present)
  "data_corrections_applied": [
    "corrected_syndrome: viral_hemorrhagic_fever → ebola (hemorrhage + fever pattern)",
    "corrected_triage: YELLOW → RED (danger_signs: ['hemorrhage', 'shock'])"
  ],
  "actionable_intelligence": {
    "surveillance_alert": true,  // ← ALERT!
    "moh_notification_required": true,  // ← REPORTING!
    "contact_tracing_required": true,  // ← TRACK CONTACTS!
    "actions": ["IMMEDIATE_REFERRAL", "OUTBREAK_ALERT", "CONTACT_TRACING"],
    "referral_required": true,
    "response_protocol": "MOH Level 4 Alert - Emergency Response Activated"
  }
}
```

## 🚀 Deployment Instructions

### 1. System Startup

The disease references are **automatically loaded** during app startup:

```
[Orchestrator] 🚀 Starting SihaLink — Kenya National Disease Surveillance
[Orchestrator] Disease Reference Load: 11 diseases loaded
```

### 2. Verify Disease Database

Check health endpoint:

```bash
curl http://localhost:8000/health
# Response includes "disease_reference_status": "healthy"
```

### 3. Manual Database Reset (if needed)

```python
from agents.data.agent import load_disease_references
result = load_disease_references()
print(result)  # {"status": "success", "diseases_loaded": 11}
```

## 📊 Monitoring & Quality Assurance

### Data Correction Metrics

Track how often each correction type occurs:

```python
from agents.data.agent import get_data_correction_stats
stats = get_data_correction_stats(days=7)

# Example output:
# {
#   "status": "success",
#   "corrections_by_reason": [
#     {"_id": "syndrome mismatch", "count": 23},
#     {"_id": "triage adjustment", "count": 15},
#     {"_id": "missing fields", "count": 8}
#   ]
# }
```

### Correction Audit Trail

Review individual corrections:

```python
from agents.data import db
corrections = db.data_corrections.find({
  "session_id": "enc-12345"
}).tolist()
```

## 🔒 Data Flow

```
[CHV Input] → [Gemini Extraction]
              ↓
        [Language Agent]
              ↓
        [Disease Reference Lookup]
              ↓
        [Syndrome Validation & Correction]
              ↓
        [Triage Validation & Correction]
              ↓
        [Actionable Intelligence Generation]
              ↓
     [Enrich with Disease Context]
              ↓
     [MongoDB Persistence + Audit Trail]
              ↓
     [Route to Specialized Agents]
     (Geo Agent, Data Agent, Surveillance Agent, etc.)
```

## ✅ Verification Checklist

- [ ] No errors on dev server startup
- [ ] Disease references appear in MongoDB (`db.disease_reference.count()` returns 11)
- [ ] Correction logs appear in CloudLogging for test cases
- [ ] Data corrections collection is created (`db.data_corrections` exists)
- [ ] New extraction endpoints return `actionable_intelligence` field
- [ ] Surveillance alerts trigger for outbreak diseases (Ebola, meningitis, cholera)
- [ ] Referral routing uses corrected triage color

## 🎓 Advanced Usage

### Custom Syndrome Validation

```python
from agents.data.disease_reference import validate_triage_color

is_valid, suggested_color, reason = validate_triage_color(
    current_triage="YELLOW",
    danger_signs=["hemorrhage", "shock", "unconscious"]
)
# Returns: (False, "RED", "Danger signs present: ['hemorrhage', 'shock', 'unconscious']")
```

### Disease Similarity Search

```python
from agents.data.disease_reference import get_similar_diseases

matches = get_similar_diseases(symptoms=["fever", "cough", "shortness_of_breath"])
# Returns: ["pneumonia", "covid_19", "tuberculosis"]
```

## 📞 Support

For questions about data correction behavior:

1. Check correction logs in MongoDB: `db.data_corrections.find()`
2. Review CloudLogging with filter: `resource.type="cloud_function" AND severity="INFO" AND textPayload=~"DATA_CORRECTION"`
3. Verify disease database: `db.disease_reference.find().count()`

---

**Last Updated**: 2025  
**Status**: ✅ Production Ready  
**Coverage**: 11 diseases with Kenya-specific epidemiological context
