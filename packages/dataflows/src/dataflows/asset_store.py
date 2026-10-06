"""Private, transactional storage for a DFLS data space.

Data spaces are trusted local managed storage. Pickle preserves pandas indexes,
dtypes and timezones; never open a database supplied by an untrusted party.
Asset bytes and preparation manifests are immutable. Only the request lookup
index changes when a subsequent prepare succeeds. This module has no research,
publication, retention or automatic deletion semantics.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from enum import Enum
from hashlib import sha256
import json
import os
from pathlib import Path
import pickle
import sqlite3
from typing import Any
from uuid import UUID, uuid4

import pandas as pd

from .contract import DataIdentity, DataResult, DataSpace, DataStatus, PreparedDataRef


class StoreError(Exception):
    """A stable storage failure, suitable for conversion to a public error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_plain(item) for item in value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return {"type": type(value).__name__, "value": value.isoformat()}
    if isinstance(value, (UUID, Path)):
        return {"type": type(value).__name__, "value": str(value)}
    raise TypeError(f"unsupported asset metadata type: {type(value).__name__}")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False, default=_json_default)


@contextmanager
def _storage_errors() -> Iterator[None]:
    try:
        yield
    except StoreError:
        raise
    except sqlite3.OperationalError as exc:
        message = str(exc)
        if "locked" in message or "busy" in message:
            code = "SPACE_LOCK_TIMEOUT"
        elif "no such table" in message or "no such column" in message:
            code = "SPACE_CORRUPT"
        else:
            code = "SPACE_IO_ERROR"
        raise StoreError(code, message) from exc
    except sqlite3.DatabaseError as exc:
        raise StoreError("SPACE_CORRUPT", str(exc)) from exc
    except OSError as exc:
        raise StoreError("SPACE_IO_ERROR", str(exc)) from exc


class AssetStore:
    """One SQLite database per space; writers serialize across processes."""

    SCHEMA_VERSION = 1

    def __init__(self, base_dir: Path, space: DataSpace) -> None:
        if not isinstance(base_dir, Path) or not isinstance(space, DataSpace):
            raise TypeError("base_dir must be Path and space must be DataSpace")
        if space.path.is_absolute() or space.path.drive or str(space.path) in ("", "."):
            raise StoreError("SPACE_PATH_INVALID", "data space requires a non-empty relative path")
        with _storage_errors():
            self.base_dir = base_dir.resolve()
            self.root = (self.base_dir / space.path).resolve()
            if not self.root.is_relative_to(self.base_dir) or self.root == self.base_dir:
                raise StoreError("SPACE_PATH_INVALID", "data space escapes its base directory")
            self.root.mkdir(parents=True, exist_ok=True)
            self.path = self.root / "assets.sqlite3"
            self._check_path()
            if not self.path.exists():
                self._create_database()
            with self._reader() as connection:
                self.space_id = self._metadata(connection)

    def _create_database(self) -> None:
        """Publish a complete database with an atomic exclusive hard link.

        An existing empty database is corruption; it cannot double as the marker
        for another initializer. Build privately inside the same data space and
        let precisely one concurrent initializer publish the final filename.
        """
        temporary = self.root / f".{uuid4()}.initializing.sqlite3"
        with temporary.open("xb"):
            pass
        try:
            connection = sqlite3.connect(temporary, timeout=60)
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._initialize(connection)
                self._metadata(connection)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()
            self._check_path()
            try:
                os.link(temporary, self.path)
            except FileExistsError:
                # Another initializer published first; validate that database.
                pass
        finally:
            temporary.unlink(missing_ok=True)

    def _check_path(self) -> None:
        if self.root.resolve() != self.root or not self.root.is_relative_to(self.base_dir):
            raise StoreError("SPACE_PATH_INVALID", "data space path has changed")
        # SQLite may create journal/sidecar files next to its database.
        for suffix in ("", "-journal", "-wal", "-shm"):
            path = Path(str(self.path) + suffix)
            if not path.resolve().is_relative_to(self.root):
                raise StoreError("SPACE_PATH_INVALID", "database or sidecar escapes data space")

    def _initialize(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE space_metadata (id INTEGER PRIMARY KEY CHECK(id=1), "
            "schema_version INTEGER NOT NULL, space_id TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO space_metadata VALUES (1, ?, ?)",
                           (self.SCHEMA_VERSION, str(uuid4())))
        connection.execute(
            "CREATE TABLE assets (asset_id TEXT PRIMARY KEY, payload_sha256 TEXT NOT NULL, "
            "payload BLOB NOT NULL, acquired_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE asset_lookup (request_key TEXT PRIMARY KEY, asset_id TEXT NOT NULL "
            "REFERENCES assets(asset_id))"
        )
        connection.execute(
            "CREATE TABLE preparations (preparation_id TEXT PRIMARY KEY, "
            "manifest_sha256 TEXT NOT NULL, manifest TEXT NOT NULL, prepared_at TEXT NOT NULL)"
        )
        self._preparation_index(connection)

    @staticmethod
    def _preparation_index(connection: sqlite3.Connection) -> None:
        # Add a disposable lookup index without rewriting immutable assets/manifests.
        connection.execute(
            "CREATE TABLE IF NOT EXISTS preparation_lookup (request_key TEXT PRIMARY KEY, "
            "preparation_id TEXT NOT NULL REFERENCES preparations(preparation_id))"
        )

    def _metadata(self, connection: sqlite3.Connection) -> UUID:
        expected_columns = {
            "space_metadata": ("id", "schema_version", "space_id"),
            "assets": ("asset_id", "payload_sha256", "payload", "acquired_at"),
            "asset_lookup": ("request_key", "asset_id"),
            "preparations": ("preparation_id", "manifest_sha256", "manifest", "prepared_at"),
        }
        for table, expected in expected_columns.items():
            actual = tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))
            if actual != expected:
                raise StoreError("SPACE_CORRUPT", "data space database schema differs")
        lookup_columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(preparation_lookup)"))
        if lookup_columns and lookup_columns != ("request_key", "preparation_id"):
            raise StoreError("SPACE_CORRUPT", "preparation lookup schema differs")
        row = connection.execute(
            "SELECT schema_version, space_id FROM space_metadata WHERE id=1"
        ).fetchone()
        if row is None:
            raise StoreError("SPACE_CORRUPT", "data space metadata is missing")
        if row[0] != self.SCHEMA_VERSION:
            raise StoreError("SPACE_VERSION_UNSUPPORTED", "unsupported data space schema version")
        try:
            result = UUID(row[1])
        except (TypeError, ValueError, AttributeError) as exc:
            raise StoreError("SPACE_CORRUPT", "invalid data space identity") from exc
        if hasattr(self, "space_id") and result != self.space_id:
            raise StoreError("SPACE_MISMATCH", "data space identity changed")
        return result

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit successful work, including partial preparation, as one transaction."""
        with _storage_errors():
            self._check_path()
            # rw refuses to recreate a database removed after initialization.
            connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=60)
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("BEGIN IMMEDIATE")
                self._metadata(connection)
                self._preparation_index(connection)
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

    @contextmanager
    def _reader(self) -> Iterator[sqlite3.Connection]:
        with _storage_errors():
            self._check_path()
            if not self.path.is_file():
                raise StoreError("SPACE_MISSING", "data space database is missing")
            connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=60)
            try:
                self._metadata(connection)
                yield connection
            finally:
                connection.close()

    @staticmethod
    def _asset_id(dataframe: pd.DataFrame, identity: DataIdentity,
                  warnings: tuple[str, ...]) -> str:
        from .facade import canonical_frame_sha256

        actual = canonical_frame_sha256(dataframe)
        if actual != identity.content_sha256:
            raise StoreError("ASSET_CORRUPT", "dataframe content differs from data identity")
        identity_data = {"identity": _plain(identity), "warnings": warnings}
        return sha256(_canonical(identity_data).encode("utf-8")).hexdigest()

    def put_asset(self, connection: sqlite3.Connection, *, key: str,
                  dataframe: pd.DataFrame, identity: DataIdentity,
                  warnings: tuple[str, ...] = ()) -> str:
        with _storage_errors():
            try:
                asset_id = self._asset_id(dataframe, identity, tuple(warnings))
                payload = pickle.dumps((dataframe, _plain(identity), tuple(warnings)), protocol=5)
            except (TypeError, ValueError, pickle.PickleError) as exc:
                raise StoreError("ASSET_SERIALIZATION_FAILED", str(exc)) from exc
            existing = connection.execute(
                "SELECT 1 FROM assets WHERE asset_id=?", (asset_id,)
            ).fetchone()
            if existing is None:
                connection.execute("INSERT INTO assets VALUES (?, ?, ?, ?)",
                                   (asset_id, sha256(payload).hexdigest(), payload,
                                    datetime.now(UTC).isoformat()))
            else:
                # Corrupt immutable assets must never be silently overwritten.
                self.read_asset(connection, asset_id)
            connection.execute(
                "INSERT INTO asset_lookup VALUES (?, ?) ON CONFLICT(request_key) "
                "DO UPDATE SET asset_id=excluded.asset_id", (key, asset_id)
            )
            return asset_id

    def lookup_asset(self, connection: sqlite3.Connection, key: str) -> str | None:
        with _storage_errors():
            row = connection.execute(
                "SELECT asset_id FROM asset_lookup WHERE request_key=?", (key,)
            ).fetchone()
            return row[0] if row is not None else None

    def lookup_preparation(self, connection: sqlite3.Connection, key: str) -> PreparedDataRef | None:
        row = connection.execute(
            "SELECT p.preparation_id, p.manifest_sha256 FROM preparation_lookup AS l "
            "LEFT JOIN preparations AS p ON p.preparation_id=l.preparation_id WHERE l.request_key=?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        if row[0] is None:
            raise StoreError("PREPARATION_CORRUPT", "cached preparation is missing")
        try:
            return PreparedDataRef(self.space_id, UUID(row[0]), row[1])
        except (TypeError, ValueError) as exc:
            raise StoreError("PREPARATION_CORRUPT", "cached preparation identity is invalid") from exc

    def cache_preparation(self, connection: sqlite3.Connection, key: str, reference: PreparedDataRef) -> None:
        if reference.space_id != self.space_id:
            raise StoreError("SPACE_MISMATCH", "cached preparation belongs to another space")
        connection.execute(
            "INSERT INTO preparation_lookup VALUES (?, ?) ON CONFLICT(request_key) "
            "DO UPDATE SET preparation_id=excluded.preparation_id",
            (key, str(reference.preparation_id)),
        )

    def read_asset(self, connection: sqlite3.Connection, asset_id: str) -> DataResult:
        with _storage_errors():
            row = connection.execute(
                "SELECT payload_sha256, payload FROM assets WHERE asset_id=?", (asset_id,)
            ).fetchone()
            if row is None:
                raise StoreError("ASSET_MISSING", "prepared data asset is missing")
            digest, payload = row
            try:
                if sha256(payload).hexdigest() != digest:
                    raise StoreError("ASSET_CORRUPT", "data asset payload checksum differs")
                frame, identity_data, warnings = pickle.loads(payload)
                identity = DataIdentity(**identity_data)
                if not isinstance(frame, pd.DataFrame):
                    raise ValueError("asset payload does not contain a dataframe")
                if self._asset_id(frame, identity, tuple(warnings)) != asset_id:
                    raise StoreError("ASSET_CORRUPT", "data asset identity checksum differs")
                return DataResult(DataStatus.READY, frame, identity, warnings=tuple(warnings))
            except StoreError:
                raise
            except Exception as exc:
                raise StoreError("ASSET_CORRUPT", "data asset payload failed validation") from exc

    def publish(self, connection: sqlite3.Connection, entries: list[dict]) -> PreparedDataRef:
        with _storage_errors():
            if not entries:
                raise StoreError("PREPARATION_INVALID", "preparation requires at least one input")
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("request"), dict):
                    raise StoreError("PREPARATION_INVALID", "invalid preparation entry")
                self.read_asset(connection, entry.get("asset_id"))
            try:
                manifest = _canonical(entries)
            except (TypeError, ValueError) as exc:
                raise StoreError("PREPARATION_INVALID", str(exc)) from exc
            digest = sha256(manifest.encode("utf-8")).hexdigest()
            preparation_id = uuid4()
            connection.execute("INSERT INTO preparations VALUES (?, ?, ?, ?)",
                               (str(preparation_id), digest, manifest, datetime.now(UTC).isoformat()))
            return PreparedDataRef(self.space_id, preparation_id, digest)

    def load_preparation(self, reference: PreparedDataRef) -> list[dict]:
        if reference.space_id != self.space_id:
            raise StoreError("SPACE_MISMATCH", "preparation belongs to another data space")
        with self._reader() as connection:
            row = connection.execute(
                "SELECT manifest_sha256, manifest FROM preparations WHERE preparation_id=?",
                (str(reference.preparation_id),),
            ).fetchone()
            if row is None:
                raise StoreError("UNKNOWN_REF", "preparation reference does not exist")
            digest, manifest = row
            try:
                if (sha256(manifest.encode("utf-8")).hexdigest() != digest
                        or digest != reference.manifest_sha256):
                    raise StoreError("PREPARATION_CORRUPT", "preparation manifest checksum differs")
                entries = json.loads(manifest)
                if not isinstance(entries, list) or not entries or any(
                    not isinstance(entry, dict)
                    or not isinstance(entry.get("request"), dict)
                    or not isinstance(entry.get("asset_id"), str)
                    for entry in entries
                ):
                    raise ValueError("invalid preparation entries")
                return entries
            except StoreError:
                raise
            except (TypeError, ValueError, AttributeError) as exc:
                raise StoreError("PREPARATION_CORRUPT", "invalid preparation manifest") from exc

    def read(self, asset_id: str) -> DataResult:
        with self._reader() as connection:
            return self.read_asset(connection, asset_id)
