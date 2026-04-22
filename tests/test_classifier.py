"""Classifier tests: each training example should classify to its labeled archetype.

Also validates that the score is normalized to [0, 1] and that reasons always
contain at least one entry.
"""

import pytest

from app.services.classifier import classify_job
from app.services.data_loader import load_classification_examples


@pytest.mark.parametrize("example", load_classification_examples())
def test_training_examples_classify_correctly(example):
    jd = example["job_title"] + ": " + " ".join(example["keywords"])
    result = classify_job(jd)
    assert result.archetype_id == example["chosen_archetype"], (
        f"{example['job_title']} -> got {result.archetype_id}, "
        f"expected {example['chosen_archetype']}"
    )
    assert 0.0 <= result.score <= 1.0
    assert result.reasons, "classifier should always surface at least one reason"


def test_fintech_jd_picks_B():
    jd = "Build financial transaction systems with auditability and compliance requirements."
    assert classify_job(jd).archetype_id == "B_fintech_transaction_systems"


def test_streaming_jd_picks_C():
    jd = "Own the Kafka streaming pipelines and real-time ingestion for our analytics platform."
    assert classify_job(jd).archetype_id == "C_data_streaming_systems"


def test_distributed_jd_picks_D():
    jd = "Backend infrastructure role focused on low latency, fault tolerance, and concurrency."
    assert classify_job(jd).archetype_id == "D_distributed_systems"


def test_empty_input_defaults_gracefully():
    result = classify_job("")
    assert result.archetype_id in {
        "A_general_ai_platform",
        "B_fintech_transaction_systems",
        "C_data_streaming_systems",
        "D_distributed_systems",
    }
    assert result.score == 0.0
    assert result.reasons
