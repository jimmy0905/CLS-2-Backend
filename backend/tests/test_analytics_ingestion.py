import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.backgrounTaskHandler import (
    affected_month_refresh_range,
    affected_month_refresh_ranges,
    affected_reporting_months,
    build_raw_row_data,
    catalog_rollup_names,
    existing_reporting_months,
)


def test_new_upload_raw_rows_are_json_objects() -> None:
    row = pd.Series(
        {
            "score": 4.5,
            "visited_at": datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc),
        }
    )

    result = build_raw_row_data(7, row)

    assert result == {
        "index": 7,
        "row": {"score": 4.5, "visited_at": "2026-08-25 12:00:00+00:00"},
    }
    assert isinstance(result, dict)


def test_raw_rows_preserve_explicit_non_finite_values_for_dq_detection() -> None:
    row = pd.Series(
        {
            "missing_weight": float("nan"),
            "infinite_weight": float("inf"),
            "negative_infinite_weight": float("-inf"),
            "textual_nan": "NaN",
        }
    )

    result = build_raw_row_data(8, row)

    assert result["row"] == {
        "missing_weight": None,
        "infinite_weight": "Infinity",
        "negative_infinite_weight": "-Infinity",
        "textual_nan": "NaN",
    }


def test_affected_reporting_months_are_sorted_and_deduplicated() -> None:
    dataframe = pd.DataFrame(
        {
            "survey_order_date": [
                "2026-08-25T12:00:00Z",
                "2026-07-01 01:00:00",
                "invalid",
                "2026-08-01 00:00:00",
            ]
        }
    )

    assert affected_reporting_months(dataframe) == ["2026-07", "2026-08"]


def test_affected_reporting_months_tolerate_a_missing_date_column() -> None:
    assert affected_reporting_months(pd.DataFrame({"answer": ["ok"]})) == []


def test_affected_month_refresh_range_covers_complete_partitions() -> None:
    assert affected_month_refresh_range(["2026-08", "2026-06", "2026-07"]) == (
        "2026-06-01",
        "2026-09-01",
    )
    assert affected_month_refresh_range([]) is None


def test_sparse_affected_months_create_separate_targeted_refreshes() -> None:
    assert affected_month_refresh_ranges(
        ["2026-01", "2026-02", "2026-05", "2026-12", "2027-01"]
    ) == [
        ("2026-01-01", "2026-03-01"),
        ("2026-05-01", "2026-06-01"),
        ("2026-12-01", "2027-02-01"),
    ]


def test_existing_months_are_included_before_an_upsert_moves_a_response() -> None:
    class Query:
        def filter(self, *_args):
            return self

        def all(self):
            return [(datetime(2026, 1, 15, tzinfo=timezone.utc),)]

    class Db:
        def query(self, *_args):
            return Query()

    dataframe = pd.DataFrame(
        {
            "survey_id": [101],
            "respondent_id": [202],
            "survey_order_date": ["2026-02-01T00:00:00Z"],
        }
    )

    assert existing_reporting_months(Db(), dataframe) == ["2026-01"]


def test_catalog_rollup_names_use_the_compiler_contract() -> None:
    assert catalog_rollup_names(
        {
            "cubeCatalog": {
                "rollups": [
                    {"name": "chart_store_score", "semanticView": "survey_responses"},
                    {"name": "chart_topics", "semanticView": "survey_topics"},
                ]
            }
        }
    ) == [
        "survey_responses.chart_store_score",
        "survey_topics.chart_topics",
    ]
