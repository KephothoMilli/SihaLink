from datetime import datetime, timedelta

def get_geospatial_cluster_pipeline(county_name: str, hours=24):
    """
    Pipeline A: Detects spikes in specific syndromes within a Ward.
    """
    time_window = datetime.utcnow() - timedelta(hours=hours)
    
    return [
        {
            "$match": {
                "timestamp": {"$gte": time_window},
                "admin_hierarchy.county": county_name
            }
        },
        {
            "$group": {
                "_id": {
                    "syndrome": "$extracted.syndrome",
                    "ward": "$admin_hierarchy.ward"
                },
                "count": {"$sum": 1},
                "avg_severity_score": {
                    "$avg": {
                        "$switch": {
                            "branches": [
                                {"case": {"$eq": ["$extracted.severity", "severe"]}, "then": 3},
                                {"case": {"$eq": ["$extracted.severity", "moderate"]}, "then": 2}
                            ],
                            "default": 1
                        }
                    }
                },
                "encounter_ids": {"$push": "$encounter_id"}
            }
        },
        {
            "$match": {
                "count": {"$gte": 5}  # Threshold for signal detection
            }
        },
        {"$sort": {"count": -1}}
    ]

def get_vector_similarity_pipeline(query_vector: list, lat: float, lng: float):
    """
    Pipeline B: Uses Atlas Vector Search to find semantically similar cases 
    within a 50km radius, regardless of the 'syndrome' label.
    """
    return [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 100,
                "limit": 20
            }
        },
        {
            "$addFields": {"vector_score": {"$meta": "vectorSearchScore"}}
        },
        {
            "$match": {
                "vector_score": {"$gte": 0.85},
                "timestamp": {"$gte": datetime.utcnow() - timedelta(days=3)}
            }
        },
        {
            "$group": {
                "_id": "$extracted.syndrome",
                "count": {"$sum": 1},
                "avg_similarity": {"$avg": "$vector_score"},
                "encounter_ids": {"$push": "$encounter_id"}
            }
        }
    ]