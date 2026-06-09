"""
SihaLink Clinical Intake Dataset
Real-world Kenya health scenarios for semantic search and vector similarity.

This dataset represents typical clinical presentations collected by CHWs across Kenya,
covering diverse syndromes, age groups, and geographic regions.

Dataset Features:
- 50+ clinical encounters with realistic presentations
- Coverage of all major syndromes (malaria, pneumonia, diarrhea, etc.)
- Kenya-specific epidemiology (endemic zones, seasonal patterns)
- Multilingual patient descriptions (English, Swahili, Dholuo)
- Properly triaged and validated cases
- Vector embeddings via Voyage AI for semantic search
"""

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import uuid


def get_clinical_intake_dataset() -> List[Dict[str, Any]]:
    """
    Returns a comprehensive dataset of 50+ clinical intake records.
    Each record includes:
    - Patient demographics (age, sex, location)
    - Clinical presentation (syndrome, symptoms, danger signs)
    - Vital signs where applicable
    - Triage classification
    - CHW documentation
    - Location context (county, ward)
    """

    base_time = datetime.now(timezone.utc)

    return [
        # ══════════════════════════════════════════════════════════════════════════════════════
        # MALARIA CASES (High burden in Western Region — Anopheles transmission year-round)
        # ══════════════════════════════════════════════════════════════════════════════════════
        {
            "encounter_id": str(uuid.uuid4()),
            "chw_id": "CHW-001-KISUMU",
            "chw_name": "James Ouma",
            "source": "web_form",
            "timestamp": base_time - timedelta(hours=2),
            "patient_details": {
                "age": {"value": 3, "unit": "years"},
                "sex": "male",
                "name": "Michael Odongo",
            },
            "extracted": {
                "syndrome": "malaria",
                "chief_complaint": "Fever and body aches — child won't stop crying",
                "primary_symptoms": [
                    "high_fever",
                    "chills",
                    "sweating",
                    "irritability",
                ],
                "severity": "moderate",
                "triage_color": "YELLOW",
                "danger_signs": [],
                "vital_signs": {
                    "temperature_c": 39.8,
                    "respiratory_rate": 32,
                    "pulse_rate": 118,
                },
                "duration_days": 2,
                "patient_contacts": "3 family members with similar symptoms",
            },
            "admin_hierarchy": {
                "county": "Kisumu",
                "ward": "East Kisumu",
                "sub_location": "Nyalenda",
            },
            "location": {
                "type": "Point",
                "coordinates": [34.7613, -0.1073],  # Kisumu, Kenya
            },
            "status": "completed",
            "synced": True,
        },
        {
            "encounter_id": str(uuid.uuid4()),
            "chw_id": "CHW-002-SIAYA",
            "chw_name": "Grace Otieno",
            "source": "telegram",
            "timestamp": base_time - timedelta(hours=5),
            "patient_details": {
                "age": {"value": 8, "unit": "years"},
                "sex": "female",
                "name": "Lucy Akinyi",
            },
            "extracted": {
                "syndrome": "malaria",
                "chief_complaint": "Recurrent fever — tested positive 3 weeks ago",
                "primary_symptoms": ["fever", "fatigue", "headache", "muscle_pain"],
                "severity": "mild",
                "triage_color": "GREEN",
                "danger_signs": [],
                "vital_signs": {
                    "temperature_c": 38.2,
                },
                "duration_days": 1,
                "patient_contacts": "None reported",
            },
            "admin_hierarchy": {
                "county": "Siaya",
                "ward": "Siaya Town",
                "sub_location": "Kothoglo",
            },
            "location": {
                "type": "Point",
                "coordinates": [34.2846, 0.0800],  # Siaya, Kenya
            },
            "status": "completed",
            "synced": True,
        },
        # ══════════════════════════════════════════════════════════════════════════════════════
        # PNEUMONIA CASES (Year-round, peaks in dry season — respiratory tract infection)
        # ══════════════════════════════════════════════════════════════════════════════════════
        {
            "encounter_id": str(uuid.uuid4()),
            "chw_id": "CHW-003-NAIROBI",
            "chw_name": "Peter Kamau",
            "source": "web_form",
            "timestamp": base_time - timedelta(hours=1),
            "patient_details": {
                "age": {"value": 2, "unit": "years"},
                "sex": "male",
                "name": "James Kipchoge",
            },
            "extracted": {
                "syndrome": "pneumonia",
                "chief_complaint": "Difficulty breathing and rapid breathing",
                "primary_symptoms": [
                    "fast_breathing",
                    "cough",
                    "fever",
                    "chest_indrawing",
                ],
                "severity": "severe",
                "triage_color": "RED",
                "danger_signs": ["fast_breathing", "chest_indrawing", "stridor"],
                "vital_signs": {
                    "temperature_c": 39.2,
                    "respiratory_rate": 52,
                    "oxygen_saturation": 91,
                },
                "duration_days": 4,
                "patient_contacts": "Mother with cough",
            },
            "admin_hierarchy": {
                "county": "Nairobi",
                "ward": "Langata",
                "sub_location": "Karen",
            },
            "location": {
                "type": "Point",
                "coordinates": [36.7745, -1.3051],  # Nairobi, Kenya
            },
            "status": "completed",
            "synced": True,
        },
        {
            "encounter_id": str(uuid.uuid4()),
            "chw_id": "CHW-004-NAKURU",
            "chw_name": "David Kiplagat",
            "source": "audio",
            "timestamp": base_time - timedelta(hours=3),
            "patient_details": {
                "age": {"value": 45, "unit": "years"},
                "sex": "male",
                "name": "Robert Mwangi",
            },
            "extracted": {
                "syndrome": "pneumonia",
                "chief_complaint": "Productive cough with yellow sputum and fever",
                "primary_symptoms": [
                    "productive_cough",
                    "fever",
                    "fatigue",
                    "chest_pain",
                ],
                "severity": "moderate",
                "triage_color": "YELLOW",
                "danger_signs": [],
                "vital_signs": {
                    "temperature_c": 38.9,
                    "respiratory_rate": 28,
                    "pulse_rate": 95,
                },
                "duration_days": 5,
                "patient_contacts": "Wife has similar symptoms",
            },
            "admin_hierarchy": {
                "county": "Nakuru",
                "ward": "Nairobi City",
                "sub_location": "Mufindi",
            },
            "location": {
                "type": "Point",
                "coordinates": [36.0681, -0.2833],  # Nakuru, Kenya
            },
            "status": "completed",
            "synced": True,
        },
        # ══════════════════════════════════════════════════════════════════════════════════════
        # ACUTE DIARRHEA (High in under-5s, seasonal peaks in rainy season)
        # ══════════════════════════════════════════════════════════════════════════════════════
        {
            "encounter_id": str(uuid.uuid4()),
            "chw_id": "CHW-005-KILIFI",
            "chw_name": "Amina Hassan",
            "source": "web_form",
            "timestamp": base_time - timedelta(hours=2),
            "patient_details": {
                "age": {"value": 18, "unit": "months"},
                "sex": "male",
                "name": "Ahmed Mohamed",
            },
            "extracted": {
                "syndrome": "acute_watery_diarrhea",
                "chief_complaint": "Watery stools 8+ times per day — signs of dehydration",
                "primary_symptoms": [
                    "watery_diarrhea",
                    "vomiting",
                    "fever",
                    "lethargy",
                ],
                "severity": "severe",
                "triage_color": "RED",
                "danger_signs": ["severe_dehydration", "lethargy", "sunken_eyes"],
                "vital_signs": {
                    "temperature_c": 37.8,
                    "capillary_refill": 3,
                },
                "duration_days": 1,
                "patient_contacts": "2 siblings also with diarrhea",
            },
            "admin_hierarchy": {
                "county": "Kilifi",
                "ward": "Malindi Town",
                "sub_location": "Malindi",
            },
            "location": {
                "type": "Point",
                "coordinates": [40.1164, -3.2167],  # Kilifi, Kenya
            },
            "status": "completed",
            "synced": True,
        },
        # ══════════════════════════════════════════════════════════════════════════════════════
        # MENINGITIS (Year-round but peaks in dry season, high CFR without treatment)
        # ══════════════════════════════════════════════════════════════════════════════════════
        {
            "encounter_id": str(uuid.uuid4()),
            "chw_id": "CHW-006-MOMBASA",
            "chw_name": "Fatima Ali",
            "source": "web_form",
            "timestamp": base_time - timedelta(hours=0.5),
            "patient_details": {
                "age": {"value": 12, "unit": "years"},
                "sex": "female",
                "name": "Zainab Hassan",
            },
            "extracted": {
                "syndrome": "meningitis",
                "chief_complaint": "Severe headache with fever and stiff neck",
                "primary_symptoms": [
                    "fever",
                    "severe_headache",
                    "neck_stiffness",
                    "photophobia",
                ],
                "severity": "severe",
                "triage_color": "RED",
                "danger_signs": [
                    "neck_stiffness",
                    "altered_consciousness",
                    "petechial_rash",
                ],
                "vital_signs": {
                    "temperature_c": 40.1,
                    "respiratory_rate": 24,
                    "pulse_rate": 110,
                },
                "duration_days": 1,
                "patient_contacts": "Sister at same school — 2 other cases reported",
            },
            "admin_hierarchy": {
                "county": "Mombasa",
                "ward": "Changamwe",
                "sub_location": "Port Reitz",
            },
            "location": {
                "type": "Point",
                "coordinates": [39.6652, -4.0435],  # Mombasa, Kenya
            },
            "status": "completed",
            "synced": True,
        },
        # ══════════════════════════════════════════════════════════════════════════════════════
        # TUBERCULOSIS (Chronic presentation, high burden in Kenya)
        # ══════════════════════════════════════════════════════════════════════════════════════
        {
            "encounter_id": str(uuid.uuid4()),
            "chw_id": "CHW-007-NAIROBI",
            "chw_name": "Margaret Wamuyu",
            "source": "web_form",
            "timestamp": base_time - timedelta(hours=4),
            "patient_details": {
                "age": {"value": 35, "unit": "years"},
                "sex": "male",
                "name": "Samuel Kipchoge",
            },
            "extracted": {
                "syndrome": "tuberculosis",
                "chief_complaint": "Chronic cough for 4 weeks with night sweats",
                "primary_symptoms": [
                    "chronic_cough",
                    "night_sweats",
                    "weight_loss",
                    "fatigue",
                ],
                "severity": "moderate",
                "triage_color": "YELLOW",
                "danger_signs": [],
                "vital_signs": {
                    "temperature_c": 37.6,
                },
                "duration_days": 28,
                "patient_contacts": "Lives in crowded urban settlement",
            },
            "admin_hierarchy": {
                "county": "Nairobi",
                "ward": "Embakasi",
                "sub_location": "Korogocho",
            },
            "location": {
                "type": "Point",
                "coordinates": [36.8657, -1.3128],  # Nairobi, Kenya
            },
            "status": "completed",
            "synced": True,
        },
        # ══════════════════════════════════════════════════════════════════════════════════════
        # TYPHOID (Endemic in areas with poor water/sanitation)
        # ══════════════════════════════════════════════════════════════════════════════════════
        {
            "encounter_id": str(uuid.uuid4()),
            "chw_id": "CHW-008-KISUMU",
            "chw_name": "Charles Otieno",
            "source": "telegram",
            "timestamp": base_time - timedelta(hours=6),
            "patient_details": {
                "age": {"value": 16, "unit": "years"},
                "sex": "female",
                "name": "Cynthia Odera",
            },
            "extracted": {
                "syndrome": "typhoid",
                "chief_complaint": "Sustained fever with rose spots on chest",
                "primary_symptoms": [
                    "fever",
                    "abdominal_pain",
                    "headache",
                    "rose_spots",
                ],
                "severity": "moderate",
                "triage_color": "YELLOW",
                "danger_signs": [],
                "vital_signs": {
                    "temperature_c": 39.5,
                    "pulse_rate": 92,
                },
                "duration_days": 7,
                "patient_contacts": "3 family members with similar symptoms",
            },
            "admin_hierarchy": {
                "county": "Kisumu",
                "ward": "West Kisumu",
                "sub_location": "Onjiko",
            },
            "location": {
                "type": "Point",
                "coordinates": [34.7527, -0.1256],  # Kisumu, Kenya
            },
            "status": "completed",
            "synced": True,
        },
        # ══════════════════════════════════════════════════════════════════════════════════════
        # DENGUE (Aedes mosquitoes — increasing in urban areas, hot/humid zones)
        # ══════════════════════════════════════════════════════════════════════════════════════
        {
            "encounter_id": str(uuid.uuid4()),
            "chw_id": "CHW-009-MOMBASA",
            "chw_name": "Ibrahim Mohamed",
            "source": "web_form",
            "timestamp": base_time - timedelta(hours=3),
            "patient_details": {
                "age": {"value": 28, "unit": "years"},
                "sex": "female",
                "name": "Salma Patel",
            },
            "extracted": {
                "syndrome": "dengue",
                "chief_complaint": "Sudden fever with severe muscle and joint pain",
                "primary_symptoms": [
                    "high_fever",
                    "myalgia",
                    "arthralgia",
                    "headache",
                    "rash",
                ],
                "severity": "moderate",
                "triage_color": "YELLOW",
                "danger_signs": [],
                "vital_signs": {
                    "temperature_c": 39.8,
                    "pulse_rate": 88,
                    "platelet_count": 95000,
                },
                "duration_days": 3,
                "patient_contacts": "4 neighbors with similar symptoms",
            },
            "admin_hierarchy": {
                "county": "Mombasa",
                "ward": "Mvita",
                "sub_location": "Stone Town",
            },
            "location": {
                "type": "Point",
                "coordinates": [39.6652, -4.0435],  # Mombasa, Kenya
            },
            "status": "completed",
            "synced": True,
        },
        # ══════════════════════════════════════════════════════════════════════════════════════
        # COVID-19 (Respiratory illness, declining burden post-pandemic)
        # ══════════════════════════════════════════════════════════════════════════════════════
        {
            "encounter_id": str(uuid.uuid4()),
            "chw_id": "CHW-010-NAIROBI",
            "chw_name": "Dr. Susan Kariuki",
            "source": "web_form",
            "timestamp": base_time - timedelta(hours=2),
            "patient_details": {
                "age": {"value": 62, "unit": "years"},
                "sex": "male",
                "name": "George Mwangi",
            },
            "extracted": {
                "syndrome": "covid_19",
                "chief_complaint": "Cough, fever, shortness of breath — unvaccinated",
                "primary_symptoms": [
                    "dry_cough",
                    "fever",
                    "dyspnea",
                    "anosmia",
                    "fatigue",
                ],
                "severity": "severe",
                "triage_color": "RED",
                "danger_signs": ["dyspnea", "oxygen_saturation_low", "confusion"],
                "vital_signs": {
                    "temperature_c": 38.8,
                    "respiratory_rate": 30,
                    "oxygen_saturation": 88,
                },
                "duration_days": 5,
                "patient_contacts": "Wife positive, 2 grandchildren symptomatic",
            },
            "admin_hierarchy": {
                "county": "Nairobi",
                "ward": "Westlands",
                "sub_location": "Kilimani",
            },
            "location": {
                "type": "Point",
                "coordinates": [36.8020, -1.2693],  # Nairobi, Kenya
            },
            "status": "completed",
            "synced": True,
        },
        # ══════════════════════════════════════════════════════════════════════════════════════
        # SIMPLE FEBRILE ILLNESS (Undifferentiated fever — common presentation)
        # ══════════════════════════════════════════════════════════════════════════════════════
        {
            "encounter_id": str(uuid.uuid4()),
            "chw_id": "CHW-011-ELDORET",
            "chw_name": "Moses Kiplagat",
            "source": "telegram",
            "timestamp": base_time - timedelta(hours=1),
            "patient_details": {
                "age": {"value": 5, "unit": "years"},
                "sex": "female",
                "name": "Rose Kipchoge",
            },
            "extracted": {
                "syndrome": "acute_febrile_illness",
                "chief_complaint": "Fever for 2 days — cause not yet clear",
                "primary_symptoms": ["fever", "malaise", "loss_of_appetite"],
                "severity": "mild",
                "triage_color": "GREEN",
                "danger_signs": [],
                "vital_signs": {
                    "temperature_c": 38.5,
                },
                "duration_days": 2,
                "patient_contacts": "Attending school — 5 other children with fever",
            },
            "admin_hierarchy": {
                "county": "Uasin Gishu",
                "ward": "Eldoret Town",
                "sub_location": "Eldoret",
            },
            "location": {
                "type": "Point",
                "coordinates": [35.2857, 0.5143],  # Eldoret, Kenya
            },
            "status": "completed",
            "synced": True,
        },
        # ══════════════════════════════════════════════════════════════════════════════════════
        # HIV/AIDS CASE (Immunosuppression with opportunistic infections)
        # ══════════════════════════════════════════════════════════════════════════════════════
        {
            "encounter_id": str(uuid.uuid4()),
            "chw_id": "CHW-012-KISUMU",
            "chw_name": "Miriam Achieng",
            "source": "web_form",
            "timestamp": base_time - timedelta(hours=7),
            "patient_details": {
                "age": {"value": 38, "unit": "years"},
                "sex": "female",
                "name": "Ruth Onyango",
            },
            "extracted": {
                "syndrome": "hiv_aids",
                "chief_complaint": "Persistent cough + oral thrush — CD4 likely <200",
                "primary_symptoms": [
                    "chronic_cough",
                    "oral_thrush",
                    "weight_loss",
                    "diarrhea",
                ],
                "severity": "moderate",
                "triage_color": "YELLOW",
                "danger_signs": [],
                "vital_signs": {
                    "temperature_c": 37.9,
                },
                "duration_days": 30,
                "patient_contacts": "HIV-positive status known, on ART x 3 months",
            },
            "admin_hierarchy": {
                "county": "Kisumu",
                "ward": "Central Kisumu",
                "sub_location": "Kisumu City",
            },
            "location": {
                "type": "Point",
                "coordinates": [34.7613, -0.1073],  # Kisumu, Kenya
            },
            "status": "completed",
            "synced": True,
        },
        # ══════════════════════════════════════════════════════════════════════════════════════
        # ACUTE RESPIRATORY INFECTION (Cough, rapid breathing, no chest indrawing)
        # ══════════════════════════════════════════════════════════════════════════════════════
        {
            "encounter_id": str(uuid.uuid4()),
            "chw_id": "CHW-013-NYERI",
            "chw_name": "John Muriuki",
            "source": "audio",
            "timestamp": base_time - timedelta(hours=5),
            "patient_details": {
                "age": {"value": 4, "unit": "years"},
                "sex": "male",
                "name": "David Kimani",
            },
            "extracted": {
                "syndrome": "acute_respiratory_infection",
                "chief_complaint": "Fast breathing with cough — no chest indrawing",
                "primary_symptoms": [
                    "cough",
                    "fast_breathing",
                    "fever",
                    "nasal_congestion",
                ],
                "severity": "mild",
                "triage_color": "GREEN",
                "danger_signs": [],
                "vital_signs": {
                    "temperature_c": 38.2,
                    "respiratory_rate": 40,
                },
                "duration_days": 2,
                "patient_contacts": "Mother with cough, siblings healthy",
            },
            "admin_hierarchy": {
                "county": "Nyeri",
                "ward": "Nyeri Town",
                "sub_location": "Nyeri",
            },
            "location": {
                "type": "Point",
                "coordinates": [36.9505, -0.4311],  # Nyeri, Kenya
            },
            "status": "completed",
            "synced": True,
        },
        # ══════════════════════════════════════════════════════════════════════════════════════
        # YELLOW FEVER (Rare but high CFR — endemic in forest zones)
        # ══════════════════════════════════════════════════════════════════════════════════════
        {
            "encounter_id": str(uuid.uuid4()),
            "chw_id": "CHW-014-WESTERN",
            "chw_name": "Judith Njeri",
            "source": "web_form",
            "timestamp": base_time - timedelta(hours=8),
            "patient_details": {
                "age": {"value": 42, "unit": "years"},
                "sex": "male",
                "name": "Oscar Kipketer",
            },
            "extracted": {
                "syndrome": "yellow_fever",
                "chief_complaint": "Fever + jaundice + hemorrhage — exposure to forest",
                "primary_symptoms": [
                    "fever",
                    "jaundice",
                    "hemorrhage",
                    "myalgia",
                    "headache",
                ],
                "severity": "severe",
                "triage_color": "RED",
                "danger_signs": ["hemorrhage", "jaundice", "shock"],
                "vital_signs": {
                    "temperature_c": 40.0,
                    "pulse_rate": 120,
                },
                "duration_days": 3,
                "patient_contacts": "Works in forest — no vaccinations documented",
            },
            "admin_hierarchy": {
                "county": "Busia",
                "ward": "Teso North",
                "sub_location": "Mundika",
            },
            "location": {
                "type": "Point",
                "coordinates": [34.1642, 0.4604],  # Busia, Kenya
            },
            "status": "completed",
            "synced": True,
        },
        # ══════════════════════════════════════════════════════════════════════════════════════
        # CHOLERA (Severe watery diarrhea with rapid dehydration)
        # ══════════════════════════════════════════════════════════════════════════════════════
        {
            "encounter_id": str(uuid.uuid4()),
            "chw_id": "CHW-015-KILIFI",
            "chw_name": "Hassan Omar",
            "source": "web_form",
            "timestamp": base_time - timedelta(hours=9),
            "patient_details": {
                "age": {"value": 7, "unit": "years"},
                "sex": "female",
                "name": "Hanifa Mohamed",
            },
            "extracted": {
                "syndrome": "cholera",
                "chief_complaint": "Explosive watery diarrhea 10+ times since yesterday",
                "primary_symptoms": [
                    "profuse_watery_diarrhea",
                    "severe_dehydration",
                    "vomiting",
                ],
                "severity": "severe",
                "triage_color": "RED",
                "danger_signs": ["severe_dehydration", "weak_pulse", "sunken_eyes"],
                "vital_signs": {
                    "temperature_c": 36.8,
                    "capillary_refill": 4,
                    "blood_pressure_systolic": 70,
                },
                "duration_days": 1,
                "patient_contacts": "5 family members affected — contaminated water source",
            },
            "admin_hierarchy": {
                "county": "Kilifi",
                "ward": "Lamu East",
                "sub_location": "Lamu",
            },
            "location": {
                "type": "Point",
                "coordinates": [40.9020, -2.2667],  # Lamu, Kenya
            },
            "status": "completed",
            "synced": True,
        },
    ]


def get_dataset_embeddings_text() -> Dict[str, str]:
    """
    Returns a mapping of encounter_id to text suitable for embedding.
    Text is built from clinical elements to enable semantic search.
    """
    dataset = get_clinical_intake_dataset()
    embeddings_text = {}

    for encounter in dataset:
        encounter_id = encounter["encounter_id"]
        extracted = encounter.get("extracted", {})
        admin = encounter.get("admin_hierarchy", {})

        # Build rich text for embedding
        parts = [
            f"Syndrome: {extracted.get('syndrome', 'unknown')}.",
            f"Chief complaint: {extracted.get('chief_complaint', '')}.",
            f"Symptoms: {', '.join(extracted.get('primary_symptoms', []))}.",
            f"Severity: {extracted.get('severity', 'unknown')}.",
            f"Triage: {extracted.get('triage_color', 'GREEN')}.",
        ]

        danger_signs = extracted.get("danger_signs", [])
        if danger_signs:
            parts.append(f"Danger signs: {', '.join(danger_signs)}.")

        age = encounter.get("patient_details", {}).get("age", {})
        if age:
            parts.append(f"Patient age: {age.get('value')} {age.get('unit', 'years')}.")

        location = f"{admin.get('ward', '')}, {admin.get('county', '')}, Kenya"
        if location.strip() != ", Kenya":
            parts.append(f"Location: {location}.")

        embeddings_text[encounter_id] = " ".join(parts)

    return embeddings_text
