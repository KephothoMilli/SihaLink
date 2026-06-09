import json
import os
import random
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from pymongo import MongoClient
import uuid

load_dotenv()
MONGODB_URI = os.getenv("MONGODB_ATLAS_URI")

COUNTIES = ["Nairobi", "Mombasa", "Kisumu", "Homa Bay", "Kiambu"]
WARDS = {
    "Nairobi": ["Kibera", "Mathare", "Kawangware"],
    "Mombasa": ["Nyali", "Kisauni", "Likoni"],
    "Kisumu": ["Nyalenda", "Obunga", "Manyatta"],
    "Homa Bay": ["Karachuonyo", "Ndhiwa", "Rangwe"],
    "Kiambu": ["Ruaka", "Kikuyu", "Thika"]
}

SYNDROMES = [
    "acute_watery_diarrhea", "acute_respiratory_infection", 
    "acute_febrile_illness", "malaria", "cholera", "measles"
]

SYMPTOMS = [
    "fever", "cough", "diarrhea", "vomiting", "headache",
    "fatigue", "muscle_pain", "difficulty_breathing", "rash"
]

FACILITIES = [
    {"name": "Kenyatta National Hospital", "county": "Nairobi", "lat": -1.3005, "lng": 36.8078},
    {"name": "Coast General Hospital", "county": "Mombasa", "lat": -4.0500, "lng": 39.6667},
    {"name": "JOOTRH", "county": "Kisumu", "lat": -0.1022, "lng": 34.7617},
    {"name": "Homa Bay Referral", "county": "Homa Bay", "lat": -0.5273, "lng": 34.4539},
    {"name": "Kiambu Level 5", "county": "Kiambu", "lat": -1.1714, "lng": 36.8356}
]

def generate_chws():
    chws = []
    # Ensure at least one CHW per ward
    for county, wards in WARDS.items():
        for ward in wards:
            for _ in range(2): # 2 CHWs per ward = 30 total
                chw_id = f"CHW-{uuid.uuid4().hex[:6].upper()}"
                chws.append({
                    "chw_id": chw_id,
                    "name": f"CHW {random.randint(100, 999)}",
                    "county": county,
                    "ward": ward,
                    "telegram_id": random.randint(100000000, 999999999),
                    "phone": f"+2547{random.randint(10000000, 99999999)}",
                    "languages": ["Swahili", "English"],
                    "status": "active",
                    "registered_at": datetime.now(timezone.utc) - timedelta(days=60),
                    "last_active": datetime.now(timezone.utc)
                })
    return chws

def generate_protocols():
    return [
        {
            "protocol_id": "PROTO-CHOLERA-ALL-1",
            "syndrome": "cholera",
            "county": "all",
            "alert_level": "RED",
            "immediate_actions": ["Activate county cholera task force", "Deploy ORS"],
            "chw_actions": ["Conduct household visits", "Distribute ORS", "Record cases"],
            "follow_up_days": [1, 2, 7],
            "reporting_threshold": 1,
            "status": "active",
            "created_at": datetime.now(timezone.utc) - timedelta(days=30)
        },
        {
            "protocol_id": "PROTO-MEASLES-ALL-1",
            "syndrome": "measles",
            "county": "all",
            "alert_level": "YELLOW",
            "immediate_actions": ["Verify diagnosis", "Activate vaccination plan"],
            "chw_actions": ["Map unvaccinated children", "Record cases"],
            "follow_up_days": [7, 14],
            "reporting_threshold": 1,
            "status": "active",
            "created_at": datetime.now(timezone.utc) - timedelta(days=30)
        }
    ]

def _make_encounter(chws, county, ward, syndrome, triage, timestamp):
    chw = random.choice([c for c in chws if c["county"] == county and c["ward"] == ward])
    facility = next(f for f in FACILITIES if f["county"] == county)
    encounter_id = f"ENC-{uuid.uuid4().hex[:8].upper()}"
    return {
        "encounter_id": encounter_id,
        "session_id": f"sim-{uuid.uuid4()}",
        "chw_id": chw["chw_id"],
        "timestamp": timestamp,
        "extracted": {
            "syndrome": syndrome,
            "triage_color": triage,
            "symptoms": random.sample(SYMPTOMS, k=2),
            "chief_complaint": "Simulated complaint",
            "age": random.randint(1, 60),
            "sex": random.choice(["male", "female"]),
        },
        "location": {
            "type": "Point",
            "coordinates": [facility["lng"] + random.uniform(-0.02, 0.02), facility["lat"] + random.uniform(-0.02, 0.02)]
        },
        "admin_hierarchy": {
            "county": county,
            "ward": ward,
            "country": "Kenya"
        },
        "nearest_facilities": [facility],
        "synced": True
    }

def generate_encounters(chws):
    encounters = []
    now = datetime.now(timezone.utc)
    
    # 1. Background noise (500 cases over 30 days)
    for _ in range(500):
        county = random.choice(COUNTIES)
        ward = random.choice(WARDS[county])
        
        # Test CHW gap detection: Ndhiwa gets 0 cases in last 7 days
        if ward == "Ndhiwa":
            timestamp = now - timedelta(days=random.randint(8, 30))
        else:
            timestamp = now - timedelta(days=random.randint(0, 30), hours=random.randint(0, 23))
            
        encounters.append(_make_encounter(
            chws, county, ward, 
            random.choice(SYNDROMES), 
            random.choice(["GREEN", "GREEN", "YELLOW", "RED"]), 
            timestamp
        ))
        
    # 2. Outbreak Cluster (Cholera in Kisumu -> Manyatta in last 48 hours)
    for _ in range(15):
        timestamp = now - timedelta(hours=random.randint(1, 48))
        encounters.append(_make_encounter(chws, "Kisumu", "Manyatta", "cholera", "RED", timestamp))
        
    # 3. Cross-County Spread (Measles rising in 3 counties in last 3 days)
    for county in ["Nairobi", "Mombasa", "Kiambu"]:
        for _ in range(8):
            ward = random.choice(WARDS[county])
            timestamp = now - timedelta(days=random.randint(0, 3))
            encounters.append(_make_encounter(chws, county, ward, "measles", "YELLOW", timestamp))
            
    # 4. Silent Pandemic Trend (ARI in Nairobi growing week over week for 4 weeks)
    for week in range(4):
        # Week 0 (4 weeks ago) -> 5 cases, Week 1 -> 10, Week 2 -> 15, Week 3 (now) -> 25
        cases = 5 + (week * 5) + (5 if week == 3 else 0)
        for _ in range(cases):
            timestamp = now - timedelta(days=(3-week)*7 + random.randint(0, 6))
            encounters.append(_make_encounter(chws, "Nairobi", random.choice(WARDS["Nairobi"]), "acute_respiratory_infection", "GREEN", timestamp))

    return encounters

def generate_alerts():
    now = datetime.now(timezone.utc)
    return [
        {
            "alert_id": f"Kisumu-cholera-Manyatta-{now.strftime('%Y%m%d%H')}",
            "alert_type": "spike",
            "syndrome": "cholera",
            "location": {"county": "Kisumu", "ward": "Manyatta"},
            "status": "active",
            "timestamp": now,
            "detected_at": now,
            "count": 15,
            "percent_above_baseline": 300
        },
        {
            "alert_id": f"spread-measles-{now.strftime('%Y%m%d%H')}",
            "alert_type": "cross_county_spread",
            "syndrome": "measles",
            "counties_affected": [
                {"county": "Nairobi", "count": 8},
                {"county": "Mombasa", "count": 8},
                {"county": "Kiambu", "count": 8}
            ],
            "escalation_level": "NATIONAL",
            "status": "active",
            "timestamp": now,
            "detected_at": now
        }
    ]

def main():
    print("Generating highly robust synthetic Kenya dataset...")
    
    chws = generate_chws()
    protocols = generate_protocols()
    encounters = generate_encounters(chws)
    alerts = generate_alerts()
    
    # We will let the background agents generate referrals and follow_ups dynamically,
    # or we can seed a few just to have dashboard data immediately.
    # To keep it reliable, we will seed some referrals for RED cases.
    referrals = []
    follow_ups = []
    contact_traces = []
    
    for enc in encounters:
        if enc["extracted"]["triage_color"] in ["RED", "YELLOW"] and random.random() > 0.5:
            referrals.append({
                "referral_id": f"REF-{uuid.uuid4().hex[:8].upper()}",
                "encounter_id": enc["encounter_id"],
                "chw_id": enc["chw_id"],
                "status": random.choice(["pending", "accepted", "completed"]),
                "timestamp": enc["timestamp"],
                "location": enc["admin_hierarchy"]
            })
            
        follow_ups.append({
            "follow_up_id": f"FU-{uuid.uuid4().hex[:8].upper()}",
            "encounter_id": enc["encounter_id"],
            "chw_id": enc["chw_id"],
            "county": enc["admin_hierarchy"]["county"],
            "status": random.choice(["pending", "completed"]),
            "due_date": enc["timestamp"] + timedelta(days=3),
            "created_at": enc["timestamp"]
        })

    data = {
        "chws": chws, "protocols": protocols, "encounters": encounters,
        "referrals": referrals, "follow_ups": follow_ups, "alerts": alerts
    }
    
    file_path = os.path.join(os.path.dirname(__file__), "..", "data", "seed_kenya_data.json")
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    
    if not MONGODB_URI:
        print("Skipping DB ingestion.")
        return

    print("Connected to MongoDB Atlas. Dropping collections to ensure fresh state...")
    client = MongoClient(MONGODB_URI)
    db = client.sihalink
    
    # Drop to ensure clean state
    for coll in ["chws", "protocols", "encounters", "referrals", "follow_ups", "alerts", "contact_traces", "baselines"]:
        db[coll].drop()
        
    print("Ingesting data...")
    if chws: db.chws.insert_many(chws)
    if protocols: db.protocols.insert_many(protocols)
    if encounters: db.encounters.insert_many(encounters)
    if referrals: db.referrals.insert_many(referrals)
    if follow_ups: db.follow_ups.insert_many(follow_ups)
    if alerts: db.alerts.insert_many(alerts)
    
    # Optional: We could run the update_baselines here manually via python code to prep it
    
    print("Data ingestion complete!")

if __name__ == "__main__":
    main()
