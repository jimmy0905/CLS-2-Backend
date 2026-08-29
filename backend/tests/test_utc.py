from datetime import datetime, timezone
import unittest

from core.time import (
    as_timezone,
    as_utc,
    local_isoformat,
    resolve_timezone,
    utc_isoformat,
    utc_now,
)


class UtcHelperTests(unittest.TestCase):
    def test_utc_now_returns_timezone_aware_utc_datetime(self) -> None:
        self.assertEqual(utc_now().tzinfo, timezone.utc)

    def test_as_utc_attaches_utc_to_naive_datetime(self) -> None:
        value = as_utc(datetime(2026, 8, 4, 12, 30))

        self.assertEqual(value, datetime(2026, 8, 4, 12, 30, tzinfo=timezone.utc))

    def test_utc_isoformat_includes_utc_offset(self) -> None:
        value = utc_isoformat(datetime(2026, 8, 4, 20, 30, tzinfo=timezone.utc))

        self.assertEqual(value, "2026-08-04T20:30:00+00:00")

    def test_resolves_iana_timezone_and_formats_local_time(self) -> None:
        value = datetime(2026, 8, 4, 16, 30, tzinfo=timezone.utc)

        self.assertEqual(resolve_timezone("Asia/Hong_Kong").key, "Asia/Hong_Kong")
        self.assertEqual(
            local_isoformat(value, "Asia/Hong_Kong"),
            "2026-08-05T00:30:00+08:00",
        )
        self.assertEqual(as_timezone(value, "America/New_York").hour, 12)

    def test_rejects_unknown_timezone(self) -> None:
        with self.assertRaises(ValueError):
            resolve_timezone("Not/A_Timezone")


if __name__ == "__main__":
    unittest.main()
