import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.analytics import CatalogField, FieldType, FilterSpec, SemanticCatalog
from utils.analytics_drilldown import DrilldownSpec, build_drilldown_statement


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
