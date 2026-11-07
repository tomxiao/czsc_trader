"""Normalize legacy account health within the caller's migration transaction."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
import sqlite3

from .lifecycle import AccountHealth


HEALTH_SCHEMA_KEY = "account_health_schema_version"
HEALTH_RECEIPT_KEY = "account_health_migration_receipt"


class AccountHealthMigrationError(RuntimeError):
    """Persisted account health cannot be safely migrated to the current contract."""


def migrate_account_health(connection: sqlite3.Connection, now: str) -> None:
    """Map READY to OK once, preserving all other account and historical facts.

    The caller owns the transaction, schema-version update and rollback. The
    receipt lives in settings so migration never rewrites historical events or
    changes an account's business-operation timestamp.
    """
    if not connection.in_transaction:
        raise RuntimeError("account health migration requires an existing transaction")
    if datetime.fromisoformat(now).tzinfo is None:
        raise ValueError("migration time must include a timezone")
    markers = dict(connection.execute(
        "SELECT key,value FROM settings WHERE key IN (?,?)",
        (HEALTH_SCHEMA_KEY, HEALTH_RECEIPT_KEY),
    ).fetchall())
    if markers and (markers.get(HEALTH_SCHEMA_KEY) != "1" or HEALTH_RECEIPT_KEY not in markers):
        raise AccountHealthMigrationError("unsupported or partially migrated account health schema")
    accounts = connection.execute(
        "SELECT account_id,health FROM virtual_accounts ORDER BY account_id"
    ).fetchall()
    allowed = {value.value for value in AccountHealth}
    if not markers:
        allowed.add("READY")
    for account_id, health in accounts:
        if health not in allowed:
            raise AccountHealthMigrationError(f"{account_id}: invalid account health {health!r}")
    if markers:
        try:
            receipt = json.loads(markers[HEALTH_RECEIPT_KEY])
        except (TypeError, ValueError) as exc:
            raise AccountHealthMigrationError("invalid account health migration receipt") from exc
        if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
            raise AccountHealthMigrationError("invalid account health migration receipt")
        return
    changes = [
        {"account_id": account_id, "from": health, "to": AccountHealth.OK.value}
        for account_id, health in accounts if health == "READY"
    ]
    receipt = {
        "schema_version": 1,
        "occurred_at": now,
        "source_counts": dict(sorted(Counter(health for _, health in accounts).items())),
        "changes": changes,
    }
    connection.execute(
        "UPDATE virtual_accounts SET health=? WHERE health='READY'", (AccountHealth.OK.value,),
    )
    connection.executemany("INSERT INTO settings(key,value) VALUES(?,?)", (
        (HEALTH_SCHEMA_KEY, "1"),
        (HEALTH_RECEIPT_KEY, json.dumps(receipt, ensure_ascii=False, sort_keys=True)),
    ))
