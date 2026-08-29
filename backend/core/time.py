from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = "UTC"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_isoformat(value: datetime | None) -> str | None:
    utc_value = as_utc(value)
    return utc_value.isoformat() if utc_value else None


def resolve_timezone(name: str | None) -> ZoneInfo:
    """Resolve an optional IANA timezone, defaulting to UTC."""

    if name is None:
        name = DEFAULT_TIMEZONE
    if not isinstance(name, str) or not name or len(name) > 64:
        raise ValueError("timezone must be a valid IANA timezone")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("timezone must be a valid IANA timezone") from error


def as_timezone(
    value: datetime | None, timezone_name: str | None = None
) -> datetime | None:
    """Convert a stored timestamp to the requested display timezone."""

    utc_value = as_utc(value)
    return utc_value.astimezone(resolve_timezone(timezone_name)) if utc_value else None


def local_isoformat(
    value: datetime | None, timezone_name: str | None = None
) -> str | None:
    """Format a stored timestamp in the requested display timezone."""

    local_value = as_timezone(value, timezone_name)
    return local_value.isoformat() if local_value else None
