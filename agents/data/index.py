"""
SihaLink Atlas Index Manager
Autonomous creation and verification of all MongoDB indexes including
Atlas Vector Search and Atlas Search (full-text) indexes.

Uses pymongo 4.6+ SearchIndexModel API — the correct way to manage
Atlas Search indexes programmatically (not the legacy db.command approach).

Collections managed:
  encounters  — geospatial + compound + vector search + full-text search
  alerts      — compound status/county/time
  referrals   — encounter linkage + triage queries
  follow_ups  — CHW task scheduling queries
  chws        — registry lookups
  protocols   — syndrome lookups
  baselines   — county/syndrome unique
"""

import logging
from typing import Any, Dict

from pymongo.database import Database
from pymongo import GEOSPHERE, ASCENDING, DESCENDING
from pymongo.errors import OperationFailure

logger = logging.getLogger("SihaLink-IndexManager")


# ── Atlas Search index definitions ───────────────────────────────────────────

# Vector Search index — cosine similarity on 768-dim Google embeddings
# OR 1024-dim Voyage AI embeddings (dimension auto-detected at runtime)
VECTOR_INDEX_GOOGLE: Dict[str, Any] = {
    "name": "vector_index",
    "type": "vectorSearch",
    "definition": {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": 768,       # Google text-embedding-004
                "similarity": "cosine",
            },
            # Pre-filter fields — allow $vectorSearch to filter by county/syndrome
            {"type": "filter", "path": "admin_hierarchy.county"},
            {"type": "filter", "path": "extracted.syndrome"},
            {"type": "filter", "path": "extracted.triage_color"},
            {"type": "filter", "path": "timestamp"},
        ]
    },
}

VECTOR_INDEX_VOYAGE: Dict[str, Any] = {
    "name": "vector_index_voyage",
    "type": "vectorSearch",
    "definition": {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": 1024,      # Voyage AI voyage-4
                "similarity": "cosine",
            },
            {"type": "filter", "path": "admin_hierarchy.county"},
            {"type": "filter", "path": "extracted.syndrome"},
            {"type": "filter", "path": "extracted.triage_color"},
            {"type": "filter", "path": "timestamp"},
        ]
    },
}

# Full-text Atlas Search index — enables $search on clinical text fields
FULLTEXT_INDEX: Dict[str, Any] = {
    "name": "encounters_text_search",
    "definition": {
        "mappings": {
            "dynamic": False,
            "fields": {
                "extracted.chief_complaint":  {"type": "string", "analyzer": "lucene.english"},
                "extracted.syndrome":         {"type": "string"},
                "extracted.primary_symptoms": {"type": "string"},
                "admin_hierarchy.county":     {"type": "string"},
                "admin_hierarchy.ward":       {"type": "string"},
            },
        }
    },
}

# Protocol full-text search — CHWs can search protocols by keyword
PROTOCOL_SEARCH_INDEX: Dict[str, Any] = {
    "name": "protocols_text_search",
    "definition": {
        "mappings": {
            "dynamic": False,
            "fields": {
                "syndrome":          {"type": "string"},
                "immediate_actions": {"type": "string", "analyzer": "lucene.english"},
                "chw_actions":       {"type": "string", "analyzer": "lucene.english"},
            },
        }
    },
}


class IndexManager:
    """
    Manages all MongoDB regular indexes and Atlas Search/Vector Search indexes
    for the SihaLink database. All operations are idempotent.
    """

    def __init__(self, db: Database):
        self.db = db

    # ── Entry point ───────────────────────────────────────────────────────────

    def ensure_all_indexes(self, embedding_dim: int = 768) -> Dict[str, Any]:
        """
        Create all regular and Atlas Search indexes. Safe to call on every startup.

        Args:
            embedding_dim: Dimension of the active embedding provider (768 or 1024).
                           Determines which vector index definition to use.

        Returns:
            dict summarising what was created vs already existed.
        """
        results: Dict[str, Any] = {
            "regular_indexes": self._ensure_regular_indexes(),
            "vector_search":   self._ensure_vector_search_index(embedding_dim),
            "fulltext_search": self._ensure_fulltext_indexes(),
        }
        logger.info("✅ All indexes verified: %s", results)
        return results

    # ── Regular (B-tree / geospatial) indexes ─────────────────────────────────

    def _ensure_regular_indexes(self) -> str:
        try:
            # encounters
            self.db.encounters.create_index([("location", GEOSPHERE)])
            self.db.encounters.create_index(
                [("extracted.syndrome", ASCENDING), ("timestamp", DESCENDING)]
            )
            self.db.encounters.create_index(
                [("admin_hierarchy.county", ASCENDING), ("timestamp", DESCENDING)]
            )
            self.db.encounters.create_index(
                [("chw_id", ASCENDING), ("timestamp", DESCENDING)]
            )
            self.db.encounters.create_index(
                [("synced", ASCENDING), ("queued_at", ASCENDING)]
            )

            # alerts
            self.db.alerts.create_index(
                [("location.county", ASCENDING), ("status", ASCENDING),
                 ("timestamp", DESCENDING)]
            )
            self.db.alerts.create_index(
                [("alert_id", ASCENDING)], unique=True, sparse=True
            )
            self.db.alerts.create_index(
                [("alert_type", ASCENDING), ("status", ASCENDING)]
            )

            # referrals
            self.db.referrals.create_index([("encounter_id", ASCENDING)])
            self.db.referrals.create_index(
                [("location.county", ASCENDING), ("status", ASCENDING),
                 ("timestamp", DESCENDING)]
            )
            self.db.referrals.create_index(
                [("triage_color", ASCENDING), ("status", ASCENDING)]
            )

            # follow_ups
            self.db.follow_ups.create_index(
                [("follow_up_id", ASCENDING)], unique=True
            )
            self.db.follow_ups.create_index([("encounter_id", ASCENDING)])
            self.db.follow_ups.create_index(
                [("chw_id", ASCENDING), ("status", ASCENDING), ("due_date", ASCENDING)]
            )
            self.db.follow_ups.create_index(
                [("county", ASCENDING), ("status", ASCENDING), ("due_date", ASCENDING)]
            )

            # chws
            self.db.chws.create_index([("chw_id", ASCENDING)], unique=True)
            self.db.chws.create_index(
                [("county", ASCENDING), ("ward", ASCENDING), ("status", ASCENDING)]
            )
            self.db.chws.create_index([("telegram_id", ASCENDING)], sparse=True)

            # protocols
            self.db.protocols.create_index(
                [("syndrome", ASCENDING), ("county", ASCENDING)], unique=True
            )
            self.db.protocols.create_index([("status", ASCENDING)])

            # baselines
            self.db.baselines.create_index(
                [("county", ASCENDING), ("syndrome", ASCENDING)], unique=True
            )

            return "ok"
        except OperationFailure as exc:
            logger.warning("Regular index warning: %s", exc)
            return f"warning: {exc}"

    # ── Atlas Vector Search index ─────────────────────────────────────────────

    def _ensure_vector_search_index(self, embedding_dim: int) -> str:
        """
        Create the Atlas Vector Search index using pymongo 4.6+ SearchIndexModel.
        Chooses the correct dimension based on the active embedding provider.
        """
        try:
            from pymongo.operations import SearchIndexModel

            # Pick definition based on active embedding dimension
            if embedding_dim == 1024:
                defn = VECTOR_INDEX_VOYAGE
                index_name = "vector_index_voyage"
            else:
                defn = VECTOR_INDEX_GOOGLE
                index_name = "vector_index"

            # Check if index already exists
            existing = list(self.db.encounters.list_search_indexes())
            existing_names = {idx.get("name") for idx in existing}

            if index_name in existing_names:
                logger.info("Vector Search index '%s' already exists", index_name)
                return "exists"

            model = SearchIndexModel(
                definition=defn["definition"],
                name=defn["name"],
                type=defn.get("type", "vectorSearch"),
            )
            self.db.encounters.create_search_index(model)
            logger.info("✅ Atlas Vector Search index '%s' created (%d dims)", index_name, embedding_dim)
            return "created"

        except ImportError:
            # pymongo < 4.6 — fall back to db.command
            return self._ensure_vector_search_index_legacy(embedding_dim)
        except Exception as exc:
            logger.warning("Vector Search index creation note: %s", exc)
            return f"note: {exc}"

    def _ensure_vector_search_index_legacy(self, embedding_dim: int) -> str:
        """Fallback for pymongo < 4.6 using db.command."""
        dim = embedding_dim
        index_def = {
            "mappings": {
                "dynamic": False,
                "fields": {
                    "embedding": {
                        "type": "knnVector",
                        "dimensions": dim,
                        "similarity": "cosine",
                    }
                },
            }
        }
        try:
            self.db.command(
                "createSearchIndexes",
                "encounters",
                indexes=[{"name": "vector_index", "definition": index_def}],
            )
            logger.info("✅ Vector Search index created via legacy command (%d dims)", dim)
            return "created_legacy"
        except OperationFailure as exc:
            logger.info("Vector Search index legacy note: %s", exc)
            return f"legacy_note: {exc}"

    # ── Atlas full-text Search indexes ────────────────────────────────────────

    def _ensure_fulltext_indexes(self) -> str:
        """Create Atlas Search full-text indexes for encounters and protocols."""
        created = []
        try:
            from pymongo.operations import SearchIndexModel

            # Encounters full-text
            enc_existing = {
                idx.get("name")
                for idx in self.db.encounters.list_search_indexes()
            }
            if FULLTEXT_INDEX["name"] not in enc_existing:
                model = SearchIndexModel(
                    definition=FULLTEXT_INDEX["definition"],
                    name=FULLTEXT_INDEX["name"],
                )
                self.db.encounters.create_search_index(model)
                created.append(FULLTEXT_INDEX["name"])
                logger.info("✅ Full-text search index created: %s", FULLTEXT_INDEX["name"])

            # Protocols full-text
            proto_existing = {
                idx.get("name")
                for idx in self.db.protocols.list_search_indexes()
            }
            if PROTOCOL_SEARCH_INDEX["name"] not in proto_existing:
                model = SearchIndexModel(
                    definition=PROTOCOL_SEARCH_INDEX["definition"],
                    name=PROTOCOL_SEARCH_INDEX["name"],
                )
                self.db.protocols.create_search_index(model)
                created.append(PROTOCOL_SEARCH_INDEX["name"])
                logger.info("✅ Protocol search index created: %s", PROTOCOL_SEARCH_INDEX["name"])

            return f"created: {created}" if created else "all_exist"

        except ImportError:
            logger.info("SearchIndexModel not available (pymongo < 4.6) — skipping full-text indexes")
            return "skipped_old_driver"
        except Exception as exc:
            logger.warning("Full-text index note: %s", exc)
            return f"note: {exc}"

    # ── Atlas Search query helpers ────────────────────────────────────────────

    def build_vector_search_pipeline(
        self,
        query_vector: list,
        num_candidates: int = 150,
        limit: int = 20,
        filter_county: str | None = None,
        filter_syndrome: str | None = None,
        min_score: float = 0.75,
        index_name: str = "vector_index",
    ) -> list:
        """
        Build a $vectorSearch aggregation pipeline with optional pre-filters.
        Uses the new Atlas Vector Search syntax (not $search knnBeta).

        Args:
            query_vector:     Embedding of the query text.
            num_candidates:   Candidate pool size (higher = better recall, slower).
            limit:            Max results to return.
            filter_county:    Optional county pre-filter.
            filter_syndrome:  Optional syndrome pre-filter.
            min_score:        Minimum cosine similarity score to include.
            index_name:       Name of the vector search index to use.

        Returns:
            MongoDB aggregation pipeline list.
        """
        vector_search_stage: Dict[str, Any] = {
            "$vectorSearch": {
                "index": index_name,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": num_candidates,
                "limit": limit,
            }
        }

        # Add pre-filters if provided (requires filter fields in index definition)
        filters = {}
        if filter_county:
            filters["admin_hierarchy.county"] = {"$eq": filter_county}
        if filter_syndrome:
            filters["extracted.syndrome"] = {"$eq": filter_syndrome}
        if filters:
            vector_search_stage["$vectorSearch"]["filter"] = filters

        return [
            vector_search_stage,
            {"$addFields": {"vector_score": {"$meta": "vectorSearchScore"}}},
            {"$match": {"vector_score": {"$gte": min_score}}},
            {
                "$project": {
                    "_id": 0,
                    "encounter_id": 1,
                    "extracted.syndrome": 1,
                    "extracted.triage_color": 1,
                    "extracted.chief_complaint": 1,
                    "admin_hierarchy.county": 1,
                    "admin_hierarchy.ward": 1,
                    "timestamp": 1,
                    "vector_score": 1,
                }
            },
        ]

    def build_fulltext_search_pipeline(
        self,
        query: str,
        county: str | None = None,
        limit: int = 10,
    ) -> list:
        """
        Build an Atlas Search $search pipeline for full-text clinical queries.
        Useful for CHWs searching protocols or supervisors querying encounters.

        Args:
            query:   Free-text search query.
            county:  Optional county filter.
            limit:   Max results.

        Returns:
            MongoDB aggregation pipeline list.
        """
        search_stage: Dict[str, Any] = {
            "$search": {
                "index": "encounters_text_search",
                "compound": {
                    "must": [
                        {
                            "text": {
                                "query": query,
                                "path": [
                                    "extracted.chief_complaint",
                                    "extracted.syndrome",
                                    "extracted.primary_symptoms",
                                ],
                                "fuzzy": {"maxEdits": 1},
                            }
                        }
                    ],
                    "filter": [],
                },
            }
        }

        if county:
            search_stage["$search"]["compound"]["filter"].append(
                {"text": {"query": county, "path": "admin_hierarchy.county"}}
            )

        return [
            search_stage,
            {"$addFields": {"search_score": {"$meta": "searchScore"}}},
            {"$sort": {"search_score": DESCENDING}},
            {"$limit": limit},
            {
                "$project": {
                    "_id": 0,
                    "encounter_id": 1,
                    "extracted.syndrome": 1,
                    "extracted.chief_complaint": 1,
                    "admin_hierarchy": 1,
                    "timestamp": 1,
                    "search_score": 1,
                }
            },
        ]
