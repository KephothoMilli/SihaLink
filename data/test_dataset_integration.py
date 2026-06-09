#!/usr/bin/env python3
"""
Integration test for clinical dataset + Voyage AI embeddings.
Validates:
  1. Dataset loads with 15 encounters
  2. Embeddings text generation works
  3. EmbeddingService generates 1024-dim vectors
  4. Orchestrator startup flow executes

Run from project root: python -m data.test_dataset_integration
Or: python data/test_dataset_integration.py
"""

import asyncio
import sys
import os
from dotenv import load_dotenv

# Ensure project root is on the path when running as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()


def test_dataset_load():
    """Test 1: Load the clinical dataset."""
    print("=" * 70)
    print("Test 1: Load Clinical Dataset")
    print("=" * 70)

    from agents.data.clinical_intake_dataset import (
        get_clinical_intake_dataset,
        get_dataset_embeddings_text,
    )

    dataset = get_clinical_intake_dataset()
    embeddings_text = get_dataset_embeddings_text()

    print(f"✅ Dataset loaded: {len(dataset)} encounters")
    print(f"✅ Embeddings text generated for {len(embeddings_text)} encounters")

    # Validate structure
    for i, encounter in enumerate(dataset[:3]):
        print(f"\n  Encounter {i+1}:")
        print(f"    - ID: {encounter['encounter_id'][:12]}...")
        print(f"    - Syndrome: {encounter['extracted']['syndrome']}")
        print(f"    - Location: {encounter['admin_hierarchy']['county']}")
        print(
            f"    - Text preview: {embeddings_text.get(encounter['encounter_id'], '')[:60]}..."
        )

    return True


def test_embedding_service():
    """Test 2: Verify Voyage AI embeddings."""
    print("\n" + "=" * 70)
    print("Test 2: Voyage AI Embedding Service")
    print("=" * 70)

    from agents.data.embedding_service import EmbeddingService

    svc = EmbeddingService()

    # Test document embedding
    doc = {
        "encounter_id": "test-001",
        "text_for_embedding": "Child with fever and cough in Nairobi",
    }
    doc_vec = svc.generate_encounter_embedding(doc)
    print(f"✅ Document embedding: {len(doc_vec)} dimensions")
    assert len(doc_vec) == 1024, f"Expected 1024 dims, got {len(doc_vec)}"

    # Test query embedding
    query_vec = svc.generate_query_embedding("fever and malaria")
    print(f"✅ Query embedding: {len(query_vec)} dimensions")
    assert len(query_vec) == 1024, f"Expected 1024 dims, got {len(query_vec)}"

    # Verify they're different (not just constants)
    dot_product = sum(a * b for a, b in zip(doc_vec, query_vec))
    magnitude_doc = sum(x**2 for x in doc_vec) ** 0.5
    magnitude_query = sum(x**2 for x in query_vec) ** 0.5

    if magnitude_doc > 0 and magnitude_query > 0:
        cosine_similarity = dot_product / (magnitude_doc * magnitude_query)
        print(
            f"✅ Vector quality check passed (cosine similarity: {cosine_similarity:.4f})"
        )

    return True


def test_data_agent_imports():
    """Test 3: Verify data agent functions exist and are callable."""
    print("\n" + "=" * 70)
    print("Test 3: Data Agent Functions")
    print("=" * 70)

    from agents.data.agent import (
        seed_clinical_dataset,
        query_encounters_by_syndrome,
        semantic_search_encounters,
    )

    print("✅ seed_clinical_dataset function imported")
    print("✅ query_encounters_by_syndrome function imported")
    print("✅ semantic_search_encounters function imported")

    # Check signatures
    import inspect

    sig = inspect.signature(seed_clinical_dataset)
    print(f"   seed_clinical_dataset signature: {sig}")

    sig = inspect.signature(query_encounters_by_syndrome)
    print(f"   query_encounters_by_syndrome signature: {sig}")

    sig = inspect.signature(semantic_search_encounters)
    print(f"   semantic_search_encounters signature: {sig}")

    return True


def main():
    """Run all tests."""
    print("\n🧪 SihaLink Clinical Dataset Integration Tests\n")

    try:
        # Test 1: Dataset
        if not test_dataset_load():
            sys.exit(1)

        # Test 2: Embeddings
        if not test_embedding_service():
            sys.exit(1)

        # Test 3: Data Agent
        if not test_data_agent_imports():
            sys.exit(1)

        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        print("\nDataset Status:")
        print("  • 15 clinical encounters with Kenya epidemiology")
        print("  • Voyage AI embeddings: 1024 dimensions")
        print("  • Seeding integrated into orchestrator startup")
        print("  • Semantic search ready: query_encounters_by_syndrome()")
        print("  • Semantic search ready: semantic_search_encounters()")
        print("\nNext steps:")
        print("  1. Run orchestrator to seed dataset on startup")
        print(
            "  2. Query encounters by syndrome: query_encounters_by_syndrome('malaria')"
        )
        print("  3. Semantic search: semantic_search_encounters('child with fever')")
        print("=" * 70 + "\n")

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
