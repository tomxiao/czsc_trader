"""Offline, atomic replacement of account execution bindings."""

from pathlib import Path
import sqlite3

from .account_binding import (
    AccountBindingUpdate,
    AccountBindingUpdateResult,
    AccountBindingUpdateStatus,
)
from .runtime_lock import RuntimeDatabaseLock
from .runtime_release import load_release
from .srt_advice_client import SrtAdviceClient
from .store import RUNTIME_DATABASE_SCHEMA_VERSION, _update_account_bindings


def update_account_bindings(
    runtime_root: Path,
    target_release_id: str,
    updates: tuple[AccountBindingUpdate, ...],
) -> AccountBindingUpdateResult:
    """Update existing accounts while PTE is stopped; never activate a release."""
    if type(updates) is not tuple or not updates:
        raise ValueError("account binding updates must be a nonempty tuple")
    if any(type(update) is not AccountBindingUpdate for update in updates):
        raise TypeError("account binding updates require AccountBindingUpdate values")
    account_ids = tuple(update.account_id for update in updates)
    if len(set(account_ids)) != len(account_ids):
        raise ValueError("account binding updates contain duplicate accounts")
    release = load_release(runtime_root, target_release_id)
    shared = release.runtime_root / "shared"
    database = shared / "state" / "runtime.db"
    if not database.is_file():
        raise ValueError("account binding update requires an existing runtime database")
    with RuntimeDatabaseLock(database):
        # Open the existing schema directly: PaperStore initialization performs
        # migrations and other writes outside this maintenance transaction.
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=rw", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT value FROM settings WHERE key='runtime_database_schema_version'"
            ).fetchone()
            if (
                row is None or int(row[0]) != RUNTIME_DATABASE_SCHEMA_VERSION
                or int(row[0]) not in release.manifest["database_schema"]["compatible"]
            ):
                raise ValueError("account binding update requires the current database schema")
            client = SrtAdviceClient(repo_root=release.release_root, data_dir=shared / "data")
            bindings = []
            for update in updates:
                account = connection.execute(
                    "SELECT * FROM virtual_accounts WHERE account_id=?", (update.account_id,),
                ).fetchone()
                if account is None:
                    raise ValueError(f"unknown account: {update.account_id}")
                binding = client.validate_account_binding(
                    strategy_id=account["strategy_id"],
                    strategy_version=account["strategy_version"],
                    symbol=account["symbol"], asset=account["asset_type"],
                )
                bindings.append((update, binding))
            # Detect package changes during validation before modifying the DB.
            if load_release(runtime_root, target_release_id).manifest_sha256 != release.manifest_sha256:
                raise ValueError("target release changed during account binding validation")
            _update_account_bindings(connection, tuple(bindings))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
    return AccountBindingUpdateResult(AccountBindingUpdateStatus.COMMITTED, account_ids)
