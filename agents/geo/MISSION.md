# Geo Agent — Mission File

## Identity

**Name:** `geo_agent`  
**Role:** Geospatial Intelligence & Facility Routing Specialist  
**Model:** Google Maps Platform (Places, Directions, Geocoding APIs)  
**Language:** Python (synchronous + async via thread executor)

---

## Mission

Transform GPS coordinates into Kenya's administrative hierarchy and find the nearest health facilities with accurate ETAs — so every patient report is geographically anchored and every referral reaches the right facility.

**Without the Geo Agent, alerts have no location. Referrals have no destination. Outbreaks have no map.**

---

## Inputs

| Field            | Type  | Description                           |
| ---------------- | ----- | ------------------------------------- |
| `encounter_json` | dict  | Clinical extraction from Intake Agent |
| `latitude`       | float | GPS latitude from CHV device          |
| `longitude`      | float | GPS longitude from CHV device         |

---

## Outputs

```json
{
  "admin_hierarchy": {
    "village":    "Koguta",
    "ward":       "East Karachuonyo",
    "sub_county": "Homa Bay Town",
    "county":     "Homa Bay",
    "region":     "Nyanza"
  },
  "location": {
    "type":        "Point",
    "coordinates": [34.4571, -0.5273]
  },
  "nearest_facilities": [
    {
      "name":        "Homa Bay County Teaching & Referral Hospital",
      "place_id":    "ChIJ...",
      "distance_km": 3.2,
      "eta_minutes": 12,
      "type":        "hospital",
      "open_now":    true
    }
  ],
  "recommended_facility": { ... },
  "search_radius_km": 50
}
```

---

## WHO / MoH Facility Search Logic

1. Search within 10 km radius — if ≥1 result, return top 3 by ETA
2. Expand to 25 km — if ≥1 result, return top 3
3. Expand to 50 km — return whatever is found; warn if empty
4. Tag `triage_color = RED` encounters with emergency hospital preference
5. Calculate real driving time (Google Directions API), not straight-line distance

---

## Swarm Event Published

- `encounter.geolocated` — payload: enriched encounter with admin hierarchy + facilities

---

## Admin Hierarchy Mapping

Kenya has 47 counties → sub-counties → wards → villages.  
The Geo Agent uses reverse geocoding (Google Maps) + a regex parser to extract the full hierarchy from the formatted address returned.

---

## Non-negotiable Rules

1. Never block the pipeline if Maps API is unavailable — return `{"county": "Unknown"}` and continue
2. Always store `location` as a GeoJSON Point for MongoDB `$geoNear` pipelines
3. ETA must be driving time, not walking or flying
4. Flag any encounter where coordinates fall outside Kenya's bounding box

---

## Swarm Observability & Infrastructure Integration

As a critical component of the SihaLink Health Diseases Outbreak Swarm, this agent integrates seamlessly with our enterprise infrastructure:

- **Dynatrace Observability:** All operations are tracked via OpenTelemetry and Dynatrace RUM, providing full-stack visibility, automated anomaly detection, and end-to-end tracing across the swarm.
- **MongoDB Atlas & Vector Search:** Utilizes MongoDB Atlas for resilient, globally distributed storage. Seamlessly integrates with Atlas Vector Search for semantic similarity matching of clinical encounters and outbreak protocols.
- **Fluid & Responsive UI:** Provides consistent, high-performance API endpoints to ensure the frontend dashboard remains fluid and responsive under load.
- **Swarm Intelligence:** Acts dependably as a node in the autonomous, multi-agent swarm network, guaranteeing perfect coordination for national health disease outbreak management.
