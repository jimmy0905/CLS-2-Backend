import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.analytics import validate_identifier
from utils.analytics_catalog import candidate_slug, infer_candidate


def test_candidate_inference_records_type_drift_and_safe_samples() -> None:
    candidate = infer_candidate("Customer Score", [1, 2.5, "bad", None, 2.5])

    assert candidate.slug == "raw_customer_score"
    assert candidate.inferred_type == "string"
    assert candidate.type_conflicts == ["number", "string"]
    assert candidate.sample_values == [1, 2.5, "bad"]


def test_candidate_inference_distinguishes_boolean_date_and_time() -> None:
    assert infer_candidate("consent", [True, False]).inferred_type == "boolean"
    assert infer_candidate("day", [date(2026, 8, 25)]).inferred_type == "date"
    assert infer_candidate("at", [time(9, 30)]).inferred_type == "time"


def test_candidate_slug_is_bounded_and_stable() -> None:
    header = "A very long imported header " * 10

    first = candidate_slug(header)

    assert first == candidate_slug(header)
    assert len(first) <= 63
    assert validate_identifier(first) == first
    assert first.startswith("raw_a_very_long_imported_header")


def test_candidate_samples_are_bounded_before_persistence() -> None:
    candidate = infer_candidate("comment", ["x" * 10_000])

    assert candidate.sample_values == ["x" * 500]


def test_candidate_samples_serialize_non_finite_numbers_as_dq_sentinels() -> None:
    candidate = infer_candidate("weight", [1.0, float("inf"), float("-inf")])

    assert candidate.sample_values == [1.0, "Infinity", "-Infinity"]
