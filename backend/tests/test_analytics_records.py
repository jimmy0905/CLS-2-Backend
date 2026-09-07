import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.analytics.endpoints.analytics import RecordFilterInput, RecordQueryInput
from features.analytics.model.semantic import CatalogField, FieldType, SemanticCatalog
from features.analytics.repository import records
from features.analytics.repository.records import (
    DEFAULT_PROJECTED_RECORD_FIELDS,
    _json_value,
    build_projected_record_statement,
    query_records,
)


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
                slug="survey_id",
                label="Survey ID",
                semantic_view="survey_responses",
                data_type=FieldType.STRING,
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


def _filter(member: str, operator: str, *, value=None, values=None):
    return RecordFilterInput(
        member=member,
        operator=operator,
        value=value,
        values=values,
    )


def test_record_query_representation_contract_and_limits() -> None:
    default_projection = RecordQueryInput(
        resource="surveys",
        representation="projected",
    )
    assert default_projection.fields is None
    assert DEFAULT_PROJECTED_RECORD_FIELDS[:3] == ("id", "survey_id", "reported_at")

    custom = RecordQueryInput(
        resource="surveys",
        representation="projected",
        fields=["survey_id", "reported_at", "store_name"],
        cursor=100,
        size=250,
    )
    assert custom.fields == ("survey_id", "reported_at", "store_name")

    RecordQueryInput(resource="stores", representation="full", size=1_000)
    for payload in (
        {"resource": "surveys", "size": 101},
        {"resource": "surveys", "representation": "projected", "size": 251},
        {"resource": "stores", "representation": "projected"},
        {"resource": "surveys", "representation": "projected", "page": 2},
        {
            "resource": "surveys",
            "representation": "projected",
            "order": [{"member": "id", "direction": "asc"}],
        },
        {
            "resource": "surveys",
            "representation": "projected",
            "fields": ["id", "id"],
        },
        {"resource": "surveys", "fields": ["id"]},
        {"resource": "surveys", "cursor": 1},
    ):
        with pytest.raises(ValidationError):
            RecordQueryInput.model_validate(payload)


def test_full_record_response_keeps_page_total_and_nested_items(monkeypatch) -> None:
    survey = SimpleNamespace(to_dict=lambda timezone: {"id": 7, "store": {"store_key": 1}})

    class Query:
        def order_by(self, *args):
            return self

        def count(self):
            return 1

        def offset(self, value):
            assert value == 0
            return self

        def limit(self, value):
            assert value == 100
            return self

        def all(self):
            return [survey]

    monkeypatch.setattr(records, "build_record_query", lambda *args, **kwargs: Query())
    result = query_records(object(), "surveys", (), (), 1, 100, "Asia/Hong_Kong")

    assert result == {
        "resource": "surveys",
        "representation": "full",
        "items": [{"id": 7, "store": {"store_key": 1}}],
        "page": 1,
        "size": 100,
        "total": 1,
        "has_more": False,
        "timezone": "Asia/Hong_Kong",
    }


def test_projected_records_reject_role_hidden_field() -> None:
    with pytest.raises(ValueError, match="visible"):
        build_projected_record_statement(
            fields=("id", "private_score"),
            filters=(),
            cursor=None,
            size=100,
            timezone_name=None,
            catalog=_catalog(),
            role="viewer",
            raw_fields={"private_score": ("Private Score", FieldType.NUMBER)},
        )


def test_promoted_source_key_is_bound_and_cursor_is_stable() -> None:
    source_key = "score'); DROP TABLE surveys; --"
    statement = build_projected_record_statement(
        fields=("id", "private_score"),
        filters=(
            _filter("private_score", "greater_than", value=3),
        ),
        cursor=100,
        size=25,
        timezone_name=None,
        catalog=_catalog(),
        role="admin",
        raw_fields={"private_score": (source_key, FieldType.NUMBER)},
    )
    compiled = statement.compile()
    sql = str(compiled)

    assert source_key not in sql
    assert source_key in compiled.params.values()
    assert 26 in compiled.params.values()
    assert "is_deleted" in sql
    assert "ORDER BY surveys.id ASC" in sql
    assert 100 in compiled.params.values()


def test_projected_records_support_assignment_exists_filters() -> None:
    statement = build_projected_record_statement(
        fields=("id", "survey_id"),
        filters=(_filter("topic", "equals", value="Delivery"),),
        cursor=None,
        size=100,
        timezone_name=None,
        catalog=_catalog(),
        role="viewer",
        raw_fields={},
    ).compile()
    sql = str(statement)

    assert "EXISTS" in sql
    assert "survey_topics" in sql
    assert "topics" in sql


def test_projected_records_use_timezone_for_timestamp_filters_and_display() -> None:
    statement = build_projected_record_statement(
        fields=("id", "reported_at"),
        filters=(
            _filter(
                "reported_at",
                "greater_than_or_equal",
                value="2026-08-04",
            ),
        ),
        cursor=None,
        size=100,
        timezone_name="Asia/Hong_Kong",
        catalog=_catalog(),
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
            "Asia/Hong_Kong",
        )
        == "2026-08-04T00:30:00+08:00"
    )
