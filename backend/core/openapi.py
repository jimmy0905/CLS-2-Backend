from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

_COMPONENT_NAMES = {
    "features__dashboard__endpoints__dashboard__StoreResponse": (
        "routers__dashboard__StoreResponse"
    ),
    "features__feedback__endpoint__surveys__StoreResponse": (
        "routers__surveys__StoreResponse"
    ),
    "features__master_data__dto__StoreResponse": ("routers__stores__StoreResponse"),
    "features__strategy__endpoints__strategy__StoreResponse": (
        "routers__strategy__StoreResponse"
    ),
}


def install_openapi_component_compatibility(app: FastAPI) -> None:
    """Retain historical component names after DTO modules move by feature."""
    default_openapi: Callable[[], dict[str, Any]] = app.openapi

    def compatible_openapi() -> dict[str, Any]:
        schema = default_openapi()
        schemas = schema.get("components", {}).get("schemas", {})
        for current_name, historical_name in _COMPONENT_NAMES.items():
            component = schemas.pop(current_name, None)
            if component is not None:
                schemas[historical_name] = component
        _rewrite_component_references(schema)
        app.openapi_schema = schema
        return schema

    # FastAPI documents replacing this instance hook; its stubs expose it as a method.
    app.openapi = compatible_openapi  # type: ignore[method-assign]


def _rewrite_component_references(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str):
                value[key] = _COMPONENT_NAMES.get(
                    item.removeprefix("#/components/schemas/"),
                    item.removeprefix("#/components/schemas/"),
                )
                if not value[key].startswith("#/components/schemas/"):
                    value[key] = f"#/components/schemas/{value[key]}"
            else:
                _rewrite_component_references(item)
    elif isinstance(value, list):
        for item in value:
            _rewrite_component_references(item)
