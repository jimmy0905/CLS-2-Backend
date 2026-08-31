from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "2026_08_31_0018_frontend_owned_identity.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "frontend_identity_migration", MIGRATION
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identity_cutover_follows_the_current_migration_head() -> None:
    migration = load_migration()
    assert migration.revision == "0018_frontend_identity"
    assert migration.down_revision == "0017_assignment_view_grants"


def test_admin_receipt_checksum_matches_the_frontend_import_cli() -> None:
    migration = load_migration()
    rows = [
        SimpleNamespace(id="a", username=" Admin ", password="hash-a"),
        SimpleNamespace(id="b", username="SECOND", password="hash-b"),
    ]
    expected = hashlib.sha256(b"a\0admin\0hash-a\nb\0second\0hash-b\n").hexdigest()
    assert migration._admin_checksum(rows) == expected


def test_admin_receipt_checksum_uses_the_frontend_nfkc_normalization() -> None:
    migration = load_migration()
    rows = [
        SimpleNamespace(
            id="a",
            username=" \uff21\uff24\uff2d\uff29\uff2e ",
            password="hash",
        )
    ]
    expected = hashlib.sha256(b"a\0admin\0hash\n").hexdigest()
    assert migration._admin_checksum(rows) == expected


class _ReceiptResult:
    def __init__(self, receipt):
        self.receipt = receipt

    def mappings(self):
        return self

    def one_or_none(self):
        return self.receipt


class _ReceiptConnection:
    def __init__(self, admins, receipt_table, receipt):
        self.admins = admins
        self.receipt_table = receipt_table
        self.receipt = receipt

    def execute(self, statement, parameters=None):
        if "SELECT id, username, password" in str(statement):
            return self.admins
        return _ReceiptResult(self.receipt)

    def scalar(self, statement):
        return self.receipt_table


@pytest.mark.parametrize(
    "receipt_table,receipt,expected_message",
    [
        (None, None, "have not been imported"),
        ("frontend_auth_migration_receipts", None, "count mismatch"),
        (
            "frontend_auth_migration_receipts",
            {"admin_count": 2, "admin_checksum": "wrong"},
            "count mismatch",
        ),
        (
            "frontend_auth_migration_receipts",
            {"admin_count": 1, "admin_checksum": "wrong"},
            "checksum mismatch",
        ),
    ],
)
def test_frontend_import_guard_blocks_missing_or_mismatched_receipts(
    monkeypatch, receipt_table, receipt, expected_message
) -> None:
    migration = load_migration()
    admins = [SimpleNamespace(id="a", username="admin", password="hash")]
    connection = _ReceiptConnection(admins, receipt_table, receipt)
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

    with pytest.raises(RuntimeError, match=expected_message):
        migration._verify_frontend_import()


def test_frontend_import_guard_accepts_the_matching_receipt(monkeypatch) -> None:
    migration = load_migration()
    admins = [SimpleNamespace(id="a", username="admin", password="hash")]
    receipt = {
        "admin_count": 1,
        "admin_checksum": migration._admin_checksum(admins),
    }
    connection = _ReceiptConnection(admins, "frontend_auth_migration_receipts", receipt)
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

    migration._verify_frontend_import()


def test_cutover_contains_receipt_guard_and_actor_snapshot_backfill() -> None:
    source = MIGRATION.read_text()
    assert "frontend_auth_migration_receipts" in source
    assert "receipt checksum mismatch" in source
    assert "entra:" in source and "admin:" in source and "legacy:" in source
    assert 'op.drop_table("users")' in source
    assert 'op.drop_table("login_records")' in source
