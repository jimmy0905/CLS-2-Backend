import importlib
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import core.config as config
from core.logging import (
    JsonFormatter,
    LogContextFilter,
    _build_file_handler,
    _replace_handlers,
    bind_request_id,
    log_retention_cutoff,
    purge_rotated_log_files,
    reset_request_id,
)


class JsonFormatterTests(unittest.TestCase):
    def test_includes_context_source_and_operational_fields(self) -> None:
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
            record.upload_task_id = "upload-123"
            record.export_job_id = "export-123"

            payload = json.loads(JsonFormatter().format(record))
        finally:
            reset_request_id(token)

        self.assertEqual(payload["event"], "http.request.completed")
        self.assertEqual(payload["request_id"], "request-123")
        self.assertEqual(payload["status_code"], 200)
        self.assertEqual(payload["upload_task_id"], "upload-123")
        self.assertEqual(payload["export_job_id"], "export-123")
        self.assertEqual(payload["source"]["module"], Path(__file__).stem)
        self.assertEqual(payload["process_id"], os.getpid())
        self.assertIn("thread_name", payload)

    def test_exception_contains_type_cause_and_stack_trace(self) -> None:
        try:
            try:
                raise ValueError("upstream failure")
            except ValueError as error:
                raise RuntimeError("request failed") from error
        except RuntimeError:
            record = logging.LogRecord(
                name="tests",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="Request failed",
                args=(),
                exc_info=sys.exc_info(),
            )

        payload = json.loads(JsonFormatter().format(record))

        self.assertEqual(payload["exception"]["type"], "RuntimeError")
        self.assertEqual(payload["exception"]["message"], "request failed")
        self.assertEqual(payload["exception"]["cause"]["type"], "ValueError")
        self.assertIn(
            "ValueError: upstream failure", payload["exception"]["stack_trace"]
        )

    def test_does_not_serialize_unapproved_sensitive_extra_fields(self) -> None:
        record = logging.LogRecord(
            name="tests",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Request completed",
            args=(),
            exc_info=None,
        )
        record.request_body = '{"password":"secret"}'
        record.authorization = "Bearer secret"
        record.query_string = "token=secret"

        rendered = JsonFormatter().format(record)

        self.assertNotIn("secret", rendered)
        self.assertNotIn("request_body", rendered)
        self.assertNotIn("authorization", rendered)
        self.assertNotIn("query_string", rendered)


class LoggingSinkTests(unittest.TestCase):
    def test_stdout_and_persistent_file_receive_the_same_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / "server.log"
            stream = io.StringIO()
            formatter = JsonFormatter()
            stdout_handler = logging.StreamHandler(stream)
            stdout_handler.addFilter(LogContextFilter())
            stdout_handler.setFormatter(formatter)
            with patch("core.logging.SERVER_LOG_FILE", str(log_path)):
                file_handler = _build_file_handler(formatter)

            self.assertIsNotNone(file_handler)
            self.assertEqual(file_handler.when, "MIDNIGHT")
            self.assertTrue(file_handler.utc)
            self.assertEqual(file_handler.backupCount, 30)
            test_logger = logging.getLogger("tests.dual_sink")
            test_logger.handlers.clear()
            test_logger.propagate = False
            test_logger.setLevel(logging.INFO)
            test_logger.addHandler(stdout_handler)
            test_logger.addHandler(file_handler)
            try:
                test_logger.info(
                    "Upload completed",
                    extra={
                        "event": "upload.completed",
                        "upload_task_id": "upload-123",
                    },
                )
                file_handler.flush()
            finally:
                for handler in test_logger.handlers[:]:
                    test_logger.removeHandler(handler)
                    handler.close()
                test_logger.propagate = True

            stdout_payload = json.loads(stream.getvalue())
            file_payload = json.loads(log_path.read_text(encoding="utf-8"))
            self.assertEqual(stdout_payload, file_payload)

    def test_replacing_handlers_closes_the_previous_handler(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_logger = logging.getLogger("tests.handler_replacement")
            test_logger.handlers.clear()
            previous_handler = logging.FileHandler(
                Path(temporary_directory) / "previous.log"
            )
            replacement_handler = logging.StreamHandler(io.StringIO())
            test_logger.addHandler(previous_handler)

            _replace_handlers(test_logger, [replacement_handler])

            self.assertEqual(test_logger.handlers, [replacement_handler])
            self.assertIsNone(previous_handler.stream)
            _replace_handlers(test_logger, [])

    def test_repeated_configuration_keeps_one_handler_per_sink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            backend_directory = Path(__file__).resolve().parents[1]
            environment = os.environ | {
                "PYTHONPATH": str(backend_directory),
                "SERVER_LOG_FILE": str(Path(temporary_directory) / "server.log"),
            }
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import logging; from core.logging import configure_logging; "
                    "configure_logging(); configure_logging(); "
                    "print(len(logging.getLogger().handlers))",
                ],
                check=True,
                capture_output=True,
                env=environment,
                text=True,
            )

        self.assertEqual(result.stdout.strip(), "2")

    def test_unavailable_file_sink_reports_a_diagnostic_and_keeps_stdout_available(
        self,
    ) -> None:
        with (
            patch("core.logging.SERVER_LOG_FILE", "/unwritable/server.log"),
            patch("core.logging.Path.mkdir", side_effect=PermissionError("denied")),
            patch("core.logging._emit_file_logging_diagnostic") as diagnostic,
        ):
            handler = _build_file_handler(JsonFormatter())

        self.assertIsNone(handler)
        diagnostic.assert_called_once()


class RetentionTests(unittest.TestCase):
    def test_log_cutoff_uses_independent_configured_number_of_days(self) -> None:
        now = datetime(2026, 8, 25, 9, 30, tzinfo=UTC)

        self.assertEqual(
            log_retention_cutoff(retention_days=30, now=now),
            datetime(2026, 7, 26, 9, 30, tzinfo=UTC),
        )

    def test_purge_rotated_log_files_removes_only_expired_archives(self) -> None:
        now = datetime(2026, 8, 25, 9, 30, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / "server.log"
            expired_log = Path(f"{log_path}.2026-07-25")
            retained_log = Path(f"{log_path}.2026-08-01")
            expired_log.touch()
            retained_log.touch()
            os.utime(expired_log, (now.timestamp() - 31 * 86_400,) * 2)
            os.utime(retained_log, (now.timestamp() - 24 * 86_400,) * 2)

            deleted = purge_rotated_log_files(
                now=now,
                log_file=str(log_path),
                retention_days=30,
            )

            self.assertEqual(deleted, 1)
            self.assertFalse(expired_log.exists())
            self.assertTrue(retained_log.exists())


class LoggingConfigurationTests(unittest.TestCase):
    def test_server_log_retention_days_is_a_positive_environment_integer(self) -> None:
        original_value = os.environ.get("SERVER_LOG_RETENTION_DAYS")
        try:
            os.environ.pop("SERVER_LOG_RETENTION_DAYS", None)
            self.assertEqual(importlib.reload(config).SERVER_LOG_RETENTION_DAYS, 30)

            os.environ["SERVER_LOG_RETENTION_DAYS"] = "14"
            self.assertEqual(importlib.reload(config).SERVER_LOG_RETENTION_DAYS, 14)

            os.environ["SERVER_LOG_RETENTION_DAYS"] = "0"
            with self.assertRaisesRegex(ValueError, "SERVER_LOG_RETENTION_DAYS"):
                importlib.reload(config)
        finally:
            if original_value is None:
                os.environ.pop("SERVER_LOG_RETENTION_DAYS", None)
            else:
                os.environ["SERVER_LOG_RETENTION_DAYS"] = original_value
            importlib.reload(config)


if __name__ == "__main__":
    unittest.main()
