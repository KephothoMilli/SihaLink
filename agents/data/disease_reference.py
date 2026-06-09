"""
Disease Reference Database — Comprehensive clinical information for all supported diseases.

This module provides structured disease data including:
  - Clinical presentations (symptoms, signs, severity)
  - Case definitions (WHO/CDC standards)
  - Risk factors and epidemiology
  - Transmission patterns
  - Treatment guidance
  - Kenya-specific considerations
  - Triage algorithms
  - Follow-up protocols

Data used by:
  - Intake Agent (validation & correction)
  - Surveillance Agent (outbreak detection)
  - Protocol Research Agent (response strategies)
  - Data Agent (persistence & analytics)
"""

DISEASE_DATABASE = {
    # ══════════════════════════════════════════════════════════════════════════
    # VIRAL HEMORRHAGIC FEVERS
    # ══════════════════════════════════════════════════════════════════════════
    
    "ebola": {
        "name": "Ebola Virus Disease",
        "category": "viral_hemorrhagic_fever",
        "synonyms": ["EVD", "Ebola fever", "Ebola", "haemorrhagic fever"],
        "case_definition": {
            "suspected": "Acute onset fever + ≥2 symptoms: weakness, headache, muscle pain, vomiting, rash, bleeding",
            "probable": "Suspected + epidemiologic link to confirmed case",
            "confirmed": "Lab evidence: PCR, antigen detection, antibodies",
        },
        "clinical_features": {
            "onset": "2-21 days incubation",
            "early_symptoms": [
                "fever (>38.3°C)",
                "severe headache",
                "severe weakness/fatigue",
                "muscle pain",
                "diarrhea",
            ],
            "late_symptoms": [
                "bleeding (gums, nose, GI)",
                "hemorrhagic rash",
                "vomiting blood",
                "internal bleeding",
                "multi-organ failure",
            ],
        },
        "triage": {
            "RED": "All suspected cases; fever + any hemorrhagic sign; fever + 2+ WHO danger signs",
            "YELLOW": "Fever + 2-3 early symptoms; close contact with confirmed case",
            "GREEN": "Asymptomatic; routine screening",
        },
        "risk_factors": [
            "Contact with blood/bodily fluids of infected person",
            "Contact with corpses",
            "Fruit bat exposure",
            "Healthcare worker without PPE",
            "Rural residence in endemic zones",
        ],
        "transmission": "Direct contact with blood/bodily fluids; NOT airborne",
        "case_fatality_rate": "50-90%",
        "management": {
            "immediate": "Immediate referral to isolation facility; contact tracing",
            "supportive": "IV fluids, electrolyte management, management of shock",
            "monitoring": "Daily blood tests, vital signs q4h",
            "follow_up": [1, 3, 7, 14, 30],  # days
        },
        "kenya_context": {
            "endemic_zones": ["Western Kenya", "Rift Valley"],
            "outbreak_history": "Sporadic cases; last confirmed 2015",
            "response_protocol": "MOH Level 4 alert; IPC isolation; lab confirmation mandatory",
            "reporting": "Immediate notification to county epidemiologist",
        },
    },

    "covid_19": {
        "name": "COVID-19 (SARS-CoV-2)",
        "category": "acute_respiratory_infection",
        "synonyms": ["COVID", "Coronavirus", "SARS-CoV-2", "C19"],
        "case_definition": {
            "suspected": "Cough/sore throat/dyspnea + fever OR contact with confirmed case",
            "probable": "Suspected + CT/CXR findings; high-risk exposure",
            "confirmed": "RT-PCR/antigen positive",
        },
        "clinical_features": {
            "onset": "2-14 days incubation",
            "mild_moderate": [
                "fever (50-75%)",
                "dry cough",
                "fatigue",
                "loss of taste/smell",
                "sore throat",
            ],
            "severe": [
                "dyspnea",
                "SpO₂ <94%",
                "RR >30",
                "confusion",
                "chest pain",
            ],
            "critical": [
                "ARDS",
                "Septic shock",
                "Multi-organ failure",
                "Thromboembolism",
            ],
        },
        "triage": {
            "RED": "SpO₂ <94%, RR >30, shock, confusion; immunocompromised + symptoms",
            "YELLOW": "Fever + 2 respiratory symptoms; SpO₂ 94-97%; vulnerable patients",
            "GREEN": "Asymptomatic; mild symptoms in low-risk patients",
        },
        "risk_factors": [
            "Age >60",
            "Hypertension",
            "Diabetes",
            "Obesity",
            "Chronic lung disease",
            "Immunosuppression",
            "Pregnancy",
        ],
        "transmission": "Airborne droplets; aerosol in enclosed spaces",
        "management": {
            "mild": "Home isolation, paracetamol, fluid, monitor SpO₂",
            "moderate": "Hospital observation, oxygen if SpO₂ <94%, monitor vitals",
            "severe": "Oxygen therapy, steroids (dexamethasone), consider remdesivir",
            "critical": "ICU, mechanical ventilation, ECMO consideration",
            "follow_up": [7, 14, 28, 60],  # days
        },
        "kenya_context": {
            "endemic_status": "Circulating; endemic phase",
            "vaccination_status": "Check for prior vaccination/infection",
            "response_protocol": "Testing based on risk; hospitalization if moderate-severe",
            "reporting": "Daily MOH dashboard; county surveillance",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # RESPIRATORY INFECTIONS
    # ══════════════════════════════════════════════════════════════════════════

    "pneumonia": {
        "name": "Community-Acquired Pneumonia",
        "category": "acute_respiratory_infection",
        "synonyms": ["CAP", "chest infection", "lung infection", "bronchopneumonia"],
        "case_definition": {
            "suspected": "Cough/dyspnea + fever + CXR or clinical consolidation",
            "probable": "Clinical symptoms + CXR findings",
            "confirmed": "Lab isolation + clinical; PCR/antigen positive",
        },
        "clinical_features": {
            "onset": "Acute (hours-days)",
            "symptoms": [
                "productive cough",
                "dyspnea",
                "fever",
                "chills",
                "pleuritic chest pain",
                "hemoptysis (severe)",
            ],
            "signs": [
                "tachypnea (RR >40)",
                "SpO₂ <90%",
                "chest wall indrawing",
                "nasal flaring",
                "focal crackles/consolidation",
            ],
        },
        "triage": {
            "RED": "SpO₂ <90%, RR >40, severe malnutrition, immunocompromised, age <2",
            "YELLOW": "SpO₂ 90-94%, RR 30-40, moderate symptoms, age 2-59 with comorbidity",
            "GREEN": "RR <30, SpO₂ >95%, no danger signs, age 2-59 well",
        },
        "risk_factors": [
            "Age <5 or >65",
            "Malnutrition",
            "HIV/AIDS",
            "Chronic lung disease",
            "Smoking",
            "Recent hospitalization",
            "Aspiration risk",
        ],
        "transmission": "Airborne droplets; person-to-person",
        "management": {
            "outpatient_mild": "Amoxicillin 1.5g TDS or azithromycin; follow-up 48h",
            "hospitalized": "Ceftriaxone ± macrolide; oxygen if SpO₂ <90%; IV fluids",
            "severe": "Broad-spectrum antibiotics; ICU if ARDS",
            "follow_up": [2, 7, 14, 28],  # days
        },
        "kenya_context": {
            "common_pathogens": ["S. pneumoniae", "H. influenzae", "S. aureus"],
            "drug_sensitivity": "Growing resistance; use national guidelines",
            "treatment_protocol": "MOH standard treatment guidelines for CAP",
            "reporting": "Notifiable if confirmed; county surveillance",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # PARASITIC INFECTIONS
    # ══════════════════════════════════════════════════════════════════════════

    "malaria": {
        "name": "Malaria",
        "category": "acute_febrile_illness",
        "synonyms": ["malaria fever", "plasmodium", "fever", "chills", "ague"],
        "case_definition": {
            "suspected": "Fever + history of exposure in endemic area",
            "probable": "Fever + positive rapid diagnostic test (RDT)",
            "confirmed": "Blood smear OR RDT positive + clinical symptoms",
        },
        "clinical_features": {
            "onset": "7-14 days incubation",
            "uncomplicated": [
                "fever (38.5-40°C)",
                "chills",
                "sweats",
                "headache",
                "muscle aches",
                "nausea/vomiting",
            ],
            "severe": [
                "cerebral malaria (impaired consciousness)",
                "acute kidney injury",
                "severe anemia",
                "respiratory distress",
                "hypoglycemia",
                "lactic acidosis",
            ],
        },
        "triage": {
            "RED": "Altered mental status, seizures, severe anemia, hypoglycemia, renal failure",
            "YELLOW": "Fever + signs of dehydration, vomiting, pregnant women, age <5",
            "GREEN": "Uncomplicated fever in endemic area; alert, able to drink",
        },
        "risk_factors": [
            "Residence/travel in endemic area",
            "Age <5",
            "Pregnancy (1st trimester critical)",
            "Non-immune travelers",
            "Immunosuppression",
        ],
        "transmission": "Mosquito vectors (Anopheles); peaks in rainy season",
        "management": {
            "uncomplicated": "Artemisinin combination therapy (ACT); e.g., artemether-lumefantrine",
            "severe": "IV artesunate; transfusion if Hb <5; supportive care",
            "pregnant": "Quinine 1st trimester; ACTs 2nd/3rd trimester",
            "follow_up": [3, 7, 14],  # days
        },
        "prevention": "ITNs, IRS, chemoprophylaxis for travelers, seasonal chemotherapy",
        "kenya_context": {
            "endemic_zones": "Western, Nyanza, coastal regions",
            "peak_season": "Rainy seasons (Apr-Jun, Oct-Dec)",
            "treatment": "MOH-approved ACT; artemether-lumefantrine preferred",
            "reporting": "District surveillance; seasonal trends tracked",
            "prevention_program": "Free ITNs at ANCs, free treatment <5y & pregnant",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # BACTERIAL INFECTIONS
    # ══════════════════════════════════════════════════════════════════════════

    "meningitis": {
        "name": "Bacterial Meningitis",
        "category": "meningitis",
        "synonyms": ["spinal meningitis", "meningococcemia", "cerebrospinal fever"],
        "case_definition": {
            "suspected": "Fever + neck stiffness/altered sensorium or petechial rash",
            "probable": "Clinical + CSF pleocytosis",
            "confirmed": "CSF culture or PCR positive; petechiae + meningeal signs",
        },
        "clinical_features": {
            "onset": "Acute (6-24 hours)",
            "classic_triad": [
                "fever (high)",
                "neck stiffness",
                "altered mental status",
            ],
            "additional": [
                "severe headache",
                "photophobia",
                "petechial rash",
                "rapid progression",
                "seizures",
            ],
        },
        "triage": {
            "RED": "ANY fever + neck stiffness; fever + petechiae; altered sensorium; infant <3m with fever",
            "YELLOW": "Suspected but no neck stiffness yet; close contact with confirmed case",
            "GREEN": "N/A for meningitis — all suspected cases are RED",
        },
        "risk_factors": [
            "Age <5 or >65",
            "Crowded conditions",
            "Immunosuppression",
            "Asplenia",
            "Recent head trauma",
            "Persistent CSF leak",
        ],
        "transmission": "Airborne droplets; person-to-person",
        "management": {
            "immediate": "IMMEDIATE lumbar puncture (LP); blood cultures before antibiotics",
            "antibiotics": "Ceftriaxone 2g IV Q12H + vancomycin IV; empiric until organism identified",
            "adjuncts": "Dexamethasone 10mg IV Q6H × 4 days; antipyretics",
            "supportive": "ICU if altered MS; seizure precautions",
            "follow_up": [1, 3, 7, 14, 30],  # days; neurodevelopmental assessment
        },
        "chemoprophylaxis": "Rifampicin for close contacts; prophylaxis of household contacts",
        "kenya_context": {
            "endemic_serogroups": "A, W, X (meningitis belt); W increasing",
            "vaccination": "PCV13 routine; MenAfriVac in risk groups",
            "response": "Immediate LP; MOH notification; contact tracing",
            "reporting": "Urgent notification; line-list for surveillance",
        },
    },

    "tuberculosis": {
        "name": "Tuberculosis",
        "category": "acute_respiratory_infection",
        "synonyms": ["TB", "pulmonary TB", "PTB", "consumption", "white plague"],
        "case_definition": {
            "suspect": "Cough ≥2 weeks + any systemic symptom (fever, weight loss, night sweats)",
            "probable": "Clinical + CXR findings suggestive of TB",
            "confirmed": "Sputum/specimen positive for M. tuberculosis (smear, culture, GeneXpert)",
        },
        "clinical_features": {
            "onset": "Insidious (weeks-months)",
            "pulmonary": [
                "chronic cough ≥2 weeks",
                "hemoptysis",
                "chest pain",
                "dyspnea",
                "fever",
                "night sweats",
                "weight loss",
            ],
            "constitutional": [
                "fatigue",
                "malaise",
                "anorexia",
                "weight loss",
            ],
        },
        "triage": {
            "RED": "Hemoptysis + respiratory symptoms; immunocompromised + TB suspect",
            "YELLOW": "Cough ≥2 weeks + fever/weight loss; TB contact",
            "GREEN": "TB suspect awaiting diagnostic; known TB on treatment, stable",
        },
        "risk_factors": [
            "HIV/AIDS",
            "Malnutrition",
            "Diabetes",
            "Smoking",
            "Alcohol abuse",
            "Crowded conditions",
            "TB contact",
            "Healthcare workers",
        ],
        "transmission": "Airborne; primarily pulmonary TB",
        "management": {
            "diagnosis": "GeneXpert MTB/RIF (gold standard); sputum smear; CXR",
            "treatment": "Standard 6-month regimen: 2HRZE / 4HR (DOTS strategy)",
            "adherence": "Directly observed therapy (DOT); community health workers",
            "follow_up": [2, 5, 6, 12, 18, 24],  # months; adherence monitoring
            "treatment_support": "Nutritional support; comorbidity management",
        },
        "hiv_coinfection": "Urgent ART; tb-hiv specialist care; adverse drug interactions",
        "kenya_context": {
            "burden": "High TB prevalence; TB/HIV 20-25%",
            "diagnosis": "GeneXpert at all level-3+ facilities; free testing",
            "treatment": "Free DOTs via county TB programs",
            "reporting": "TB case registers; quarterly to National TB Program",
            "prevention": "TB preventive therapy (TPT) for HIV+ contacts",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # IMMUNOLOGICAL DISEASES
    # ══════════════════════════════════════════════════════════════════════════

    "hiv_aids": {
        "name": "HIV/AIDS",
        "category": "hiv_aids",
        "synonyms": ["HIV", "AIDS", "human immunodeficiency virus", "acquired immunodeficiency"],
        "case_definition": {
            "hiv_positive": "Positive HIV test (rapid/ELISA/Western blot)",
            "aids": "HIV+ AND CD4 <200 cells/μL OR AIDS-defining illness",
            "advanced": "CD4 <50: CMV, crypto, PCP, TB",
        },
        "clinical_features": {
            "acute_infection": [
                "fever",
                "rash",
                "adenopathy",
                "pharyngitis",
                "fatigue",
            ],
            "chronic_asymptomatic": "None; CD4 counts remain high",
            "symptomatic": [
                "persistent diarrhea",
                "weight loss",
                "opportunistic infections",
                "tuberculosis",
                "oral thrush",
                "herpes zoster",
            ],
            "aids_defining": [
                "Pneumocystis jirovecii pneumonia (PCP)",
                "Cryptococcal meningitis",
                "Toxoplasma encephalitis",
                "CMV disease",
                "Cryptococcal disease",
                "TB",
            ],
        },
        "triage": {
            "RED": "AIDS-defining illness; CD4 <50; opportunistic infection",
            "YELLOW": "CD4 100-200; symptomatic; recent diagnosis",
            "GREEN": "CD4 >200 on ART; virally suppressed; asymptomatic",
        },
        "risk_factors": [
            "Unprotected sexual contact",
            "Occupational exposure",
            "Mother-to-child transmission",
            "Blood transfusion (rare now)",
        ],
        "transmission": "Sexual, blood-borne, vertical (MTCT)",
        "management": {
            "diagnosis": "HIV rapid test + confirmatory test (2 tests mandatory)",
            "treatment": "Initiate ART immediately after diagnosis (Test & Treat)",
            "first_line": "TLD (Tenofovir/Lamivudine/Dolutegravir)",
            "monitoring": "CD4 baseline + 6m; viral load 6m; adherence assessment",
            "follow_up": [2, 4, 12, 24],  # weeks/months after ART initiation",
            "prophylaxis": "CTX if CD4 <200; TB preventive therapy; MAC if CD4 <50",
        },
        "kenya_context": {
            "prevalence": "~4% adult population; higher in coastal/Nairobi",
            "treatment": "Free ART via MOH centers; universal coverage",
            "testing": "Free HTS at all health facilities",
            "reporting": "NASCOP surveillance; quarterly reporting",
            "targets": "UNAIDS 95-95-95: diagnose, treat, virally suppress",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # GASTROINTESTINAL INFECTIONS
    # ══════════════════════════════════════════════════════════════════════════

    "cholera": {
        "name": "Cholera",
        "category": "acute_watery_diarrhea",
        "synonyms": ["rice water stools", "acute watery diarrhea", "severe dehydration"],
        "case_definition": {
            "suspected": "Acute watery diarrhea ≥3 stools/day; dehydration",
            "probable": "Clinical + epidemiologic link to confirmed case",
            "confirmed": "Vibrio cholerae isolated from stool; positive rapid test",
        },
        "clinical_features": {
            "onset": "Abrupt (hours)",
            "symptoms": [
                "profuse watery diarrhea (rice water stools)",
                "vomiting",
                "rapid dehydration",
                "hypovolemic shock",
                "leg cramps",
                "no fever",
            ],
            "dehydration": [
                "minimal: 3-5% weight loss",
                "moderate: 6-9% weight loss, lethargy",
                "severe: ≥10% weight loss, unconscious, weak pulse",
            ],
        },
        "triage": {
            "RED": "Severe dehydration; shock; severe malnutrition; age <5; pregnant",
            "YELLOW": "Moderate dehydration; multiple comorbidities",
            "GREEN": "Minimal dehydration; well-appearing; age 5-59",
        },
        "transmission": "Contaminated food/water; poor sanitation",
        "management": {
            "rehydration": "ORS for mild-moderate; IV if severe (Ringer's lactate)",
            "antibiotics": "Azithromycin or tetracycline (reduces diarrhea duration 50%)",
            "electrolytes": "Potassium replacement; zinc supplementation",
            "nutrition": "Resume feeding after rehydration",
            "follow_up": [1, 3, 7],  # days for complications",
        },
        "prevention": "Water treatment, sanitation, vaccination (oral vaccine available)",
        "kenya_context": {
            "endemic": "Coastal, Old Town Mombasa; seasonal peaks",
            "outbreaks": "Reported periodically; vigilance during rainy seasons",
            "treatment": "Free at MOH facilities; ORS stockpiles at health centers",
            "reporting": "Cholera case is notifiable; IPC isolation",
        },
    },

    "typhoid": {
        "name": "Enteric Fever (Typhoid)",
        "category": "acute_febrile_illness",
        "synonyms": ["enteric fever", "Salmonella typhi", "rose spots fever"],
        "case_definition": {
            "suspected": "Fever ≥1 week + rose spots rash; constipation or diarrhea; splenomegaly",
            "probable": "Clinical + blood culture positive",
            "confirmed": "Salmonella typhi isolated from blood/urine; positive serology",
        },
        "clinical_features": {
            "onset": "7-14 days",
            "week_1": ["sustained fever", "headache", "myalgias", "abdominal pain"],
            "week_2": ["rose spots rash", "splenomegaly", "diarrhea/constipation", "delirium"],
            "week_3": ["complications if untreated: perforation, shock, death"],
        },
        "triage": {
            "RED": "Altered mental status, signs of perforation, septic shock",
            "YELLOW": "High fever + abdominal distension, splenomegaly",
            "GREEN": "Uncomplicated fever; stable vitals; no complications",
        },
        "risk_factors": [
            "Poor sanitation",
            "Contaminated food/water",
            "Urban crowding",
            "Healthcare worker exposure",
        ],
        "transmission": "Fecal-oral; contaminated water/food",
        "management": {
            "antibiotics": "Fluoroquinolone (ciprofloxacin) OR 3rd-gen cephalosporin if resistant",
            "duration": "7-14 days",
            "supportive": "IV fluids, electrolyte management, antipyretics",
            "complications": "Perforation requires surgical intervention",
            "follow_up": [3, 7, 14],  # days; stool culture clearance",
        },
        "prevention": "Sanitation, water treatment, typhoid vaccination",
        "kenya_context": {
            "endemic": "Urban areas, poor sanitation zones",
            "treatment": "MOH guidelines; fluoroquinolone first-line",
            "reporting": "Notifiable disease; sentinel surveillance",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # VECTOR-BORNE DISEASES
    # ══════════════════════════════════════════════════════════════════════════

    "dengue": {
        "name": "Dengue Fever",
        "category": "acute_febrile_illness",
        "synonyms": ["dengue", "breakbone fever", "Aedes fever"],
        "case_definition": {
            "suspected": "Acute fever (2-7 days) + ≥2 symptoms in endemic area",
            "probable": "Clinical + epidemiologic link",
            "confirmed": "IgM antibody; NS1 antigen; PCR positive",
        },
        "clinical_features": {
            "onset": "3-14 days incubation",
            "symptoms": [
                "abrupt high fever",
                "severe headache",
                "retro-orbital pain",
                "myalgias",
                "rash (appears on defervescence)",
                "mild hemorrhagic manifestations",
            ],
            "dengue_hemorrhagic": [
                "fever + hemorrhagic manifestations",
                "mucosal bleeding",
                "petechiae",
                "thrombocytopenia <100k",
            ],
            "dengue_shock": [
                "severe plasma leakage",
                "hypotension",
                "shock",
                "organ failure",
            ],
        },
        "triage": {
            "RED": "Dengue hemorrhagic/shock; severe thrombocytopenia; signs of plasma leakage",
            "YELLOW": "Fever + hemorrhagic signs; pregnancy; age <15 or >65",
            "GREEN": "Uncomplicated fever; good perfusion; platelets >100k",
        },
        "risk_factors": [
            "Living in endemic urban areas",
            "Daytime exposure to Aedes mosquitoes",
            "Secondary dengue infection (higher risk DHF)",
        ],
        "transmission": "Aedes aegypti mosquitoes; peak morning/evening",
        "management": {
            "outpatient": "Daily monitoring; paracetamol; NSAIDs contraindicated",
            "hospitalized": "IV fluids; maintain hematocrit <45%; platelet transfusion if <20k",
            "severe": "ICU; pressors if shock; manage ARDS if present",
            "follow_up": [1, 3, 7, 14],  # days for dengue hemorrhagic risk",
        },
        "prevention": "Mosquito control; screen windows; wear protective clothing",
        "kenya_context": {
            "endemic_areas": "Coastal region, parts of Rift Valley",
            "outbreaks": "Periodic, related to rainy seasons",
            "testing": "Available at reference labs",
            "reporting": "Surveillance; outbreak investigation",
        },
    },

    "yellow_fever": {
        "name": "Yellow Fever",
        "category": "viral_hemorrhagic_fever",
        "synonyms": ["yellow jack", "vomito negro"],
        "case_definition": {
            "suspected": "Fever + jaundice; fever + hemorrhage",
            "probable": "Clinical + exposure in endemic area",
            "confirmed": "Serology (IgM) or PCR; culture",
        },
        "clinical_features": {
            "onset": "3-6 days incubation",
            "mild": ["fever", "headache", "myalgias", "backache"],
            "severe": [
                "high fever",
                "jaundice",
                "abdominal pain",
                "vomiting",
                "bleeding",
                "renal failure",
                "shock",
            ],
        },
        "triage": {
            "RED": "Any fever + jaundice; fever + hemorrhage; jaundice + abdominal pain",
            "YELLOW": "Fever in endemic area; contact with YF case",
            "GREEN": "Vaccinated asymptomatic; routine screening",
        },
        "transmission": "Aedes mosquitoes; occupational exposure in forest zones",
        "management": {
            "supportive": "IV fluids, electrolyte management, antipyretics",
            "no_specific": "No antiviral; management is supportive only",
            "complications": "Manage hemorrhage, renal failure, hepatic failure",
            "follow_up": [7, 14, 28],  # days; convalescence monitoring",
        },
        "prevention": "Vaccination (single dose, lifelong immunity); mosquito precautions",
        "kenya_context": {
            "endemic": "Forest zones; occupational risk",
            "vaccination": "Recommended for travelers; occupational exposures",
            "reporting": "Notifiable; immediate MOH notification",
        },
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# SYMPTOM-TO-DISEASE MAPPING (for intake data correction)
# ══════════════════════════════════════════════════════════════════════════════

SYMPTOM_DISEASE_MAP = {
    "hemorrhage": ["ebola", "yellow_fever", "dengue", "malaria"],
    "petechiae": ["meningitis", "ebola", "dengue"],
    "hemoptysis": ["tuberculosis", "pneumonia", "ebola"],
    "neck_stiffness": ["meningitis"],
    "watery_diarrhea": ["cholera", "covid_19"],
    "bloody_diarrhea": ["cholera", "typhoid", "dysentery"],
    "rice_water_stools": ["cholera"],
    "jaundice": ["yellow_fever", "typhoid", "malaria"],
    "rose_spots": ["typhoid"],
    "chronic_cough": ["tuberculosis", "pneumonia"],
    "breathlessness": ["pneumonia", "covid_19", "ebola"],
    "seizures": ["meningitis", "malaria", "ebola"],
    "altered_mental_status": ["meningitis", "malaria", "ebola"],
    "high_fever": ["malaria", "ebola", "meningitis", "typhoid", "yellow_fever"],
    "night_sweats": ["tuberculosis", "hiv_aids"],
    "weight_loss": ["tuberculosis", "hiv_aids", "malaria"],
    "rash_with_fever": ["covid_19", "ebola", "dengue", "yellow_fever"],
}

# ══════════════════════════════════════════════════════════════════════════════
# TRIAGE COLOR MAPPING (for data validation)
# ══════════════════════════════════════════════════════════════════════════════

TRIAGE_COLOR_FEATURES = {
    "RED": [
        "unconscious",
        "convulsions",
        "inability_to_drink",
        "severe_dehydration",
        "respiratory_distress",
        "severe_malnutrition",
        "hemorrhage",
        "shock",
        "altered_mental_status",
    ],
    "YELLOW": [
        "moderate_dehydration",
        "fever_high",
        "fast_breathing",
        "severe_vomiting",
        "bloody_diarrhea",
        "rash_with_fever",
        "persistent_cough",
    ],
    "GREEN": [
        "mild_symptoms",
        "fever_low",
        "no_danger_signs",
        "normal_alertness",
    ],
}


def get_disease_info(disease: str) -> dict:
    """Get comprehensive disease information."""
    return DISEASE_DATABASE.get(disease.lower(), {})


def get_similar_diseases(symptoms: list) -> list:
    """Get list of diseases matching symptoms."""
    matching_diseases = set()
    for symptom in symptoms:
        if symptom.lower() in SYMPTOM_DISEASE_MAP:
            matching_diseases.update(SYMPTOM_DISEASE_MAP[symptom.lower()])
    return list(matching_diseases)


def validate_triage_color(triage_color: str, danger_signs: list) -> tuple:
    """
    Validate triage color and suggest correction if needed.
    Returns (is_valid, suggested_color, reason).
    """
    if triage_color not in ("RED", "YELLOW", "GREEN"):
        return False, "YELLOW", f"Invalid triage color: {triage_color}"

    # Check for RED danger signs
    red_features = TRIAGE_COLOR_FEATURES["RED"]
    has_red_signs = any(sign in danger_signs for sign in red_features)
    if has_red_signs and triage_color != "RED":
        return False, "RED", f"Danger signs present: {[s for s in danger_signs if s in red_features]}"

    # Check for YELLOW symptoms
    yellow_features = TRIAGE_COLOR_FEATURES["YELLOW"]
    has_yellow_signs = any(sign in danger_signs for sign in yellow_features)
    if has_yellow_signs and triage_color == "GREEN":
        return False, "YELLOW", f"Concerning signs present: {[s for s in danger_signs if s in yellow_features]}"

    return True, triage_color, "Triage color consistent with presentation"
