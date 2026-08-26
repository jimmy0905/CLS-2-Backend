from datetime import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.analytics import CatalogField, FieldType, FilterSpec, SemanticCatalog
from utils.analytics_drilldown import DrilldownSpec, _json_value, build_drilldown_statement


def _catalog() -> SemanticCatalog:
    return SemanticCatalog(
        fields=[
            CatalogField(
                slug="id",
                label="ID",
                semantic_view="survey_responses",
                data_type=FieldType.NUMBER,
            ),
            CatalogField(
                slug="store_name",
                label="Store",
                semantic_view="survey_responses",
                data_type=FieldType.STRING,
            ),
            CatalogField(
                slug="reported_at",
                label="Reported at",
                semantic_view="survey_responses",
                data_type=FieldType.DATE,
            ),
            CatalogField(
                slug="private_score",
                label="Private score",
                semantic_view="survey_responses",
                data_type=FieldType.NUMBER,
                visibility="admin",
            ),
        ]
    )


def test_drilldown_rejects_role_hidden_field() -> None:
    with pytest.raises(ValueError, match="visible"):
        build_drilldown_statement(
            DrilldownSpec(fields=["id", "private_score"]),
            _catalog(),
            role="viewer",
            raw_fields={"private_score": ("Private Score", FieldType.NUMBER)},
        )


def test_raw_source_key_is_bound_not_interpolated_into_sql() -> None:
    source_key = "score'); DROP TABLE surveys; --"
    statement = build_drilldown_statement(
        DrilldownSpec(
            fields=["id", "private_score"],
            filters=[
                FilterSpec(
                    member="private_score", operator="greater_than", value=3
                )
            ],
            cursor=100,
            limit=25,
        ),
        _catalog(),
        role="admin",
        raw_fields={"private_score": (source_key, FieldType.NUMBER)},
    )
    compiled = statement.compile()

    assert source_key not in str(compiled)
    assert source_key in compiled.params.values()
    assert 26 in compiled.params.values()


def test_drilldown_uses_timezone_for_timestamp_filters_and_display() -> None:
    spec = DrilldownSpec(
        fields=["id", "reported_at"],
        filters=[
            FilterSpec(
                member="reported_at",
                operator="greater_than_or_equal",
                value="2026-08-04",
            )
        ],
        timezone="Asia/Hong_Kong",
    )
    statement = build_drilldown_statement(
        spec,
        _catalog(),
        role="viewer",
        raw_fields={},
    ).compile()

    timestamp_values = [
        value for value in statement.params.values() if isinstance(value, datetime)
    ]
    assert timestamp_values == [datetime.fromisoformat("2026-08-03T16:00:00+00:00")]
    assert (
        _json_value(
            datetime.fromisoformat("2026-08-03T16:30:00+00:00"),
            spec.timezone,
        )
        == "2026-08-04T00:30:00+08:00"
    )
