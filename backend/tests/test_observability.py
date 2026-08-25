import json
import logging
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from utils.logger import JsonFormatter, bind_request_id, reset_request_id
from utils.retention import purge_rotated_log_files, retention_cutoff


class JsonFormatterTests(unittest.TestCase):
    def test_includes_request_context_and_operational_fields(self) -> None:
        token = bind_request_id("request-123")
        try:
            record = logging.LogRecord(
                name="tests",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="Request completed",
                args=(),
                exc_info=None,
            )
            record.event = "http.request.completed"
            record.method = "GET"
            record.path = "/health"
            record.status_code = 200
            record.request_id = "request-123"

            payload = json.loads(JsonFormatter().format(record))
        finally:
            reset_request_id(token)

        self.assertEqual(payload["event"], "http.request.completed")
        self.assertEqual(payload["request_id"], "request-123")
        self.assertEqual(payload["status_code"], 200)


class RetentionTests(unittest.TestCase):
    def test_cutoff_uses_configured_number_of_days(self) -> None:
        now = datetime(2026, 8, 25, 9, 30, tzinfo=timezone.utc)

        self.assertEqual(
            retention_cutoff(retention_days=30, now=now),
            datetime(2026, 7, 26, 9, 30, tzinfo=timezone.utc),
        )

    def test_purge_rotated_log_files_removes_only_expired_archives(self) -> None:
        now = datetime(2026, 8, 25, 9, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / "server.log"
            expired_log = Path(f"{log_path}.2026-07-25")
            retained_log = Path(f"{log_path}.2026-08-01")
            expired_log.touch()
            retained_log.touch()
            os.utime(expired_log, (now.timestamp() - 31 * 86_400,) * 2)
            os.utime(retained_log, (now.timestamp() - 24 * 86_400,) * 2)

            with patch("utils.retention.SERVER_LOG_FILE", str(log_path)):
                deleted = purge_rotated_log_files(retention_cutoff(30, now))

            self.assertEqual(deleted, 1)
            self.assertFalse(expired_log.exists())
            self.assertTrue(retained_log.exists())


if __name__ == "__main__":
    unittest.main()
