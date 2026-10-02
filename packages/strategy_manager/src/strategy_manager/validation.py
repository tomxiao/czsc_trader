from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Iterable

from .errors import ValidationError


STRATEGY_ID_PATTERN = re.compile(r"S[0-9]{3}$")
VERSION_PATTERN = re.compile(r"v[1-9][0-9]*$")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}$")
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*$")


def require_exact_fields(
    value: dict[str, Any], required: Iterable[str], optional: Iterable[str] = ()
) -> None:
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - value.keys())
    unknown = sorted(value.keys() - allowed)
    if missing:
        raise ValidationError(f"missing fields: {', '.join(missing)}")
    if unknown:
        raise ValidationError(f"unknown fields: {', '.join(unknown)}")


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a nonblank string")
    return value.strip()


def require_identifier(value: Any, field: str) -> str:
    text = require_string(value, field)
    if not IDENTIFIER_PATTERN.fullmatch(text):
        raise ValidationError(f"{field} has invalid format")
    return text


def require_strategy_id(value: Any) -> str:
    text = require_string(value, "strategy_id")
    if value != text or not STRATEGY_ID_PATTERN.fullmatch(text):
        raise ValidationError("strategy_id must match S plus three digits")
    return text


def require_version(value: Any) -> str:
    text = require_string(value, "version")
    if value != text or not VERSION_PATTERN.fullmatch(text):
        raise ValidationError("version must match v plus a positive integer")
    return text


def require_sha256(value: Any, field: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    text = require_string(value, field)
    if not SHA256_PATTERN.fullmatch(text):
        raise ValidationError(f"{field} must be a lowercase SHA-256 hex digest")
    return text


def require_timestamp(value: Any, field: str) -> str:
    text = require_string(value, field)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"{field} must include a timezone")
    return text


def require_date(value: Any, field: str) -> str:
    text = require_string(value, field)
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(f"{field} must be YYYY-MM-DD") from exc
    return text


def require_schema_version(value: Any) -> int:
    if value != 1 or isinstance(value, bool):
        raise ValidationError("schema_version must be 1")
    return 1


def require_number(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field} must be numeric")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ValidationError(f"{field} must be at least {minimum}")
    return number
