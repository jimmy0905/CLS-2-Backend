from datetime import datetime, timezone
import unittest

from utils.utc import as_utc, utc_isoformat, utc_now


class UtcHelperTests(unittest.TestCase):
    def test_utc_now_returns_timezone_aware_utc_datetime(self) -> None:
        self.assertEqual(utc_now().tzinfo, timezone.utc)

    def test_as_utc_attaches_utc_to_naive_datetime(self) -> None:
        value = as_utc(datetime(2026, 8, 4, 12, 30))

        self.assertEqual(value, datetime(2026, 8, 4, 12, 30, tzinfo=timezone.utc))

    def test_utc_isoformat_includes_utc_offset(self) -> None:
        value = utc_isoformat(datetime(2026, 8, 4, 20, 30, tzinfo=timezone.utc))

        self.assertEqual(value, "2026-08-04T20:30:00+00:00")


if __name__ == "__main__":
    unittest.main()