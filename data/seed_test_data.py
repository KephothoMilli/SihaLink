"""
SihaLink — Test Data Seeder
===========================
Generates and persists realistic Kenya public health test data to MongoDB Atlas.

Collections populated:
  chws               — 24 Community Health Workers across 8 counties
  encounters         — 120 clinical encounters (30 days) with Voyage AI embeddings
  alerts             — 18 active outbreak alerts
  baselines          — County-syndrome baselines (4-week rolling averages)
  follow_ups         — Follow-up tasks scheduled from encounters
  contact_traces     — 12 active contact traces with contacts
  protocols          — WHO/MoH response protocols for all IDSR syndromes
  agent_logs         — Intake and pipeline processing logs
  referrals          — Patient referral records
  workflow_states    — Workflow state machine history

Run:
    python scripts/seed_test_data.py

Requirements:
    pip install pymongo python-dotenv voyageai
    MONGODB_ATLAS_URI and VOYAGE_API_KEY must be set in .env
"""

import os
import sys
import random
import logging
from datetime import datetime, timedelta
from uuid import uuid4

# ── path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient, GEOSPHERE, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("SihaLink-Seeder")

# ═══════════════════════════════════════════════════════════════════
# CONNECTION
# ═══════════════════════════════════════════════════════════════════

uri = os.getenv("MONGODB_ATLAS_URI")
if not uri:
    logger.error("MONGODB_ATLAS_URI not set. Exiting.")
    sys.exit(1)

client = MongoClient(uri, appname="sihalink-seeder")
db = client.sihalink
logger.info("✅ Connected to MongoDB Atlas — database: sihalink")

# ═══════════════════════════════════════════════════════════════════
# EMBEDDING SERVICE
# ═══════════════════════════════════════════════════════════════════

def get_embedding(text: str) -> list:
    """Generate embedding via Voyage AI. Falls back to zero vector."""
    voyage_key = os.getenv("VOYAGE_API_KEY")
    if not voyage_key:
        logger.debug("No VOYAGE_API_KEY — using zero vector")
        return [0.0] * 1024
    try:
        import voyageai
        vc = voyageai.Client(api_key=voyage_key)
        result = vc.embed(texts=[text], model="voyage-4", input_type="document")
        return result.embeddings[0]
    except Exception as exc:
        logger.warning("Voyage AI embed failed: %s — zero vector", exc)
        return [0.0] * 1024

# ═══════════════════════════════════════════════════════════════════
# MASTER REFERENCE DATA
# ═══════════════════════════════════════════════════════════════════

COUNTIES = {
    "Homa Bay":   {"lat": -0.5273,  "lng": 34.4571, "wards": ["East Karachuonyo", "Kasipul", "Kabondo Kasipul", "Rangwe"]},
    "Kisumu":     {"lat": -0.0917,  "lng": 34.7679, "wards": ["Central Kisumu", "Kisumu North", "Winam", "Nyando"]},
    "Nairobi":    {"lat": -1.2921,  "lng": 36.8219, "wards": ["Mathare", "Kibera", "Korogocho", "Mukuru"]},
    "Mombasa":    {"lat": -4.0435,  "lng": 39.6682, "wards": ["Changamwe", "Miritini", "Chaani", "Port Reitz"]},
    "Garissa":    {"lat": -0.4532,  "lng": 39.6461, "wards": ["Garissa Township", "Balambala", "Lagdera", "Ijara"]},
    "Turkana":    {"lat":  3.1166,  "lng": 35.5966, "wards": ["Turkana East", "Turkana North", "Turkana Central", "Kalokol"]},
    "Kilifi":     {"lat": -3.5107,  "lng": 39.9093, "wards": ["Kilifi North", "Kilifi South", "Magarini", "Ganze"]},
    "Kisii":      {"lat": -0.6817,  "lng": 34.7667, "wards": ["Bomachoge Chache", "Bobasi", "Nyaribari Chache", "Kitutu Chache"]},
}

SYNDROMES = [
    "cholera", "measles", "acute_watery_diarrhea", "acute_respiratory_infection",
    "malnutrition_severe", "acute_febrile_illness", "malaria", "tuberculosis",
    "dengue", "typhoid", "meningitis", "pneumonia",
]

TRIAGE_DIST = ["RED"] * 15 + ["YELLOW"] * 40 + ["GREEN"] * 45  # realistic Kenya mix

LANGUAGES = {
    "Homa Bay": ["Dholuo", "Swahili", "English"],
    "Kisumu":   ["Dholuo", "Swahili", "English"],
    "Nairobi":  ["Swahili", "English"],
    "Mombasa":  ["Swahili", "English", "Mijikenda"],
    "Garissa":  ["Somali", "Swahili", "English"],
    "Turkana":  ["Turkana", "Swahili", "English"],
    "Kilifi":   ["Swahili", "Mijikenda", "English"],
    "Kisii":    ["Gusii", "Swahili", "English"],
}

SYMPTOMS_BY_SYNDROME = {
    "cholera":                    ["profuse watery diarrhoea", "vomiting", "leg cramps", "severe dehydration", "sunken eyes"],
    "measles":                    ["high fever", "maculopapular rash", "runny nose", "cough", "red eyes", "Koplik spots"],
    "acute_watery_diarrhea":      ["watery stools", "abdominal cramps", "nausea", "mild dehydration", "fever"],
    "acute_respiratory_infection":["cough", "fast breathing", "chest indrawing", "nasal flaring", "fever"],
    "malnutrition_severe":        ["MUAC < 11.5cm", "bilateral oedema", "wasting", "lethargy", "inability to eat"],
    "acute_febrile_illness":      ["high fever >38.5°C", "chills", "headache", "myalgia", "rigors"],
    "malaria":                    ["fever", "chills", "headache", "vomiting", "anaemia", "splenomegaly"],
    "tuberculosis":               ["chronic cough >2 weeks", "blood in sputum", "night sweats", "weight loss", "fatigue"],
    "dengue":                     ["high fever", "severe headache", "retro-orbital pain", "rash", "joint pain", "bleeding gums"],
    "typhoid":                    ["sustained fever", "abdominal pain", "rose spots", "constipation", "hepatosplenomegaly"],
    "meningitis":                 ["stiff neck", "high fever", "severe headache", "photophobia", "altered consciousness"],
    "pneumonia":                  ["cough", "fast breathing", "chest pain", "fever", "cyanosis", "grunting"],
}

FACILITIES = {
    "Homa Bay": [{"name": "Homa Bay County Teaching & Referral Hospital", "eta_minutes": 15, "distance_km": 3.2}],
    "Kisumu":   [{"name": "Jaramogi Oginga Odinga Teaching and Referral Hospital", "eta_minutes": 20, "distance_km": 4.8}],
    "Nairobi":  [{"name": "Kenyatta National Hospital", "eta_minutes": 25, "distance_km": 6.0}],
    "Mombasa":  [{"name": "Coast General Teaching and Referral Hospital", "eta_minutes": 18, "distance_km": 4.1}],
    "Garissa":  [{"name": "Garissa County Referral Hospital", "eta_minutes": 30, "distance_km": 7.5}],
    "Turkana":  [{"name": "Lodwar County Referral Hospital", "eta_minutes": 45, "distance_km": 12.0}],
    "Kilifi":   [{"name": "Kilifi County Hospital", "eta_minutes": 22, "distance_km": 5.3}],
    "Kisii":    [{"name": "Kisii Teaching and Referral Hospital", "eta_minutes": 17, "distance_km": 3.8}],
}

WHO_CODES = {
    "cholera": "CHL", "measles": "MEA", "acute_watery_diarrhea": "AWD",
    "acute_respiratory_infection": "ARI", "malnutrition_severe": "SAM",
    "acute_febrile_illness": "AFI", "malaria": "MAL", "tuberculosis": "TUB",
    "dengue": "DEN", "typhoid": "TYP", "meningitis": "MEN", "pneumonia": "PNE",
}

def rnd_hex(n=8): return uuid4().hex[:n].upper()
def days_ago(n): return datetime.utcnow() - timedelta(days=n)
def hours_ago(n): return datetime.utcnow() - timedelta(hours=n)

# ═══════════════════════════════════════════════════════════════════
# 1. COMMUNITY HEALTH WORKERS
# ═══════════════════════════════════════════════════════════════════

CHW_NAMES = [
    "Achieng Otieno", "Onyango Odhiambo", "Adhiambo Auma", "Ochieng Nyambok",
    "Wanjiku Kamau", "Mwangi Kariuki", "Njeri Gitau", "Kimani Waweru",
    "Fatuma Hassan", "Abdi Omar", "Halima Issack", "Mohamed Aden",
    "Lopidia Nakol", "Akiru Erot", "Lokwang Lowot", "Nakalong Ekal",
    "Zawadi Mwamba", "Juma Bora", "Amina Suleiman", "Rashid Kipkoech",
    "Kiptoo Rutto", "Jepchirchir Bett", "Cherono Koech", "Rotich Mutai",
]

chw_ids = []
chw_telegram_ids = {}

def seed_chws():
    logger.info("👥 Seeding CHWs...")
    docs = []
    county_list = list(COUNTIES.keys())
    for i, name in enumerate(CHW_NAMES):
        county = county_list[i % len(county_list)]
        wards = COUNTIES[county]["wards"]
        ward = random.choice(wards)
        chw_id = f"CHW-{rnd_hex(6)}"
        telegram_id = random.randint(100000000, 999999999)
        chw_ids.append(chw_id)
        chw_telegram_ids[chw_id] = telegram_id
        doc = {
            "chw_id":       chw_id,
            "name":         name,
            "county":       county,
            "sub_county":   county,
            "ward":         ward,
            "telegram_id":  telegram_id,
            "phone":        f"+2547{random.randint(10000000,99999999)}",
            "supervisor_id": f"SUP-{rnd_hex(4)}",
            "status":       "active",
            "languages":    LANGUAGES[county],
            "registered_at": days_ago(random.randint(30, 365)),
            "last_active":   days_ago(random.randint(0, 7)),
            "created_at":    days_ago(random.randint(30, 365)),
        }
        docs.append(doc)
    db.chws.delete_many({})
    db.chws.insert_many(docs)
    logger.info("  ✅ Inserted %d CHWs", len(docs))

# ═══════════════════════════════════════════════════════════════════
# 2. ENCOUNTERS (with embeddings)
# ═══════════════════════════════════════════════════════════════════

encounter_ids = []

def build_encounter_text(enc):
    ext = enc.get("extracted", {})
    adm = enc.get("admin_hierarchy", {})
    syndrome  = ext.get("syndrome", "unknown")
    symptoms  = ", ".join(ext.get("symptoms", []))
    triage    = ext.get("triage_color", "GREEN")
    complaint = ext.get("chief_complaint", "")
    county    = adm.get("county", "")
    ward      = adm.get("ward", "")
    sex       = ext.get("sex", "unknown")
    age       = ext.get("age", {})
    age_str   = f"{age.get('value','?')} {age.get('unit','years')}"
    return (
        f"Syndrome: {syndrome}. Triage: {triage}. Symptoms: {symptoms}. "
        f"Complaint: {complaint}. Patient: {age_str} {sex}. "
        f"Location: {ward} ward, {county} county, Kenya."
    )

def seed_encounters():
    logger.info("🏥 Seeding encounters (120)...")
    docs = []
    county_list = list(COUNTIES.keys())

    for i in range(120):
        county = county_list[i % len(county_list)]
        county_data = COUNTIES[county]
        wards = county_data["wards"]
        ward = random.choice(wards)
        syndrome = random.choice(SYNDROMES)
        triage = random.choice(TRIAGE_DIST)
        chw_id = random.choice(chw_ids) if chw_ids else f"CHW-{rnd_hex(6)}"
        symptoms = random.sample(SYMPTOMS_BY_SYNDROME.get(syndrome, ["fever", "malaise"]), k=random.randint(2, 4))
        age_val = random.choice([1, 2, 3, 4, 5, 8, 12, 15, 25, 35, 45, 60])
        age_unit = "months" if age_val <= 12 and random.random() < 0.3 else "years"
        ts = days_ago(random.randint(0, 30)) - timedelta(hours=random.randint(0, 23))

        enc_id = f"ENC-{rnd_hex(8)}"
        encounter_ids.append(enc_id)

        # Add jitter to coordinates so $geoNear works well
        lat = county_data["lat"] + random.uniform(-0.15, 0.15)
        lng = county_data["lng"] + random.uniform(-0.15, 0.15)

        enc = {
            "encounter_id":    enc_id,
            "chw_id":          chw_id,
            "session_id":      f"sess-{rnd_hex(8)}",
            "timestamp":       ts,
            "synced":          True,
            "source":          random.choice(["telegram", "web_form", "audio"]),
            "extracted": {
                "syndrome":        syndrome,
                "triage_color":    triage,
                "chief_complaint": f"{', '.join(symptoms[:2])} — {syndrome.replace('_', ' ')}",
                "symptoms":        symptoms,
                "age":             {"value": age_val, "unit": age_unit},
                "sex":             random.choice(["male", "female"]),
                "confidence":      round(random.uniform(0.72, 0.98), 2),
                "detected_language": random.choice(LANGUAGES[county]),
                "duration_days":   random.randint(1, 14),
                "severity":        "severe" if triage == "RED" else ("moderate" if triage == "YELLOW" else "mild"),
                "vital_signs": {
                    "temperature_c":    round(36.5 + random.uniform(0, 4), 1),
                    "respiratory_rate": random.randint(16, 60),
                    "heart_rate":       random.randint(60, 140),
                },
            },
            "location": {
                "type":        "Point",
                "coordinates": [lng, lat],
            },
            "admin_hierarchy": {
                "county":     county,
                "sub_county": county,
                "ward":       ward,
                "village":    f"{ward} Village {random.randint(1,5)}",
            },
            "nearest_facilities": FACILITIES.get(county, []),
            "embedding":      [],  # filled below
            "queued_at":      None,
        }

        # Generate Voyage AI embedding
        enc["embedding"] = get_embedding(build_encounter_text(enc))
        docs.append(enc)

    db.encounters.delete_many({})
    db.encounters.insert_many(docs)
    try:
        db.encounters.create_index([("location", GEOSPHERE)])
        db.encounters.create_index([("extracted.syndrome", ASCENDING), ("timestamp", DESCENDING)])
        db.encounters.create_index([("admin_hierarchy.county", ASCENDING), ("timestamp", DESCENDING)])
        db.encounters.create_index([("chw_id", ASCENDING)])
    except Exception:
        pass
    logger.info("  ✅ Inserted %d encounters with Voyage AI embeddings", len(docs))

# ═══════════════════════════════════════════════════════════════════
# 3. BASELINES
# ═══════════════════════════════════════════════════════════════════

def seed_baselines():
    logger.info("📊 Seeding baselines...")
    docs = []
    for county in COUNTIES:
        for syndrome in SYNDROMES:
            weekly_avg = round(random.uniform(1.5, 12.0), 2)
            docs.append({
                "county":         county,
                "syndrome":       syndrome,
                "weekly_avg":     weekly_avg,
                "total_cases":    int(weekly_avg * 4),
                "weeks_with_data": 4,
                "sufficient_data": True,
                "updated_at":     datetime.utcnow(),
            })
    db.baselines.delete_many({})
    for doc in docs:
        db.baselines.update_one(
            {"county": doc["county"], "syndrome": doc["syndrome"]},
            {"$set": doc},
            upsert=True,
        )
    logger.info("  ✅ Inserted %d baseline documents", len(docs))

# ═══════════════════════════════════════════════════════════════════
# 4. ALERTS
# ═══════════════════════════════════════════════════════════════════

alert_ids = []

def seed_alerts():
    logger.info("🚨 Seeding alerts...")
    docs = []
    alert_types = [
        ("cholera", "Homa Bay", "East Karachuonyo", "RED", "spike", 38, 85.0, "HIGH"),
        ("measles", "Kisumu", "Central Kisumu", "YELLOW", "spike", 22, 47.0, "MEDIUM"),
        ("malaria", "Mombasa", "Changamwe", "YELLOW", "spike", 31, 62.5, "MEDIUM"),
        ("acute_respiratory_infection", "Nairobi", "Mathare", "YELLOW", "spike", 45, 120.0, "HIGH"),
        ("acute_watery_diarrhea", "Garissa", "Garissa Township", "YELLOW", "spike", 19, 38.0, "MEDIUM"),
        ("tuberculosis", "Turkana", "Turkana East", "RED", "spike", 12, 200.0, "HIGH"),
        ("dengue", "Kilifi", "Kilifi North", "YELLOW", "spike", 9, 180.0, "HIGH"),
        ("malnutrition_severe", "Turkana", "Turkana North", "RED", "spike", 27, 350.0, "HIGH"),
        ("meningitis", "Kisii", "Bomachoge Chache", "RED", "spike", 6, 500.0, "HIGH"),
        # Silent pandemic signals
        ("malaria", "Kisumu", "Multiple", "YELLOW", "silent_pandemic", 0, 0, "MEDIUM"),
        ("acute_febrile_illness", "Nairobi", "Multiple", "YELLOW", "silent_pandemic", 0, 0, "LOW"),
        ("cholera", "Mombasa", "Multiple", "RED", "silent_pandemic", 0, 0, "HIGH"),
        # Cross-county spread
        ("measles", "NATIONAL", "Multiple Counties", "RED", "cross_county_spread", 0, 0, "HIGH"),
        # CHW outreach gaps
        ("chw_outreach_gap", "Homa Bay", "Kasipul", "YELLOW", "chw_outreach_gap", 0, 0, "MEDIUM"),
        ("chw_outreach_gap", "Garissa", "Balambala", "YELLOW", "chw_outreach_gap", 0, 0, "HIGH"),
        ("chw_outreach_gap", "Turkana", "Kalokol", "YELLOW", "chw_outreach_gap", 0, 0, "CRITICAL"),
        # Resolved alert (for history)
        ("typhoid", "Kisumu", "Winam", "YELLOW", "spike", 14, 75.0, "MEDIUM"),
        ("pneumonia", "Kilifi", "Ganze", "YELLOW", "spike", 18, 60.0, "MEDIUM"),
    ]

    enc_sample = encounter_ids[:12] if len(encounter_ids) >= 12 else encounter_ids

    for idx, (syndrome, county, ward, alert_level, alert_type, count, pct, risk) in enumerate(alert_types):
        ts = hours_ago(random.randint(1, 168))
        alert_id = f"{county.replace(' ', '_')}-{syndrome}-{ward.replace(' ', '_')}-{ts.strftime('%Y%m%d%H')}"
        alert_ids.append(alert_id)

        doc = {
            "alert_id":               alert_id,
            "syndrome":               syndrome,
            "alert_type":             alert_type,
            "status":                 "resolved" if idx >= 16 else "active",
            "alert_level":            alert_level,
            "risk_level":             risk,
            "location": {
                "county": county,
                "ward":   ward,
            },
            "count":                  count,
            "percent_above_baseline": pct,
            "encounter_ids":          random.sample(enc_sample, k=min(3, len(enc_sample))),
            "detected_at":            ts.isoformat(),
            "escalation_level":       "NATIONAL" if syndrome == "measles" and alert_type == "cross_county_spread" else "COUNTY",
            "recommended_actions":    [
                f"Activate {county} rapid response team for {syndrome.replace('_', ' ')}",
                "Deploy emergency supplies to affected wards",
                "Conduct active case search in surrounding villages",
                "Issue community advisory via SihaLink broadcast",
            ],
        }

        if alert_type == "silent_pandemic":
            doc.update({
                "trend_delta":    random.randint(3, 12),
                "weekly_counts":  [random.randint(2, 8) for _ in range(4)],
                "weekly_avg":     round(random.uniform(3, 8), 1),
                "weeks_observed": 4,
                "total_cases":    random.randint(12, 40),
                "signal_type":    "silent_pandemic",
            })

        if alert_type == "cross_county_spread":
            doc.update({
                "counties_affected": [
                    {"county": "Kisumu",  "count": 22, "wards_affected": 3, "latest_case": hours_ago(6).isoformat()},
                    {"county": "Siaya",   "count": 18, "wards_affected": 2, "latest_case": hours_ago(8).isoformat()},
                    {"county": "Homa Bay","count": 15, "wards_affected": 2, "latest_case": hours_ago(12).isoformat()},
                ],
                "counties_count": 3,
            })

        if idx >= 16:
            doc.update({
                "resolved_by":      f"DO-{random.choice(list(COUNTIES.keys()))[:3].upper()}",
                "resolved_at":      days_ago(random.randint(1, 5)).isoformat(),
                "resolution_notes": "Outbreak contained after emergency response. Follow-up surveillance ongoing.",
                "acknowledged_by":  "district_officer_01",
                "acknowledged_at":  hours_ago(random.randint(4, 24)).isoformat(),
            })

        docs.append(doc)

    db.alerts.delete_many({})
    db.alerts.insert_many(docs)
    try:
        db.alerts.create_index([("alert_id", ASCENDING)], unique=True, sparse=True)
        db.alerts.create_index([("location.county", ASCENDING), ("status", ASCENDING)])
    except Exception:
        pass
    logger.info("  ✅ Inserted %d alerts", len(docs))

# ═══════════════════════════════════════════════════════════════════
# 5. FOLLOW-UPS
# ═══════════════════════════════════════════════════════════════════

followup_ids = []

def seed_follow_ups():
    logger.info("📅 Seeding follow-ups...")
    docs = []
    schedules = {"RED": [1, 3, 7, 14], "YELLOW": [2, 7, 14], "GREEN": [7]}
    outcomes  = ["improved", "stable", "deteriorated", "referred", None, None, None]

    # Use first 30 encounters
    sample_encounters = db.encounters.find({}, {"_id": 0}).limit(30)
    for enc in sample_encounters:
        triage   = enc.get("extracted", {}).get("triage_color", "GREEN")
        syndrome = enc.get("extracted", {}).get("syndrome", "unknown")
        enc_id   = enc.get("encounter_id", rnd_hex(8))
        chw_id   = enc.get("chw_id", random.choice(chw_ids) if chw_ids else "CHW-TEST")
        county   = enc.get("admin_hierarchy", {}).get("county", "Nairobi")
        ward     = enc.get("admin_hierarchy", {}).get("ward", "Unknown")
        ts       = enc.get("timestamp", datetime.utcnow())

        for day_offset in schedules.get(triage, [7]):
            fu_id    = f"FU-{rnd_hex(8)}"
            due_date = ts + timedelta(days=day_offset)
            outcome  = random.choice(outcomes)
            status   = "completed" if outcome else ("pending" if due_date > datetime.utcnow() else "pending")
            followup_ids.append(fu_id)

            doc = {
                "follow_up_id":    fu_id,
                "encounter_id":    enc_id,
                "chw_id":          chw_id,
                "county":          county,
                "ward":            ward,
                "due_date":        due_date,
                "day_offset":      day_offset,
                "status":          status,
                "triage_color":    triage,
                "syndrome":        syndrome,
                "chief_complaint": enc.get("extracted", {}).get("chief_complaint", ""),
                "patient":         enc.get("extracted", {}).get("age"),
                "created_at":      ts,
                "notes":           "",
            }
            if outcome:
                doc.update({
                    "outcome":       outcome,
                    "completed_by":  chw_id,
                    "completed_at":  due_date + timedelta(hours=random.randint(0, 8)),
                    "notes":         f"Patient {outcome}. Follow-up completed via home visit.",
                })
            docs.append(doc)

    db.follow_ups.delete_many({})
    db.follow_ups.insert_many(docs)
    try:
        db.follow_ups.create_index([("chw_id", ASCENDING), ("status", ASCENDING)])
        db.follow_ups.create_index([("county", ASCENDING), ("status", ASCENDING)])
        db.follow_ups.create_index([("encounter_id", ASCENDING)])
    except Exception:
        pass
    logger.info("  ✅ Inserted %d follow-up tasks", len(docs))

# ═══════════════════════════════════════════════════════════════════
# 6. CONTACT TRACES (with View Details datasets)
# ═══════════════════════════════════════════════════════════════════

TRACE_SCENARIOS = [
    {"syndrome": "cholera",       "county": "Homa Bay",  "ward": "East Karachuonyo", "contacts": 8,  "confirmed": 2, "tier": "HOUSEHOLD"},
    {"syndrome": "measles",       "county": "Kisumu",    "ward": "Central Kisumu",   "contacts": 12, "confirmed": 3, "tier": "COMMUNITY"},
    {"syndrome": "malaria",       "county": "Mombasa",   "ward": "Changamwe",        "contacts": 5,  "confirmed": 1, "tier": "HOUSEHOLD"},
    {"syndrome": "tuberculosis",  "county": "Nairobi",   "ward": "Mathare",          "contacts": 6,  "confirmed": 2, "tier": "HOUSEHOLD"},
    {"syndrome": "meningitis",    "county": "Kisii",     "ward": "Bomachoge Chache", "contacts": 4,  "confirmed": 1, "tier": "HOUSEHOLD"},
    {"syndrome": "dengue",        "county": "Kilifi",    "ward": "Kilifi North",     "contacts": 9,  "confirmed": 2, "tier": "COMMUNITY"},
    {"syndrome": "typhoid",       "county": "Kisumu",    "ward": "Winam",            "contacts": 7,  "confirmed": 1, "tier": "COMMUNITY"},
    {"syndrome": "cholera",       "county": "Mombasa",   "ward": "Miritini",         "contacts": 11, "confirmed": 3, "tier": "HOUSEHOLD"},
    {"syndrome": "measles",       "county": "Nairobi",   "ward": "Kibera",           "contacts": 15, "confirmed": 4, "tier": "COMMUNITY"},
    {"syndrome": "malaria",       "county": "Garissa",   "ward": "Garissa Township", "contacts": 6,  "confirmed": 2, "tier": "HOUSEHOLD"},
    {"syndrome": "acute_respiratory_infection", "county": "Turkana", "ward": "Turkana East", "contacts": 8, "confirmed": 2, "tier": "HOUSEHOLD"},
    {"syndrome": "typhoid",       "county": "Kilifi",    "ward": "Magarini",         "contacts": 5,  "confirmed": 1, "tier": "FACILITY"},
]

CONTACT_NAMES = [
    "John Otieno", "Mary Adhiambo", "James Ochieng", "Grace Auma", "Peter Odhiambo",
    "Sarah Wanjiku", "David Kamau", "Esther Njeri", "Joseph Mwangi", "Ruth Gitau",
    "Hassan Abdi", "Fatuma Omar", "Ahmed Mohamed", "Zahra Issack", "Liban Hassan",
]

def seed_contact_traces():
    logger.info("🔗 Seeding contact traces with View Details datasets...")
    docs = []

    enc_list = list(db.encounters.find({"extracted.triage_color": "RED"}, {"_id": 0}).limit(12))
    if not enc_list:
        enc_list = list(db.encounters.find({}, {"_id": 0}).limit(12))

    for i, scenario in enumerate(TRACE_SCENARIOS):
        syndrome = scenario["syndrome"]
        county   = scenario["county"]
        ward     = scenario["ward"]
        n_contacts = scenario["contacts"]
        n_confirmed = scenario["confirmed"]

        # Pick an index encounter
        enc = enc_list[i % len(enc_list)] if enc_list else {}
        enc_id = enc.get("encounter_id", f"ENC-{rnd_hex(8)}")
        chw_id = enc.get("chw_id", random.choice(chw_ids) if chw_ids else f"CHW-{rnd_hex(6)}")
        ts = days_ago(random.randint(2, 15))

        trace_id = f"CT-{rnd_hex(8)}"

        # Build contacts with rich View Details data
        contacts = []
        statuses = (
            ["confirmed"] * n_confirmed +
            ["cleared"] * (n_contacts // 3) +
            ["contacted"] * (n_contacts // 4) +
            ["identified"] * (n_contacts - n_confirmed - n_contacts // 3 - n_contacts // 4)
        )
        while len(statuses) < n_contacts:
            statuses.append("identified")
        statuses = statuses[:n_contacts]
        random.shuffle(statuses)

        tiers = ["HOUSEHOLD"] * (n_contacts // 2) + ["COMMUNITY"] * (n_contacts - n_contacts // 2)
        random.shuffle(tiers)

        assigned_chws = random.sample(chw_ids[:8] if len(chw_ids) >= 8 else chw_ids, k=min(3, len(chw_ids)))

        for j in range(n_contacts):
            contact_id   = f"CON-{rnd_hex(8)}"
            contact_status = statuses[j]
            risk_tier    = tiers[j]
            assigned_chw = random.choice(assigned_chws)
            due_date     = ts + timedelta(days=CONTACT_DUE_DAYS.get(risk_tier, 2))
            name = random.choice(CONTACT_NAMES) if j < len(CONTACT_NAMES) else f"Contact {j+1}"

            contact = {
                "contact_id":     contact_id,
                "name":           name,           # for View Details display
                "risk_tier":      risk_tier,
                "encounter_id":   f"ENC-{rnd_hex(8)}" if contact_status == "confirmed" else None,
                "source":         "encounter_search" if j > 0 else "presumptive_household",
                "location":       {"county": county, "ward": ward},
                "status":         contact_status,
                "confirmed_case": contact_status == "confirmed",
                "notes":          _contact_notes(contact_status, syndrome),
                "assigned_chw":   assigned_chw,
                "follow_up_id":   f"FU-CT-{rnd_hex(8)}",
                "due_date":       due_date.isoformat(),
                "completed_at":   (due_date + timedelta(hours=random.randint(1, 12))).isoformat()
                                   if contact_status in ("cleared", "confirmed", "contacted") else None,
                "completed_by":   assigned_chw if contact_status not in ("identified",) else None,
                # Extra View Details fields
                "age":            {"value": random.randint(1, 70), "unit": "years"},
                "sex":            random.choice(["male", "female"]),
                "phone":          f"+2547{random.randint(10000000,99999999)}",
                "relationship_to_index": random.choice(["household member", "neighbour", "classmate", "coworker", "unknown"]),
                "symptoms_reported":     random.sample(SYMPTOMS_BY_SYNDROME.get(syndrome, ["fever"]), k=random.randint(0, 2)) if contact_status in ("confirmed", "contacted") else [],
                "last_exposure_date":    (ts - timedelta(days=random.randint(1, 7))).isoformat(),
            }
            contacts.append(contact)

        contacted_count = sum(1 for c in contacts if c["status"] != "identified")
        overdue = sum(1 for c in contacts
                      if c["status"] == "identified"
                      and c["due_date"] and c["due_date"] < datetime.utcnow().isoformat())

        # Build rich history
        history = [
            {
                "event":     "trace_initiated",
                "timestamp": ts.isoformat(),
                "by":        "surveillance_agent",
                "detail":    f"{n_contacts} contacts identified in {ward}, {county}",
            }
        ]
        for c in contacts[:3]:
            if c["status"] in ("contacted", "cleared", "confirmed"):
                history.append({
                    "event":      f"contact_{c['status']}",
                    "timestamp":  (ts + timedelta(hours=random.randint(4, 48))).isoformat(),
                    "by":         c["assigned_chw"],
                    "contact_id": c["contact_id"],
                    "detail":     _contact_notes(c["status"], syndrome),
                })

        trace_doc = {
            "trace_id":            trace_id,
            "index_encounter_id":  enc_id,
            "alert_id":            random.choice(alert_ids) if alert_ids else None,
            "syndrome":            syndrome,
            "status":              "active",
            "escalation_level":    "COUNTY",
            "initiated_by":        "surveillance_agent",
            "index_case": {
                "chw_id":       chw_id,
                "triage_color": "RED",
                "location":     {"county": county, "ward": ward},
                "timestamp":    ts.isoformat(),
                "patient":      {
                    "age":  {"value": random.randint(1, 60), "unit": "years"},
                    "sex":  random.choice(["male", "female"]),
                    "name": random.choice(CONTACT_NAMES),
                },
            },
            "contact_window": {
                "start": (ts - timedelta(days=7)).isoformat(),
                "end":   (ts + timedelta(days=2)).isoformat(),
                "days":  7,
            },
            "contacts":           contacts,
            "total_contacts":     n_contacts,
            "contacted_count":    contacted_count,
            "confirmed_cases":    n_confirmed,
            "overdue_contacts":   overdue,
            "assigned_chws":      assigned_chws,
            "history":            history,
            "created_at":         ts.isoformat(),
            "resolved_at":        None,
            "analytics": {
                "completion_rate_pct":   round(contacted_count / n_contacts * 100, 1),
                "secondary_attack_rate": round(n_confirmed / max(n_contacts, 1) * 100, 1),
                "status_histogram": {
                    "identified": sum(1 for c in contacts if c["status"] == "identified"),
                    "contacted":  sum(1 for c in contacts if c["status"] == "contacted"),
                    "assessed":   sum(1 for c in contacts if c["status"] == "assessed"),
                    "cleared":    sum(1 for c in contacts if c["status"] == "cleared"),
                    "confirmed":  n_confirmed,
                    "overdue":    overdue,
                },
                "tier_histogram": {
                    "HOUSEHOLD":  sum(1 for c in contacts if c["risk_tier"] == "HOUSEHOLD"),
                    "COMMUNITY":  sum(1 for c in contacts if c["risk_tier"] == "COMMUNITY"),
                    "FACILITY":   sum(1 for c in contacts if c["risk_tier"] == "FACILITY"),
                    "UNKNOWN":    0,
                },
            },
        }
        docs.append(trace_doc)

    db.contact_traces.delete_many({})
    db.contact_traces.insert_many(docs)
    try:
        db.contact_traces.create_index([("trace_id", ASCENDING)], unique=True)
        db.contact_traces.create_index([("syndrome", ASCENDING), ("status", ASCENDING)])
        db.contact_traces.create_index([("index_case.location.county", ASCENDING)])
    except Exception:
        pass
    logger.info("  ✅ Inserted %d contact traces (%d total contacts)",
                len(docs), sum(s["contacts"] for s in TRACE_SCENARIOS))

CONTACT_DUE_DAYS = {"HOUSEHOLD": 1, "COMMUNITY": 2, "FACILITY": 2, "UNKNOWN": 3}

def _contact_notes(status, syndrome):
    notes = {
        "confirmed": f"Patient presenting with {syndrome.replace('_',' ')} symptoms. Referred to facility.",
        "cleared":   "No symptoms reported. Household hygiene advised. Follow-up complete.",
        "contacted": "Visited household. Patient under observation. No symptoms yet.",
        "assessed":  "Screened for symptoms. Sample collected for lab analysis.",
        "identified": "",
    }
    return notes.get(status, "")

# ═══════════════════════════════════════════════════════════════════
# 7. PROTOCOLS
# ═══════════════════════════════════════════════════════════════════

PROTOCOL_DATA = {
    "cholera": {
        "alert_level": "RED", "who_idsr_code": "CHL",
        "immediate_actions": [
            "Activate county cholera task force within 2 hours",
            "Deploy oral rehydration solution (ORS) to affected wards",
            "Establish cholera treatment centres (CTCs) within 24 hours",
            "Conduct rapid water quality testing in affected area",
            "Issue boil-water advisory via Telegram broadcast",
        ],
        "chw_actions": [
            "Conduct household visits in affected ward — identify symptomatic contacts",
            "Distribute ORS sachets and hygiene kits",
            "Record all cases using SihaLink intake",
            "Follow up all cases at 24h, 48h, and 7 days",
        ],
        "follow_up_days": [1, 2, 7], "reporting_threshold": 1,
    },
    "measles": {
        "alert_level": "YELLOW", "who_idsr_code": "MEA",
        "immediate_actions": [
            "Verify diagnosis with rapid antigen test",
            "Activate supplementary immunisation activity (SIA) planning",
            "Identify unvaccinated children in affected ward",
            "Notify county immunisation coordinator",
        ],
        "chw_actions": [
            "Map all unvaccinated children under 5 in the ward",
            "Conduct door-to-door vaccination campaign",
            "Record all suspected cases via SihaLink",
            "Follow up confirmed cases at 7 and 14 days",
        ],
        "follow_up_days": [7, 14], "reporting_threshold": 1,
    },
    "malaria": {
        "alert_level": "YELLOW", "who_idsr_code": "MAL",
        "immediate_actions": [
            "Confirm with rapid diagnostic test (RDT) before treatment",
            "Administer ACT (artemether-lumefantrine) per national guidelines",
            "Refer severe malaria immediately to facility",
            "Notify county malaria coordinator if ≥5 cases in 48h",
        ],
        "chw_actions": [
            "Distribute long-lasting insecticidal nets (LLINs) to affected households",
            "Screen under-5s and pregnant women with RDT",
            "Follow up all confirmed cases at 3 and 7 days",
        ],
        "follow_up_days": [3, 7, 14], "reporting_threshold": 5,
    },
    "tuberculosis": {
        "alert_level": "YELLOW", "who_idsr_code": "TUB",
        "immediate_actions": [
            "Confirm with sputum smear or GeneXpert MTB/RIF testing",
            "Register on county TB register and notify NTLD programme",
            "Initiate 6-month directly observed therapy (DOTS) immediately",
            "Screen all household contacts",
        ],
        "chw_actions": [
            "Provide daily DOTS supervision for first 2 months",
            "Trace all defaulters within 24 hours of missed dose",
            "Screen household contacts with symptom screen",
        ],
        "follow_up_days": [7, 14, 28, 60, 90, 150, 180], "reporting_threshold": 1,
    },
    "acute_respiratory_infection": {
        "alert_level": "YELLOW", "who_idsr_code": "ARI",
        "immediate_actions": [
            "Identify high-risk groups (elderly, immunocompromised, under 5)",
            "Ensure adequate stock of amoxicillin at health facilities",
            "Issue community advisory on respiratory hygiene",
        ],
        "chw_actions": [
            "Screen all household contacts of confirmed cases",
            "Refer severe cases immediately",
            "Follow up at 3 and 7 days",
        ],
        "follow_up_days": [3, 7], "reporting_threshold": 10,
    },
    "acute_watery_diarrhea": {
        "alert_level": "YELLOW", "who_idsr_code": "AWD",
        "immediate_actions": [
            "Assess water and sanitation conditions in affected area",
            "Distribute ORS to households with children under 5",
            "Refer severe dehydration cases immediately",
        ],
        "chw_actions": [
            "Conduct WASH assessment in affected households",
            "Distribute ORS and zinc supplements",
            "Follow up all cases under 5 at 48 hours",
        ],
        "follow_up_days": [2, 5], "reporting_threshold": 5,
    },
}

def seed_protocols():
    logger.info("📋 Seeding protocols...")
    docs = []
    counties_to_seed = ["all"] + list(COUNTIES.keys())[:4]

    for syndrome, data in PROTOCOL_DATA.items():
        for county in counties_to_seed[:3]:  # seed 3 counties per syndrome
            protocol_id = f"PROTO-{syndrome.upper()[:6]}-{county[:3].upper()}-{datetime.utcnow().strftime('%Y%m%d')}"
            doc = {
                "protocol_id":         protocol_id,
                "syndrome":            syndrome,
                "county":              county,
                "alert_level":         data["alert_level"],
                "immediate_actions":   data["immediate_actions"],
                "chw_actions":         data["chw_actions"],
                "follow_up_days":      data["follow_up_days"],
                "reporting_threshold": data["reporting_threshold"],
                "who_idsr_code":       data["who_idsr_code"],
                "source_authority":    random.choice(["WHO", "MOH Kenya", "CDC", "TEMPLATE"]),
                "sources_consulted":   [
                    "WHO IDSR Technical Guidelines 4th Edition (2022)",
                    "Kenya MoH Integrated Management of Acute Malnutrition (2023)",
                    "CDC Emergency Response Guidelines",
                ],
                "research_summary":    f"Protocol for {syndrome.replace('_',' ')} based on WHO IDSR and Kenya MOH guidelines.",
                "created_at":          days_ago(random.randint(0, 30)).isoformat(),
                "status":              "active",
                "version":             random.randint(1, 3),
            }
            docs.append(doc)

    db.protocols.delete_many({})
    for doc in docs:
        try:
            db.protocols.update_one(
                {"syndrome": doc["syndrome"], "county": doc["county"]},
                {"$set": doc, "$setOnInsert": {"first_created": datetime.utcnow().isoformat()}},
                upsert=True,
            )
        except Exception:
            pass
    logger.info("  ✅ Inserted %d protocols", len(docs))

# ═══════════════════════════════════════════════════════════════════
# 8. REFERRALS
# ═══════════════════════════════════════════════════════════════════

def seed_referrals():
    logger.info("🚑 Seeding referrals...")
    docs = []
    red_yellow = list(db.encounters.find(
        {"extracted.triage_color": {"$in": ["RED", "YELLOW"]}}, {"_id": 0}
    ).limit(25))

    for enc in red_yellow:
        extracted = enc.get("extracted", {})
        admin = enc.get("admin_hierarchy", {})
        county = admin.get("county", "Nairobi")
        facility = FACILITIES.get(county, [{"name": "County Hospital", "eta_minutes": 20}])[0]

        doc = {
            "referral_id":    f"REF-{rnd_hex(8)}",
            "encounter_id":   enc.get("encounter_id"),
            "timestamp":      enc.get("timestamp", datetime.utcnow()),
            "status":         random.choice(["pending", "accepted", "completed", "redirected"]),
            "triage_color":   extracted.get("triage_color"),
            "syndrome":       extracted.get("syndrome"),
            "chief_complaint": extracted.get("chief_complaint", ""),
            "patient": {
                "age": extracted.get("age"),
                "sex": extracted.get("sex"),
            },
            "location": {
                "county":    county,
                "sub_county": county,
                "ward":      admin.get("ward", "Unknown"),
                "coordinates": enc.get("location", {}).get("coordinates"),
            },
            "nearest_facility": {
                "name":        facility["name"],
                "eta_minutes": facility["eta_minutes"],
            },
            "all_facilities": FACILITIES.get(county, []),
            "chw_id":         enc.get("chw_id"),
        }
        docs.append(doc)

    if docs:
        db.referrals.delete_many({})
        db.referrals.insert_many(docs)
        try:
            db.referrals.create_index([("encounter_id", ASCENDING)])
            db.referrals.create_index([("location.county", ASCENDING), ("status", ASCENDING)])
        except Exception:
            pass
    logger.info("  ✅ Inserted %d referrals", len(docs))

# ═══════════════════════════════════════════════════════════════════
# 9. AGENT LOGS (intake + pipeline processing)
# ═══════════════════════════════════════════════════════════════════

def seed_agent_logs():
    logger.info("📝 Seeding agent logs...")
    docs = []
    agents = ["Intake Agent", "Geo Agent", "Data Agent", "Surveillance Agent", "Contact Tracing Agent"]
    steps  = ["INTAKE", "LANGUAGE", "EXTRACTION", "GEO", "STORING", "SURVEILLANCE", "CONTACT_TRACE"]
    levels = ["INFO", "SUCCESS", "WARNING", "ERROR"]
    level_weights = [70, 20, 8, 2]

    for i in range(200):
        agent = random.choice(agents)
        step  = random.choice(steps)
        level = random.choices(levels, weights=level_weights)[0]
        enc_id = random.choice(encounter_ids) if encounter_ids else f"ENC-{rnd_hex(8)}"
        ts = hours_ago(random.randint(0, 720))

        messages = {
            ("Intake Agent",          "INTAKE"):       "📋 Received web form submission",
            ("Intake Agent",          "LANGUAGE"):     "🌍 Language detected: Swahili (confidence: 94%)",
            ("Intake Agent",          "EXTRACTION"):   "✅ Clinical extraction complete — syndrome: cholera, triage: RED",
            ("Geo Agent",             "GEO"):          "📍 Location enriched: Kasipul ward, Homa Bay",
            ("Data Agent",            "STORING"):      "💾 Encounter stored: embedding 1024 dims",
            ("Surveillance Agent",    "SURVEILLANCE"): "🔍 Outbreak detection: 3 alerts detected in Homa Bay",
            ("Contact Tracing Agent", "CONTACT_TRACE"): "🔗 Trace initiated: 8 contacts identified",
        }
        msg = messages.get((agent, step), f"{step} processing completed for session {enc_id[:12]}")

        doc = {
            "log_id":     f"LOG-{rnd_hex(8)}",
            "agent":      agent,
            "step":       step,
            "level":      level,
            "message":    msg,
            "session_id": enc_id,
            "timestamp":  ts,
            "duration_ms": random.randint(50, 4000),
            "metadata": {
                "county":   random.choice(list(COUNTIES.keys())),
                "syndrome": random.choice(SYNDROMES),
            },
        }
        if level == "ERROR":
            doc["error"] = random.choice([
                "MongoDB connection timeout",
                "Voyage AI embedding quota exceeded",
                "Gemini API rate limit — retrying",
                "GPS coordinates missing — using county centroid",
            ])
        docs.append(doc)

    db.agent_logs.delete_many({})
    db.agent_logs.insert_many(docs)
    logger.info("  ✅ Inserted %d agent logs", len(docs))

# ═══════════════════════════════════════════════════════════════════
# 10. WORKFLOW STATES
# ═══════════════════════════════════════════════════════════════════

def seed_workflow_states():
    logger.info("⚙️  Seeding workflow states...")
    docs = []
    states = ["COMPLETE", "COMPLETE", "COMPLETE", "COMPLETE", "DECISION_GATE",
              "OFFLINE_QUEUED", "FAILED", "NOTIFYING"]

    for i, enc_id in enumerate(encounter_ids[:30]):
        state = random.choice(states)
        ts = days_ago(random.randint(0, 7))
        county = random.choice(list(COUNTIES.keys()))
        chw = random.choice(chw_ids) if chw_ids else f"CHW-{rnd_hex(6)}"

        history = [{"state": "PENDING",   "timestamp": ts.isoformat(), "note": "Created"}]
        for s in ["INTAKE", "GEO", "STORING", state]:
            ts += timedelta(minutes=random.randint(1, 5))
            history.append({"state": s, "timestamp": ts.isoformat(), "note": f"{s} completed"})

        doc = {
            "workflow_id":  enc_id,
            "session_id":   enc_id,
            "state":        state,
            "source":       random.choice(["telegram", "web_form", "audio"]),
            "chw_id":       chw,
            "county":       county,
            "created_at":   days_ago(random.randint(0, 7)).isoformat(),
            "updated_at":   ts.isoformat(),
            "history":      history,
            "data":         {"county": county, "syndrome": random.choice(SYNDROMES)},
            "errors":       [],
            "retries":      {},
        }
        if state == "FAILED":
            doc["errors"] = [{"error": "MongoDB timeout", "state": "STORING", "ts": ts.isoformat()}]
        docs.append(doc)

    db.workflow_states.delete_many({})
    db.workflow_states.insert_many(docs)
    try:
        db.workflow_states.create_index([("workflow_id", ASCENDING)], unique=True)
        db.workflow_states.create_index([("state", ASCENDING), ("updated_at", DESCENDING)])
    except Exception:
        pass
    logger.info("  ✅ Inserted %d workflow states", len(docs))

# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    logger.info("=" * 60)
    logger.info("  SihaLink Test Data Seeder")
    logger.info("=" * 60)

    seed_chws()
    seed_encounters()
    seed_baselines()
    seed_alerts()
    seed_follow_ups()
    seed_contact_traces()
    seed_protocols()
    seed_referrals()
    seed_agent_logs()
    seed_workflow_states()

    # ── Summary ───────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info("  ✅ Seed complete — collection counts:")
    for col in ["chws", "encounters", "alerts", "baselines", "follow_ups",
                "contact_traces", "protocols", "referrals", "agent_logs", "workflow_states"]:
        count = db[col].count_documents({})
        logger.info("     %-20s %d documents", col, count)
    logger.info("=" * 60)

    client.close()

if __name__ == "__main__":
    main()
