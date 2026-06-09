# SihaLink — Test & Seed Data

All test datasets, seed scripts, and fixture files for the SihaLink multi-agent disease surveillance system.

## Files

| File                          | Purpose                                                                                                                                                               |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `seed_test_data.py`           | **Primary seeder** — 120 encounters, 24 CHWs, 18 alerts, 12 contact traces, protocols, follow-ups, referrals, agent logs, workflow states. Uses Voyage AI embeddings. |
| `seed_kenya_data.json`        | Static JSON reference data — Kenya county coordinates, ward names, disease codes                                                                                      |
| `clinical_intake_dataset.py`  | Synthetic clinical intake examples in Dholuo, Swahili, Kikuyu, Somali, English for Intake Agent testing                                                               |
| `test_dataset_integration.py` | Integration tests — verifies seed data is queryable and agents can process it                                                                                         |
| `test_dataset_quick.py`       | Quick smoke tests — minimal data sanity checks                                                                                                                        |
| `test_health.py`              | Health check tests — all agent endpoints respond correctly                                                                                                            |

## Run the seeder

```bash
# From project root
cd c:\Users\kephotho\Devpost\SihaLink
SihaLinkEnv\Scripts\python.exe data\seed_test_data.py
```

## Requirements

```
MONGODB_ATLAS_URI=<your atlas URI>   # required
VOYAGE_API_KEY=<your voyage key>     # optional — falls back to zero vectors
```

## What gets seeded

- **24 CHWs** across 8 Kenya counties (Homa Bay, Kisumu, Nairobi, Mombasa, Garissa, Turkana, Kilifi, Kisii)
- **120 encounters** spanning 30 days — realistic triage distribution (15% RED, 40% YELLOW, 45% GREEN) with Voyage AI vector embeddings
- **18 alerts** — spike, silent pandemic, cross-county spread, CHW outreach gap, and resolved alerts
- **County-syndrome baselines** for 8 counties × 12 syndromes
- **Follow-up tasks** auto-scheduled per triage color (RED: days 1,3,7,14 / YELLOW: 2,7,14 / GREEN: 7)
- **12 contact traces** with full contact records, View Details fields (name, relationship, symptoms), analytics histograms
- **Protocols** for 6 IDSR syndromes × 3 counties with WHO/MOH source authority
- **25 referrals** for RED/YELLOW encounters
- **200 agent logs** across all agents
- **30 workflow states** with full state machine history
