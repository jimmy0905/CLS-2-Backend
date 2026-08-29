"""Serialization helpers for master-data persistence objects."""

from typing import Any

from infrastructure.database.dbo.Store import Store

STORE_FIELDS = (
    "store_key",
    "store_name_english",
    "store_name_local",
    "bu_key",
    "area_manager",
    "store_format",
    "store_type",
    "operations_controller",
    "regional_manager",
    "px",
    "csr",
    "dr",
    "mag_type",
    "cf_grouping",
    "store_brand",
    "competitor",
    "region",
    "area",
    "province",
    "territory",
    "toh",
    "district",
    "city",
    "operations_manager",
    "district_manager",
    "sic",
    "soc",
    "tech_life_type",
    "operation_manager_tl",
    "region_manager_tl",
    "relocation",
    "latitude",
    "longitude",
    "store_open_date",
    "store_close_date",
    "is_closed",
)


def store_to_dict(store: Store) -> dict[str, Any]:
    """Return the former DBO ``to_dict`` contract without DBO serialization."""

    return {field: getattr(store, field) for field in STORE_FIELDS}
