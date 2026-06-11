#!/usr/bin/env python3
"""
SihaLink — Re-embed all MongoDB documents with Voyage AI voyage-3

Replaces any existing embeddings (wrong dimensions, zero vectors, or missing)
with fresh Voyage AI voyage-3 embeddings (1024 dims, cosine similarity).

Collections processed:
  encounters   — clinical encounter records (primary RAG collection)
  protocols    — WHO/MoH response protocols
  agent_logs   — agent decision logs

Usage:
  python data/reembed_voyage.py
  python data/reembed_voyage.py --dry-run          # preview only, no writes
  python data/reembed_voyage.py --collection encounters
  python data/reembed_voyage.py --batch-size 25
  python data/reembed_voyage.py --force             # re-embed even correct-dim docs

Requirements:
  VOYAGE_API_KEY and MONGODB_ATLAS_URI must be set in .env
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Load .env before any other imports ───────────────────────────────────────
ROOT = Path(__file__).parent.parent
env_path = ROOT / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("reembed")

VOYAGE_MODEL = "voyage-3"
VOYAGE_DIM   = 1024
BATCH_SIZE   = 20   # Voyage AI recommended batch size


# ── Voyage AI client ──────────────────────────────────────────────────────────

def get_voyage_client():
    api_key = os.getenv("VOYAGE_API_KEY")
    if not api_key:
        logger.error("VOYAGE_API_KEY not set in environment")
        sys.exit(1)
    try:
        import voyageai
        client = voyageai.Client(api_key=api_key)
        # Quick connectivity test
        test = client.embed(["test"], model=VOYAGE_MODEL, input_type="document")
        assert len(test.embeddings[0]) == VOYAGE_DIM, \
            f"Unexpected dim: {len(test.embeddings[0])}"
        logger.info("✅ Voyage AI connected — %s (%d dims)", VOYAGE_MODEL, VOYAGE_DIM)
        return client
    except ImportError:
        logger.error("voyageai not installed — run: pip install voyageai==0.3.7")
        sys.exit(1)
    except Exception as exc:
        logger.error("Voyage AI connection failed: %s", exc)
        sys.exit(1)


# ── MongoDB client ────────────────────────────────────────────────────────────

def get_db():
    uri = os.getenv("MONGODB_ATLAS_URI")
    if not uri:
        logger.error("MONGODB_ATLAS_URI not set in environment")
        sys.exit(1)
    from pymongo import MongoClient
    client = MongoClient(uri, appname="sihalink-reembed", serverSelectionTimeoutMS=10000)
    client.admin.command("ping")
    logger.info("✅ MongoDB connected")
    return client.sihalink


# ── Text builders (mirrors embedding_service.py) ─────────────────────────────

def _age_bucket(age: Optional[Dict[str, Any]]) -> str:
    if not age:
        return "unknown age"
    value = age.get("value", 0)
    unit  = age.get("unit", "years")
    if unit == "days":                              return "neonate"
    if unit == "months":                            return "under-5"
    if unit == "years" and value < 5:               return "under-5"
    if unit == "years" and value < 15:              return "child"
    if unit == "years" and value < 60:              return "adult"
    return "elderly"


def build_encounter_text(doc: Dict[str, Any]) -> str:
    extracted = doc.get("extracted", {})
    admin     = doc.get("admin_hierarchy", {})

    syndrome     = extracted.get("syndrome", "unknown")
    symptoms     = (
        ", ".join(extracted.get("symptoms", []) or extracted.get("primary_symptoms", []))
        or "none"
    )
    severity     = extracted.get("severity", "unknown")
    triage       = extracted.get("triage_color", "GREEN")
    complaint    = extracted.get("chief_complaint", "")
    danger_signs = ", ".join(extracted.get("danger_signs", [])) or "none"
    age_bucket   = _age_bucket(extracted.get("age"))
    sex          = extracted.get("sex", "unknown")
    duration     = extracted.get("duration_days")
    county       = admin.get("county", "")
    ward         = admin.get("ward", "")

    parts = [
        f"Syndrome: {syndrome}.",
        f"Symptoms: {symptoms}.",
        f"Severity: {severity}.",
        f"Triage: {triage}.",
    ]
    if complaint:
        parts.append(f"Chief complaint: {complaint}.")
    if danger_signs != "none":
        parts.append(f"Danger signs: {danger_signs}.")
    parts.append(f"Patient: {age_bucket} {sex}.")
    if duration:
        parts.append(f"Duration: {duration} days.")
    if county or ward:
        parts.append(f"Location: {ward} ward, {county} county, Kenya.")
    return " ".join(parts)


def build_protocol_text(doc: Dict[str, Any]) -> str:
    syndrome       = doc.get("syndrome", "unknown")
    alert_level    = doc.get("alert_level", "YELLOW")
    immediate      = "; ".join(doc.get("immediate_actions", [])[:3])
    chw_actions    = "; ".join(doc.get("chw_actions", [])[:3])
    return (
        f"Protocol: {syndrome} ({alert_level}). "
        f"Immediate actions: {immediate}. "
        f"CHW actions: {chw_actions}."
    )


def build_log_text(doc: Dict[str, Any]) -> str:
    agent  = doc.get("agent_name", "unknown")
    step   = doc.get("step", "")
    detail = doc.get("detail", "")
    return f"Agent: {agent}. Step: {step}. {detail}"


TEXT_BUILDERS = {
    "encounters": build_encounter_text,
    "protocols":  build_protocol_text,
    "agent_logs": build_log_text,
}


# ── Core re-embedding logic ───────────────────────────────────────────────────

def needs_reembed(doc: Dict[str, Any], force: bool) -> bool:
    """Return True if the document needs its embedding replaced."""
    if force:
        return True
    embedding = doc.get("embedding")
    if not embedding:
        return True                            # missing
    if not isinstance(embedding, list):
        return True                            # corrupt
    if len(embedding) != VOYAGE_DIM:
        return True                            # wrong dimension
    if all(v == 0.0 for v in embedding[:10]):
        return True                            # zero vector (failed embed)
    return False


def reembed_collection(
    db,
    voyage_client,
    collection_name: str,
    batch_size: int,
    dry_run: bool,
    force: bool,
) -> Dict[str, int]:
    """Re-embed all documents in a collection that need it."""
    from pymongo import UpdateOne

    coll        = db[collection_name]
    text_builder = TEXT_BUILDERS.get(collection_name)
    if not text_builder:
        logger.warning("No text builder for %s — skipping", collection_name)
        return {"skipped": 0, "updated": 0, "errors": 0, "total": 0}

    total   = coll.count_documents({})
    pending = [d for d in coll.find({}, {"_id": 1, "embedding": 1, "extracted": 1,
                                          "admin_hierarchy": 1, "syndrome": 1,
                                          "alert_level": 1, "immediate_actions": 1,
                                          "chw_actions": 1, "agent_name": 1,
                                          "step": 1, "detail": 1})
               if needs_reembed(d, force)]

    logger.info(
        "Collection %-12s: %d total, %d need re-embedding",
        collection_name, total, len(pending),
    )

    if not pending:
        return {"skipped": total, "updated": 0, "errors": 0, "total": total}

    updated = 0
    errors  = 0

    for i in range(0, len(pending), batch_size):
        batch = pending[i: i + batch_size]

        # Build texts
        texts  = []
        doc_ids = []
        for doc in batch:
            try:
                text = text_builder(doc)
                if text.strip():
                    texts.append(text)
                    doc_ids.append(doc["_id"])
            except Exception as exc:
                logger.warning("Text build failed for %s: %s", doc["_id"], exc)
                errors += 1

        if not texts:
            continue

        # Embed batch with Voyage AI (document type for inserts)
        try:
            result = voyage_client.embed(
                texts=texts,
                model=VOYAGE_MODEL,
                input_type="document",
            )
            embeddings = result.embeddings
        except Exception as exc:
            logger.error("Voyage AI batch embed failed (batch %d): %s", i // batch_size, exc)
            errors += len(texts)
            # Rate limit backoff
            time.sleep(2)
            continue

        # Validate and write
        ops = []
        for doc_id, emb in zip(doc_ids, embeddings):
            if len(emb) != VOYAGE_DIM:
                logger.warning("Unexpected dim %d for %s", len(emb), doc_id)
                errors += 1
                continue
            ops.append(UpdateOne(
                {"_id": doc_id},
                {"$set": {
                    "embedding":       emb,
                    "embedding_model": VOYAGE_MODEL,
                    "embedding_dim":   VOYAGE_DIM,
                    "reembedded_at":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }},
            ))

        if ops and not dry_run:
            try:
                res = coll.bulk_write(ops, ordered=False)
                updated += res.modified_count
            except Exception as exc:
                logger.error("Bulk write failed: %s", exc)
                errors += len(ops)
        elif ops and dry_run:
            updated += len(ops)   # count as "would update"

        done = min(i + batch_size, len(pending))
        pct  = done / len(pending) * 100
        logger.info(
            "  %s: %d/%d (%.0f%%) — %d updated%s",
            collection_name, done, len(pending), pct, updated,
            " [DRY RUN]" if dry_run else "",
        )

        # Polite rate limiting — Voyage AI free tier: 100 RPM
        time.sleep(0.7)

    return {
        "total":   total,
        "updated": updated,
        "skipped": total - len(pending),
        "errors":  errors,
    }


# ── Atlas Vector Search index ─────────────────────────────────────────────────

def recreate_vector_index(db, dry_run: bool) -> None:
    """
    Drop and recreate the Atlas Vector Search index with 1024 dims (voyage-3).
    Safe to run: index rebuild is async in Atlas — reads still work during rebuild.
    """
    if dry_run:
        logger.info("[DRY RUN] Would recreate vector_index with %d dims", VOYAGE_DIM)
        return

    index_def = {
        "fields": [{
            "type":          "vector",
            "path":          "embedding",
            "numDimensions": VOYAGE_DIM,
            "similarity":    "cosine",
        }]
    }

    for collection_name in ("encounters", "agent_logs"):
        coll = db[collection_name]
        # Drop existing index if present
        try:
            coll.drop_search_index("vector_index")
            logger.info("Dropped existing vector_index on %s", collection_name)
            time.sleep(2)   # allow Atlas to process the drop
        except Exception:
            pass  # Index may not exist yet

        # Create with correct dimensions
        try:
            coll.create_search_index({
                "name":       "vector_index",
                "type":       "vectorSearch",
                "definition": index_def,
            })
            logger.info(
                "✅ Vector index created on %s (%d dims, cosine)",
                collection_name, VOYAGE_DIM,
            )
        except Exception as exc:
            logger.warning("Index create note (%s): %s", collection_name, exc)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Re-embed SihaLink MongoDB documents with Voyage AI voyage-3"
    )
    parser.add_argument(
        "--collection",
        choices=["encounters", "protocols", "agent_logs", "all"],
        default="all",
        help="Which collection to re-embed (default: all)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=BATCH_SIZE,
        help=f"Documents per Voyage AI API call (default: {BATCH_SIZE})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview only — no writes to MongoDB",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-embed all documents even if they already have 1024-dim embeddings",
    )
    parser.add_argument(
        "--skip-index", action="store_true",
        help="Skip Atlas Vector Search index recreation",
    )
    args = parser.parse_args()

    print()
    print("=" * 58)
    print("     SihaLink -- Voyage AI Re-Embedding Script")
    print("=" * 58)
    print(f"  Model:      {VOYAGE_MODEL} ({VOYAGE_DIM} dims, cosine)")
    print(f"  Collection: {args.collection}")
    print(f"  Batch size: {args.batch_size}")
    print(f"  Dry run:    {args.dry_run}")
    print(f"  Force:      {args.force}")
    print()

    if args.dry_run:
        logger.warning("DRY RUN MODE — no changes will be written to MongoDB")

    voyage_client = get_voyage_client()
    db            = get_db()

    collections = (
        ["encounters", "protocols", "agent_logs"]
        if args.collection == "all"
        else [args.collection]
    )

    totals = {"total": 0, "updated": 0, "skipped": 0, "errors": 0}
    start  = time.time()

    for cname in collections:
        result = reembed_collection(
            db, voyage_client, cname,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            force=args.force,
        )
        for k in totals:
            totals[k] += result.get(k, 0)

    elapsed = time.time() - start

    # Recreate vector index with correct dims
    if not args.skip_index and "encounters" in collections:
        logger.info("Recreating Atlas Vector Search indexes...")
        recreate_vector_index(db, args.dry_run)

    print()
    print("=" * 58)
    print("             Re-Embedding Complete")
    print("=" * 58)
    print(f"  Documents processed : {totals['total']}")
    print(f"  Embeddings updated  : {totals['updated']}" + (" [DRY RUN]" if args.dry_run else ""))
    print(f"  Already correct     : {totals['skipped']}")
    print(f"  Errors              : {totals['errors']}")
    print(f"  Time elapsed        : {elapsed:.1f}s")
    if not args.dry_run:
        print()
        print("  NOTE: Atlas Vector Search index rebuild is async.")
        print("  Check status: MongoDB Atlas > Search Indexes > vector_index")
        print("  Status shows BUILDING then READY (usually 1-5 min).")
    print()


if __name__ == "__main__":
    main()
