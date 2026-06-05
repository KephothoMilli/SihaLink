"""
Data Agent — SihaLink (MongoDB MCP superpower layer)
Collections:
  encounters   — clinical encounters with vector embeddings
  alerts       — outbreak alerts (separate from referrals)
  referrals    — patient referral records (split from alerts)
  follow_ups   — scheduled patient follow-up tasks for CHWs
  chws         — Community Health Worker registry
  protocols    — WHO/MoH response protocols (written by Surveillance Agent)
  baselines    — 4-week rolling syndrome baselines

All blocking pymongo calls run in a thread executor to keep FastAPI healthy.
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from bson import ObjectId
from pymongo import MongoClient, GEOSPHERE, ASCENDING, DESCENDING
from pymongo.errors import OperationFailure, DuplicateKeyError

from .embedding_service import EmbeddingService

logger = logging.getLogger("SihaLink-DataAgent")

# ── Follow-up interval rules (days after encounter) ──────────────────────────
FOLLOWUP_SCHEDULE: Dict[str, List[int]] = {
    "RED": [1, 3, 7, 14],  # Daily then weekly
    "YELLOW": [2, 7, 14],  # 48h then weekly
    "GREEN": [7],  # Single 7-day check
}


class DataAgent:
    """MongoDB operations for the SihaLink swarm."""

    def __init__(self):
        uri = os.getenv("MONGODB_ATLAS_URI")
        if not uri:
            logger.warning("⚠️ MONGODB_ATLAS_URI not set. Running in degraded mode.")
            self.client = None
            self.db = None
            self.embedding_svc = None
            self.connected = False
            return

        try:
            self.client = MongoClient(
                uri,
                appname="sihalink",
            )
            # Test connection without blocking
            self.client.admin.command("ping")
            self.db = self.client.sihalink
            self.embedding_svc = EmbeddingService()
            self.connected = True
            logger.info("✅ MongoDB connected successfully")
            # Create indexes after successful connection
            self.ensure_indexes()
            # Create Atlas Search + Vector Search indexes (non-blocking on error)
            try:
                self.ensure_search_indexes()
            except Exception as idx_exc:
                logger.warning("Search index setup skipped: %s", idx_exc)
        except Exception as e:
            logger.error("❌ Failed to connect to MongoDB: %s", e)
            logger.warning("Running in degraded mode. Some features may be limited.")
            self.client = None
            self.db = None
            self.embedding_svc = None
            self.connected = False

    # ══════════════════════════════════════════════════════════════════════════
    # INDEX MANAGEMENT  (autonomous — MongoDB MCP superpower)
    # ══════════════════════════════════════════════════════════════════════════

    def ensure_indexes(self):
        """Idempotent index creation across all collections. Called on startup."""
        if not self.connected or self.db is None:
            logger.warning("⚠️ Cannot create indexes: MongoDB not connected")
            return

        try:
            # ── encounters ────────────────────────────────────────────────────
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

            # ── alerts ────────────────────────────────────────────────────────
            self.db.alerts.create_index(
                [
                    ("location.county", ASCENDING),
                    ("status", ASCENDING),
                    ("timestamp", DESCENDING),
                ]
            )
            self.db.alerts.create_index(
                [("alert_id", ASCENDING)], unique=True, sparse=True
            )
            self.db.alerts.create_index(
                [("alert_type", ASCENDING), ("status", ASCENDING)]
            )

            # ── referrals (separate collection) ───────────────────────────────
            self.db.referrals.create_index([("encounter_id", ASCENDING)])
            self.db.referrals.create_index(
                [
                    ("location.county", ASCENDING),
                    ("status", ASCENDING),
                    ("timestamp", DESCENDING),
                ]
            )
            self.db.referrals.create_index(
                [("triage_color", ASCENDING), ("status", ASCENDING)]
            )

            # ── follow_ups ────────────────────────────────────────────────────
            self.db.follow_ups.create_index([("encounter_id", ASCENDING)])
            self.db.follow_ups.create_index(
                [("chw_id", ASCENDING), ("status", ASCENDING), ("due_date", ASCENDING)]
            )
            self.db.follow_ups.create_index(
                [("county", ASCENDING), ("status", ASCENDING), ("due_date", ASCENDING)]
            )
            self.db.follow_ups.create_index([("follow_up_id", ASCENDING)], unique=True)

            # ── chws ──────────────────────────────────────────────────────────
            self.db.chws.create_index([("chw_id", ASCENDING)], unique=True)
            self.db.chws.create_index(
                [("county", ASCENDING), ("ward", ASCENDING), ("status", ASCENDING)]
            )
            self.db.chws.create_index([("telegram_id", ASCENDING)], sparse=True)

            # ── protocols ─────────────────────────────────────────────────────
            self.db.protocols.create_index(
                [("syndrome", ASCENDING), ("county", ASCENDING)], unique=True
            )
            self.db.protocols.create_index([("status", ASCENDING)])

            # ── baselines ─────────────────────────────────────────────────────
            self.db.baselines.create_index(
                [("county", ASCENDING), ("syndrome", ASCENDING)], unique=True
            )

            # ── agent_logs ────────────────────────────────────────────────────
            self.db.agent_logs.create_index(
                [("session_id", ASCENDING), ("timestamp", ASCENDING)]
            )
            self.db.agent_logs.create_index([("agent_name", ASCENDING)])

            logger.info("✅ MongoDB indexes verified across all collections")
        except OperationFailure as exc:
            logger.warning("Index creation warning: %s", exc)

    def create_vector_search_index(self) -> Dict[str, Any]:
        """
        Creates the Atlas Vector Search index on encounters.embedding.
        Requires MongoDB Atlas M10+ cluster. Idempotent — safe to call repeatedly.
        Uses 3072 dims to match gemini-embedding-001 (or 1024 for Voyage AI).
        """
        from .embedding_service import get_embedding_dim
        dims = get_embedding_dim()
        index_def = {
            "mappings": {
                "dynamic": False,
                "fields": {
                    "embedding": {
                        "type": "knnVector",
                        "dimensions": dims,
                        "similarity": "cosine",
                    }
                },
            }
        }
        logger.info("Creating Atlas Vector Search indexes (dims=%d) ...", dims)
        try:
            self.db.command(
                "createSearchIndexes",
                "encounters",
                indexes=[{"name": "vector_index", "definition": index_def}],
            )
            logger.info("✅ Atlas Vector Search index created on encounters")
        except OperationFailure as exc:
            logger.info("Vector search index note (encounters may already exist): %s", exc)
            
        try:
            self.db.command(
                "createSearchIndexes",
                "agent_logs",
                indexes=[{"name": "vector_index", "definition": index_def}],
            )
            logger.info("✅ Atlas Vector Search index created on agent_logs")
            return {"created": True, "index": "vector_index", "dimensions": dims}
        except OperationFailure as exc:
            logger.info("Vector search index note (agent_logs may already exist): %s", exc)
            return {"created": False, "note": str(exc)}

    # ══════════════════════════════════════════════════════════════════════════
    # ENCOUNTERS
    # ══════════════════════════════════════════════════════════════════════════

    async def insert_encounter(self, encounter_doc: Dict[str, Any]) -> str:
        """Insert a geo-enriched encounter with vector embedding."""
        encounter_doc["timestamp"] = datetime.utcnow()
        encounter_doc["synced"] = True
        try:
            encounter_doc["embedding"] = (
                self.embedding_svc.generate_encounter_embedding(encounter_doc)
            )
        except Exception as exc:
            logger.warning("Embedding generation failed (non-fatal): %s", exc)

        loop = asyncio.get_running_loop()
        inserted_id = await loop.run_in_executor(
            None, lambda: self.db.encounters.insert_one(encounter_doc).inserted_id
        )
        logger.info("Encounter inserted: %s", inserted_id)
        return str(inserted_id)

    async def batch_insert_encounters(
        self, encounters: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Batch insert up to 50 encounters (offline sync). Generates embeddings."""
        now = datetime.utcnow()
        for doc in encounters:
            doc["timestamp"] = now
            doc["synced"] = True
            try:
                doc["embedding"] = self.embedding_svc.generate_encounter_embedding(doc)
            except Exception:
                pass

        loop = asyncio.get_running_loop()
        inserted_ids = await loop.run_in_executor(
            None,
            lambda: [
                str(i)
                for i in self.db.encounters.insert_many(
                    encounters, ordered=False
                ).inserted_ids
            ],
        )
        return {"inserted_count": len(inserted_ids), "inserted_ids": inserted_ids}

    async def sync_offline_encounters(
        self, encounters: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Process encounters queued while offline. Inserts in batches of 50."""
        total = len(encounters)
        synced = 0
        errors = 0
        for i in range(0, total, 50):
            batch = encounters[i : i + 50]
            try:
                result = await self.batch_insert_encounters(batch)
                synced += result["inserted_count"]
            except Exception as exc:
                logger.error("Batch sync error: %s", exc)
                errors += len(batch)
        return {"total": total, "synced": synced, "errors": errors}

    async def detect_schema_evolution(self, new_doc: Dict[str, Any]) -> List[str]:
        """Return list of new field names vs the most recent stored encounter."""
        loop = asyncio.get_running_loop()
        latest = await loop.run_in_executor(
            None,
            lambda: self.db.encounters.find_one(
                {}, sort=[("timestamp", DESCENDING)], projection={"_id": 0}
            ),
        )
        if not latest:
            return []
        new_keys = set(new_doc.keys()) - set(latest.keys())
        if new_keys:
            logger.info("Schema evolution detected — new fields: %s", new_keys)
        return list(new_keys)

    # ══════════════════════════════════════════════════════════════════════════
    # DEGRADED-MODE GUARD
    # ══════════════════════════════════════════════════════════════════════════

    def _check_db(self) -> bool:
        """Return True if DB is available; log a warning and return False if not.

        All synchronous methods that access self.db should call this first and
        return an empty/default result immediately when it returns False.
        This prevents AttributeError: 'NoneType' has no attribute '...' when
        MongoDB is unreachable (e.g., IP not on Atlas allowlist).
        """
        if not self.connected or self.db is None:
            logger.warning(
                "⚠️  MongoDB not connected — operation skipped (degraded mode). "
                "Add your IP to Atlas Network Access to restore connectivity."
            )
            return False
        return True

    # ══════════════════════════════════════════════════════════════════════════
    # ALERTS  (outbreak signals — separate from referrals)
    # ══════════════════════════════════════════════════════════════════════════

    def query_active_alerts(self, county: Optional[str] = None) -> List[Dict[str, Any]]:
        """Synchronous query for active alerts. Used by Telegram bot commands."""
        if not self._check_db():
            return []
        query: Dict[str, Any] = {"status": "active"}
        if county:
            query["location.county"] = county
        return list(
            self.db.alerts.find(query, {"_id": 0})
            .sort("timestamp", DESCENDING)
            .limit(20)
        )

    def get_active_alerts(self, county: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.query_active_alerts(county)

    async def update_alert_status(
        self, alert_id: str, status: str, user_id: str
    ) -> Dict[str, Any]:
        """Acknowledge or update an alert status."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.db.alerts.update_one(
                {"_id": ObjectId(alert_id)},
                {
                    "$set": {
                        "status": status,
                        "acknowledged_by": user_id,
                        "acknowledged_at": datetime.utcnow(),
                    }
                },
            ),
        )
        return {
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
        }

    async def resolve_alert(
        self, alert_id: str, notes: str, user_id: str
    ) -> Dict[str, Any]:
        """Mark an alert as resolved with notes."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.db.alerts.update_one(
                {"_id": ObjectId(alert_id)},
                {
                    "$set": {
                        "status": "resolved",
                        "resolved_by": user_id,
                        "resolved_at": datetime.utcnow(),
                        "resolution_notes": notes,
                    }
                },
            ),
        )
        return {
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
        }

    # ══════════════════════════════════════════════════════════════════════════
    # REFERRALS  (patient referral records — split from alerts collection)
    # ══════════════════════════════════════════════════════════════════════════

    async def insert_referral(self, encounter_doc: Dict[str, Any]) -> str:
        """
        Store a referral record for a RED/YELLOW triage encounter.
        Written to the dedicated `referrals` collection (not `alerts`).
        """
        extracted = encounter_doc.get("extracted", {})
        admin = encounter_doc.get("admin_hierarchy", {})
        facilities = encounter_doc.get("nearest_facilities", [])
        top_facility = facilities[0] if facilities else {}

        referral_doc = {
            "referral_id": f"REF-{uuid4().hex[:8].upper()}",
            "encounter_id": encounter_doc.get("encounter_id"),
            "timestamp": datetime.utcnow(),
            "status": "pending",  # pending → accepted / redirected
            "triage_color": extracted.get("triage_color"),
            "syndrome": extracted.get("syndrome"),
            "chief_complaint": extracted.get("chief_complaint", ""),
            "patient": {
                "age": extracted.get("age"),
                "sex": extracted.get("sex"),
            },
            "location": {
                "county": admin.get("county", "Unknown"),
                "sub_county": admin.get("sub_county", "Unknown"),
                "ward": admin.get("ward", "Unknown"),
                "coordinates": encounter_doc.get("location", {}).get("coordinates"),
            },
            "nearest_facility": {
                "name": top_facility.get("name", ""),
                "eta_minutes": top_facility.get("eta_minutes", 0),
                "place_id": top_facility.get("place_id", ""),
            },
            "all_facilities": facilities,
            "chw_id": encounter_doc.get("chw_id"),
        }

        loop = asyncio.get_running_loop()
        inserted_id = await loop.run_in_executor(
            None, lambda: self.db.referrals.insert_one(referral_doc).inserted_id
        )
        logger.info("Referral inserted: %s", inserted_id)
        return str(inserted_id)

    async def update_referral_status(
        self, referral_id: str, status: str, notes: str = ""
    ) -> Dict[str, Any]:
        """Update referral status: pending → accepted / redirected / completed."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.db.referrals.update_one(
                {"referral_id": referral_id},
                {
                    "$set": {
                        "status": status,
                        "updated_at": datetime.utcnow(),
                        "notes": notes,
                    }
                },
            ),
        )
        return {
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
        }

    def query_referrals(
        self,
        county: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Query referrals with optional county and status filters."""
        if not self._check_db():
            return []
        query: Dict[str, Any] = {}
        if county:
            query["location.county"] = county
        if status:
            query["status"] = status
        return list(
            self.db.referrals.find(query, {"_id": 0})
            .sort("timestamp", DESCENDING)
            .limit(limit)
        )

    # ══════════════════════════════════════════════════════════════════════════
    # FOLLOW-UPS  (patient follow-up task scheduling)
    # ══════════════════════════════════════════════════════════════════════════

    async def schedule_follow_ups(
        self, encounter_doc: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Auto-schedule follow-up tasks for a CHV based on triage color.

        Schedule rules (days after encounter):
          RED    → [1, 3, 7, 14]   — daily then weekly
          YELLOW → [2, 7, 14]      — 48h then weekly
          GREEN  → [7]             — single 7-day check

        Each follow-up is a separate document in the `follow_ups` collection,
        assigned to the CHW who recorded the encounter.

        Args:
            encounter_doc: Enriched encounter with encounter_id, chw_id, extracted.

        Returns:
            dict with scheduled_count and follow_up_ids.
        """
        extracted = encounter_doc.get("extracted", {})
        admin = encounter_doc.get("admin_hierarchy", {})
        triage = extracted.get("triage_color", "GREEN")
        encounter_id = encounter_doc.get("encounter_id", "")
        chw_id = encounter_doc.get("chw_id", "unknown")
        now = datetime.utcnow()

        day_offsets = FOLLOWUP_SCHEDULE.get(triage, FOLLOWUP_SCHEDULE["GREEN"])
        docs = []
        for day in day_offsets:
            due = now + timedelta(days=day)
            docs.append(
                {
                    "follow_up_id": f"FU-{uuid4().hex[:8].upper()}",
                    "encounter_id": encounter_id,
                    "chw_id": chw_id,
                    "county": admin.get("county", "Unknown"),
                    "ward": admin.get("ward", "Unknown"),
                    "due_date": due,
                    "day_offset": day,
                    "status": "pending",
                    "triage_color": triage,
                    "syndrome": extracted.get("syndrome", "unknown"),
                    "chief_complaint": extracted.get("chief_complaint", ""),
                    "patient": {
                        "age": extracted.get("age"),
                        "sex": extracted.get("sex"),
                    },
                    "created_at": now,
                    "notes": "",
                }
            )

        if not docs:
            return {"scheduled_count": 0, "follow_up_ids": []}

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.db.follow_ups.insert_many(docs, ordered=False),
        )
        ids = [str(i) for i in result.inserted_ids]
        logger.info(
            "Scheduled %d follow-ups for encounter %s (triage=%s)",
            len(ids),
            encounter_id,
            triage,
        )
        return {"scheduled_count": len(ids), "follow_up_ids": ids}

    def get_pending_follow_ups(
        self,
        chw_id: Optional[str] = None,
        county: Optional[str] = None,
        overdue_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve pending follow-up tasks for a CHW or county.
        Used by the Telegram /followup command and the dashboard.
        """
        if not self._check_db():
            return []
        query: Dict[str, Any] = {"status": "pending"}
        if chw_id:
            query["chw_id"] = chw_id
        if county:
            query["county"] = county
        if overdue_only:
            query["due_date"] = {"$lte": datetime.utcnow()}

        return list(
            self.db.follow_ups.find(query, {"_id": 0})
            .sort("due_date", ASCENDING)
            .limit(50)
        )

    async def complete_follow_up(
        self,
        follow_up_id: str,
        outcome: str,
        notes: str = "",
        chw_id: str = "unknown",
    ) -> Dict[str, Any]:
        """
        Mark a follow-up as completed with outcome and notes.

        Args:
            follow_up_id: The follow_up_id string.
            outcome:      'improved' | 'stable' | 'deteriorated' | 'referred' | 'deceased'
            notes:        Free-text CHV notes (voice-transcribed or typed).
            chw_id:       CHW who completed the follow-up.

        Returns:
            dict with matched_count and modified_count.
        """
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.db.follow_ups.update_one(
                {"follow_up_id": follow_up_id},
                {
                    "$set": {
                        "status": "completed",
                        "outcome": outcome,
                        "notes": notes,
                        "completed_by": chw_id,
                        "completed_at": datetime.utcnow(),
                    }
                },
            ),
        )
        return {
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
        }

    async def reschedule_follow_up(
        self,
        follow_up_id: str,
        new_due_date: datetime,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Reschedule a follow-up to a new date (e.g., patient was unavailable)."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.db.follow_ups.update_one(
                {"follow_up_id": follow_up_id},
                {
                    "$set": {
                        "due_date": new_due_date,
                        "rescheduled_at": datetime.utcnow(),
                        "reschedule_reason": reason,
                    }
                },
            ),
        )
        return {
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
        }

    def get_follow_up_summary(self, county: str) -> Dict[str, Any]:
        """
        Aggregate follow-up completion stats for a county.
        Used by the /status Telegram command and the dashboard.
        """
        pipeline = [
            {"$match": {"county": county}},
            {
                "$group": {
                    "_id": "$status",
                    "count": {"$sum": 1},
                }
            },
        ]
        rows = list(self.db.follow_ups.aggregate(pipeline))
        summary = {row["_id"]: row["count"] for row in rows}
        overdue = self.db.follow_ups.count_documents(
            {
                "county": county,
                "status": "pending",
                "due_date": {"$lte": datetime.utcnow()},
            }
        )
        return {
            "county": county,
            "pending": summary.get("pending", 0),
            "completed": summary.get("completed", 0),
            "overdue": overdue,
        }

    # ══════════════════════════════════════════════════════════════════════════
    # CHWs  (Community Health Worker registry)
    # ══════════════════════════════════════════════════════════════════════════

    async def register_chw(self, chw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Register or update a CHW in the registry.
        Called when a CHW first uses the Telegram bot (/register command).

        Args:
            chw_data: dict with chw_id, name, county, ward, telegram_id,
                      phone (optional), supervisor_id (optional).

        Returns:
            dict with chw_id and upserted status.
        """
        now = datetime.utcnow()
        chw_doc = {
            "chw_id": chw_data.get("chw_id", f"CHW-{uuid4().hex[:6].upper()}"),
            "name": chw_data.get("name", "Unknown"),
            "county": chw_data.get("county", "Unknown"),
            "ward": chw_data.get("ward", "Unknown"),
            "sub_county": chw_data.get("sub_county", ""),
            "telegram_id": chw_data.get("telegram_id"),
            "phone": chw_data.get("phone", ""),
            "supervisor_id": chw_data.get("supervisor_id", ""),
            "status": "active",
            "registered_at": now,
            "last_active": now,
            "languages": chw_data.get("languages", ["Swahili", "English"]),
        }

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.db.chws.update_one(
                {"chw_id": chw_doc["chw_id"]},
                {"$set": chw_doc, "$setOnInsert": {"created_at": now}},
                upsert=True,
            ),
        )
        logger.info("CHW registered/updated: %s", chw_doc["chw_id"])
        return {
            "chw_id": chw_doc["chw_id"],
            "upserted": result.upserted_id is not None,
            "modified": result.modified_count,
        }

    def get_chw(self, chw_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a CHW record by chw_id."""
        return self.db.chws.find_one({"chw_id": chw_id}, {"_id": 0})

    def get_chw_by_telegram(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a CHW record by Telegram chat ID."""
        return self.db.chws.find_one({"telegram_id": telegram_id}, {"_id": 0})

    def list_chws(
        self,
        county: Optional[str] = None,
        ward: Optional[str] = None,
        status: str = "active",
    ) -> List[Dict[str, Any]]:
        """List CHWs filtered by county, ward, and status."""
        query: Dict[str, Any] = {"status": status}
        if county:
            query["county"] = county
        if ward:
            query["ward"] = ward
        return list(self.db.chws.find(query, {"_id": 0}).sort("name", ASCENDING))

    async def update_chw_last_active(self, chw_id: str) -> None:
        """Stamp the CHW's last_active timestamp. Called on every encounter submission."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self.db.chws.update_one(
                {"chw_id": chw_id},
                {"$set": {"last_active": datetime.utcnow()}},
            ),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # PROTOCOLS  (WHO/MoH response protocols — written by Surveillance Agent)
    # ══════════════════════════════════════════════════════════════════════════

    async def upsert_protocol(self, protocol_doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Store or update a response protocol generated by the Surveillance Agent.
        Protocols are keyed by (syndrome, county) — county='all' for national protocols.

        Args:
            protocol_doc: Full protocol dict from formulate_response_protocol().

        Returns:
            dict with protocol_id and upserted status.
        """
        now = datetime.utcnow()
        syndrome = protocol_doc.get("syndrome", "unknown")
        county = protocol_doc.get("county", "all")

        # Embed the protocol text for semantic search
        protocol_text = (
            f"Protocol for {syndrome} in {county}. "
            f"Actions: {'; '.join(protocol_doc.get('immediate_actions', []))}. "
            f"CHW tasks: {'; '.join(protocol_doc.get('chw_actions', []))}."
        )
        try:
            protocol_doc["embedding"] = self.embedding_svc.generate_text_embedding(
                protocol_text
            )
        except Exception:
            pass  # embedding is best-effort

        protocol_doc.setdefault("protocol_id", f"PROTO-{uuid4().hex[:8].upper()}")
        protocol_doc["updated_at"] = now
        protocol_doc.setdefault("created_at", now)
        protocol_doc.setdefault("status", "active")

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.db.protocols.update_one(
                {"syndrome": syndrome, "county": county},
                {"$set": protocol_doc, "$setOnInsert": {"created_at": now}},
                upsert=True,
            ),
        )
        logger.info("Protocol upserted: %s / %s", syndrome, county)
        return {
            "protocol_id": protocol_doc["protocol_id"],
            "upserted": result.upserted_id is not None,
            "modified": result.modified_count,
        }

    def get_protocol(
        self,
        syndrome: str,
        county: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve the active protocol for a syndrome.
        Prefers county-specific protocol; falls back to national ('all').

        Args:
            syndrome: WHO IDSR syndrome category.
            county:   Optional county for localised protocol.

        Returns:
            Protocol dict or None if not found.
        """
        # Try county-specific first
        if county:
            doc = self.db.protocols.find_one(
                {"syndrome": syndrome, "county": county, "status": "active"},
                {"_id": 0, "embedding": 0},
                sort=[("updated_at", DESCENDING)],
            )
            if doc:
                return doc

        # Fall back to national protocol
        return self.db.protocols.find_one(
            {"syndrome": syndrome, "county": "all", "status": "active"},
            {"_id": 0, "embedding": 0},
            sort=[("updated_at", DESCENDING)],
        )

    def search_protocols_fulltext(
        self, query: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Full-text search across protocols using Atlas Search.
        Falls back to regex if Atlas Search index not available.

        Args:
            query: Free-text search (e.g., 'cholera ORS treatment').
            limit: Max results.

        Returns:
            List of matching protocol dicts.
        """
        try:
            pipeline = [
                {
                    "$search": {
                        "index": "protocols_text_search",
                        "text": {
                            "query": query,
                            "path": ["syndrome", "immediate_actions", "chw_actions"],
                            "fuzzy": {"maxEdits": 1},
                        },
                    }
                },
                {"$addFields": {"search_score": {"$meta": "searchScore"}}},
                {"$sort": {"search_score": DESCENDING}},
                {"$limit": limit},
                {"$project": {"_id": 0, "embedding": 0}},
            ]
            return list(self.db.protocols.aggregate(pipeline))
        except Exception:
            # Fallback: simple regex search
            import re

            pattern = re.compile(query, re.IGNORECASE)
            return list(
                self.db.protocols.find(
                    {
                        "$or": [
                            {"syndrome": pattern},
                            {"immediate_actions": pattern},
                            {"chw_actions": pattern},
                        ]
                    },
                    {"_id": 0, "embedding": 0},
                ).limit(limit)
            )

    def list_protocols(self, county: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all active protocols, optionally filtered by county."""
        query: Dict[str, Any] = {"status": "active"}
        if county:
            query["$or"] = [{"county": county}, {"county": "all"}]
        return list(
            self.db.protocols.find(query, {"_id": 0, "embedding": 0}).sort(
                "syndrome", ASCENDING
            )
        )

    # ══════════════════════════════════════════════════════════════════════════
    # ATLAS SEARCH INDEX MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════

    def ensure_search_indexes(self) -> Dict[str, Any]:
        """
        Create all Atlas Search and Vector Search indexes idempotently.
        Called on startup. Requires MongoDB Atlas M10+ cluster.

        Indexes created:
          encounters.vector_index         — Atlas Vector Search (1024 or 768 dims)
          protocols.protocols_text_search — Atlas Search full-text
          encounters.encounters_search    — Atlas Search full-text on encounters
          alerts.alerts_search            — Atlas Search on alerts
        """
        from .embedding_service import get_embedding_dim
        results: Dict[str, Any] = {}

        dim = get_embedding_dim()

        # ── 1. encounters: Vector Search ──────────────────────────────────────
        vector_def = {
            "fields": [{
                "type":          "vector",
                "path":          "embedding",
                "numDimensions": dim,
                "similarity":    "cosine",
            }]
        }
        results["vector_index"] = self._create_search_index(
            "encounters", "vector_index", vector_def, index_type="vectorSearch"
        )

        # ── 2. protocols: full-text Atlas Search ──────────────────────────────
        proto_def = {
            "mappings": {
                "dynamic": False,
                "fields": {
                    "syndrome":         {"type": "string", "analyzer": "lucene.standard"},
                    "immediate_actions": {"type": "string", "analyzer": "lucene.standard"},
                    "chw_actions":       {"type": "string", "analyzer": "lucene.standard"},
                    "county":            {"type": "string"},
                    "alert_level":       {"type": "string"},
                }
            }
        }
        results["protocols_text_search"] = self._create_search_index(
            "protocols", "protocols_text_search", proto_def
        )

        # ── 3. encounters: full-text Atlas Search ─────────────────────────────
        enc_def = {
            "mappings": {
                "dynamic": False,
                "fields": {
                    "extracted.syndrome":         {"type": "string", "analyzer": "lucene.standard"},
                    "extracted.chief_complaint":  {"type": "string", "analyzer": "lucene.standard"},
                    "extracted.primary_symptoms": {"type": "string", "analyzer": "lucene.standard"},
                    "admin_hierarchy.county":     {"type": "string"},
                    "admin_hierarchy.ward":        {"type": "string"},
                    "chw_id":                      {"type": "string"},
                }
            }
        }
        results["encounters_search"] = self._create_search_index(
            "encounters", "encounters_search", enc_def
        )

        # ── 4. alerts: full-text Atlas Search ────────────────────────────────
        alert_def = {
            "mappings": {
                "dynamic": False,
                "fields": {
                    "syndrome":            {"type": "string", "analyzer": "lucene.standard"},
                    "location.county":     {"type": "string"},
                    "location.ward":       {"type": "string"},
                    "alert_type":          {"type": "string"},
                    "status":              {"type": "string"},
                }
            }
        }
        results["alerts_search"] = self._create_search_index(
            "alerts", "alerts_search", alert_def
        )

        logger.info("✅ Atlas Search indexes verified: %s",
                    {k: v.get("status") for k, v in results.items()})
        return results

    def _create_search_index(
        self,
        collection: str,
        index_name: str,
        definition: Dict[str, Any],
        index_type: str = "search",
    ) -> Dict[str, Any]:
        """
        Create an Atlas Search or Atlas Vector Search index idempotently.
        Uses the pymongo 4.7+ SearchIndexModel API when available,
        falls back to the createSearchIndexes database command.
        """
        try:
            # pymongo >= 4.7 exposes create_search_index
            from pymongo.operations import SearchIndexModel  # type: ignore
            model = SearchIndexModel(definition=definition, name=index_name,
                                     type=index_type)
            self.db[collection].create_search_index(model)
            return {"status": "created", "index": index_name}
        except Exception as create_exc:
            # Already exists or Atlas Search not supported on this tier
            if "already exists" in str(create_exc).lower() or \
               "duplicate" in str(create_exc).lower():
                return {"status": "exists", "index": index_name}
            # Fallback: raw command
            try:
                self.db.command(
                    "createSearchIndexes",
                    collection,
                    indexes=[{
                        "name":       index_name,
                        "type":       index_type,
                        "definition": definition,
                    }],
                )
                return {"status": "created_via_command", "index": index_name}
            except Exception as cmd_exc:
                logger.warning("Search index '%s' on '%s': %s",
                               index_name, collection, cmd_exc)
                return {"status": "skipped", "index": index_name,
                        "reason": str(cmd_exc)}

    # ══════════════════════════════════════════════════════════════════════════
    # ATLAS VECTOR SEARCH — semantic similarity queries
    # ══════════════════════════════════════════════════════════════════════════

    def vector_search_encounters(
        self,
        query_text: str,
        county: Optional[str] = None,
        syndrome: Optional[str] = None,
        limit: int = 10,
        num_candidates: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Find clinically similar past encounters using Atlas Vector Search.
        Uses a QUERY embedding (not document) for best recall.

        Practical uses:
          - "Find similar cases to this child with fever + rash in Kisumu"
          - Silent pandemic detection: cluster similar cases across counties
          - Protocol recommendation: surface how similar cases were managed

        Args:
            query_text:     Natural-language clinical description.
            county:         Optional county filter (post-filter).
            syndrome:       Optional syndrome filter (post-filter).
            limit:          Number of results (default 10).
            num_candidates: ANN candidates before filtering (default 100).

        Returns:
            List of encounter dicts with vector_score field.
        """
        if not self.connected or not self.embedding_svc:
            return []

        query_vec = self.embedding_svc.generate_query_embedding(query_text)

        # Build post-filters
        post_filter: Dict[str, Any] = {}
        if county:
            post_filter["admin_hierarchy.county"] = county
        if syndrome:
            post_filter["extracted.syndrome"] = syndrome

        pipeline: List[Dict[str, Any]] = [
            {
                "$vectorSearch": {
                    "index":         "vector_index",
                    "path":          "embedding",
                    "queryVector":   query_vec,
                    "numCandidates": num_candidates,
                    "limit":         limit,
                    **({"filter": post_filter} if post_filter else {}),
                }
            },
            {
                "$addFields": {
                    "vector_score": {"$meta": "vectorSearchScore"}
                }
            },
            {
                "$project": {
                    "_id":       0,
                    "embedding": 0,
                }
            },
        ]

        try:
            results = list(self.db.encounters.aggregate(pipeline))
            logger.info("Vector search: %d results for '%s'",
                        len(results), query_text[:60])
            return results
        except Exception as exc:
            logger.error("Vector search failed: %s", exc)
            return []

    def vector_search_protocols(
        self,
        query_text: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search across response protocols.
        Called when a CHW asks "what do I do for a child with bloody diarrhea?"

        Args:
            query_text: Free-text clinical question in any language (pre-translated).
            limit:      Max results (default 5).

        Returns:
            List of protocol dicts ranked by semantic similarity.
        """
        if not self.connected or not self.embedding_svc:
            return []

        query_vec = self.embedding_svc.generate_query_embedding(query_text)
        pipeline: List[Dict[str, Any]] = [
            {
                "$vectorSearch": {
                    "index":         "vector_index",
                    "path":          "embedding",
                    "queryVector":   query_vec,
                    "numCandidates": 50,
                    "limit":         limit,
                }
            },
            {"$addFields": {"vector_score": {"$meta": "vectorSearchScore"}}},
            {"$project": {"_id": 0, "embedding": 0}},
        ]
        try:
            return list(self.db.protocols.aggregate(pipeline))
        except Exception as exc:
            logger.error("Protocol vector search failed: %s", exc)
            # Fallback to full-text search
            return self.search_protocols_fulltext(query_text, limit)

    # ══════════════════════════════════════════════════════════════════════════
    # ATLAS SEARCH — full-text search across encounters and alerts
    # ══════════════════════════════════════════════════════════════════════════

    def search_encounters(
        self,
        query: str,
        county: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Full-text Atlas Search across encounter records.
        Searches chief_complaint, syndrome, symptoms, and location fields.
        Falls back to regex if Atlas Search index unavailable.
        """
        try:
            search_stage: Dict[str, Any] = {
                "$search": {
                    "index": "encounters_search",
                    "compound": {
                        "must": [{
                            "text": {
                                "query": query,
                                "path": [
                                    "extracted.chief_complaint",
                                    "extracted.syndrome",
                                    "extracted.primary_symptoms",
                                ],
                                "fuzzy": {"maxEdits": 1},
                            }
                        }],
                        **({"filter": [{"text": {"query": county,
                                                  "path": "admin_hierarchy.county"}}]}
                           if county else {}),
                    },
                }
            }
            pipeline = [
                search_stage,
                {"$addFields": {"search_score": {"$meta": "searchScore"}}},
                {"$sort": {"search_score": DESCENDING}},
                {"$limit": limit},
                {"$project": {"_id": 0, "embedding": 0}},
            ]
            return list(self.db.encounters.aggregate(pipeline))
        except Exception:
            import re
            pattern = re.compile(query, re.IGNORECASE)
            q: Dict[str, Any] = {
                "$or": [
                    {"extracted.chief_complaint": pattern},
                    {"extracted.syndrome": pattern},
                ]
            }
            if county:
                q["admin_hierarchy.county"] = county
            return list(
                self.db.encounters.find(q, {"_id": 0, "embedding": 0}).limit(limit)
            )

    def search_alerts(
        self,
        query: str,
        county: Optional[str] = None,
        status: str = "active",
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Full-text Atlas Search across outbreak alerts.
        Falls back to regex query.
        """
        try:
            must = [{"text": {"query": query,
                               "path": ["syndrome", "location.county", "location.ward"],
                               "fuzzy": {"maxEdits": 1}}}]
            filter_clauses = [{"equals": {"path": "status", "value": status}}]
            if county:
                filter_clauses.append(
                    {"text": {"query": county, "path": "location.county"}}
                )
            pipeline = [
                {"$search": {"index": "alerts_search",
                              "compound": {"must": must, "filter": filter_clauses}}},
                {"$addFields": {"search_score": {"$meta": "searchScore"}}},
                {"$sort": {"search_score": DESCENDING}},
                {"$limit": limit},
                {"$project": {"_id": 0}},
            ]
            return list(self.db.alerts.aggregate(pipeline))
        except Exception:
            import re
            pattern = re.compile(query, re.IGNORECASE)
            q: Dict[str, Any] = {
                "status": status,
                "$or": [{"syndrome": pattern}, {"location.county": pattern}],
            }
            if county:
                q["location.county"] = county
            return list(self.db.alerts.find(q, {"_id": 0}).limit(limit))

    # ══════════════════════════════════════════════════════════════════════════
    # DASHBOARD AGGREGATIONS — pre-computed stats for the web portal
    # ══════════════════════════════════════════════════════════════════════════

    def get_national_dashboard(self) -> Dict[str, Any]:
        """
        Full national surveillance dashboard snapshot.
        Returned by GET /surveillance/dashboard for the web portal.

        Returns:
          - encounters_today / this_week / this_month
          - syndrome_breakdown (top syndromes, 7 days)
          - triage_breakdown (RED/YELLOW/GREEN counts, 7 days)
          - county_hotspots (counties with most active alerts)
          - active_alert_count / resolved_today
          - chw_activity (encounters per CHW, 7 days)
          - timeline (daily encounter counts, last 30 days)
        """
        if not self.connected:
            return {"status": "degraded", "message": "MongoDB not connected"}

        now = datetime.utcnow()
        today_start  = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago     = now - timedelta(days=7)
        month_ago    = now - timedelta(days=30)

        # ── encounter counts ──────────────────────────────────────────────────
        enc_today = self.db.encounters.count_documents(
            {"timestamp": {"$gte": today_start}}
        )
        enc_week  = self.db.encounters.count_documents(
            {"timestamp": {"$gte": week_ago}}
        )
        enc_month = self.db.encounters.count_documents(
            {"timestamp": {"$gte": month_ago}}
        )

        # ── syndrome breakdown (7 days) ───────────────────────────────────────
        syndrome_pipeline = [
            {"$match": {"timestamp": {"$gte": week_ago}}},
            {"$group": {"_id": "$extracted.syndrome", "count": {"$sum": 1}}},
            {"$sort": {"count": DESCENDING}},
            {"$limit": 10},
            {"$project": {"syndrome": "$_id", "count": 1, "_id": 0}},
        ]
        syndrome_breakdown = list(self.db.encounters.aggregate(syndrome_pipeline))

        # ── triage breakdown (7 days) ─────────────────────────────────────────
        triage_pipeline = [
            {"$match": {"timestamp": {"$gte": week_ago}}},
            {"$group": {"_id": "$extracted.triage_color", "count": {"$sum": 1}}},
            {"$project": {"triage": "$_id", "count": 1, "_id": 0}},
        ]
        triage_raw = list(self.db.encounters.aggregate(triage_pipeline))
        triage_breakdown = {r["triage"]: r["count"] for r in triage_raw if r.get("triage")}

        # ── county hotspots ───────────────────────────────────────────────────
        hotspot_pipeline = [
            {"$match": {"status": "active"}},
            {"$group": {"_id": "$location.county", "alert_count": {"$sum": 1}}},
            {"$sort": {"alert_count": DESCENDING}},
            {"$limit": 10},
            {"$project": {"county": "$_id", "alert_count": 1, "_id": 0}},
        ]
        county_hotspots = list(self.db.alerts.aggregate(hotspot_pipeline))

        # ── alert counts ──────────────────────────────────────────────────────
        active_alerts   = self.db.alerts.count_documents({"status": "active"})
        resolved_today  = self.db.alerts.count_documents(
            {"status": "resolved", "resolved_at": {"$gte": today_start}}
        )

        # ── daily timeline (last 30 days) ─────────────────────────────────────
        timeline_pipeline = [
            {"$match": {"timestamp": {"$gte": month_ago}}},
            {"$group": {
                "_id": {
                    "year":  {"$year":  "$timestamp"},
                    "month": {"$month": "$timestamp"},
                    "day":   {"$dayOfMonth": "$timestamp"},
                },
                "count": {"$sum": 1},
            }},
            {"$sort": {"_id.year": ASCENDING, "_id.month": ASCENDING, "_id.day": ASCENDING}},
            {"$project": {
                "_id": 0,
                "date": {"$dateToString": {
                    "format": "%Y-%m-%d",
                    "date": {"$dateFromParts": {
                        "year": "$_id.year", "month": "$_id.month", "day": "$_id.day"
                    }},
                }},
                "count": 1,
            }},
        ]
        timeline = list(self.db.encounters.aggregate(timeline_pipeline))

        # ── CHW activity (7 days) ─────────────────────────────────────────────
        chw_pipeline = [
            {"$match": {"timestamp": {"$gte": week_ago}}},
            {"$group": {
                "_id": "$chw_id",
                "encounters": {"$sum": 1},
                "red_cases":    {"$sum": {"$cond": [{"$eq": ["$extracted.triage_color", "RED"]},    1, 0]}},
                "yellow_cases": {"$sum": {"$cond": [{"$eq": ["$extracted.triage_color", "YELLOW"]}, 1, 0]}},
            }},
            {"$sort": {"encounters": DESCENDING}},
            {"$limit": 20},
            {"$project": {"chw_id": "$_id", "encounters": 1,
                          "red_cases": 1, "yellow_cases": 1, "_id": 0}},
        ]
        chw_activity = list(self.db.encounters.aggregate(chw_pipeline))

        return {
            "status":            "ok",
            "generated_at":      now.isoformat(),
            "encounters": {
                "today":      enc_today,
                "this_week":  enc_week,
                "this_month": enc_month,
            },
            "syndrome_breakdown": syndrome_breakdown,
            "triage_breakdown":   triage_breakdown,
            "county_hotspots":    county_hotspots,
            "alerts": {
                "active":         active_alerts,
                "resolved_today": resolved_today,
            },
            "timeline":     timeline,
            "chw_activity": chw_activity,
        }

    def get_county_dashboard(self, county: str) -> Dict[str, Any]:
        """
        County-level dashboard for the district officer view.
        Same shape as national dashboard but scoped to one county.
        """
        if not self.connected:
            return {"status": "degraded"}

        now        = datetime.utcnow()
        week_ago   = now - timedelta(days=7)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        match_county = {"admin_hierarchy.county": county}
        match_week   = {"admin_hierarchy.county": county,
                        "timestamp": {"$gte": week_ago}}

        enc_today = self.db.encounters.count_documents(
            {**match_county, "timestamp": {"$gte": today_start}}
        )

        syndrome_pipeline = [
            {"$match": match_week},
            {"$group": {"_id": "$extracted.syndrome", "count": {"$sum": 1}}},
            {"$sort": {"count": DESCENDING}},
            {"$limit": 8},
            {"$project": {"syndrome": "$_id", "count": 1, "_id": 0}},
        ]

        active_alerts = list(
            self.db.alerts.find(
                {"location.county": county, "status": "active"},
                {"_id": 0},
            ).sort("detected_at", DESCENDING).limit(10)
        )

        pending_followups = self.db.follow_ups.count_documents(
            {"county": county, "status": "pending"}
        )
        overdue_followups = self.db.follow_ups.count_documents(
            {"county": county, "status": "pending",
             "due_date": {"$lte": now}}
        )
        active_chws = self.db.chws.count_documents(
            {"county": county, "status": "active"}
        )

        return {
            "county":            county,
            "status":            "ok",
            "generated_at":      now.isoformat(),
            "encounters_today":  enc_today,
            "syndrome_breakdown": list(
                self.db.encounters.aggregate(syndrome_pipeline)
            ),
            "active_alerts":     active_alerts,
            "alerts_count":      len(active_alerts),
            "follow_ups": {
                "pending": pending_followups,
                "overdue": overdue_followups,
            },
            "active_chws": active_chws,
        }

    # ══════════════════════════════════════════════════════════════════════════
    # UPDATE REFERRAL STATUS  (called from Telegram bot callback)
    # ══════════════════════════════════════════════════════════════════════════

    def update_referral_status_sync(
        self, referral_id: str, status: str, notes: str = ""
    ) -> Dict[str, Any]:
        """Synchronous referral status update for Telegram callbacks."""
        result = self.db.referrals.update_one(
            {"referral_id": referral_id},
            {"$set": {"status": status, "notes": notes,
                       "updated_at": datetime.utcnow()}},
        )
        return {"matched": result.matched_count, "modified": result.modified_count}

    # ══════════════════════════════════════════════════════════════════════════
    # SEARCH PROTOCOLS  (kept for backward compat with data/agent.py)
    # ══════════════════════════════════════════════════════════════════════════

    def search_protocols(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Hybrid search: try vector search first, fall back to full-text.
        Used by the ADK tool and the /tool/search_protocols endpoint.
        """
        # Try semantic (vector) first — higher quality
        vec_results = self.vector_search_protocols(query, limit=limit)
        if vec_results:
            return vec_results
        # Fall back to Atlas Search full-text
        return self.search_protocols_fulltext(query, limit=limit)

    # ══════════════════════════════════════════════════════════════════════════
    # AGENT LOGS
    # ══════════════════════════════════════════════════════════════════════════

    async def insert_agent_log(
        self, agent_name: str, step: str, detail: str, level: str, session_id: str
    ) -> str:
        """Insert a vectorized agent decision log."""
        doc = {
            "agent_name": agent_name,
            "step": step,
            "detail": detail,
            "level": level,
            "session_id": session_id,
            "timestamp": datetime.utcnow(),
        }
        try:
            doc["embedding"] = self.embedding_svc.generate_text_embedding(
                f"{agent_name} [{step}]: {detail}"
            )
        except Exception as exc:
            logger.warning("Agent log embedding failed: %s", exc)

        loop = asyncio.get_running_loop()
        inserted_id = await loop.run_in_executor(
            None, lambda: self.db.agent_logs.insert_one(doc).inserted_id
        )
        return str(inserted_id)

    def query_agent_logs(self, session_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch recent agent logs, optionally filtered by session."""
        query = {}
        if session_id:
            query["session_id"] = session_id

        cursor = self.db.agent_logs.find(query, {"embedding": 0}).sort("timestamp", DESCENDING).limit(limit)
        results = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            if "timestamp" in doc:
                doc["timestamp"] = doc["timestamp"].isoformat()
            results.append(doc)
        
        # Return in ascending order for UI display
        return list(reversed(results))

    def search_agent_logs(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Semantic search over agent logs using Atlas Vector Search."""
        try:
            query_vector = self.embedding_svc.generate_query_embedding(query)
        except Exception as exc:
            logger.error("Failed to generate query embedding: %s", exc)
            return []

        pipeline = [
            {
                "$vectorSearch": {
                    "index": "vector_index",
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": limit * 10,
                    "limit": limit,
                }
            },
            {"$project": {"embedding": 0, "score": {"$meta": "vectorSearchScore"}}},
        ]

        try:
            results = list(self.db.agent_logs.aggregate(pipeline))
            for doc in results:
                doc["_id"] = str(doc["_id"])
                if "timestamp" in doc:
                    doc["timestamp"] = doc["timestamp"].isoformat()
            return results
        except OperationFailure as exc:
            logger.error("Vector search failed on agent_logs: %s", exc)
            return []
