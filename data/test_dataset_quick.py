#!/usr/bin/env python3
"""
Quick test: Just verify dataset loads.
Run from project root: python -m data.test_dataset_quick
Or: python data/test_dataset_quick.py
"""

import sys
import os

# Ensure project root is on the path when running as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("Importing clinical dataset...")
from agents.data.clinical_intake_dataset import (
    get_clinical_intake_dataset,
    get_dataset_embeddings_text,
)

print("Loading dataset...")
dataset = get_clinical_intake_dataset()
print(f"✅ Dataset loaded: {len(dataset)} encounters")

print("Generating embeddings text...")
embeddings_text = get_dataset_embeddings_text()
print(f"✅ Embeddings text: {len(embeddings_text)} entries")

print("\n✅ Dataset integration test PASSED")
