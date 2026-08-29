#!/usr/bin/env python3
"""Verify the HTTP and SQLAlchemy contracts preserved during refactors."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
BASELINE = BACKEND / "contracts" / "baseline.json"
OPENAPI_SNAPSHOT = BACKEND / "contracts" / "openapi.json"
ROUTES_SNAPSHOT = BACKEND / "contracts" / "routes.json"
METADATA_SNAPSHOT = BACKEND / "contracts" / "metadata.json"
sys.path.insert(0, str(BACKEND))


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _route_manifest(openapi: dict[str, Any]) -> list[dict[str, str | None]]:
    methods = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
    return sorted(
        (
            {
                "path": path,
                "method": method.upper(),
                "operation_id": operation.get("operationId"),
            }
            for path, item in openapi["paths"].items()
            for method, operation in item.items()
            if method in methods
        ),
        key=lambda item: (str(item["path"]), str(item["method"])),
    )


def _default_descriptor(default: Any) -> str | None:
    """Return a deterministic description without callable memory addresses."""

    if default is None:
        return None
    argument = getattr(default, "arg", None)
    if callable(argument):
        module = getattr(argument, "__module__", "")
        name = getattr(argument, "__qualname__", type(argument).__qualname__)
        return f"callable:{module}.{name}"
    if argument is not None:
        return f"value:{argument}"
    sequence_name = getattr(default, "name", None)
    if sequence_name:
        return f"sequence:{sequence_name}"
    return f"type:{type(default).__module__}.{type(default).__qualname__}"


def _constraint_manifest(table: Any) -> list[dict[str, Any]]:
    """Describe constraints structurally, avoiding SQLAlchemy repr addresses."""

    constraints: list[dict[str, Any]] = []
    for constraint in table.constraints:
        entry: dict[str, Any] = {
            "type": type(constraint).__qualname__,
            "name": constraint.name,
            "columns": tuple(column.name for column in constraint.columns),
        }
        elements = getattr(constraint, "elements", ())
        if elements:
            entry["foreign_keys"] = tuple(
                f"{element.parent.name}->{element.target_fullname}"
                for element in elements
            )
        sqltext = getattr(constraint, "sqltext", None)
        if sqltext is not None:
            entry["sqltext"] = str(sqltext)
        constraints.append(entry)
    return sorted(
        constraints,
        key=lambda item: (
            str(item["type"]),
            str(item["name"]),
            tuple(str(value) for value in item["columns"]),
        ),
    )


def _metadata_manifest() -> list[dict[str, Any]]:
    from infrastructure.database.registry import Base

    manifest: list[dict[str, Any]] = []
    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name):
        manifest.append(
            {
                "name": table.name,
                "columns": [
                    {
                        "name": column.name,
                        "type": str(column.type),
                        "nullable": column.nullable,
                        "primary_key": column.primary_key,
                        "unique": column.unique,
                        "default": _default_descriptor(column.default),
                        "server_default": _default_descriptor(column.server_default),
                    }
                    for column in table.columns
                ],
                "foreign_keys": sorted(
                    f"{foreign_key.parent.name}->{foreign_key.target_fullname}"
                    for foreign_key in table.foreign_keys
                ),
                "indexes": sorted(
                    (
                        index.name,
                        tuple(column.name for column in index.columns),
                        index.unique,
                    )
                    for index in table.indexes
                ),
                "constraints": _constraint_manifest(table),
            }
        )
    return manifest


def main() -> int:
    from app import app

    baseline = json.loads(BASELINE.read_text())
    openapi = app.openapi()
    metadata = _metadata_manifest()
    actual = {
        "openapi_sha256": _digest(openapi),
        "route_manifest_sha256": _digest(_route_manifest(openapi)),
        "metadata_sha256": _digest(metadata),
        "table_count": len(metadata),
    }
    snapshots = {
        OPENAPI_SNAPSHOT: openapi,
        ROUTES_SNAPSHOT: _route_manifest(openapi),
        METADATA_SNAPSHOT: metadata,
    }
    failures = [
        f"{name}: expected {expected}, got {actual[name]}"
        for name, expected in baseline.items()
        if actual.get(name) != expected
    ]
    for path, value in snapshots.items():
        if not path.exists():
            failures.append(f"missing normalized contract snapshot: {path}")
            continue
        expected_digest = _digest(json.loads(path.read_text()))
        actual_digest = _digest(value)
        if expected_digest != actual_digest:
            failures.append(
                f"{path.name}: expected {expected_digest}, got {actual_digest}"
            )
    if failures:
        print("Backend contract regression detected:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(
        "Backend contracts are unchanged: "
        f"{actual['table_count']} tables, "
        f"{len(_route_manifest(openapi))} operations"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
