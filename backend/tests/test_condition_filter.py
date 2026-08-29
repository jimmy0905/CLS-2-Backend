from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

from fastapi import HTTPException
import pandas as pd
from sqlalchemy.sql import operators

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.feedback.filtering import build_survey_filter_conditions
from features.ingestion.service import parse_optional_cls


class SurveyFilterDateRangeTests(unittest.TestCase):
    def test_parses_utc_timestamp_boundaries_as_aware_utc_datetimes(self) -> None:
        conditions = build_survey_filter_conditions(
            {
                "from_date": "2026-08-03T16:00:00.000Z",
                "to_date": "2026-08-04T16:00:00.000Z",
            }
        )

        self.assertEqual(
            conditions[1].right.value, datetime(2026, 8, 3, 16, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(
            conditions[2].right.value, datetime(2026, 8, 4, 16, 0, tzinfo=timezone.utc)
        )

    def test_converts_offset_aware_timestamp_to_aware_utc_datetime(self) -> None:
        conditions = build_survey_filter_conditions(
            {"from_date": "2026-08-04T00:00:00+08:00"}
        )

        self.assertEqual(
            conditions[1].right.value, datetime(2026, 8, 3, 16, 0, tzinfo=timezone.utc)
        )

    def test_to_date_uses_exclusive_upper_bound(self) -> None:
        conditions = build_survey_filter_conditions(
            {"to_date": "2026-08-04T16:00:00.000Z"}
        )

        self.assertIs(conditions[1].operator, operators.lt)

    def test_rejects_invalid_timestamp_format(self) -> None:
        with self.assertRaises(HTTPException) as error_context:
            build_survey_filter_conditions({"from_date": "not-a-timestamp"})

        self.assertEqual(error_context.exception.status_code, 400)

    def test_rejects_date_only_string_filter(self) -> None:
        with self.assertRaises(HTTPException) as error_context:
            build_survey_filter_conditions({"to_date": "2026-08-04"})

        self.assertEqual(error_context.exception.status_code, 400)

    def test_rejects_timezone_less_timestamp_string_filter(self) -> None:
        with self.assertRaises(HTTPException) as error_context:
            build_survey_filter_conditions({"from_date": "2026-08-04T00:00:00"})

        self.assertEqual(error_context.exception.status_code, 400)

    def test_timezone_interprets_date_only_boundary_as_local_time(self) -> None:
        conditions = build_survey_filter_conditions(
            {
                "from_date": "2026-08-04",
                "timezone": "Asia/Hong_Kong",
            }
        )

        self.assertEqual(
            conditions[1].right.value,
            datetime(2026, 8, 3, 16, 0, tzinfo=timezone.utc),
        )


class SurveyClsTests(unittest.TestCase):
    def test_cls_range_filters_are_inclusive(self) -> None:
        conditions = build_survey_filter_conditions(
            {"min_cls": 10.0, "max_cls": 90.0}
        )

        self.assertIs(conditions[1].operator, operators.ge)
        self.assertEqual(conditions[1].right.value, 10.0)
        self.assertIs(conditions[2].operator, operators.le)
        self.assertEqual(conditions[2].right.value, 90.0)

    def test_cls_filters_are_omitted_when_bounds_are_null(self) -> None:
        conditions = build_survey_filter_conditions({})

        self.assertEqual(len(conditions), 1)

    def test_parses_cls_and_legacy_csl_source_headers(self) -> None:
        self.assertEqual(parse_optional_cls(pd.Series({"CLS": "100.0"})), 100.0)
        self.assertEqual(parse_optional_cls(pd.Series({"CSL": 75})), 75.0)

    def test_missing_or_blank_cls_is_null(self) -> None:
        self.assertIsNone(parse_optional_cls(pd.Series({"CLS": None})))
        self.assertIsNone(parse_optional_cls(pd.Series({"answer": "comment"})))


if __name__ == "__main__":
    unittest.main()
