from __future__ import annotations

import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.analytics_statistics import (
    WeightDataQualityError,
    kish_effective_sample_size,
    mean_confidence_interval,
    proportion_confidence_interval,
    validate_confidence_level,
    validate_weight_pairs,
    weighted_mean_confidence_interval,
    weighted_proportion_confidence_interval,
    mean_confidence_interval_from_summary,
    weighted_mean_confidence_interval_from_summary,
    weighted_proportion_confidence_interval_from_summary,
)


@pytest.mark.parametrize("level", [0.8, 0.95, 0.999])
def test_confidence_level_accepts_configured_range(level: float) -> None:
    assert validate_confidence_level(level) == level


@pytest.mark.parametrize("level", [0.7999, 1.0, float("nan")])
def test_confidence_level_rejects_out_of_range_or_non_finite(level: float) -> None:
    with pytest.raises(ValueError, match="confidence level"):
        validate_confidence_level(level)


def test_student_t_mean_interval_matches_reference_fixture() -> None:
    result = mean_confidence_interval([1, 2, 3, 4, 5], 0.95)

    assert result.estimate == pytest.approx(3.0)
    assert result.lower == pytest.approx(1.0367568385)
    assert result.upper == pytest.approx(4.9632431615)
    assert result.sample_size == 5
    assert result.effective_sample_size is None
    assert result.method == "student_t_mean"
    assert result.approximate is False


def test_mean_interval_handles_null_empty_small_and_constant_groups() -> None:
    empty = mean_confidence_interval([None, None], 0.95)
    assert empty.estimate is None
    assert empty.lower is None
    assert empty.sample_size == 0

    small = mean_confidence_interval([7, None], 0.95)
    assert small.estimate == 7
    assert small.lower is None
    assert "at least two" in (small.warning or "")

    constant = mean_confidence_interval([4, 4, 4], 0.95)
    assert constant.lower == 4
    assert constant.upper == 4


def test_wilson_proportion_interval_matches_reference_fixture() -> None:
    result = proportion_confidence_interval(50, 100, 0.95)

    assert result.estimate == pytest.approx(0.5)
    assert result.lower == pytest.approx(0.4038315304)
    assert result.upper == pytest.approx(0.5961684696)
    assert result.sample_size == 100
    assert result.method == "wilson_proportion"


def test_wilson_interval_rejects_invalid_counts_and_handles_empty_group() -> None:
    with pytest.raises(ValueError, match="successes"):
        proportion_confidence_interval(3, 2, 0.95)
    empty = proportion_confidence_interval(0, 0, 0.95)
    assert empty.estimate is None
    assert empty.sample_size == 0


def test_weight_validation_excludes_null_pairs_and_allows_zero_weights() -> None:
    values, weights = validate_weight_pairs(
        [1, None, 3, 4],
        [1, 2, None, 0],
    )

    assert values.tolist() == [1.0, 4.0]
    assert weights.tolist() == [1.0, 0.0]


@pytest.mark.parametrize(
    "weights",
    [
        [1, -1],
        [1, float("inf")],
        [1, float("nan")],
    ],
)
def test_invalid_weights_raise_visible_data_quality_error(weights: list[float]) -> None:
    with pytest.raises(WeightDataQualityError) as error:
        validate_weight_pairs([1, 2], weights)

    assert error.value.invalid_indices == (1,)


def test_kish_effective_sample_size_and_weighted_interval() -> None:
    assert kish_effective_sample_size([1, 1, 2]) == pytest.approx(8 / 3)

    result = weighted_mean_confidence_interval([1, 2, 3], [1, 1, 2], 0.95)

    assert result.estimate == pytest.approx(2.25)
    assert result.sample_size == 3
    assert result.effective_sample_size == pytest.approx(8 / 3)
    assert result.lower < result.estimate < result.upper
    assert result.method == "kish_weighted_t_mean"
    assert result.approximate is True
    assert "clustering" in (result.warning or "")


def test_weighted_interval_handles_zero_total_weight() -> None:
    result = weighted_mean_confidence_interval([1, 2], [0, 0], 0.95)

    assert result.estimate is None
    assert result.effective_sample_size == 0
    assert "positive total weight" in (result.warning or "")


def test_weighted_proportion_interval_is_bounded() -> None:
    result = weighted_proportion_confidence_interval(
        [1, 1, 0, 1],
        [1, 2, 1, 4],
        0.9,
    )

    assert result.estimate == pytest.approx(0.875)
    assert 0 <= result.lower <= result.estimate
    assert result.estimate <= result.upper <= 1
    assert result.method == "kish_weighted_t_proportion"


def test_non_finite_values_are_a_data_quality_error_when_weighted() -> None:
    with pytest.raises(WeightDataQualityError, match="non-finite value"):
        validate_weight_pairs([1, math.inf], [1, 1])


def test_mean_interval_from_cube_summary_matches_raw_fixture() -> None:
    summary = mean_confidence_interval_from_summary(
        estimate=3.0,
        sample_size=5,
        sample_variance=2.5,
        confidence_level=0.95,
    )

    assert summary == mean_confidence_interval([1, 2, 3, 4, 5], 0.95)


def test_weighted_interval_from_cube_summary_matches_raw_fixture() -> None:
    summary = weighted_mean_confidence_interval_from_summary(
        pair_count=3,
        weight_sum=4,
        weight_sum_squares=6,
        weighted_value_sum=9,
        weighted_value_square_sum=23,
        confidence_level=0.95,
    )
    raw = weighted_mean_confidence_interval([1, 2, 3], [1, 1, 2], 0.95)

    assert summary.estimate == pytest.approx(raw.estimate)
    assert summary.lower == pytest.approx(raw.lower)
    assert summary.upper == pytest.approx(raw.upper)
    assert summary.effective_sample_size == pytest.approx(raw.effective_sample_size)


def test_weighted_proportion_from_cube_summary_is_bounded() -> None:
    summary = weighted_proportion_confidence_interval_from_summary(
        pair_count=4,
        weight_sum=8,
        weight_sum_squares=22,
        success_weight_sum=7,
        confidence_level=0.9,
    )

    assert summary.estimate == pytest.approx(0.875)
    assert 0 <= summary.lower <= summary.estimate <= summary.upper <= 1
