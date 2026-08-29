#!/usr/bin/env python3
"""Capture normalized HTTP and persistence snapshots after an approved baseline."""

from __future__ import annotations

import json
import sys

from verify_backend_contracts import (
    BASELINE,
    METADATA_SNAPSHOT,
    OPENAPI_SNAPSHOT,
    ROUTES_SNAPSHOT,
    _digest,
    _metadata_manifest,
    _route_manifest,
)


def _write_json(path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def main() -> int:
    from app import app

    openapi = app.openapi()
    metadata = _metadata_manifest()
    routes = _route_manifest(openapi)
    _write_json(OPENAPI_SNAPSHOT, openapi)
    _write_json(ROUTES_SNAPSHOT, routes)
    _write_json(METADATA_SNAPSHOT, metadata)
    _write_json(
        BASELINE,
        {
            "openapi_sha256": _digest(openapi),
            "route_manifest_sha256": _digest(routes),
            "metadata_sha256": _digest(metadata),
            "table_count": len(metadata),
        },
    )
    print("Captured normalized OpenAPI, route, and metadata contract snapshots")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(BASELINE.parent.parent))
    raise SystemExit(main())
