"""
SihaLink Embedding Service
Generates semantic embeddings for clinical encounters, protocols, and search queries.

Provider priority:
  1. Voyage AI  voyage-4  (1024 dims) — MongoDB's recommended partner.
     Best multilingual + medical retrieval quality. Required for production.
  2. Google gemini-embedding-001 (3072 dims) — via google-genai SDK (fallback)
  3. Zero vector — never crashes the pipeline

Two embedding types follow the Voyage AI best-practice distinction:
  document — used when inserting data (encounters, protocols)
  query    — used when searching (vector similarity, semantic search)
  Using the correct type significantly improves Atlas Vector Search recall.

Environment:
  VOYAGE_API_KEY — https://www.voyageai.com  (preferred)
  GEMINI_API_KEY — Google AI fallback
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("SihaLink-Embedding")

# ── Dimension constants ───────────────────────────────────────────────────────
VOYAGE_DIM  = 1024  # voyage-4
GOOGLE_DIM  = 3072  # gemini-embedding-001 (text-embedding-004 not available on v1)

_active_dim: int = GOOGLE_DIM   # updated at init


def get_embedding_dim() -> int:
    """Return the dimension of embeddings produced by the active provider."""
    return _active_dim


def _age_bucket(age: Optional[Dict[str, Any]]) -> str:
    if not age:
        return "unknown age"
    value = age.get("value", 0)
    unit  = age.get("unit", "years")
    if unit == "days":
        return "neonate"
    if unit == "months" or (unit == "years" and value < 5):
        return "under-5"
    if unit == "years" and value < 15:
        return "child"
    if unit == "years" and value < 60:
        return "adult"
    return "elderly"


class EmbeddingService:
    """
    Multi-provider embedding service with automatic fallback chain.
    Always produces a vector — never raises, never blocks the pipeline.

    Usage:
        svc = EmbeddingService()
        # Insert path (document)
        vec = svc.generate_encounter_embedding(encounter_doc)
        vec = svc.generate_text_embedding("cholera protocol")
        # Search path (query)
        vec = svc.generate_query_embedding("child with fever and diarrhea")
    """

    def __init__(self) -> None:
        global _active_dim
        self._voyage_client = None
        self._genai_client  = None
        self._genai_legacy  = None

        voyage_key = os.getenv("VOYAGE_API_KEY")
        gemini_key = os.getenv("GEMINI_API_KEY")

        # 1. Try Voyage AI
        if voyage_key:
            try:
                import voyageai
                self._voyage_client = voyageai.Client(api_key=voyage_key)
                _active_dim = VOYAGE_DIM
                logger.info("✅ Embedding: Voyage AI voyage-4 (%d dims)", VOYAGE_DIM)
            except ImportError:
                logger.warning("voyageai not installed — pip install voyageai")

        # 2. Try google-genai SDK
        # When GOOGLE_GENAI_USE_VERTEXAI=TRUE, use ADC (Application Default Credentials)
        # not an API key — Vertex AI rejects API keys with 401 UNAUTHENTICATED.
        if self._voyage_client is None:
            use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").upper() in ("1", "TRUE")
            if use_vertex:
                # Vertex AI path — uses ADC automatically, no api_key needed
                project  = os.getenv("GOOGLE_CLOUD_PROJECT", "")
                location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
                if project:
                    try:
                        from google import genai as _genai
                        self._genai_client = _genai.Client(
                            vertexai=True,
                            project=project,
                            location=location,
                        )
                        _active_dim = GOOGLE_DIM
                        logger.info(
                            "✅ Embedding: Vertex AI gemini-embedding-001 (%d dims) project=%s",
                            GOOGLE_DIM, project,
                        )
                    except Exception as exc:
                        logger.warning("Vertex AI embedding init failed: %s", exc)
                else:
                    logger.warning("GOOGLE_CLOUD_PROJECT not set — Vertex AI embedding unavailable")
            elif gemini_key:
                # AI Studio path — API key works here
                try:
                    from google import genai as _genai
                    self._genai_client = _genai.Client(api_key=gemini_key)
                    _active_dim = GOOGLE_DIM
                    logger.info("✅ Embedding: Google gemini-embedding-001 (%d dims)", GOOGLE_DIM)
                except ImportError:
                    logger.error("google-genai not installed — zero vectors will be used")

        if self._voyage_client is None and self._genai_client is None:
            logger.warning("⚠️  No embedding provider — set VOYAGE_API_KEY or GEMINI_API_KEY")

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def dimension(self) -> int:
        return _active_dim

    @property
    def provider(self) -> str:
        if self._voyage_client:
            return "voyage-4"
        if self._genai_client:
            return "gemini-embedding-001"
        return "none"

    def generate_encounter_embedding(self, encounter_doc: Dict[str, Any]) -> List[float]:
        """
        Generate a document embedding for a clinical encounter.
        Builds a rich clinical text fingerprint before embedding.
        """
        text = self._build_encounter_text(encounter_doc)
        return self._embed(text, input_type="document")

    def generate_text_embedding(self, text: str) -> List[float]:
        """Generate a document embedding for arbitrary text (protocols, notes)."""
        return self._embed(text, input_type="document")

    def generate_query_embedding(self, query_text: str) -> List[float]:
        """
        Generate a QUERY embedding for Atlas Vector Search.
        Voyage AI uses a different model path for queries vs documents —
        this distinction materially improves recall (15–30% in benchmarks).
        Always use this method when the vector will be used in $vectorSearch.
        """
        return self._embed(query_text, input_type="query")

    # ── Text fingerprint ──────────────────────────────────────────────────────

    def _build_encounter_text(self, encounter_doc: Dict[str, Any]) -> str:
        """
        Build an information-dense text fingerprint for embedding.
        Field order is consistent — improves clustering in vector space.
        """
        extracted = encounter_doc.get("extracted", {})
        admin     = encounter_doc.get("admin_hierarchy", {})

        syndrome     = extracted.get("syndrome", "unknown")
        symptoms     = ", ".join(extracted.get("primary_symptoms", [])) or "none"
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

    # ── Embedding dispatch ────────────────────────────────────────────────────

    def _embed(self, text: str, input_type: str = "document") -> List[float]:
        """
        Dispatch embedding to the active provider with fallback chain.
        Never raises — returns zero vector on total failure.

        input_type: "document" for inserts, "query" for $vectorSearch queries.
        """
        if not text or not text.strip():
            return [0.0] * _active_dim

        # 1. Voyage AI — best quality, natively supports document/query distinction
        if self._voyage_client:
            try:
                result = self._voyage_client.embed(
                    texts=[text],
                    model="voyage-4",
                    input_type=input_type,
                )
                vec = result.embeddings[0]
                if vec and len(vec) == VOYAGE_DIM:
                    return vec
            except Exception as exc:
                logger.warning("Voyage AI embed failed: %s", exc)

        # 2. Google genai SDK (gemini-embedding-001 — 3072 dims)
        if self._genai_client:
            try:
                from google.genai import types as gt
                task = (
                    "RETRIEVAL_DOCUMENT" if input_type == "document"
                    else "RETRIEVAL_QUERY"
                )
                resp = self._genai_client.models.embed_content(
                    model="gemini-embedding-001",
                    contents=text,
                    config=gt.EmbedContentConfig(
                        task_type=task,
                    ),
                )
                embs = resp.embeddings
                if embs and hasattr(embs[0], "values"):
                    vec = list(embs[0].values)
                    if len(vec) > 0:
                        return vec
            except Exception as exc:
                logger.warning("google-genai embed failed: %s", exc)

        logger.warning("All embedding providers failed — zero vector (%d dims)", _active_dim)
        return [0.0] * _active_dim
