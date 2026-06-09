# Quick Start: Testing Data Correction Features

## 🧪 Test the New Data Correction & Validation System

### Prerequisites

- Dev server running: `python start-dev.ps1` (Windows) or `bash start-dev.sh` (Linux/Mac)
- MongoDB Atlas connected (check health endpoint)
- Gemini API key configured

---

## Test 1: Verify Disease Reference Database

### Check MongoDB

```bash
# Connect to MongoDB and verify disease_reference collection
db.disease_reference.count()          # Should return: 11
db.disease_reference.find().pretty()  # Should show: ebola, covid_19, malaria, etc.
```

### Check App Logs

Look for startup message:

```
[Orchestrator] 🚀 Starting SihaLink — Kenya National Disease Surveillance
[Orchestrator] Disease Reference Load: 11 diseases loaded
```

---

## Test 2: Test Malaria Correction

### Submit Test Form

**URL**: `http://localhost:4200` (Angular frontend)

**Form Data**:

```
Chief Complaint: "Fever with chills and sweating"
Symptoms: ["fever", "chills", "sweating", "malaise"]
Duration: 3 days
Temperature: 39.5°C
Age: 25 years
Sex: Male
```

### Expected Result

The Intake Agent should:

1. ✅ Infer syndrome as "malaria" (from symptoms)
2. ✅ Correct triage from GREEN to YELLOW
3. ✅ Add disease context (case definition, management)
4. ✅ Include actionable intelligence

**Check Response**:

```json
{
  "syndrome": "malaria",
  "triage_color": "YELLOW",
  "data_corrections_applied": [
    "inferred_syndrome: malaria from symptoms",
    "corrected_triage: GREEN → YELLOW"
  ],
  "disease_context": {
    "name": "Malaria",
    "category": "parasitic_fever",
    "kenya_context": {
      "endemic_zones": ["Western Region", "Nyanza Region"]
    }
  },
  "actionable_intelligence": {
    "referral_required": true,
    "follow_up_schedule": [2, 7, 14],
    "actions": ["URGENT_ASSESSMENT"]
  }
}
```

---

## Test 3: Test Ebola Outbreak Alert

### Submit Test Form with Danger Signs

```
Chief Complaint: "Hemorrhage and fever"
Symptoms: ["hemorrhage", "fever", "weakness"]
Danger Signs: ["hemorrhage", "shock"]
Triage (manually set): "YELLOW"  # Deliberately wrong
Age: 35
Sex: Female
```

### Expected Corrections

1. ✅ Syndrome corrected: "viral_hemorrhagic_fever" → "ebola"
2. ✅ Triage corrected: YELLOW → RED (because danger signs present)
3. ✅ Outbreak alert triggered

**Check Response**:

```json
{
  "syndrome": "ebola",
  "triage_color": "RED",
  "data_corrections_applied": [
    "corrected_triage: YELLOW → RED (Danger signs: ['hemorrhage', 'shock'])"
  ],
  "actionable_intelligence": {
    "surveillance_alert": true,         // ← OUTBREAK ALERT!
    "moh_notification_required": true,  // ← MOH NOTIFICATION!
    "contact_tracing_required": true,   // ← CONTACT TRACING!
    "actions": ["IMMEDIATE_REFERRAL", "OUTBREAK_ALERT", "CONTACT_TRACING"],
    "response_protocol": "MOH Level 4 Alert"
  }
}
```

---

## Test 4: Test Correction Audit Trail

### Check MongoDB Data Corrections Collection

```bash
db.data_corrections.find().pretty()

# Expected result:
# {
#   "_id": ObjectId(...),
#   "session_id": "enc-12345",
#   "original_extraction": {...original data...},
#   "corrected_extraction": {...corrected data...},
#   "correction_reason": "syndrome mismatch",
#   "timestamp": ISODate(...),
#   "corrected_by": "intake_agent_auto"
# }
```

### Get Correction Statistics

```python
from agents.data.agent import get_data_correction_stats

stats = get_data_correction_stats(days=1)
print(stats)

# Expected output:
# {
#   "status": "success",
#   "period_days": 1,
#   "corrections_by_reason": [
#     {"_id": "inferred_syndrome", "count": 2},
#     {"_id": "corrected_triage", "count": 1}
#   ]
# }
```

---

## Test 5: Test Symptoms-to-Disease Lookup

### Direct Function Test

```python
from agents.data.agent import search_diseases_by_symptom

# Test 1: Hemorrhage symptoms
results = search_diseases_by_symptom("hemorrhage", limit=5)
print(f"Diseases with hemorrhage: {[r['disease'] for r in results]}")
# Expected: ["ebola", "yellow_fever", "dengue", "malaria"]

# Test 2: Respiratory symptoms
results = search_diseases_by_symptom("cough", limit=5)
print(f"Diseases with cough: {[r['disease'] for r in results]}")
# Expected: ["pneumonia", "covid_19", "tuberculosis"]
```

---

## Test 6: Test Different Triage Scenarios

### Scenario A: Danger Signs Not Recognized

```python
from agents.intake.agent import correct_and_validate_extraction

extraction = {
    "syndrome": "malaria",
    "triage_color": "GREEN",  # Wrong!
    "danger_signs": ["convulsions", "unconscious"],  # Severe danger signs
    "symptoms": ["fever", "severe_headache"]
}

corrected = correct_and_validate_extraction(extraction, "test-session")
print(f"Original triage: GREEN")
print(f"Corrected triage: {corrected['triage_color']}")  # Should be RED
print(f"Reason: {corrected['data_corrections_applied']}")
```

### Scenario B: Age Validation

```python
extraction = {
    "syndrome": "malaria",
    "age_value": 200,  # Unrealistic!
    "age_unit": "years"
}

corrected = correct_and_validate_extraction(extraction, "test-session")
print(f"Age flagged as unrealistic: {corrected.get('age_value_corrected')}")
print(f"Corrections: {corrected['data_corrections_applied']}")
```

---

## Test 7: API Health Check

### Verify All Systems Ready

```bash
curl http://localhost:8000/health

# Expected response should include:
# {
#   "status": "ok",
#   "mongodb": "healthy",
#   "disease_reference_status": "healthy",
#   "gemini": "healthy"
# }
```

---

## 🔍 Monitoring & Debugging

### CloudLogging Queries

**View all data corrections:**

```
resource.type="cloud_function"
AND severity="INFO"
AND textPayload=~"DATA_CORRECTION"
```

**View outbreak alerts:**

```
resource.type="cloud_function"
AND severity="INFO"
AND textPayload=~"OUTBREAK_ALERT"
```

**View correction failures:**

```
resource.type="cloud_function"
AND severity="ERROR"
AND textPayload=~"data_correction|disease_reference"
```

### MongoDB Queries

**Find corrections for specific syndrome:**

```javascript
db.data_corrections.find({
  "corrected_extraction.syndrome": "ebola"
}).pretty()
```

**Get correction statistics:**

```javascript
db.data_corrections.aggregate([
  { $group: { _id: "$correction_reason", count: { $sum: 1 } } },
  { $sort: { count: -1 } }
])
```

**Find sessions with multiple corrections:**

```javascript
db.data_corrections.aggregate([
  { $group: { _id: "$session_id", corrections: { $sum: 1 } } },
  { $match: { corrections: { $gte: 2 } } }
])
```

---

## ✅ Success Criteria

| Test | Pass Criteria |
|------|---------------|
| **Disease DB** | 11 diseases in MongoDB collection |
| **Malaria Test** | Syndrome auto-corrected, triage validated, actionable intelligence included |
| **Ebola Test** | Outbreak alert triggered, MOH notification flagged, contact tracing activated |
| **Audit Trail** | Corrections recorded in data_corrections collection |
| **Symptom Search** | Returns correct disease matches for symptoms |
| **Triage Validation** | Danger signs override triage color |
| **Health Check** | All systems report healthy |

---

## 🚀 Next Steps After Verification

1. **Test with Real Audio** (if available)
   - Record CHV audio with clinical presentation
   - Submit via `/intake/audio` endpoint
   - Verify correction applied to audio extraction

2. **Test Telegram Integration**
   - Send message to Telegram bot
   - Verify data correction applied
   - Check correction audit trail

3. **Monitor Performance**
   - Track correction frequency
   - Identify common extraction errors
   - Plan model retraining if needed

4. **Deploy to Production**
   - Run full test suite
   - Verify MongoDB connection to Atlas
   - Enable CloudLogging monitoring

---

## 📞 Troubleshooting

### Disease References Not Loading

**Problem**: `"diseases_loaded": 0` in startup logs  
**Solution**:

1. Check `agents/data/disease_reference.py` exists
2. Verify MongoDB Atlas connection: `mongosh --connectionString "..."`
3. Check app logs for import errors

### Corrections Not Applied

**Problem**: Extracted data doesn't show `data_corrections_applied` field  
**Solution**:

1. Verify `extract_clinical_data()` is being called (not mock)
2. Check if Gemini API is responding (not degraded mode)
3. Review CloudLogging for correction function errors

### Triage Not Corrected

**Problem**: Triage color not updated despite danger signs  
**Solution**:

1. Verify `danger_signs` field populated by Gemini
2. Check `validate_triage_color()` logic in disease_reference.py
3. Review correction logs for specific error

---

**Status**: ✅ Ready for Testing  
**Last Updated**: 2025  
**Guide Version**: 1.0
