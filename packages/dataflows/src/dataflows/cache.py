"""Process-safe, disposable local cache owned by the DFLS host.

Payloads use pickle to preserve pandas dtypes and indexes exactly. The cache
directory must be trusted local storage, never an imported evidence directory.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
import json
from pathlib import Path
import pickle
import sqlite3
import time

from .contract import DataIdentity, DataRequest, DataResult, DataStatus


class CachePolicy(StrEnum):
    READ_THROUGH = "READ_THROUGH"
    REFRESH = "REFRESH"
    CACHE_ONLY = "CACHE_ONLY"


@dataclass(frozen=True, slots=True)
class LocalCacheConfig:
    """Host policy; namespace must change when provider semantics change."""

    root: Path
    namespace: str
    max_age: timedelta
    policy: CachePolicy = CachePolicy.READ_THROUGH

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise TypeError("cache root must be Path")
        if not isinstance(self.namespace, str) or not self.namespace.strip():
            raise ValueError("cache namespace must be non-empty")
        if not isinstance(self.max_age, timedelta) or self.max_age <= timedelta(0):
            raise ValueError("cache max_age must be a positive timedelta")
        if not isinstance(self.policy, CachePolicy):
            raise TypeError("cache policy must be CachePolicy")
        object.__setattr__(self, "root", self.root.resolve())


class CacheError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _plain(value):
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_plain(item) for item in value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _key_value(value):
    if isinstance(value, Path):
        return {"path": str(value.resolve())}
    if isinstance(value, (date, datetime)):
        return {"type": type(value).__name__, "value": value.isoformat()}
    raise TypeError(f"unsupported cache key value: {type(value).__name__}")


def fetch_cached(
    config: LocalCacheConfig,
    request: DataRequest,
    fetch: Callable[[], DataResult],
    validate: Callable[[DataResult], None],
) -> DataResult:
    identity = _plain(request)
    identity["options"].pop("env_file", None)
    try:
        key = sha256(json.dumps(
            {"contract": 1, "namespace": config.namespace, "request": identity},
            sort_keys=True, separators=(",", ":"), allow_nan=False, default=_key_value,
        ).encode()).hexdigest()
    except (TypeError, ValueError) as exc:
        raise CacheError("CACHE_KEY_INVALID", str(exc)) from exc
    path = config.root / key[:2] / f"{key}.sqlite3"
    if config.policy is CachePolicy.CACHE_ONLY and not path.is_file():
        raise CacheError("CACHE_MISS", "no cached result for this request")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # One database per key permits unrelated requests to run concurrently.
        # SQLite releases locks after process death and commits replacements atomically.
        connection = sqlite3.connect(path, timeout=60)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS result "
                "(id INTEGER PRIMARY KEY CHECK(id=1), created REAL, digest TEXT, payload BLOB)"
            )
            row = connection.execute("SELECT created, digest, payload FROM result WHERE id=1").fetchone()
            if row is not None and config.policy is not CachePolicy.REFRESH:
                created, digest, payload = row
                if sha256(payload).hexdigest() != digest:
                    raise CacheError("CACHE_CORRUPT", "cache payload checksum differs")
                if 0 <= time.time() - created <= config.max_age.total_seconds():
                    try:
                        frame, data_identity, warnings = pickle.loads(payload)
                        result = DataResult(
                            DataStatus.READY, frame, DataIdentity(**data_identity),
                            warnings=tuple(warnings),
                        )
                        validate(result)
                    except Exception as exc:
                        raise CacheError("CACHE_CORRUPT", "cached data failed validation") from exc
                    connection.commit()
                    return result
                if config.policy is CachePolicy.CACHE_ONLY:
                    raise CacheError("CACHE_EXPIRED", "cached result has expired")
            if config.policy is CachePolicy.CACHE_ONLY:
                raise CacheError("CACHE_MISS", "no cached result for this request")
            result = fetch()
            if result.ready:
                payload = pickle.dumps(
                    (result.dataframe, _plain(result.identity), result.warnings), protocol=5,
                )
                connection.execute(
                    "INSERT OR REPLACE INTO result VALUES (1, ?, ?, ?)",
                    (time.time(), sha256(payload).hexdigest(), payload),
                )
            connection.commit()
            return result
        finally:
            connection.close()
    except sqlite3.OperationalError as exc:
        code = "CACHE_LOCK_TIMEOUT" if "locked" in str(exc) else "CACHE_IO_ERROR"
        raise CacheError(code, str(exc)) from exc
    except sqlite3.DatabaseError as exc:
        raise CacheError("CACHE_CORRUPT", str(exc)) from exc
    except (OSError, pickle.PickleError, TypeError) as exc:
        raise CacheError("CACHE_IO_ERROR", str(exc)) from exc
