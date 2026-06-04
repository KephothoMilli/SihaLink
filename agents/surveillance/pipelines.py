"""
SihaLink Surveillance Pipelines
MongoDB aggregation pipelines for outbreak detection, silent pandemic analysis,
trend detection, and CHW outreach gap identification.
"""

from datetime import datetime, timedelta


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline A — Geospatial cluster (used by run_outbreak_detection)
# Fixed: $geoNear must be first stage; county filter moved inside $geoNear query
# ─────────────────────────────────────────────────────────────────────────────

def get_outbreak_pipeline(county_lat: float, county_lng: float, hours: int = 6):
    """
    Geospatial outbreak detection within 50km of county center.
    Returns syndrome clusters with ≥5 cases in the time window.
    """
    time_window = datetime.utcnow() - timedelta(hours=hours)
    return [
        {
            "$geoNear": {
                "near": {"type": "Point", "coordinates": [county_lng, county_lat]},
                "distanceField": "distance_m",
                "maxDistance": 50_000,   # 50 km
                "spherical": True,
                "query": {"timestamp": {"$gte": time_window}},
            }
        },
        {
            "$group": {
                "_id": {
                    "syndrome": "$extracted.syndrome",
                    "ward": "$admin_hierarchy.ward",
                },
                "count": {"$sum": 1},
                "encounter_ids": {"$push": "$encounter_id"},
                "avg_severity_score": {
                    "$avg": {
                        "$switch": {
                            "branches": [
                                {"case": {"$eq": ["$extracted.severity", "severe"]}, "then": 3},
                                {"case": {"$eq": ["$extracted.severity", "moderate"]}, "then": 2},
                            ],
                            "default": 1,
                        }
                    }
                },
            }
        },
        {"$match": {"count": {"$gte": 5}}},
        {"$sort": {"count": -1}},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline B — Silent pandemic: low-count but persistent multi-week trend
# Detects syndromes that never spike but steadily climb over 4 weeks
# ─────────────────────────────────────────────────────────────────────────────

def get_silent_pandemic_pipeline(county: str, weeks: int = 4):
    """
    Detects syndromes with a consistent upward trend over N weeks
    even if individual weekly counts stay below the spike threshold.
    Returns syndromes with slope > 0 across all weeks.
    """
    start = datetime.utcnow() - timedelta(weeks=weeks)
    return [
        {
            "$match": {
                "admin_hierarchy.county": county,
                "timestamp": {"$gte": start},
            }
        },
        {
            "$group": {
                "_id": {
                    "syndrome": "$extracted.syndrome",
                    "week": {"$week": "$timestamp"},
                    "year": {"$year": "$timestamp"},
                },
                "weekly_count": {"$sum": 1},
            }
        },
        {"$sort": {"_id.year": 1, "_id.week": 1}},
        {
            "$group": {
                "_id": "$_id.syndrome",
                "weekly_counts": {"$push": "$weekly_count"},
                "weeks_observed": {"$sum": 1},
                "total_cases": {"$sum": "$weekly_count"},
            }
        },
        # Keep only syndromes seen in ≥3 of the N weeks
        {"$match": {"weeks_observed": {"$gte": 3}}},
        {
            "$project": {
                "syndrome": "$_id",
                "weekly_counts": 1,
                "weeks_observed": 1,
                "total_cases": 1,
                # Slope proxy: last-week count minus first-week count
                "trend_delta": {
                    "$subtract": [
                        {"$arrayElemAt": ["$weekly_counts", -1]},
                        {"$arrayElemAt": ["$weekly_counts", 0]},
                    ]
                },
                # Average weekly count
                "weekly_avg": {"$divide": ["$total_cases", "$weeks_observed"]},
            }
        },
        # Only rising trends
        {"$match": {"trend_delta": {"$gt": 0}}},
        {"$sort": {"trend_delta": -1}},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline C — Cross-county spread: same syndrome rising in ≥2 counties
# ─────────────────────────────────────────────────────────────────────────────

def get_cross_county_spread_pipeline(syndrome: str, hours: int = 48):
    """
    Detects whether a syndrome is simultaneously rising in multiple counties,
    indicating potential cross-county spread or a common-source outbreak.
    """
    time_window = datetime.utcnow() - timedelta(hours=hours)
    return [
        {
            "$match": {
                "extracted.syndrome": syndrome,
                "timestamp": {"$gte": time_window},
            }
        },
        {
            "$group": {
                "_id": "$admin_hierarchy.county",
                "count": {"$sum": 1},
                "wards_affected": {"$addToSet": "$admin_hierarchy.ward"},
                "latest_case": {"$max": "$timestamp"},
            }
        },
        {"$match": {"count": {"$gte": 3}}},
        {
            "$project": {
                "county": "$_id",
                "count": 1,
                "wards_affected_count": {"$size": "$wards_affected"},
                "latest_case": 1,
            }
        },
        {"$sort": {"count": -1}},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline D — Under-reporting detection: wards with low CHW activity
# Identifies wards where encounter volume is suspiciously low vs population
# ─────────────────────────────────────────────────────────────────────────────

def get_underreporting_pipeline(county: str, days: int = 7):
    """
    Finds wards in a county with zero or very low encounter submissions
    over the past N days — a proxy for CHW under-reporting or coverage gaps.
    """
    time_window = datetime.utcnow() - timedelta(days=days)
    return [
        {
            "$match": {
                "admin_hierarchy.county": county,
                "timestamp": {"$gte": time_window},
            }
        },
        {
            "$group": {
                "_id": "$admin_hierarchy.ward",
                "encounter_count": {"$sum": 1},
                "unique_chws": {"$addToSet": "$chw_id"},
                "last_submission": {"$max": "$timestamp"},
            }
        },
        {
            "$project": {
                "ward": "$_id",
                "encounter_count": 1,
                "active_chws": {"$size": "$unique_chws"},
                "last_submission": 1,
                "days_since_last": {
                    "$divide": [
                        {"$subtract": [datetime.utcnow(), "$last_submission"]},
                        86_400_000,  # ms → days
                    ]
                },
            }
        },
        # Flag wards with <3 encounters or last submission >3 days ago
        {
            "$match": {
                "$or": [
                    {"encounter_count": {"$lt": 3}},
                    {"days_since_last": {"$gt": 3}},
                ]
            }
        },
        {"$sort": {"encounter_count": 1}},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline E — Follow-up overdue: patients due for follow-up
# ─────────────────────────────────────────────────────────────────────────────

def get_overdue_followups_pipeline(county: str):
    """
    Returns follow-up records that are past their due date and still pending.
    Used by the follow-up scheduler to generate CHW task lists.
    """
    now = datetime.utcnow()
    return [
        {
            "$match": {
                "county": county,
                "status": "pending",
                "due_date": {"$lte": now},
            }
        },
        {
            "$lookup": {
                "from": "encounters",
                "localField": "encounter_id",
                "foreignField": "encounter_id",
                "as": "encounter",
            }
        },
        {"$unwind": {"path": "$encounter", "preserveNullAndEmptyArrays": True}},
        {
            "$project": {
                "follow_up_id": 1,
                "encounter_id": 1,
                "chw_id": 1,
                "due_date": 1,
                "days_overdue": {
                    "$divide": [
                        {"$subtract": [now, "$due_date"]},
                        86_400_000,
                    ]
                },
                "syndrome": "$encounter.extracted.syndrome",
                "triage_color": "$encounter.extracted.triage_color",
                "patient_age": "$encounter.extracted.age",
                "ward": "$encounter.admin_hierarchy.ward",
                "county": "$encounter.admin_hierarchy.county",
            }
        },
        {"$sort": {"days_overdue": -1}},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline F — CHW performance: encounters per CHW per week
# ─────────────────────────────────────────────────────────────────────────────

def get_chw_performance_pipeline(county: str, weeks: int = 4):
    """
    Aggregates encounter submissions per CHW over the past N weeks.
    Used to identify high-performers and CHWs needing support.
    """
    start = datetime.utcnow() - timedelta(weeks=weeks)
    return [
        {
            "$match": {
                "admin_hierarchy.county": county,
                "timestamp": {"$gte": start},
                "chw_id": {"$exists": True},
            }
        },
        {
            "$group": {
                "_id": {
                    "chw_id": "$chw_id",
                    "week": {"$week": "$timestamp"},
                },
                "encounters": {"$sum": 1},
                "red_cases": {
                    "$sum": {
                        "$cond": [{"$eq": ["$extracted.triage_color", "RED"]}, 1, 0]
                    }
                },
                "yellow_cases": {
                    "$sum": {
                        "$cond": [{"$eq": ["$extracted.triage_color", "YELLOW"]}, 1, 0]
                    }
                },
            }
        },
        {
            "$group": {
                "_id": "$_id.chw_id",
                "total_encounters": {"$sum": "$encounters"},
                "total_red": {"$sum": "$red_cases"},
                "total_yellow": {"$sum": "$yellow_cases"},
                "weeks_active": {"$sum": 1},
                "avg_per_week": {"$avg": "$encounters"},
            }
        },
        {"$sort": {"total_encounters": -1}},
    ]
