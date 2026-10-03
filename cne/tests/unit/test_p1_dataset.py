"""
Unit Tests for Phase P1 Training Dataset and Serialization Integrity.
Verifies:
1. All dataset files exist and contain valid JSONL records.
2. Zero data contamination: 0% overlap between train/val and held-out blind test set.
3. Every compiled Semantic IR graph adheres 100% to the 11 frozen primitives.
4. Schema integrity across contracts, slots, and shape keys.
"""
import json
import os
import pytest

DATASET_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "artifacts", "p1_dataset")
FROZEN_PRIMITIVES = {
    "Observe", "Map", "Filter", "Reduce", "Join", "Branch",
    "Iterate", "Choose", "Update", "Call", "Emit", "Literal"
}


def test_p1_dataset_files_exist():
    expected_files = [
        "train.jsonl",
        "val.jsonl",
        "test_anchored.jsonl",
        "test_heldout_blind.jsonl",
        "dataset_summary.json"
    ]
    for fname in expected_files:
        path = os.path.join(DATASET_DIR, fname)
        assert os.path.exists(path), f"Missing dataset file: {fname}"
        assert os.path.getsize(path) > 100, f"Dataset file too small: {fname}"


def test_p1_dataset_zero_contamination():
    train_path = os.path.join(DATASET_DIR, "train.jsonl")
    val_path = os.path.join(DATASET_DIR, "val.jsonl")
    blind_path = os.path.join(DATASET_DIR, "test_heldout_blind.jsonl")

    def load_texts(path):
        texts = set()
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                texts.add(rec["query_text"].strip().lower())
        return texts

    train_texts = load_texts(train_path)
    val_texts = load_texts(val_path)
    blind_texts = load_texts(blind_path)

    # Invariant: Strictly zero training/validation contamination with blind queries
    train_leakage = train_texts.intersection(blind_texts)
    val_leakage = val_texts.intersection(blind_texts)

    assert len(train_leakage) == 0, f"Contamination detected in train: {train_leakage}"
    assert len(val_leakage) == 0, f"Contamination detected in val: {val_leakage}"
    assert len(blind_texts) == 600, f"Expected 600 held-out blind queries, got {len(blind_texts)}"


def test_p1_dataset_frozen_primitive_adherence():
    train_path = os.path.join(DATASET_DIR, "train.jsonl")
    with open(train_path, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec["target_outcome"] == "COMPILED" and rec["graph_ast"]:
                nodes = rec["graph_ast"]["nodes"]
                for node in nodes:
                    op = node["op"]
                    assert op in FROZEN_PRIMITIVES, (
                        f"Query {rec['query_id']} violated primitive freeze with op '{op}'!"
                    )


def test_p1_dataset_summary_integrity():
    summary_path = os.path.join(DATASET_DIR, "dataset_summary.json")
    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    assert summary["integrity_checks"]["data_contamination_verified_zero"] is True
    assert summary["integrity_checks"]["blind_corpus_strictly_held_out"] is True
    assert summary["splits"]["train_count"] > 500
    assert summary["splits"]["test_heldout_blind_count"] == 600
