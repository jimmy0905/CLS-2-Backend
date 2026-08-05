from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

from fastapi import HTTPException
from sqlalchemy.sql import operators

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.conditionFilter import build_survey_filter_conditions


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


if __name__ == "__main__":
    unittest.main()