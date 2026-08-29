"""Reference confidence interval calculations for analytics responses."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence

import numpy as np
from scipy import stats


MIN_CONFIDENCE_LEVEL = 0.8
MAX_CONFIDENCE_LEVEL = 0.999
_WEIGHTED_WARNING = (
    "Approximation uses Kish effective sample size; clustering and "
    "stratification are not modeled."
)


class WeightDataQualityError(ValueError):
    """A weighted calculation contains invalid values or weights."""

    def __init__(self, message: str, invalid_indices: Sequence[int] = ()) -> None:
        super().__init__(message)
        self.invalid_indices = tuple(invalid_indices)


@dataclass(frozen=True)
class ConfidenceInterval:
    estimate: float | None
    lower: float | None
    upper: float | None
    confidence_level: float
    sample_size: int
    effective_sample_size: float | None
    method: str
    approximate: bool = False
    warning: str | None = None


def validate_confidence_level(confidence_level: float) -> float:
    if (
        isinstance(confidence_level, bool)
        or not isinstance(confidence_level, (int, float))
        or not math.isfinite(float(confidence_level))
        or not MIN_CONFIDENCE_LEVEL <= float(confidence_level) <= MAX_CONFIDENCE_LEVEL
    ):
        raise ValueError("confidence level must be between 0.8 and 0.999")
    return float(confidence_level)


def _finite_values(values: Iterable[float | None]) -> np.ndarray:
    result: list[float] = []
    for value in values:
        if value is None:
            continue
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("values must be finite")
        result.append(numeric)
    return np.asarray(result, dtype=float)


def mean_confidence_interval(
    values: Iterable[float | None], confidence_level: float = 0.95
) -> ConfidenceInterval:
    confidence_level = validate_confidence_level(confidence_level)
    sample = _finite_values(values)
    size = int(sample.size)
    if size == 0:
        return ConfidenceInterval(
            None,
            None,
            None,
            confidence_level,
            0,
            None,
            "student_t_mean",
            warning="No non-null observations are available.",
        )
    estimate = float(np.mean(sample))
    if size < 2:
        return ConfidenceInterval(
            estimate,
            None,
            None,
            confidence_level,
            size,
            None,
            "student_t_mean",
            warning="Student-t interval requires at least two observations.",
        )
    standard_error = float(stats.sem(sample, ddof=1))
    if standard_error == 0:
        lower = upper = estimate
    else:
        critical = float(
            stats.t.ppf((1 + confidence_level) / 2, df=size - 1)
        )
        margin = critical * standard_error
        lower, upper = estimate - margin, estimate + margin
    return ConfidenceInterval(
        estimate,
        lower,
        upper,
        confidence_level,
        size,
        None,
        "student_t_mean",
    )


def proportion_confidence_interval(
    successes: int, total: int, confidence_level: float = 0.95
) -> ConfidenceInterval:
    confidence_level = validate_confidence_level(confidence_level)
    if (
        isinstance(successes, bool)
        or isinstance(total, bool)
        or not isinstance(successes, int)
        or not isinstance(total, int)
        or total < 0
        or successes < 0
        or successes > total
    ):
        raise ValueError("successes and total must satisfy 0 <= successes <= total")
    if total == 0:
        return ConfidenceInterval(
            None,
            None,
            None,
            confidence_level,
            0,
            None,
            "wilson_proportion",
            warning="No observations are available.",
        )
    estimate = successes / total
    z = float(stats.norm.ppf((1 + confidence_level) / 2))
    denominator = 1 + z * z / total
    center = (estimate + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            estimate * (1 - estimate) / total + z * z / (4 * total * total)
        )
        / denominator
    )
    return ConfidenceInterval(
        estimate,
        max(0.0, center - margin),
        min(1.0, center + margin),
        confidence_level,
        total,
        None,
        "wilson_proportion",
    )


def validate_weight_pairs(
    values: Iterable[float | None], weights: Iterable[float | None]
) -> tuple[np.ndarray, np.ndarray]:
    value_list = list(values)
    weight_list = list(weights)
    if len(value_list) != len(weight_list):
        raise ValueError("values and weights must have the same length")

    clean_values: list[float] = []
    clean_weights: list[float] = []
    invalid_weights: list[int] = []
    invalid_values: list[int] = []
    for index, (value, weight) in enumerate(zip(value_list, weight_list)):
        # The pairwise complete-case rule excludes either-side nulls.
        if value is None or weight is None:
            continue
        try:
            numeric_weight = float(weight)
            numeric_value = float(value)
        except (TypeError, ValueError):
            raise WeightDataQualityError(
                "Weighted metric contains a non-numeric value or weight", (index,)
            ) from None
        if not math.isfinite(numeric_weight) or numeric_weight < 0:
            invalid_weights.append(index)
        if not math.isfinite(numeric_value):
            invalid_values.append(index)
        if math.isfinite(numeric_weight) and numeric_weight >= 0 and math.isfinite(
            numeric_value
        ):
            clean_values.append(numeric_value)
            clean_weights.append(numeric_weight)
    if invalid_weights:
        raise WeightDataQualityError(
            "Weighted metric contains a negative or non-finite weight",
            invalid_weights,
        )
    if invalid_values:
        raise WeightDataQualityError(
            "Weighted metric contains a non-finite value", invalid_values
        )
    return (
        np.asarray(clean_values, dtype=float),
        np.asarray(clean_weights, dtype=float),
    )


def kish_effective_sample_size(weights: Iterable[float | None]) -> float:
    numeric: list[float] = []
    invalid: list[int] = []
    for index, weight in enumerate(weights):
        if weight is None:
            continue
        try:
            value = float(weight)
        except (TypeError, ValueError):
            invalid.append(index)
            continue
        if not math.isfinite(value) or value < 0:
            invalid.append(index)
        else:
            numeric.append(value)
    if invalid:
        raise WeightDataQualityError(
            "Kish effective sample size requires non-negative finite weights",
            invalid,
        )
    if not numeric:
        return 0.0
    weight_array = np.asarray(numeric, dtype=float)
    squared_sum = float(np.dot(weight_array, weight_array))
    if squared_sum == 0:
        return 0.0
    return float(weight_array.sum() ** 2 / squared_sum)


def weighted_mean_confidence_interval(
    values: Iterable[float | None],
    weights: Iterable[float | None],
    confidence_level: float = 0.95,
) -> ConfidenceInterval:
    confidence_level = validate_confidence_level(confidence_level)
    sample, sample_weights = validate_weight_pairs(values, weights)
    size = int(sample.size)
    total_weight = float(sample_weights.sum())
    effective_size = kish_effective_sample_size(sample_weights)
    if size == 0 or total_weight <= 0:
        return ConfidenceInterval(
            None,
            None,
            None,
            confidence_level,
            size,
            effective_size,
            "kish_weighted_t_mean",
            approximate=True,
            warning=(
                "Weighted interval requires at least one pair with positive total "
                f"weight. {_WEIGHTED_WARNING}"
            ),
        )
    estimate = float(np.average(sample, weights=sample_weights))
    if effective_size <= 1:
        return ConfidenceInterval(
            estimate,
            None,
            None,
            confidence_level,
            size,
            effective_size,
            "kish_weighted_t_mean",
            approximate=True,
            warning=f"Effective sample size must exceed one. {_WEIGHTED_WARNING}",
        )

    variance = float(
        np.average(np.square(sample - estimate), weights=sample_weights)
    )
    standard_error = math.sqrt(variance / effective_size)
    if standard_error == 0:
        lower = upper = estimate
    else:
        critical = float(
            stats.t.ppf((1 + confidence_level) / 2, df=effective_size - 1)
        )
        margin = critical * standard_error
        lower, upper = estimate - margin, estimate + margin
    return ConfidenceInterval(
        estimate,
        lower,
        upper,
        confidence_level,
        size,
        effective_size,
        "kish_weighted_t_mean",
        approximate=True,
        warning=_WEIGHTED_WARNING,
    )


def weighted_proportion_confidence_interval(
    outcomes: Iterable[float | bool | None],
    weights: Iterable[float | None],
    confidence_level: float = 0.95,
) -> ConfidenceInterval:
    outcome_list = list(outcomes)
    for outcome in outcome_list:
        if outcome is not None and outcome not in {0, 1, False, True}:
            raise ValueError("weighted proportion outcomes must be zero or one")
    result = weighted_mean_confidence_interval(
        outcome_list, weights, confidence_level
    )
    return ConfidenceInterval(
        result.estimate,
        max(0.0, result.lower) if result.lower is not None else None,
        min(1.0, result.upper) if result.upper is not None else None,
        result.confidence_level,
        result.sample_size,
        result.effective_sample_size,
        "kish_weighted_t_proportion",
        approximate=True,
        warning=result.warning,
    )


def mean_confidence_interval_from_summary(
    *,
    estimate: float | None,
    sample_size: int,
    sample_variance: float | None,
    confidence_level: float = 0.95,
) -> ConfidenceInterval:
    """Calculate a Student-t interval from Cube supporting aggregates."""
    confidence_level = validate_confidence_level(confidence_level)
    if sample_size < 0:
        raise ValueError("sample size must be non-negative")
    if sample_size == 0 or estimate is None:
        return ConfidenceInterval(
            None, None, None, confidence_level, 0, None, "student_t_mean",
            warning="No non-null observations are available.",
        )
    estimate = float(estimate)
    if sample_size < 2 or sample_variance is None:
        return ConfidenceInterval(
            estimate, None, None, confidence_level, sample_size, None,
            "student_t_mean",
            warning="Student-t interval requires at least two observations.",
        )
    variance = float(sample_variance)
    if not math.isfinite(estimate) or not math.isfinite(variance) or variance < 0:
        raise ValueError("mean summary aggregates must be finite and valid")
    standard_error = math.sqrt(variance / sample_size)
    critical = float(stats.t.ppf((1 + confidence_level) / 2, df=sample_size - 1))
    margin = critical * standard_error
    return ConfidenceInterval(
        estimate,
        estimate - margin,
        estimate + margin,
        confidence_level,
        sample_size,
        None,
        "student_t_mean",
    )


def weighted_mean_confidence_interval_from_summary(
    *,
    pair_count: int,
    weight_sum: float,
    weight_sum_squares: float,
    weighted_value_sum: float,
    weighted_value_square_sum: float,
    confidence_level: float = 0.95,
) -> ConfidenceInterval:
    """Calculate the documented Kish approximation from Cube aggregates."""
    confidence_level = validate_confidence_level(confidence_level)
    numbers = (
        weight_sum,
        weight_sum_squares,
        weighted_value_sum,
        weighted_value_square_sum,
    )
    if pair_count < 0 or any(not math.isfinite(float(value)) for value in numbers):
        raise WeightDataQualityError("Weighted summary aggregates are invalid")
    if weight_sum < 0 or weight_sum_squares < 0:
        raise WeightDataQualityError("Weighted summary contains invalid weights")
    effective_size = (
        float(weight_sum) ** 2 / float(weight_sum_squares)
        if weight_sum_squares > 0
        else 0.0
    )
    if pair_count == 0 or weight_sum <= 0:
        return ConfidenceInterval(
            None, None, None, confidence_level, pair_count, effective_size,
            "kish_weighted_t_mean", approximate=True,
            warning=(
                "Weighted interval requires at least one pair with positive total "
                f"weight. {_WEIGHTED_WARNING}"
            ),
        )
    estimate = float(weighted_value_sum) / float(weight_sum)
    if effective_size <= 1:
        return ConfidenceInterval(
            estimate, None, None, confidence_level, pair_count, effective_size,
            "kish_weighted_t_mean", approximate=True,
            warning=f"Effective sample size must exceed one. {_WEIGHTED_WARNING}",
        )
    variance = max(
        0.0,
        float(weighted_value_square_sum) / float(weight_sum) - estimate * estimate,
    )
    standard_error = math.sqrt(variance / effective_size)
    critical = float(stats.t.ppf((1 + confidence_level) / 2, df=effective_size - 1))
    margin = critical * standard_error
    return ConfidenceInterval(
        estimate,
        estimate - margin,
        estimate + margin,
        confidence_level,
        pair_count,
        effective_size,
        "kish_weighted_t_mean",
        approximate=True,
        warning=_WEIGHTED_WARNING,
    )


def weighted_proportion_confidence_interval_from_summary(
    *,
    pair_count: int,
    weight_sum: float,
    weight_sum_squares: float,
    success_weight_sum: float,
    confidence_level: float = 0.95,
) -> ConfidenceInterval:
    result = weighted_mean_confidence_interval_from_summary(
        pair_count=pair_count,
        weight_sum=weight_sum,
        weight_sum_squares=weight_sum_squares,
        weighted_value_sum=success_weight_sum,
        weighted_value_square_sum=success_weight_sum,
        confidence_level=confidence_level,
    )
    return ConfidenceInterval(
        result.estimate,
        max(0.0, result.lower) if result.lower is not None else None,
        min(1.0, result.upper) if result.upper is not None else None,
        result.confidence_level,
        result.sample_size,
        result.effective_sample_size,
        "kish_weighted_t_proportion",
        approximate=True,
        warning=result.warning,
    )
