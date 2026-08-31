"""Survey-upload candidate discovery for the governed analytics catalog."""
from __future__ import annotations

import hashlib
import json
import math
import numbers
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Iterable

from core.time import utc_now


_NON_IDENTIFIER = re.compile(r"[^a-z0-9]+")
_MAX_SAMPLES = 5
_MAX_HEADERS_PER_UPLOAD = 500
_MAX_SOURCE_KEY_LENGTH = 128
_MAX_SAMPLE_TEXT_LENGTH = 500


@dataclass(frozen=True)
class CandidateInference:
    source_key: str
    slug: str
    inferred_type: str
    type_conflicts: list[str]
    sample_values: list[Any]


def candidate_slug(header: str) -> str:
    normalized = _NON_IDENTIFIER.sub("_", header.strip().lower()).strip("_")
    normalized = normalized or "field"
    slug = f"raw_{normalized}"
    if len(slug) <= 63:
        return slug
    digest = hashlib.sha256(header.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:54].rstrip('_')}_{digest}"


def _missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        result = value != value
        return bool(result)
    except (TypeError, ValueError):
        return False


def _value_type(value: Any) -> str | None:
    if _missing(value):
        return None
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, datetime):
        return "date"
    if isinstance(value, date):
        return "date"
    if isinstance(value, time):
        return "time"
    if isinstance(value, (int, float)):
        return "number" if math.isfinite(float(value)) else "string"
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.lower() in {"true", "false"}:
            return "boolean"
        try:
            parsed_number = float(stripped)
            if math.isfinite(parsed_number):
                return "number"
        except ValueError:
            pass
        try:
            datetime.fromisoformat(stripped.replace("Z", "+00:00"))
            return "date"
        except ValueError:
            pass
        try:
            time.fromisoformat(stripped)
            return "time"
        except ValueError:
            return "string"
    return "string"


def _sample_value(value: Any) -> Any:
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return _sample_value(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        numeric = float(value)
        if math.isnan(numeric):
            return "NaN"
        if math.isinf(numeric):
            return "Infinity" if numeric > 0 else "-Infinity"
    if isinstance(value, str):
        return value[:_MAX_SAMPLE_TEXT_LENGTH]
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)[
            :_MAX_SAMPLE_TEXT_LENGTH
        ]
    return value


def infer_candidate(header: str, values: Iterable[Any]) -> CandidateInference:
    types: set[str] = set()
    samples: list[Any] = []
    for value in values:
        value_type = _value_type(value)
        if value_type is None:
            continue
        types.add(value_type)
        sample = _sample_value(value)
        if sample not in samples and len(samples) < _MAX_SAMPLES:
            samples.append(sample)

    conflicts = sorted(types)
    inferred = next(iter(types)) if len(types) == 1 else "string"
    return CandidateInference(
        source_key=header,
        slug=candidate_slug(header),
        inferred_type=inferred,
        type_conflicts=conflicts if len(conflicts) > 1 else [],
        sample_values=samples,
    )


def register_upload_candidates(db: Any, dataframe: Any) -> int:
    """Upsert inferred headers without publishing them or exposing samples."""
    from infrastructure.database.dbo.AnalyticsField import AnalyticsField

    changed = 0
    for raw_header in list(dataframe.columns)[:_MAX_HEADERS_PER_UPLOAD]:
        header = str(raw_header)
        if not header or len(header) > _MAX_SOURCE_KEY_LENGTH or "\x00" in header:
            continue
        source_values = dataframe[raw_header].tolist()
        candidate = infer_candidate(header, source_values[:250])
        occurrence_count = sum(not _missing(value) for value in source_values)
        field = (
            db.query(AnalyticsField)
            .filter(
                AnalyticsField.source_kind == "raw_json",
                AnalyticsField.source_key == header,
            )
            .first()
        )
        if field is None:
            slug = candidate.slug
            collision = (
                db.query(AnalyticsField)
                .filter(AnalyticsField.slug == slug)
                .first()
            )
            if collision is not None:
                digest = hashlib.sha256(header.encode("utf-8")).hexdigest()[:8]
                slug = f"{slug[:54].rstrip('_')}_{digest}"
            field = AnalyticsField(
                slug=slug,
                label=header[:120],
                data_type=candidate.inferred_type,
                inferred_data_type=candidate.inferred_type,
                type_conflicts=candidate.type_conflicts,
                sample_values=candidate.sample_values,
                source_kind="raw_json",
                source_key=header,
                definition={},
                status="candidate",
                visibility="admin",
                is_promoted=False,
                occurrence_count=occurrence_count,
                last_seen_at=utc_now(),
                created_by_subject=None,
                created_by_label=None,
                created_by_role=None,
            )
            db.add(field)
        else:
            combined_conflicts = set(field.type_conflicts or [])
            if field.inferred_data_type and field.inferred_data_type != candidate.inferred_type:
                combined_conflicts.add(field.inferred_data_type)
                combined_conflicts.add(candidate.inferred_type)
            combined_samples = list(field.sample_values or [])
            for sample in candidate.sample_values:
                if sample not in combined_samples and len(combined_samples) < _MAX_SAMPLES:
                    combined_samples.append(sample)
            field.inferred_data_type = (
                candidate.inferred_type if not combined_conflicts else "string"
            )
            field.type_conflicts = sorted(combined_conflicts)
            field.sample_values = combined_samples
            field.occurrence_count = (field.occurrence_count or 0) + occurrence_count
            field.last_seen_at = utc_now()
        changed += 1
    db.flush()
    return changed
