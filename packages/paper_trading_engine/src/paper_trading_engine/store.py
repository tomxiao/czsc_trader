"""SQLite-backed runtime state and append-only audit events."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import re
from threading import RLock
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from .audit import (
    EVENT_CATALOG,
    AuditCategory,
    AuditEvent,
    AuditOutcome,
    AuditSeverity,
    redact_details,
)
from .broker import (
    ATTENTION_REQUIRED_INTENT_STATUSES,
    TERMINAL_INTENT_STATUSES,
    TERMINAL_ORDER_STATUSES,
    UNRESOLVED_INTENT_STATUSES,
)
from .channel import (
    CHANNEL_RECONCILIATION_ACCOUNT_TYPE,
    FUTU_SIMULATE_CN_CHANNEL_ID,
    LEGACY_FUTU_CHANNEL_ID,
    STRATEGY_ACCOUNT_TYPE,
    require_futu_simulate_cn,
)


DEFAULT_FUTU_CAPITAL_POOL = "1000000.0000"
RUNTIME_DATABASE_SCHEMA_VERSION = 2
RUNTIME_DATABASE_COMPATIBLE_VERSIONS = (1, 2)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_database_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    stored_schema = connection.execute(
        "SELECT value FROM settings WHERE key='runtime_database_schema_version'"
    ).fetchone()
    if stored_schema is None:
        return
    try:
        schema_version = int(stored_schema[0])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"PTE runtime database schema is invalid: {stored_schema[0]!r}"
        ) from exc
    if schema_version not in RUNTIME_DATABASE_COMPATIBLE_VERSIONS:
        raise RuntimeError(
            "PTE runtime database schema is incompatible: "
            f"{schema_version} not in {RUNTIME_DATABASE_COMPATIBLE_VERSIONS}"
        )


def backup_runtime_database(path: Path, *, retention: int = 3) -> Path | None:
    """Create a consistent pre-start SQLite backup and retain a small rolling set."""
    source_path = Path(path)
    if not source_path.is_file():
        return None
    backup_dir = source_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination_path = backup_dir / f"{source_path.stem}-prestart-{stamp}.db"
    source = sqlite3.connect(f"file:{source_path.resolve().as_posix()}?mode=ro", uri=True)
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    backups = sorted(
        backup_dir.glob(f"{source_path.stem}-prestart-*.db"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for obsolete in backups[max(1, int(retention)):]:
        obsolete.unlink()
    return destination_path


class PaperStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._atomic_decision_depth = 0
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        try:
            _validate_database_schema(self._connection)
        except Exception:
            self._connection.close()
            raise
        self._connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                event_id TEXT,
                occurred_at TEXT,
                category TEXT,
                severity TEXT,
                outcome TEXT,
                source TEXT,
                correlation_id TEXT,
                actor_type TEXT,
                actor_id TEXT,
                schema_version TEXT,
                account_id TEXT,
                strategy_id TEXT,
                strategy_version TEXT,
                release_hash TEXT,
                symbol TEXT,
                channel TEXT,
                decision_id TEXT,
                order_id TEXT
            );
            CREATE TABLE IF NOT EXISTS operation_failures (
                operation TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS intents (
                intent_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                decision_id TEXT NOT NULL,
                order_sequence INTEGER NOT NULL,
                channel_id TEXT NOT NULL DEFAULT 'futu_simulate_cn',
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                limit_price TEXT NOT NULL,
                valid_session TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL,
                channel_order_id TEXT,
                attention_required INTEGER NOT NULL DEFAULT 0,
                attention_reason TEXT,
                resolved_at TEXT,
                resolution_note TEXT,
                reservation_generation INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(account_id, decision_id, order_sequence)
            );
            CREATE TABLE IF NOT EXISTS orders (
                channel_order_id TEXT PRIMARY KEY,
                intent_id TEXT NOT NULL UNIQUE,
                account_id TEXT NOT NULL,
                decision_id TEXT NOT NULL,
                channel_id TEXT NOT NULL DEFAULT 'futu_simulate_cn',
                payload TEXT NOT NULL,
                cumulative_filled_quantity INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decisions (
                account_id TEXT NOT NULL,
                decision_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                signal_date TEXT NOT NULL,
                valid_session TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                superseded_by TEXT,
                superseded_at TEXT,
                PRIMARY KEY(account_id, decision_id)
            );
            CREATE TABLE IF NOT EXISTS fills (
                fill_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                decision_id TEXT NOT NULL,
                channel_id TEXT NOT NULL DEFAULT 'futu_simulate_cn',
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price TEXT NOT NULL,
                fee TEXT NOT NULL,
                realized_pnl TEXT NOT NULL DEFAULT '0.0000',
                occurred_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS account_ledger (
                ledger_entry_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                entry_type TEXT NOT NULL,
                order_id TEXT,
                fill_id TEXT,
                cash_delta TEXT NOT NULL,
                frozen_cash_delta TEXT NOT NULL,
                quantity_delta INTEGER NOT NULL,
                fee TEXT NOT NULL,
                balance_after TEXT NOT NULL,
                quantity_after INTEGER NOT NULL,
                occurred_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS account_snapshots (
                account_id TEXT NOT NULL,
                session TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(account_id, session)
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cancel_tokens (
                token TEXT PRIMARY KEY,
                channel_order_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT
            );
            CREATE TABLE IF NOT EXISTS virtual_accounts (
                account_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                baseline_version TEXT NOT NULL,
                baseline_sha256 TEXT NOT NULL,
                strategy_id TEXT,
                strategy_name_snapshot TEXT,
                strategy_version TEXT,
                release_hash TEXT,
                selection_data_cutoff TEXT,
                qualification_snapshot TEXT,
                symbol TEXT NOT NULL DEFAULT '588080.SH',
                asset_type TEXT NOT NULL DEFAULT 'etf',
                initial_cash TEXT NOT NULL,
                cash TEXT NOT NULL,
                frozen_cash TEXT NOT NULL DEFAULT '0.0000',
                total_assets TEXT NOT NULL DEFAULT '0.0000',
                quantity INTEGER NOT NULL DEFAULT 0,
                average_cost TEXT NOT NULL DEFAULT '0.0000',
                realized_pnl TEXT NOT NULL DEFAULT '0.0000',
                cycle_target INTEGER,
                paused INTEGER NOT NULL DEFAULT 0,
                observation_start TEXT,
                last_settlement_session TEXT,
                last_decision_id TEXT,
                last_decision_payload TEXT,
                health TEXT NOT NULL DEFAULT 'READY',
                last_error TEXT,
                channel_id TEXT NOT NULL DEFAULT 'futu_simulate_cn',
                account_type TEXT NOT NULL DEFAULT 'STRATEGY',
                status TEXT NOT NULL DEFAULT 'RUNNING',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        account_schema_migrated = self._migrate_account_execution_schema()
        self._drop_obsolete_virtual_reference_column()
        self._ensure_column("virtual_accounts", "average_cost", "TEXT NOT NULL DEFAULT '0.0000'")
        self._ensure_column("virtual_accounts", "realized_pnl", "TEXT NOT NULL DEFAULT '0.0000'")
        self._ensure_column("virtual_accounts", "symbol", "TEXT NOT NULL DEFAULT '588080.SH'")
        self._ensure_column("virtual_accounts", "asset_type", "TEXT NOT NULL DEFAULT 'etf'")
        self._ensure_column("virtual_accounts", "frozen_cash", "TEXT NOT NULL DEFAULT '0.0000'")
        self._ensure_column("virtual_accounts", "total_assets", "TEXT NOT NULL DEFAULT '0.0000'")
        self._ensure_column("virtual_accounts", "observation_start", "TEXT")
        self._ensure_column("virtual_accounts", "last_settlement_session", "TEXT")
        self._ensure_column("virtual_accounts", "last_decision_id", "TEXT")
        self._ensure_column("virtual_accounts", "last_decision_payload", "TEXT")
        self._ensure_column("virtual_accounts", "health", "TEXT NOT NULL DEFAULT 'READY'")
        self._ensure_column("virtual_accounts", "last_error", "TEXT")
        self._ensure_column("virtual_accounts", "strategy_id", "TEXT")
        self._ensure_column("virtual_accounts", "strategy_name_snapshot", "TEXT")
        self._ensure_column("virtual_accounts", "strategy_version", "TEXT")
        self._ensure_column("virtual_accounts", "release_hash", "TEXT")
        self._ensure_column("virtual_accounts", "selection_data_cutoff", "TEXT")
        self._ensure_column("virtual_accounts", "qualification_snapshot", "TEXT")
        self._ensure_column("virtual_accounts", "channel_id", "TEXT NOT NULL DEFAULT 'futu_simulate_cn'")
        self._ensure_column("virtual_accounts", "account_type", "TEXT NOT NULL DEFAULT 'STRATEGY'")
        self._ensure_column("decisions", "status", "TEXT NOT NULL DEFAULT 'ACTIVE'")
        self._ensure_column("decisions", "superseded_by", "TEXT")
        self._ensure_column("decisions", "superseded_at", "TEXT")
        self._connection.execute("DROP INDEX IF EXISTS uq_decisions_account_signal_date")
        self._connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_decisions_active_signal_date "
            "ON decisions(account_id,signal_date) WHERE status='ACTIVE'"
        )
        self._ensure_column("virtual_accounts", "status", "TEXT NOT NULL DEFAULT 'RUNNING'")
        self._ensure_column("fills", "realized_pnl", "TEXT NOT NULL DEFAULT '0.0000'")
        self._ensure_column("orders", "created_at", "TEXT")
        self._ensure_column("intents", "attention_required", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("intents", "attention_reason", "TEXT")
        self._ensure_column("intents", "resolved_at", "TEXT")
        self._ensure_column("intents", "resolution_note", "TEXT")
        self._ensure_column("intents", "reservation_generation", "INTEGER NOT NULL DEFAULT 0")
        self._connection.execute(
            "UPDATE intents SET reservation_generation=1 "
            "WHERE side='BUY' AND reservation_generation=0"
        )
        legacy_recovered = self._connection.execute(
            "SELECT intent_id FROM intents WHERE side='BUY' AND reservation_generation<2"
        ).fetchall()
        for recovered in legacy_recovered:
            legacy_id = str(uuid5(
                NAMESPACE_URL, f"pte-recover-reserve:{recovered['intent_id']}"
            ))
            if self._connection.execute(
                "SELECT 1 FROM account_ledger WHERE ledger_entry_id=?", (legacy_id,)
            ).fetchone() is not None:
                self._connection.execute(
                    "UPDATE intents SET reservation_generation=2 WHERE intent_id=?",
                    (recovered["intent_id"],),
                )
        for column in (
            "event_id", "occurred_at", "category", "severity", "outcome", "source",
            "correlation_id", "actor_type", "actor_id", "schema_version", "account_id",
            "strategy_id", "strategy_version", "release_hash", "symbol", "channel",
            "decision_id", "order_id",
        ):
            self._ensure_column("events", column, "TEXT")
        self._migrate_audit_events()
        self._migrate_futu_channel_scope()
        if account_schema_migrated:
            self._insert_audit_event(self._new_audit_event(
                "ACCOUNT_EXECUTION_MIGRATED", source="store", actor_type="ENGINE",
                correlation_id="account-execution-migration",
                details={"schema": "account_execution.v1", "channel": FUTU_SIMULATE_CN_CHANNEL_ID},
            ))
            for account in self.virtual_accounts():
                correlation_id = f"account-binding:{account['account_id']}"
                self._insert_audit_event(self._new_audit_event(
                    "ACCOUNT_CHANNEL_BOUND", source="store", actor_type="ENGINE",
                    correlation_id=correlation_id, account_id=account["account_id"],
                    strategy_id=account.get("strategy_id"),
                    strategy_version=account.get("strategy_version"),
                    release_hash=account.get("release_hash"), symbol=account.get("symbol"),
                    channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                    details={"migration": True, "channel_id": FUTU_SIMULATE_CN_CHANNEL_ID},
                ))
                if account.get("strategy_id"):
                    self._insert_audit_event(self._new_audit_event(
                        "ACCOUNT_STRATEGY_BOUND", source="store", actor_type="ENGINE",
                        correlation_id=correlation_id, account_id=account["account_id"],
                        strategy_id=account["strategy_id"],
                        strategy_version=account.get("strategy_version"),
                        release_hash=account.get("release_hash"), symbol=account.get("symbol"),
                        details={"migration": True},
                    ))
        self._connection.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_events_event_id ON events(event_id);
            CREATE INDEX IF NOT EXISTS idx_events_occurred_at ON events(occurred_at);
            CREATE INDEX IF NOT EXISTS idx_events_category_time ON events(category, occurred_at);
            CREATE INDEX IF NOT EXISTS idx_events_account_time ON events(account_id, occurred_at);
            CREATE INDEX IF NOT EXISTS idx_events_strategy_time
                ON events(strategy_id, strategy_version, occurred_at);
            CREATE INDEX IF NOT EXISTS idx_events_decision ON events(decision_id);
            CREATE INDEX IF NOT EXISTS idx_events_order ON events(order_id);
            """
        )
        self._connection.execute(
            "UPDATE orders SET created_at=updated_at WHERE created_at IS NULL"
        )
        self._connection.execute(
            "UPDATE virtual_accounts SET total_assets=initial_cash WHERE total_assets='0.0000' AND quantity=0"
        )
        self._connection.execute(
            "UPDATE virtual_accounts SET total_assets=printf('%.4f',"
            "CAST(cash AS REAL)+CAST(frozen_cash AS REAL)) "
            "WHERE quantity=0 AND ABS(CAST(total_assets AS REAL)-"
            "CAST(cash AS REAL)-CAST(frozen_cash AS REAL))>0.00005"
        )
        pnl_repairs = self._repair_flat_realized_pnl()
        if pnl_repairs:
            self._insert_audit_event(self._new_audit_event(
                "ACCOUNT_EXECUTION_MIGRATED", source="store", actor_type="ENGINE",
                correlation_id="flat-realized-pnl-v1",
                details={"schema": "flat_realized_pnl.v1", "accounts": pnl_repairs},
            ))
        self._connection.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES('futu_capital_pool', ?)",
            (DEFAULT_FUTU_CAPITAL_POOL,),
        )
        backfilled = self._backfill_intent_reserve_ledger()
        attention_backfill = self._backfill_intent_attention()
        if backfilled or attention_backfill["review_required"] or attention_backfill["superseded"]:
            self._insert_audit_event(self._new_audit_event(
                "ACCOUNT_EXECUTION_MIGRATED", source="store", actor_type="ENGINE",
                correlation_id="account-ledger-v2-migration",
                details={
                    "schema": "account_ledger.v2", "reserve_entries": backfilled,
                    "review_required": attention_backfill["review_required"],
                    "superseded_attempts": attention_backfill["superseded"],
                },
            ))
        self._connection.execute(
            "INSERT INTO settings(key,value) VALUES('runtime_database_schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(RUNTIME_DATABASE_SCHEMA_VERSION),),
        )
        self._connection.commit()

    @contextmanager
    def atomic_decision_update(self):
        """Serialize and atomically commit one decision and its local order intents."""
        with self._lock:
            if self._connection.in_transaction:
                raise RuntimeError("nested store transaction is not supported")
            self._connection.execute("BEGIN IMMEDIATE")
            self._atomic_decision_depth += 1
            try:
                yield
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()
            finally:
                self._atomic_decision_depth -= 1

    def _write_context(self, in_transaction: bool):
        return (
            nullcontext()
            if in_transaction or self._atomic_decision_depth
            else self._connection
        )

    def _backfill_intent_reserve_ledger(self) -> int:
        """Make pre-v2 BUY reservations visible in the reconstructable ledger."""
        from decimal import Decimal

        inserted = 0
        rows = self._connection.execute(
            "SELECT i.*,v.initial_cash FROM intents i JOIN virtual_accounts v "
            "ON v.account_id=i.account_id WHERE i.side='BUY' ORDER BY i.created_at,i.intent_id"
        ).fetchall()
        for row in rows:
            ledger_id = str(uuid5(NAMESPACE_URL, f"pte-reserve:{row['intent_id']}"))
            if self._connection.execute(
                "SELECT 1 FROM account_ledger WHERE ledger_entry_id=?", (ledger_id,),
            ).fetchone() is not None:
                continue
            payload = json.loads(row["payload"])
            fee_rate = Decimal(str(payload.get("fee_rate", "0.0005")))
            reserve = (
                Decimal(row["limit_price"]) * int(row["quantity"]) * (Decimal("1") + fee_rate)
            ).quantize(Decimal("0.0001"))
            self._connection.execute(
                "INSERT INTO account_ledger(ledger_entry_id,account_id,entry_type,order_id,fill_id,"
                "cash_delta,frozen_cash_delta,quantity_delta,fee,balance_after,quantity_after,"
                "occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ledger_id, row["account_id"], "INTENT_RESERVE", None, None,
                    str(-reserve), str(reserve), 0, "0.0000", "0.0000", 0,
                    row["created_at"],
                ),
            )
            inserted += 1
        if inserted:
            account_ids = {str(row["account_id"]) for row in rows}
            for account_id in account_ids:
                account = self._connection.execute(
                    "SELECT initial_cash FROM virtual_accounts WHERE account_id=?", (account_id,),
                ).fetchone()
                cash = Decimal(account["initial_cash"])
                quantity = 0
                entries = self._connection.execute(
                    "SELECT rowid,* FROM account_ledger WHERE account_id=? "
                    "ORDER BY occurred_at,rowid", (account_id,),
                ).fetchall()
                for entry in entries:
                    cash += Decimal(entry["cash_delta"])
                    quantity += int(entry["quantity_delta"])
                    self._connection.execute(
                        "UPDATE account_ledger SET balance_after=?,quantity_after=? WHERE rowid=?",
                        (str(cash.quantize(Decimal("0.0001"))), quantity, entry["rowid"]),
                    )
        return inserted

    def _repair_flat_realized_pnl(self) -> list[dict[str, str]]:
        """Repair legacy rounded cost bases once a virtual account is fully flat."""
        from decimal import Decimal

        repairs: list[dict[str, str]] = []
        accounts = self._connection.execute(
            "SELECT account_id,initial_cash,cash,realized_pnl FROM virtual_accounts "
            "WHERE quantity=0 AND CAST(frozen_cash AS REAL)=0"
        ).fetchall()
        for account in accounts:
            expected = (
                Decimal(account["cash"]) - Decimal(account["initial_cash"])
            ).quantize(Decimal("0.0001"))
            current = Decimal(account["realized_pnl"]).quantize(Decimal("0.0001"))
            delta = expected - current
            if abs(delta) <= Decimal("0.00005"):
                continue
            fill = self._connection.execute(
                "SELECT fill_id,realized_pnl FROM fills WHERE account_id=? AND side='SELL' "
                "ORDER BY rowid DESC LIMIT 1", (account["account_id"],),
            ).fetchone()
            if fill is None:
                continue
            self._connection.execute(
                "UPDATE virtual_accounts SET realized_pnl=? WHERE account_id=?",
                (str(expected), account["account_id"]),
            )
            self._connection.execute(
                "UPDATE fills SET realized_pnl=? WHERE fill_id=?",
                (str((Decimal(fill["realized_pnl"]) + delta).quantize(Decimal("0.0001"))),
                 fill["fill_id"]),
            )
            repairs.append({
                "account_id": str(account["account_id"]), "delta": str(delta),
                "fill_id": str(fill["fill_id"]),
            })
        return repairs

    def _backfill_intent_attention(self) -> dict[str, int]:
        """Expose unresolved legacy terminal attempts without reopening completed retries."""
        statuses = sorted(ATTENTION_REQUIRED_INTENT_STATUSES)
        placeholders = ",".join("?" for _ in statuses)
        rows = self._connection.execute(
            f"SELECT * FROM intents WHERE status IN ({placeholders}) "
            "AND attention_required=0 AND resolved_at IS NULL ORDER BY created_at,intent_id",
            statuses,
        ).fetchall()
        review_required = 0
        superseded = 0
        for row in rows:
            retry = self._connection.execute(
                "SELECT intent_id,updated_at FROM intents WHERE account_id=? AND decision_id=? "
                "AND order_sequence>? AND status='FILLED_ALL' "
                "ORDER BY order_sequence DESC LIMIT 1",
                (row["account_id"], row["decision_id"], row["order_sequence"]),
            ).fetchone()
            if retry is not None:
                self._connection.execute(
                    "UPDATE intents SET resolved_at=?,resolution_note=? WHERE intent_id=?",
                    (
                        retry["updated_at"],
                        f"迁移识别：后续执行意图 {retry['intent_id']} 已完整成交",
                        row["intent_id"],
                    ),
                )
                superseded += 1
                continue
            reason = f"历史订单未完整执行（{row['status']}），需要人工确认该次前瞻执行缺口"
            self._connection.execute(
                "UPDATE intents SET attention_required=1,attention_reason=?,updated_at=? "
                "WHERE intent_id=?",
                (reason, _utc_now(), row["intent_id"]),
            )
            self._connection.execute(
                "UPDATE virtual_accounts SET health='BLOCKED',last_error=?,updated_at=? "
                "WHERE account_id=? AND status!='RETIRED'",
                (reason, _utc_now(), row["account_id"]),
            )
            review_required += 1
        return {"review_required": review_required, "superseded": superseded}

    def _drop_obsolete_virtual_reference_column(self) -> None:
        columns = {
            row[1] for row in self._connection.execute("PRAGMA table_info(virtual_accounts)")
        }
        if "is_futu_reference" in columns:
            with self._connection:
                self._connection.execute(
                    "ALTER TABLE virtual_accounts DROP COLUMN is_futu_reference"
                )

    def _migrate_futu_channel_scope(self) -> None:
        """Map the legacy broad Futu label to the sole supported execution tuple.

        Runtime tables are migrated atomically.  Historical audit events remain
        immutable; the migration event records their legacy interpretation.
        """
        tables = ("virtual_accounts", "intents", "orders", "fills")
        values: set[str] = set()
        for table in tables:
            values.update(
                str(row[0]) for row in self._connection.execute(
                    f"SELECT DISTINCT channel_id FROM {table} WHERE channel_id IS NOT NULL"
                )
            )
        unsupported = values - {LEGACY_FUTU_CHANNEL_ID, FUTU_SIMULATE_CN_CHANNEL_ID}
        if unsupported:
            raise RuntimeError(
                "unsupported persisted execution channel(s): " + ", ".join(sorted(unsupported))
            )
        if LEGACY_FUTU_CHANNEL_ID not in values:
            return
        with self._connection:
            for table in tables:
                self._connection.execute(
                    f"UPDATE {table} SET channel_id=? WHERE channel_id=?",
                    (FUTU_SIMULATE_CN_CHANNEL_ID, LEGACY_FUTU_CHANNEL_ID),
                )
            for table, key in (("intents", "intent_id"), ("orders", "channel_order_id")):
                rows = self._connection.execute(
                    f"SELECT {key},payload FROM {table}"
                ).fetchall()
                for row in rows:
                    payload = json.loads(row["payload"])
                    if payload.get("channel_id") == LEGACY_FUTU_CHANNEL_ID:
                        payload["channel_id"] = FUTU_SIMULATE_CN_CHANNEL_ID
                        self._connection.execute(
                            f"UPDATE {table} SET payload=? WHERE {key}=?",
                            (json.dumps(payload, ensure_ascii=False), row[key]),
                        )
            self._insert_audit_event(self._new_audit_event(
                "CHANNEL_SCOPE_MIGRATED", source="store", actor_type="ENGINE",
                correlation_id="futu-simulate-cn-channel-scope-v1",
                channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                details={
                    "from_channel": LEGACY_FUTU_CHANNEL_ID,
                    "to_channel": FUTU_SIMULATE_CN_CHANNEL_ID,
                    "scope": {"broker": "Futu", "environment": "SIMULATE", "market": "CN"},
                    "historical_events_preserved": True,
                },
            ))

    def _migrate_account_execution_schema(self) -> bool:
        """Replace empty pre-account-centric trading tables without rewriting history."""
        tables = {
            row[0]
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        legacy_tables = {
            name for name in (
                "virtual_intents", "virtual_orders", "virtual_fills", "virtual_snapshots"
            ) if name in tables
        }
        intent_columns = {
            row[1] for row in self._connection.execute("PRAGMA table_info(intents)")
        }
        old_core = "account_id" not in intent_columns
        if not legacy_tables and not old_core:
            self._connection.execute(
                "INSERT INTO settings(key,value) VALUES('account_execution_schema','account_execution.v1') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
            return False
        guarded = set(legacy_tables)
        if old_core:
            guarded.update({"intents", "orders"})
        populated = {
            name: int(self._connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
            for name in guarded
        }
        if any(populated.values()):
            raise RuntimeError(
                "account-centric migration requires empty legacy trading tables: "
                + ", ".join(f"{name}={count}" for name, count in sorted(populated.items()))
            )
        with self._connection:
            for name in sorted(legacy_tables):
                self._connection.execute(f"DROP TABLE {name}")
            if old_core:
                self._connection.execute("DROP TABLE intents")
                self._connection.execute("DROP TABLE orders")
                self._connection.executescript(
                    """
                    CREATE TABLE intents (
                        intent_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                        decision_id TEXT NOT NULL, order_sequence INTEGER NOT NULL,
                        channel_id TEXT NOT NULL DEFAULT 'futu_simulate_cn', symbol TEXT NOT NULL,
                        side TEXT NOT NULL, quantity INTEGER NOT NULL, limit_price TEXT NOT NULL,
                        valid_session TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
                        channel_order_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        UNIQUE(account_id, decision_id, order_sequence)
                    );
                    CREATE TABLE orders (
                        channel_order_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL UNIQUE,
                        account_id TEXT NOT NULL, decision_id TEXT NOT NULL,
                        channel_id TEXT NOT NULL DEFAULT 'futu_simulate_cn', payload TEXT NOT NULL,
                        cumulative_filled_quantity INTEGER NOT NULL,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    """
                )
            self._connection.execute(
                "DELETE FROM settings WHERE key IN ('futu_strategy_binding','last_virtual_refresh_date')"
            )
            self._connection.execute(
                "INSERT INTO settings(key,value) VALUES('account_execution_schema','account_execution.v1') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
        return True

    @staticmethod
    def _legacy_profile(event_type: str, payload: dict[str, object]):
        aliases = {
            "DATA_PUBLISHED": "MARKET_DATA_PUBLISHED",
            "DATA_PUBLICATION_FAILED": "MARKET_DATA_PUBLICATION_FAILED",
            "FILL_INCREMENT": "ORDER_PARTIALLY_FILLED",
            "PAUSED": "ACCOUNT_PAUSED",
            "RESUMED": "ACCOUNT_RESUMED",
            "PTE_RESTART_REQUESTED": "RESTART_REQUESTED",
            "CHANNEL_INITIALIZATION_FAILED": "DEPENDENCY_DEGRADED",
            "CHANNEL_REFRESH_FAILED": "DEPENDENCY_DEGRADED",
            "VIRTUAL_STARTUP_FAILED": "VIRTUAL_ACCOUNT_FAILED",
        }
        canonical = aliases.get(event_type, event_type)
        details = dict(payload)
        if canonical not in EVENT_CATALOG:
            details = {
                **details,
                "legacy_event_type": event_type,
                "classification_reason": "legacy event type has no audit.v1 mapping",
            }
            canonical = "LEGACY_EVENT"
        category = EVENT_CATALOG[canonical]
        failure = "FAILED" in canonical or canonical == "DEPENDENCY_DEGRADED"
        severity = AuditSeverity.ERROR if failure else (
            AuditSeverity.WARNING if category is AuditCategory.OTHER else AuditSeverity.INFO
        )
        outcome = AuditOutcome.FAILURE if failure else (
            AuditOutcome.UNKNOWN if category is AuditCategory.OTHER else AuditOutcome.SUCCESS
        )
        source = "scheduler" if canonical.startswith(("MARKET_DATA", "SCHEDULER_")) else "engine"
        actor_type = "SCHEDULER" if source == "scheduler" else "ENGINE"
        return canonical, category, severity, outcome, source, actor_type, redact_details(details)

    def _migrate_audit_events(self) -> None:
        rows = self._connection.execute(
            "SELECT * FROM events WHERE event_id IS NULL OR schema_version IS NULL ORDER BY id"
        ).fetchall()
        for row in rows:
            original_payload = json.loads(row["payload"])
            canonical, category, severity, outcome, source, actor_type, details = (
                self._legacy_profile(str(row["event_type"]), original_payload)
            )
            event_id = str(uuid5(
                NAMESPACE_URL,
                f'pte-event:{row["id"]}|{row["created_at"]}|{row["event_type"]}',
            ))
            correlation = str(
                details.get("decision_id") or details.get("channel_order_id") or event_id
            )
            self._connection.execute(
                "UPDATE events SET event_id=?,occurred_at=?,event_type=?,payload=?,category=?,"
                "severity=?,outcome=?,source=?,correlation_id=?,actor_type=?,schema_version=?,"
                "account_id=?,strategy_id=?,strategy_version=?,release_hash=?,symbol=?,channel=?,"
                "decision_id=?,order_id=? WHERE id=?",
                (
                    event_id, row["created_at"], canonical,
                    json.dumps(details, ensure_ascii=False, default=str), category.value,
                    severity.value, outcome.value, source, correlation, actor_type, "audit.v1",
                    details.get("account_id"), details.get("strategy_id"),
                    details.get("strategy_version") or details.get("version"),
                    details.get("release_hash"), details.get("symbol"), details.get("channel"),
                    details.get("decision_id"),
                    details.get("order_id") or details.get("channel_order_id"), row["id"],
                ),
            )
        self._connection.execute(
            "INSERT INTO settings(key,value) VALUES('audit_schema_version','audit.v1') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )

    def _ensure_column(self, table: str, column: str, declaration: str) -> None:
        columns = {row["name"] for row in self._connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self._connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _setting(self, key: str) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else str(row["value"])

    def set_setting(self, key: str, value: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_setting(self, key: str) -> str | None:
        with self._lock:
            return self._setting(key)

    def is_paused(self) -> bool:
        with self._lock:
            return self._setting("paused") == "1"

    def set_paused(self, paused: bool) -> None:
        self.set_setting("paused", "1" if paused else "0")

    def mark_reconciled(self) -> None:
        self.set_setting("last_reconcile_at", _utc_now())

    def has_reconciled(self) -> bool:
        with self._lock:
            return self._setting("last_reconcile_at") is not None

    def create_virtual_account(
        self, account_id, name, baseline_version, baseline_sha256, initial_cash,
        *, symbol="588080.SH", asset_type="etf", strategy_id=None,
        strategy_name_snapshot=None, strategy_version=None, release_hash=None,
        qualification_snapshot=None, selection_data_cutoff=None,
        channel_id=FUTU_SIMULATE_CN_CHANNEL_ID,
    ):
        from decimal import Decimal
        cash = Decimal(initial_cash).quantize(Decimal("0.0001"))
        require_futu_simulate_cn(channel_id)
        if not cash.is_finite() or cash <= 0:
            raise ValueError("initial cash must be positive")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", str(account_id)) is None:
            raise ValueError("account id must use 1-64 letters, digits, dots, underscores or hyphens")
        if not str(name).strip() or not str(baseline_version).strip():
            raise ValueError("account name and baseline version are required")
        if asset_type not in {"etf", "stock"}:
            raise ValueError("asset type must be etf or stock")
        if re.fullmatch(r"[0-9a-f]{64}", str(baseline_sha256).lower()) is None:
            raise ValueError("baseline sha256 must contain 64 hexadecimal characters")
        strategy_values = (
            strategy_id,
            strategy_name_snapshot,
            strategy_version,
            release_hash,
            qualification_snapshot,
        )
        if any(value is not None for value in strategy_values):
            if any(value is None for value in strategy_values):
                raise ValueError("formal strategy identity must be complete")
            if re.fullmatch(r"S[0-9]{3}", str(strategy_id)) is None:
                raise ValueError("strategy id has invalid format")
            if re.fullmatch(r"v[1-9][0-9]*", str(strategy_version)) is None:
                raise ValueError("strategy version has invalid format")
            if re.fullmatch(r"[0-9a-f]{64}", str(release_hash)) is None:
                raise ValueError("strategy release hash has invalid format")
            if qualification_snapshot not in {"PAPER_READY", "LIVE_READY"}:
                raise ValueError("strategy qualification does not permit paper trading")
        try:
            selection_data_cutoff = date.fromisoformat(
                str(selection_data_cutoff)
            ).isoformat()
        except (TypeError, ValueError) as exc:
            raise ValueError("selection_data_cutoff must be a nonempty ISO date") from exc
        now = _utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO virtual_accounts(account_id,name,baseline_version,baseline_sha256,"
                "strategy_id,strategy_name_snapshot,strategy_version,release_hash,"
                "selection_data_cutoff,qualification_snapshot,symbol,asset_type,initial_cash,cash,total_assets,"
                "channel_id,account_type,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    account_id, name, baseline_version, baseline_sha256, strategy_id,
                    strategy_name_snapshot, strategy_version, release_hash,
                    selection_data_cutoff, qualification_snapshot, symbol.upper(), asset_type,
                    str(cash), str(cash), str(cash),
                    FUTU_SIMULATE_CN_CHANNEL_ID, STRATEGY_ACCOUNT_TYPE, "RUNNING", now, now,
                ),
            )
            scope = {
                "account_id": account_id, "strategy_id": strategy_id,
                "strategy_version": strategy_version, "release_hash": release_hash,
                "symbol": symbol.upper(),
            }
            self._insert_audit_event(self._new_audit_event(
                "ACCOUNT_STRATEGY_BOUND", source="account_registry",
                correlation_id=f"account:{account_id}", **scope,
                details={
                    "release_id": f"{strategy_id}-{strategy_version}",
                    "qualification": qualification_snapshot,
                },
            ))
            self._insert_audit_event(self._new_audit_event(
                "ACCOUNT_CHANNEL_BOUND", source="account_registry",
                correlation_id=f"account:{account_id}", channel=FUTU_SIMULATE_CN_CHANNEL_ID, **scope,
                details={"channel_id": FUTU_SIMULATE_CN_CHANNEL_ID},
            ))
        return self.virtual_account(account_id)

    def create_channel_reconciliation_account(self, *, account_id: str = "futu-simulate-cn-reconciliation"):
        """Create the zero-balance system ledger for verified channel fee variance."""
        from decimal import Decimal

        require_futu_simulate_cn(FUTU_SIMULATE_CN_CHANNEL_ID)
        baseline = hashlib.sha256(b"futu_simulate_cn:channel_reconciliation.v1").hexdigest()
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE channel_id=? AND account_type=?",
                (FUTU_SIMULATE_CN_CHANNEL_ID, CHANNEL_RECONCILIATION_ACCOUNT_TYPE),
            ).fetchone()
            if existing is not None:
                if Decimal(existing["initial_cash"]) != 0:
                    raise ValueError("reconciliation account must have zero initial balance")
                return dict(existing)
            now = _utc_now()
            self._connection.execute(
                "INSERT INTO virtual_accounts(account_id,name,baseline_version,baseline_sha256,"
                "symbol,asset_type,initial_cash,cash,total_assets,channel_id,account_type,status,"
                "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (account_id, "Futu模拟盘CN渠道平账账户", "channel_reconciliation.v1", baseline,
                 "CASH.CN", "cash", "0.0000", "0.0000", "0.0000",
                 FUTU_SIMULATE_CN_CHANNEL_ID, CHANNEL_RECONCILIATION_ACCOUNT_TYPE, "SYSTEM", now, now),
            )
            self._insert_audit_event(self._new_audit_event(
                "CHANNEL_RECONCILIATION_ACCOUNT_CREATED", source="account_registry",
                actor_type="OPERATOR", correlation_id=f"channel-reconciliation:{account_id}",
                account_id=account_id, channel=FUTU_SIMULATE_CN_CHANNEL_ID,
                details={"initial_balance": "0.0000", "account_type": CHANNEL_RECONCILIATION_ACCOUNT_TYPE},
            ))
        return self.virtual_account(account_id)

    def backfill_account_selection_cutoff(
        self, account_id: str, release_hash: str, selection_data_cutoff: str,
    ) -> bool:
        """Fill a legacy account cutoff once, only for an identical strategy release."""
        try:
            cutoff = date.fromisoformat(str(selection_data_cutoff)).isoformat()
        except (TypeError, ValueError) as exc:
            raise ValueError("selection_data_cutoff must be a nonempty ISO date") from exc
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE virtual_accounts SET selection_data_cutoff=?,updated_at=? "
                "WHERE account_id=? AND release_hash=? AND selection_data_cutoff IS NULL",
                (cutoff, _utc_now(), account_id, release_hash),
            )
        return cursor.rowcount == 1

    def synchronize_account_strategy_name(
        self, account_id: str, release_hash: str, strategy_name: str,
    ) -> bool:
        """Synchronize mutable display metadata while preserving release identity."""
        normalized_name = str(strategy_name).strip()
        if not normalized_name:
            raise ValueError("strategy name is required")
        with self._lock, self._connection:
            account = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE account_id=?", (account_id,)
            ).fetchone()
            if account is None:
                raise KeyError(account_id)
            if account["release_hash"] != release_hash:
                raise ValueError("strategy release hash differs from virtual account")
            if account["strategy_name_snapshot"] == normalized_name:
                return False
            previous_name = account["strategy_name_snapshot"]
            now = _utc_now()
            self._connection.execute(
                "UPDATE virtual_accounts SET strategy_name_snapshot=?,updated_at=? "
                "WHERE account_id=? AND release_hash=?",
                (normalized_name, now, account_id, release_hash),
            )
            self._insert_audit_event(self._new_audit_event(
                "ACCOUNT_STRATEGY_NAME_UPDATED",
                source="account_registry",
                correlation_id=f"account:{account_id}",
                account_id=account_id,
                strategy_id=account["strategy_id"],
                strategy_version=account["strategy_version"],
                release_hash=release_hash,
                symbol=account["symbol"],
                details={"previous_name": previous_name, "name": normalized_name},
            ))
        return True

    def rename_virtual_account(self, old_account_id: str, account_id: str, name: str):
        """Atomically migrate a runtime account identity without losing its ledger."""
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", str(account_id)) is None:
            raise ValueError("account id must use 1-64 letters, digits, dots, underscores or hyphens")
        if not str(name).strip():
            raise ValueError("account name is required")

        def replace_account_id(value):
            if isinstance(value, dict):
                return {
                    key: (account_id if key == "account_id" and item == old_account_id
                          else replace_account_id(item))
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [replace_account_id(item) for item in value]
            return value

        now = _utc_now()
        with self._lock, self._connection:
            source = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE account_id=?", (old_account_id,)
            ).fetchone()
            if source is None:
                raise KeyError(old_account_id)
            if old_account_id != account_id and self._connection.execute(
                "SELECT 1 FROM virtual_accounts WHERE account_id=?", (account_id,)
            ).fetchone() is not None:
                raise ValueError(f"virtual account already exists: {account_id}")
            if old_account_id == account_id and source["name"] == name:
                return dict(source)

            for table in ("decisions", "intents", "orders", "fills", "account_ledger", "account_snapshots"):
                self._connection.execute(
                    f"UPDATE {table} SET account_id=? WHERE account_id=?",
                    (account_id, old_account_id),
                )
            self._connection.execute(
                "UPDATE virtual_accounts SET account_id=?,name=?,updated_at=? WHERE account_id=?",
                (account_id, name, now, old_account_id),
            )

            payload_columns = (
                ("virtual_accounts", "account_id", "last_decision_payload"),
                ("intents", "intent_id", "payload"),
                ("orders", "channel_order_id", "payload"),
                ("account_snapshots", "rowid", "payload"),
                ("events", "id", "payload"),
            )
            for table, key_column, payload_column in payload_columns:
                rows = self._connection.execute(
                    f"SELECT {key_column}, {payload_column} FROM {table} "
                    f"WHERE {payload_column} IS NOT NULL"
                ).fetchall()
                for row in rows:
                    payload = json.loads(row[payload_column])
                    replaced = replace_account_id(payload)
                    if replaced != payload:
                        self._connection.execute(
                            f"UPDATE {table} SET {payload_column}=? WHERE {key_column}=?",
                            (json.dumps(replaced, ensure_ascii=False, default=str), row[key_column]),
                        )
            event = self._legacy_audit_event(
                "VIRTUAL_ACCOUNT_RENAMED",
                {"old_account_id": old_account_id, "account_id": account_id, "name": name},
                occurred_at=now,
            )
            self._insert_audit_event(event)
        return self.virtual_account(account_id)

    def migrate_pristine_virtual_account_capital(
        self, account_id: str, *, expected_initial_cash, new_initial_cash,
    ):
        """Change capital only when an account has never entered its trading lifecycle."""
        from decimal import Decimal

        expected = Decimal(expected_initial_cash).quantize(Decimal("0.0001"))
        new_value = Decimal(new_initial_cash).quantize(Decimal("0.0001"))
        if new_value <= 0 or not new_value.is_finite():
            raise ValueError("new initial cash must be positive")
        with self._lock, self._connection:
            account = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE account_id=?", (account_id,)
            ).fetchone()
            if account is None:
                raise KeyError(account_id)
            current = Decimal(account["initial_cash"])
            if current == new_value:
                return dict(account)
            history_count = sum(
                int(self._connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE account_id=?", (account_id,)
                ).fetchone()[0])
                for table in (
                    "intents", "orders", "fills", "account_snapshots",
                )
            )
            pristine = (
                current == expected
                and Decimal(account["cash"]) == expected
                and int(account["quantity"]) == 0
                and Decimal(account["average_cost"]) == 0
                and Decimal(account["realized_pnl"]) == 0
                and history_count == 0
            )
            if not pristine:
                raise ValueError("virtual account has trading history; capital migration refused")
            now = _utc_now()
            self._connection.execute(
                "UPDATE virtual_accounts SET initial_cash=?,cash=?,total_assets=?,cycle_target=NULL,"
                "last_decision_id=NULL,last_decision_payload=NULL,updated_at=? WHERE account_id=?",
                (str(new_value), str(new_value), str(new_value), now, account_id),
            )
        return self.virtual_account(account_id)

    def virtual_account(self, account_id: str):
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE account_id=?", (account_id,)
            ).fetchone()
        if row is None:
            raise KeyError(account_id)
        return dict(row)

    def virtual_accounts(self):
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM virtual_accounts ORDER BY created_at, account_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def strategy_virtual_accounts(self):
        return [
            row for row in self.virtual_accounts()
            if row.get("account_type", STRATEGY_ACCOUNT_TYPE) == STRATEGY_ACCOUNT_TYPE
        ]

    def channel_reconciliation_account(self, channel_id: str = FUTU_SIMULATE_CN_CHANNEL_ID):
        require_futu_simulate_cn(channel_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE channel_id=? AND account_type=?",
                (channel_id, CHANNEL_RECONCILIATION_ACCOUNT_TYPE),
            ).fetchone()
        return None if row is None else dict(row)

    def set_virtual_paused(self, account_id: str, paused: bool):
        with self._lock, self._connection:
            account = self._connection.execute(
                "SELECT account_type FROM virtual_accounts WHERE account_id=?", (account_id,)
            ).fetchone()
            if account is not None and account["account_type"] != STRATEGY_ACCOUNT_TYPE:
                raise ValueError("system reconciliation account cannot be paused")
            changed = self._connection.execute(
                "UPDATE virtual_accounts SET paused=?, updated_at=? WHERE account_id=?",
                (int(paused), _utc_now(), account_id),
            ).rowcount
        if not changed:
            raise KeyError(account_id)
        return self.virtual_account(account_id)

    def set_virtual_health(self, account_id: str, health: str, error: str | None = None):
        with self._lock, self._connection:
            changed = self._connection.execute(
                "UPDATE virtual_accounts SET health=?,last_error=?,updated_at=? WHERE account_id=?",
                (health, error, _utc_now(), account_id),
            ).rowcount
        if not changed:
            raise KeyError(account_id)

    def _legacy_audit_event(
        self, event_type: str, payload: dict[str, object], *, occurred_at: str | None = None,
    ) -> AuditEvent:
        canonical, category, severity, outcome, source, actor_type, details = (
            self._legacy_profile(event_type, payload)
        )
        event_id = str(uuid4())
        decision_id = details.get("decision_id")
        order_id = details.get("order_id") or details.get("channel_order_id")
        return AuditEvent(
            event_id=event_id,
            occurred_at=occurred_at or _utc_now(),
            category=category,
            event_type=canonical,
            severity=severity,
            outcome=outcome,
            source=source,
            correlation_id=str(decision_id or order_id or event_id),
            actor_type=actor_type,
            account_id=details.get("account_id"),
            strategy_id=details.get("strategy_id"),
            strategy_version=details.get("strategy_version") or details.get("version"),
            release_hash=details.get("release_hash"),
            symbol=details.get("symbol"),
            channel=details.get("channel"),
            decision_id=decision_id,
            order_id=order_id,
            details=details,
        )

    def _insert_audit_event(self, event: AuditEvent) -> None:
        self._connection.execute(
            "INSERT INTO events(created_at,event_type,payload,event_id,occurred_at,category,"
            "severity,outcome,source,correlation_id,actor_type,actor_id,schema_version,account_id,"
            "strategy_id,strategy_version,release_hash,symbol,channel,decision_id,order_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event.occurred_at, event.event_type,
                json.dumps(event.details, ensure_ascii=False, default=str),
                event.event_id, event.occurred_at, event.category.value, event.severity.value,
                event.outcome.value, event.source, event.correlation_id, event.actor_type,
                event.actor_id, event.schema_version, event.account_id, event.strategy_id,
                event.strategy_version, event.release_hash, event.symbol, event.channel,
                event.decision_id, event.order_id,
            ),
        )

    @staticmethod
    def _new_audit_event(
        event_type: str, *, source: str, correlation_id: str,
        actor_type: str = "ENGINE", account_id: str | None = None,
        strategy_id: str | None = None, strategy_version: str | None = None,
        release_hash: str | None = None, symbol: str | None = None,
        channel: str | None = None, decision_id: str | None = None,
        order_id: str | None = None, details: dict[str, object] | None = None,
    ) -> AuditEvent:
        return AuditEvent(
            event_id=str(uuid4()), occurred_at=_utc_now(),
            category=EVENT_CATALOG[event_type], event_type=event_type,
            severity=AuditSeverity.INFO, outcome=AuditOutcome.SUCCESS,
            source=source, correlation_id=correlation_id, actor_type=actor_type,
            account_id=account_id, strategy_id=strategy_id,
            strategy_version=strategy_version, release_hash=release_hash,
            symbol=symbol, channel=channel, decision_id=decision_id,
            order_id=order_id, details=redact_details(details or {}),
        )

    def append_audit_event(self, event: AuditEvent) -> dict[str, object]:
        with self._lock, self._write_context(False):
            self._insert_audit_event(event)
        return event.to_dict()

    def add_event(self, event_type: str, payload: dict[str, object]) -> None:
        """Compatibility facade for pre-audit callers."""
        event = self._legacy_audit_event(event_type, payload)
        with self._lock, self._connection:
            self._insert_audit_event(event)

    @staticmethod
    def _audit_row(row: sqlite3.Row) -> dict[str, Any]:
        details = json.loads(row["payload"])
        return {
            "id": row["id"],
            "event_id": row["event_id"],
            "occurred_at": row["occurred_at"],
            "created_at": row["occurred_at"],
            "category": row["category"],
            "event_type": row["event_type"],
            "severity": row["severity"],
            "outcome": row["outcome"],
            "source": row["source"],
            "correlation_id": row["correlation_id"],
            "actor_type": row["actor_type"],
            "actor_id": row["actor_id"],
            "schema_version": row["schema_version"],
            "account_id": row["account_id"],
            "strategy_id": row["strategy_id"],
            "strategy_version": row["strategy_version"],
            "release_hash": row["release_hash"],
            "symbol": row["symbol"],
            "channel": row["channel"],
            "decision_id": row["decision_id"],
            "order_id": row["order_id"],
            "details": details,
            "payload": details,
        }

    def query_audit_events(
        self, *, category=None, event_type=None, severity=None, outcome=None,
        account_id=None, strategy_id=None, channel=None, decision_id=None, order_id=None,
        correlation_id=None, before_id=None, limit=50,
    ) -> list[dict[str, Any]]:
        limit = int(limit)
        if not 1 <= limit <= 200:
            raise ValueError("audit event limit must be between 1 and 200")
        filters = {
            "category": category, "event_type": event_type, "severity": severity,
            "outcome": outcome, "account_id": account_id, "strategy_id": strategy_id,
            "channel": channel, "decision_id": decision_id, "order_id": order_id,
            "correlation_id": correlation_id,
        }
        clauses, values = [], []
        for column, value in filters.items():
            if value is not None:
                clauses.append(f"{column}=?")
                values.append(str(value))
        if before_id is not None:
            clauses.append("id<?")
            values.append(int(before_id))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM events{where} ORDER BY id DESC LIMIT ?",
                (*values, limit),
            ).fetchall()
        return [self._audit_row(row) for row in rows]

    def audit_event_counts(
        self, *, event_type=None, severity=None, outcome=None, account_id=None,
        strategy_id=None, channel=None, decision_id=None, order_id=None,
        correlation_id=None,
    ) -> dict[str, int]:
        """Count every matching event by category, independent of page size."""
        filters = {
            "event_type": event_type, "severity": severity, "outcome": outcome,
            "account_id": account_id, "strategy_id": strategy_id, "channel": channel,
            "decision_id": decision_id, "order_id": order_id,
            "correlation_id": correlation_id,
        }
        clauses, values = [], []
        for column, value in filters.items():
            if value is not None:
                clauses.append(f"{column}=?")
                values.append(str(value))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._connection.execute(
                f"SELECT category,COUNT(*) AS count FROM events{where} GROUP BY category",
                values,
            ).fetchall()
        result = {name: 0 for name in ("STRATEGY", "TRADING", "SYSTEM", "OTHER")}
        result.update({str(row["category"]): int(row["count"]) for row in rows})
        return result

    def has_audit_event(
        self, event_type: str, *, account_id: str | None = None,
        decision_id: str | None = None, channel: str | None = None,
        channel_is_null: bool = False,
    ) -> bool:
        filters = {"event_type": event_type, "account_id": account_id,
                   "decision_id": decision_id, "channel": channel}
        clauses, values = [], []
        for column, value in filters.items():
            if value is not None:
                clauses.append(f"{column}=?")
                values.append(str(value))
        if channel_is_null:
            clauses.append("channel IS NULL")
        with self._lock:
            row = self._connection.execute(
                f"SELECT 1 FROM events WHERE {' AND '.join(clauses)} LIMIT 1", values,
            ).fetchone()
        return row is not None

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.query_audit_events(limit=limit)

    def set_operation_failure(self, operation: str, payload: dict[str, object]) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO operation_failures(operation,payload,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(operation) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                (operation, json.dumps(payload, ensure_ascii=False, default=str), _utc_now()),
            )

    def clear_operation_failure(self, operation: str) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM operation_failures WHERE operation=?", (operation,))

    def operation_failures(self) -> list[dict[str, object]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT operation,payload,updated_at FROM operation_failures ORDER BY operation"
            ).fetchall()
        return [
            {"operation": row["operation"], **json.loads(row["payload"]), "updated_at": row["updated_at"]}
            for row in rows
        ]

    def create_account_intent(
        self, *, account_id: str, decision_id: str, order_sequence: int,
        symbol: str, side: str, quantity: int, limit_price, valid_session: str,
        fee_rate="0.0005", order_type=None, audit_event: AuditEvent | None = None,
    ) -> dict[str, Any]:
        """Persist one idempotent account order intent and reserve its cash."""
        from decimal import Decimal

        side = str(side).upper()
        order_type = str(order_type or ("LIMIT" if side == "BUY" else "MARKET")).upper()
        price = Decimal(str(limit_price)).quantize(Decimal("0.0001"))
        fee = Decimal(str(fee_rate))
        if side not in {"BUY", "SELL"}:
            raise ValueError("intent side must be BUY or SELL")
        if (side, order_type) not in {
            ("BUY", "LIMIT"),
            ("SELL", "LIMIT"),
            ("SELL", "MARKET"),
        }:
            raise ValueError("buy intents must be LIMIT; sell intents must be LIMIT or MARKET")
        if quantity <= 0 or quantity % 100:
            raise ValueError("intent quantity must use positive 100-share lots")
        identity = f"{account_id}\0{decision_id}\0{order_sequence}".encode("utf-8")
        intent_id = "PTE-" + hashlib.sha256(identity).hexdigest()[:20].upper()
        now = _utc_now()
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT * FROM intents WHERE account_id=? AND decision_id=? AND order_sequence=?",
                (account_id, decision_id, order_sequence),
            ).fetchone()
            if existing is not None:
                expected = {
                    "symbol": symbol.upper(),
                    "side": side,
                    "quantity": int(quantity),
                    "limit_price": str(price),
                    "valid_session": valid_session,
                    "order_type": order_type,
                }
                stored_payload = json.loads(existing["payload"])
                actual = {
                    key: (stored_payload.get(key, "LIMIT") if key == "order_type" else existing[key])
                    for key in expected
                }
                if actual != expected:
                    raise ValueError("existing intent differs from the idempotent request")
                return self._account_intent_row(existing)
            account = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE account_id=?", (account_id,)
            ).fetchone()
            if account is None:
                raise KeyError(account_id)
            require_futu_simulate_cn(account["channel_id"])
            if account["account_type"] != STRATEGY_ACCOUNT_TYPE:
                raise ValueError("channel reconciliation account cannot create order intents")
            if account["status"] != "RUNNING":
                raise ValueError("virtual account status does not allow order intents")
            if account["health"] == "BLOCKED":
                raise ValueError("blocked virtual account cannot create order intents")
            if bool(account["paused"]):
                raise ValueError("paused virtual account cannot create order intents")
            if side == "SELL" and quantity > int(account["quantity"]):
                raise ValueError("sell quantity exceeds account position")
            if side == "SELL":
                reserved_rows = self._connection.execute(
                    "SELECT i.quantity,COALESCE(o.cumulative_filled_quantity,0) AS filled "
                    "FROM intents i LEFT JOIN orders o ON o.intent_id=i.intent_id "
                    "WHERE i.account_id=? AND i.side='SELL' AND i.status NOT IN "
                    "('REJECTED','SUBMISSION_FAILED','SUBMIT_FAILED','EXPIRED',"
                    "'CANCELLED_ALL','FAILED','DISABLED',"
                    "'DELETED','FILL_CANCELLED','FILLED_ALL','SUPERSEDED')",
                    (account_id,),
                ).fetchall()
                reserved_quantity = sum(
                    max(0, int(row["quantity"]) - int(row["filled"])) for row in reserved_rows
                )
                if reserved_quantity + quantity > int(account["quantity"]):
                    raise ValueError("sell intents exceed account available position")
            reserve = (price * quantity * (Decimal("1") + fee)).quantize(Decimal("0.0001"))
            if side == "BUY":
                cash = Decimal(account["cash"])
                if reserve > cash:
                    raise ValueError("buy order exceeds account cash")
                self._connection.execute(
                    "UPDATE virtual_accounts SET cash=?,frozen_cash=?,updated_at=? WHERE account_id=?",
                    (
                        str((cash - reserve).quantize(Decimal("0.0001"))),
                        str((Decimal(account["frozen_cash"]) + reserve).quantize(Decimal("0.0001"))),
                        now, account_id,
                    ),
                )
            payload = {
                "account_id": account_id, "decision_id": decision_id,
                "order_sequence": order_sequence, "channel_id": account["channel_id"],
                "symbol": symbol.upper(), "side": side, "quantity": quantity,
                "limit_price": str(price), "valid_session": valid_session,
                "fee_rate": str(fee), "order_type": order_type,
            }
            self._connection.execute(
                "INSERT INTO intents(intent_id,account_id,decision_id,order_sequence,channel_id,"
                "symbol,side,quantity,limit_price,valid_session,payload,status,"
                "reservation_generation,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,'PENDING_SUBMIT',?,?,?)",
                (
                    intent_id, account_id, decision_id, order_sequence, account["channel_id"], symbol.upper(),
                    side, quantity, str(price), valid_session,
                    json.dumps(payload, ensure_ascii=False), int(side == "BUY"), now, now,
                ),
            )
            if side == "BUY":
                self._connection.execute(
                    "INSERT INTO account_ledger(ledger_entry_id,account_id,entry_type,order_id,fill_id,"
                    "cash_delta,frozen_cash_delta,quantity_delta,fee,balance_after,quantity_after,"
                    "occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(uuid5(NAMESPACE_URL, f"pte-reserve:{intent_id}")), account_id,
                        "INTENT_RESERVE", None, None, str(-reserve), str(reserve), 0,
                        "0.0000", str((cash - reserve).quantize(Decimal("0.0001"))),
                        int(account["quantity"]), now,
                    ),
                )
            if audit_event is not None:
                self._insert_audit_event(audit_event)
            row = self._connection.execute(
                "SELECT * FROM intents WHERE intent_id=?", (intent_id,)
            ).fetchone()
        return self._account_intent_row(row)

    def create_account_plan_intents(
        self, *, account_id: str, decision_id: str, symbol: str,
        valid_session: str, fee_rate, legs: list[dict[str, object]],
        audit_events: list[AuditEvent] | None = None, _in_transaction: bool = False,
    ) -> list[dict[str, Any]]:
        """Atomically persist every leg of one durable dependent execution plan."""
        from decimal import Decimal

        if not legs:
            return []
        sequences = [int(leg["sequence"]) for leg in legs]
        if sequences != list(range(len(legs))):
            raise ValueError("plan leg sequences must be contiguous")
        if audit_events is not None and len(audit_events) != len(legs):
            raise ValueError("plan audit event count differs from plan legs")
        fee = Decimal(str(fee_rate))
        now = _utc_now()
        intent_ids = {
            sequence: "PTE-" + hashlib.sha256(
                f"{account_id}\0{decision_id}\0{sequence}".encode("utf-8")
            ).hexdigest()[:20].upper()
            for sequence in sequences
        }
        with self._lock, self._write_context(_in_transaction):
            existing = self._connection.execute(
                "SELECT * FROM intents WHERE account_id=? AND decision_id=? "
                "ORDER BY order_sequence",
                (account_id, decision_id),
            ).fetchall()
            if existing:
                if len(existing) != len(legs):
                    raise ValueError("stored execution plan is incomplete")
                rows = [self._account_intent_row(row) for row in existing]
                expected = [
                    {
                        "sequence": int(leg["sequence"]),
                        "side": str(leg["side"]).upper(),
                        "quantity": int(leg["quantity"]),
                        "order_type": str(leg["order_type"]).upper(),
                        "limit_price": str(
                            Decimal(str(leg["limit_price"])).quantize(Decimal("0.0001"))
                        ),
                        "submit_after": str(leg["submit_after"]),
                        "submit_before": str(leg["submit_before"]),
                        "dependency_intent_id": (
                            None
                            if leg.get("dependency_sequence") is None
                            else intent_ids[int(leg["dependency_sequence"])]
                        ),
                    }
                    for leg in legs
                ]
                actual = [
                    {
                        "sequence": int(row["order_sequence"]),
                        "side": row["side"],
                        "quantity": int(row["quantity"]),
                        "order_type": str(row["payload"].get("order_type")),
                        "limit_price": row["limit_price"],
                        "submit_after": row["payload"].get("submit_after"),
                        "submit_before": row["payload"].get("submit_before"),
                        "dependency_intent_id": row["payload"].get("dependency_intent_id"),
                    }
                    for row in rows
                ]
                if actual != expected:
                    raise ValueError("existing execution plan differs from idempotent request")
                return rows

            account = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE account_id=?", (account_id,)
            ).fetchone()
            if account is None:
                raise KeyError(account_id)
            require_futu_simulate_cn(account["channel_id"])
            if account["account_type"] != STRATEGY_ACCOUNT_TYPE:
                raise ValueError("channel reconciliation account cannot create order intents")
            if account["status"] != "RUNNING":
                raise ValueError("virtual account status does not allow execution plans")
            if account["health"] == "BLOCKED":
                raise ValueError("blocked virtual account cannot create execution plans")
            if bool(account["paused"]):
                raise ValueError("paused virtual account cannot create execution plans")
            buy_reserve = Decimal("0")
            planned_sell = 0
            normalized: list[dict[str, object]] = []
            for leg in legs:
                sequence = int(leg["sequence"])
                side = str(leg["side"]).upper()
                order_type = str(leg["order_type"]).upper()
                quantity = int(leg["quantity"])
                price = Decimal(str(leg["limit_price"])).quantize(Decimal("0.0001"))
                dependency_sequence = leg.get("dependency_sequence")
                if side not in {"BUY", "SELL"}:
                    raise ValueError("plan intent side must be BUY or SELL")
                if (side, order_type) not in {
                    ("BUY", "LIMIT"),
                    ("SELL", "LIMIT"),
                    ("SELL", "MARKET"),
                }:
                    raise ValueError(
                        "plan buys must be LIMIT; plan sells must be LIMIT or MARKET"
                    )
                if quantity <= 0 or quantity % 100:
                    raise ValueError("plan intent quantity must use positive 100-share lots")
                if price <= 0:
                    raise ValueError("plan intent price must be positive")
                if dependency_sequence is not None:
                    dependency_sequence = int(dependency_sequence)
                    if dependency_sequence < 0 or dependency_sequence >= sequence:
                        raise ValueError("plan dependency must reference an earlier leg")
                if str(leg.get("submit_after", "")) >= str(leg.get("submit_before", "")):
                    raise ValueError("plan submission window is empty")
                if side == "BUY":
                    buy_reserve += price * quantity * (Decimal("1") + fee)
                else:
                    planned_sell += quantity
                normalized.append({
                    **leg,
                    "sequence": sequence,
                    "side": side,
                    "order_type": order_type,
                    "quantity": quantity,
                    "limit_price": str(price),
                    "dependency_sequence": dependency_sequence,
                })
            buy_reserve = buy_reserve.quantize(Decimal("0.0001"))
            cash = Decimal(account["cash"])
            if buy_reserve > cash:
                raise ValueError("execution plan buy legs exceed account cash")
            reserved_rows = self._connection.execute(
                "SELECT i.quantity,COALESCE(o.cumulative_filled_quantity,0) AS filled "
                "FROM intents i LEFT JOIN orders o ON o.intent_id=i.intent_id "
                "WHERE i.account_id=? AND i.side='SELL' AND i.status NOT IN "
                "('REJECTED','SUBMISSION_FAILED','SUBMIT_FAILED','EXPIRED',"
                "'CANCELLED_ALL','FAILED','DISABLED','DELETED','FILL_CANCELLED','FILLED_ALL',"
                "'SUPERSEDED')",
                (account_id,),
            ).fetchall()
            reserved_sell = sum(
                max(0, int(row["quantity"]) - int(row["filled"])) for row in reserved_rows
            )
            if reserved_sell + planned_sell > int(account["quantity"]):
                raise ValueError("execution plan sell legs exceed available position")
            self._connection.execute(
                "UPDATE virtual_accounts SET cash=?,frozen_cash=?,updated_at=? WHERE account_id=?",
                (
                    str((cash - buy_reserve).quantize(Decimal("0.0001"))),
                    str((Decimal(account["frozen_cash"]) + buy_reserve).quantize(Decimal("0.0001"))),
                    now,
                    account_id,
                ),
            )
            running_cash = cash
            for leg in normalized:
                sequence = int(leg["sequence"])
                dependency_sequence = leg.get("dependency_sequence")
                dependency_id = (
                    None
                    if dependency_sequence is None
                    else intent_ids[int(dependency_sequence)]
                )
                status = "PENDING_SUBMIT" if dependency_id is None else "WAITING_DEPENDENCY"
                payload = {
                    "account_id": account_id,
                    "decision_id": decision_id,
                    "order_sequence": sequence,
                    "channel_id": account["channel_id"],
                    "symbol": symbol.upper(),
                    "side": leg["side"],
                    "quantity": leg["quantity"],
                    "limit_price": leg["limit_price"],
                    "valid_session": valid_session,
                    "fee_rate": str(fee),
                    "order_type": leg["order_type"],
                    "plan_mode": str(leg["plan_mode"]),
                    "role": str(leg["role"]),
                    "checkpoint": str(leg["checkpoint"]),
                    "submit_after": str(leg["submit_after"]),
                    "submit_before": str(leg["submit_before"]),
                    "dependency_intent_id": dependency_id,
                    "dependency_required_status": leg.get("dependency_required_status"),
                }
                self._connection.execute(
                    "INSERT INTO intents(intent_id,account_id,decision_id,order_sequence,channel_id,"
                    "symbol,side,quantity,limit_price,valid_session,payload,status,"
                    "reservation_generation,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        intent_ids[sequence], account_id, decision_id, sequence, account["channel_id"],
                        symbol.upper(), leg["side"], leg["quantity"], leg["limit_price"],
                        valid_session, json.dumps(payload, ensure_ascii=False), status,
                        int(leg["side"] == "BUY"), now, now,
                    ),
                )
                if leg["side"] == "BUY":
                    reserve = (
                        Decimal(str(leg["limit_price"])) * int(leg["quantity"])
                        * (Decimal("1") + fee)
                    ).quantize(Decimal("0.0001"))
                    running_cash -= reserve
                    self._connection.execute(
                        "INSERT INTO account_ledger(ledger_entry_id,account_id,entry_type,order_id,"
                        "fill_id,cash_delta,frozen_cash_delta,quantity_delta,fee,balance_after,"
                        "quantity_after,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            str(uuid5(NAMESPACE_URL, f"pte-reserve:{intent_ids[sequence]}")),
                            account_id, "INTENT_RESERVE", None, None, str(-reserve), str(reserve),
                            0, "0.0000", str(running_cash.quantize(Decimal("0.0001"))),
                            int(account["quantity"]), now,
                        ),
                    )
            for event in audit_events or []:
                self._insert_audit_event(event)
            rows = self._connection.execute(
                "SELECT * FROM intents WHERE account_id=? AND decision_id=? "
                "ORDER BY order_sequence",
                (account_id, decision_id),
            ).fetchall()
        return [self._account_intent_row(row) for row in rows]

    def create_account_immediate_intents(
        self, *, account_id: str, decision_id: str, symbol: str,
        valid_session: str, fee_rate, orders: list[dict[str, object]],
        audit_events: list[AuditEvent] | None = None, _in_transaction: bool = False,
    ) -> list[dict[str, Any]]:
        """Atomically persist every immediate order split from one decision."""
        from decimal import Decimal

        if not orders:
            return []
        sequences = [int(order["sequence"]) for order in orders]
        if sequences != list(range(len(orders))):
            raise ValueError("immediate order sequences must be contiguous")
        if audit_events is not None and len(audit_events) != len(orders):
            raise ValueError("immediate order audit event count differs from orders")
        fee = Decimal(str(fee_rate))
        now = _utc_now()
        normalized: list[dict[str, object]] = []
        intent_ids: dict[int, str] = {}
        for order in orders:
            sequence = int(order["sequence"])
            side = str(order["side"]).upper()
            order_type = str(order["order_type"]).upper()
            quantity = int(order["quantity"])
            price = Decimal(str(order["limit_price"])).quantize(Decimal("0.0001"))
            if side not in {"BUY", "SELL"}:
                raise ValueError("intent side must be BUY or SELL")
            if (side, order_type) not in {
                ("BUY", "LIMIT"), ("SELL", "LIMIT"), ("SELL", "MARKET"),
            }:
                raise ValueError("buy intents must be LIMIT; sell intents must be LIMIT or MARKET")
            if quantity <= 0 or quantity % 100:
                raise ValueError("intent quantity must use positive 100-share lots")
            if price <= 0:
                raise ValueError("intent price must be positive")
            normalized.append({
                "sequence": sequence, "side": side, "order_type": order_type,
                "quantity": quantity, "limit_price": str(price),
            })
            identity = f"{account_id}\0{decision_id}\0{sequence}".encode("utf-8")
            intent_ids[sequence] = "PTE-" + hashlib.sha256(identity).hexdigest()[:20].upper()

        with self._lock, self._write_context(_in_transaction):
            existing = self._connection.execute(
                "SELECT * FROM intents WHERE account_id=? AND decision_id=? "
                "ORDER BY order_sequence", (account_id, decision_id),
            ).fetchall()
            if existing:
                if len(existing) != len(normalized):
                    raise ValueError("stored immediate order intents are incomplete")
                rows = [self._account_intent_row(row) for row in existing]
                expected = [{
                    "sequence": int(order["sequence"]),
                    "symbol": symbol.upper(),
                    "side": str(order["side"]),
                    "quantity": int(order["quantity"]),
                    "limit_price": str(order["limit_price"]),
                    "valid_session": valid_session,
                    "order_type": str(order["order_type"]),
                } for order in normalized]
                actual = [{
                    "sequence": int(row["order_sequence"]),
                    "symbol": row["symbol"], "side": row["side"],
                    "quantity": int(row["quantity"]),
                    "limit_price": row["limit_price"],
                    "valid_session": row["valid_session"],
                    "order_type": str(row["payload"].get("order_type", "LIMIT")),
                } for row in rows]
                if actual != expected:
                    raise ValueError("existing immediate intents differ from idempotent request")
                return rows

            account = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE account_id=?", (account_id,),
            ).fetchone()
            if account is None:
                raise KeyError(account_id)
            require_futu_simulate_cn(account["channel_id"])
            if account["account_type"] != STRATEGY_ACCOUNT_TYPE:
                raise ValueError("channel reconciliation account cannot create order intents")
            if account["status"] != "RUNNING":
                raise ValueError("virtual account status does not allow order intents")
            if account["health"] == "BLOCKED":
                raise ValueError("blocked virtual account cannot create order intents")
            if bool(account["paused"]):
                raise ValueError("paused virtual account cannot create order intents")

            buy_reserve = sum(
                (
                    Decimal(str(order["limit_price"])) * int(order["quantity"])
                    * (Decimal("1") + fee)
                    for order in normalized if order["side"] == "BUY"
                ),
                Decimal("0"),
            ).quantize(Decimal("0.0001"))
            planned_sell = sum(
                int(order["quantity"]) for order in normalized if order["side"] == "SELL"
            )
            cash = Decimal(account["cash"])
            if buy_reserve > cash:
                raise ValueError("immediate buy orders exceed account cash")
            reserved_rows = self._connection.execute(
                "SELECT i.quantity,COALESCE(o.cumulative_filled_quantity,0) AS filled "
                "FROM intents i LEFT JOIN orders o ON o.intent_id=i.intent_id "
                "WHERE i.account_id=? AND i.side='SELL' AND i.status NOT IN "
                "('REJECTED','SUBMISSION_FAILED','SUBMIT_FAILED','EXPIRED',"
                "'CANCELLED_ALL','FAILED','DISABLED','DELETED','FILL_CANCELLED','FILLED_ALL',"
                "'SUPERSEDED')",
                (account_id,),
            ).fetchall()
            reserved_sell = sum(
                max(0, int(row["quantity"]) - int(row["filled"])) for row in reserved_rows
            )
            if reserved_sell + planned_sell > int(account["quantity"]):
                raise ValueError("immediate sell orders exceed available position")

            self._connection.execute(
                "UPDATE virtual_accounts SET cash=?,frozen_cash=?,updated_at=? WHERE account_id=?",
                (
                    str((cash - buy_reserve).quantize(Decimal("0.0001"))),
                    str((Decimal(account["frozen_cash"]) + buy_reserve).quantize(Decimal("0.0001"))),
                    now, account_id,
                ),
            )
            running_cash = cash
            for order in normalized:
                sequence = int(order["sequence"])
                payload = {
                    "account_id": account_id, "decision_id": decision_id,
                    "order_sequence": sequence, "channel_id": account["channel_id"],
                    "symbol": symbol.upper(), "side": order["side"],
                    "quantity": order["quantity"], "limit_price": order["limit_price"],
                    "valid_session": valid_session, "fee_rate": str(fee),
                    "order_type": order["order_type"],
                }
                self._connection.execute(
                    "INSERT INTO intents(intent_id,account_id,decision_id,order_sequence,channel_id,"
                    "symbol,side,quantity,limit_price,valid_session,payload,status,"
                    "reservation_generation,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,'PENDING_SUBMIT',?,?,?)",
                    (
                        intent_ids[sequence], account_id, decision_id, sequence,
                        account["channel_id"], symbol.upper(), order["side"],
                        order["quantity"], order["limit_price"], valid_session,
                        json.dumps(payload, ensure_ascii=False),
                        int(order["side"] == "BUY"), now, now,
                    ),
                )
                if order["side"] == "BUY":
                    reserve = (
                        Decimal(str(order["limit_price"])) * int(order["quantity"])
                        * (Decimal("1") + fee)
                    ).quantize(Decimal("0.0001"))
                    running_cash -= reserve
                    self._connection.execute(
                        "INSERT INTO account_ledger(ledger_entry_id,account_id,entry_type,order_id,"
                        "fill_id,cash_delta,frozen_cash_delta,quantity_delta,fee,balance_after,"
                        "quantity_after,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            str(uuid5(NAMESPACE_URL, f"pte-reserve:{intent_ids[sequence]}")),
                            account_id, "INTENT_RESERVE", None, None, str(-reserve), str(reserve),
                            0, "0.0000", str(running_cash.quantize(Decimal("0.0001"))),
                            int(account["quantity"]), now,
                        ),
                    )
            for event in audit_events or []:
                self._insert_audit_event(event)
            rows = self._connection.execute(
                "SELECT * FROM intents WHERE account_id=? AND decision_id=? "
                "ORDER BY order_sequence", (account_id, decision_id),
            ).fetchall()
        return [self._account_intent_row(row) for row in rows]

    def save_account_decision(
        self, account_id: str, payload: dict[str, object], *, _in_transaction: bool = False,
    ) -> dict[str, Any]:
        decision_id = str(payload["decision_id"])
        signal_date = str(payload["signal_date"])
        valid_session = str(payload["valid_session"])
        now = _utc_now()
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
        cycle_target = int(payload.get("cycle_target_quantity") or 0) or None
        if payload.get("plan_mode") == "CORE_SETUP":
            # A core identity exists only after the setup order is fully filled.
            # The planned quantity remains available in the immutable decision payload.
            cycle_target = None
        with self._lock, self._write_context(_in_transaction):
            same_session = self._connection.execute(
                "SELECT decision_id FROM decisions "
                "WHERE account_id=? AND signal_date=? AND status='ACTIVE'",
                (account_id, signal_date),
            ).fetchone()
            if same_session is not None and same_session["decision_id"] != decision_id:
                raise ValueError(
                    "account already has another decision for the same signal date"
                )
            existing = self._connection.execute(
                "SELECT payload,status FROM decisions WHERE account_id=? AND decision_id=?",
                (account_id, decision_id),
            ).fetchone()
            if existing is not None:
                if existing["status"] != "ACTIVE":
                    raise ValueError("superseded decision cannot become active again")
                previous = json.loads(existing["payload"])
                current = json.loads(encoded)
                runtime_fields = {
                    "source_decision_id", "actual_quantity", "delta_quantity", "available_cash",
                    "portfolio_revision", "state_revision",
                }
                if not previous.get("plan_identity"):
                    runtime_fields.update({"signal_identity", "plan_identity"})
                previous_identity = {
                    key: value for key, value in previous.items() if key not in runtime_fields
                }
                current_identity = {
                    key: value for key, value in current.items() if key not in runtime_fields
                }
                if previous_identity != current_identity:
                    raise ValueError("existing decision differs from the idempotent request")
            canonical = encoded if existing is None else str(existing["payload"])
            self._connection.execute(
                "INSERT OR IGNORE INTO decisions(account_id,decision_id,payload,signal_date,"
                "valid_session,generated_at) VALUES(?,?,?,?,?,?)",
                (account_id, decision_id, encoded, signal_date, valid_session, now),
            )
            self._connection.execute(
                "UPDATE virtual_accounts SET last_decision_id=?,last_decision_payload=?,"
                "cycle_target=?,updated_at=? WHERE account_id=?",
                (decision_id, canonical, cycle_target, now, account_id),
            )
        return self.account_decision(account_id, decision_id)

    def supersede_account_decision(
        self, account_id: str, decision_id: str, superseded_by: str,
        *, audit_event: AuditEvent | None = None, _in_transaction: bool = False,
    ) -> dict[str, Any]:
        if decision_id == superseded_by:
            raise ValueError("a decision cannot supersede itself")
        now = _utc_now()
        with self._lock, self._write_context(_in_transaction):
            changed = self._connection.execute(
                "UPDATE decisions SET status='SUPERSEDED',superseded_by=?,superseded_at=? "
                "WHERE account_id=? AND decision_id=? AND status='ACTIVE'",
                (superseded_by, now, account_id, decision_id),
            ).rowcount
            if not changed:
                raise ValueError("active decision to supersede was not found")
            if audit_event is not None:
                self._insert_audit_event(audit_event)
        return self.account_decision(account_id, decision_id)

    def account_decision(self, account_id: str, decision_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM decisions WHERE account_id=? AND decision_id=?",
                (account_id, decision_id),
            ).fetchone()
        if row is None:
            raise KeyError((account_id, decision_id))
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def account_decisions(self, account_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT account_id,decision_id FROM decisions"
        values: tuple[object, ...] = ()
        if account_id is not None:
            sql += " WHERE account_id=?"
            values = (account_id,)
        sql += " ORDER BY generated_at DESC"
        with self._lock:
            keys = [tuple(row) for row in self._connection.execute(sql, values).fetchall()]
        return [self.account_decision(str(account), str(decision)) for account, decision in keys]

    @staticmethod
    def _account_intent_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        result["attention_required"] = bool(result.get("attention_required"))
        return result

    def account_intent(self, intent_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM intents WHERE intent_id=?", (intent_id,)
            ).fetchone()
        return None if row is None else self._account_intent_row(row)

    def update_account_intent_status(self, intent_id: str, status: str) -> dict[str, Any]:
        with self._lock, self._connection:
            changed = self._connection.execute(
                "UPDATE intents SET status=?,updated_at=? WHERE intent_id=?",
                (status, _utc_now(), intent_id),
            ).rowcount
        if not changed:
            raise KeyError(intent_id)
        result = self.account_intent(intent_id)
        assert result is not None
        return result

    def claim_account_intent(self, intent_id: str) -> bool:
        """Atomically grant one submitter ownership of a pending intent."""
        with self._lock, self._connection:
            changed = self._connection.execute(
                "UPDATE intents SET status='SUBMITTING',updated_at=? "
                "WHERE intent_id=? AND status='PENDING_SUBMIT'",
                (_utc_now(), intent_id),
            ).rowcount
        return bool(changed)

    def pending_account_intents(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM intents WHERE status='PENDING_SUBMIT' "
                "ORDER BY account_id,decision_id,order_sequence"
            ).fetchall()
        return [self._account_intent_row(row) for row in rows]

    def waiting_dependency_intents(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM intents WHERE status='WAITING_DEPENDENCY' "
                "ORDER BY account_id,decision_id,order_sequence"
            ).fetchall()
        return [self._account_intent_row(row) for row in rows]

    def activate_dependency_intent(self, intent_id: str) -> bool:
        with self._lock, self._connection:
            changed = self._connection.execute(
                "UPDATE intents SET status='PENDING_SUBMIT',updated_at=? "
                "WHERE intent_id=? AND status='WAITING_DEPENDENCY'",
                (_utc_now(), intent_id),
            ).rowcount
        return bool(changed)

    def unresolved_account_intents(
        self, account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in UNRESOLVED_INTENT_STATUSES)
        values: list[object] = list(sorted(UNRESOLVED_INTENT_STATUSES))
        sql = f"SELECT * FROM intents WHERE status IN ({placeholders})"
        if account_id is not None:
            sql += " AND account_id=?"
            values.append(account_id)
        sql += " ORDER BY updated_at"
        with self._lock:
            rows = self._connection.execute(sql, values).fetchall()
        return [self._account_intent_row(row) for row in rows]

    def attention_account_intents(
        self, account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM intents WHERE attention_required=1"
        values: tuple[object, ...] = ()
        if account_id is not None:
            sql += " AND account_id=?"
            values = (account_id,)
        sql += " ORDER BY updated_at"
        with self._lock:
            rows = self._connection.execute(sql, values).fetchall()
        return [self._account_intent_row(row) for row in rows]

    def require_account_intent_attention(self, intent_id: str, reason: str) -> dict[str, Any]:
        if not str(reason).strip():
            raise ValueError("intent attention reason is required")
        with self._lock, self._connection:
            changed = self._connection.execute(
                "UPDATE intents SET attention_required=1,attention_reason=?,resolved_at=NULL,"
                "resolution_note=NULL,updated_at=? WHERE intent_id=?",
                (str(reason), _utc_now(), intent_id),
            ).rowcount
        if not changed:
            raise KeyError(intent_id)
        result = self.account_intent(intent_id)
        assert result is not None
        return result

    def resolve_account_intent_attention(
        self, intent_id: str, resolution_note: str,
    ) -> dict[str, Any]:
        if not str(resolution_note).strip():
            raise ValueError("intent resolution note is required")
        now = _utc_now()
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT status,attention_required FROM intents WHERE intent_id=?", (intent_id,),
            ).fetchone()
            if row is None:
                raise KeyError(intent_id)
            if row["status"] not in TERMINAL_INTENT_STATUSES:
                raise ValueError("only terminal intents can be acknowledged")
            if not bool(row["attention_required"]):
                raise ValueError("intent does not require acknowledgement")
            self._connection.execute(
                "UPDATE intents SET attention_required=0,resolved_at=?,resolution_note=?,updated_at=? "
                "WHERE intent_id=?",
                (now, str(resolution_note), now, intent_id),
            )
        result = self.account_intent(intent_id)
        assert result is not None
        return result

    def account_intents(self, account_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM intents"
        values: tuple[object, ...] = ()
        if account_id is not None:
            sql += " WHERE account_id=?"
            values = (account_id,)
        sql += " ORDER BY created_at,order_sequence"
        with self._lock:
            rows = self._connection.execute(sql, values).fetchall()
        return [self._account_intent_row(row) for row in rows]

    def bind_channel_order(
        self, intent_id: str, channel_order_id: str, payload: dict[str, object],
        audit_event: AuditEvent | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        initial_payload = dict(payload)
        initial_payload["cumulative_filled_quantity"] = 0
        initial_payload["average_fill_price"] = 0
        with self._lock, self._connection:
            intent = self._connection.execute(
                "SELECT * FROM intents WHERE intent_id=?", (intent_id,)
            ).fetchone()
            if intent is None:
                raise KeyError(intent_id)
            if intent["status"] not in {"SUBMITTING", "SUBMISSION_UNCERTAIN"}:
                raise ValueError(f"intent cannot bind an order from status {intent['status']}")
            expected = {
                "symbol": intent["symbol"],
                "side": intent["side"],
                "quantity": int(intent["quantity"]),
                "remark": intent_id,
            }
            actual = {
                "symbol": str(payload.get("symbol", "")).upper(),
                "side": str(payload.get("side", "")).upper(),
                "quantity": int(payload.get("quantity", 0)),
                "remark": str(payload.get("remark", "")),
            }
            if actual != expected:
                raise ValueError("broker order differs from the owning intent")
            collision = self._connection.execute(
                "SELECT intent_id FROM orders WHERE channel_order_id=?",
                (str(channel_order_id),),
            ).fetchone()
            if collision is not None and collision["intent_id"] != intent_id:
                raise ValueError("channel order id is already bound to another intent")
            existing = self._connection.execute(
                "SELECT channel_order_id FROM orders WHERE intent_id=?", (intent_id,)
            ).fetchone()
            if existing is not None and existing["channel_order_id"] != str(channel_order_id):
                raise ValueError("intent is already bound to another channel order")
            self._connection.execute(
                "INSERT INTO orders(channel_order_id,intent_id,account_id,decision_id,channel_id,"
                "payload,cumulative_filled_quantity,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(channel_order_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                (
                    str(channel_order_id), intent_id, intent["account_id"], intent["decision_id"],
                    intent["channel_id"], json.dumps(initial_payload, ensure_ascii=False, default=str),
                    0, now, now,
                ),
            )
            self._connection.execute(
                "UPDATE intents SET status=?,channel_order_id=?,updated_at=? WHERE intent_id=?",
                (str(payload.get("status", "SUBMITTED")), str(channel_order_id), now, intent_id),
            )
            if audit_event is not None:
                self._insert_audit_event(audit_event)
        return self.account_order(str(channel_order_id))

    def release_account_intent(
        self, intent_id: str, status: str, *, attention_reason: str | None = None,
        audit_event: AuditEvent | None = None, _in_transaction: bool = False,
    ) -> dict[str, Any]:
        """Release the unfilled BUY reservation once and terminate an intent."""
        from decimal import Decimal

        if status not in TERMINAL_INTENT_STATUSES:
            raise ValueError("intent release requires a terminal status")
        now = _utc_now()
        with self._lock, self._write_context(_in_transaction):
            intent = self._connection.execute(
                "SELECT * FROM intents WHERE intent_id=?", (intent_id,)
            ).fetchone()
            if intent is None:
                raise KeyError(intent_id)
            if intent["status"] in TERMINAL_INTENT_STATUSES:
                return self._account_intent_row(intent)
            account = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE account_id=?", (intent["account_id"],)
            ).fetchone()
            order = self._connection.execute(
                "SELECT * FROM orders WHERE intent_id=?", (intent_id,)
            ).fetchone()
            filled = 0 if order is None else int(order["cumulative_filled_quantity"])
            release = Decimal("0")
            old_cash = Decimal(account["cash"])
            old_frozen = Decimal(account["frozen_cash"])
            if intent["side"] == "BUY":
                fee_rate = Decimal(json.loads(intent["payload"]).get("fee_rate", "0.0005"))
                remaining = max(0, int(intent["quantity"]) - filled)
                release = (
                    Decimal(intent["limit_price"]) * remaining * (Decimal("1") + fee_rate)
                ).quantize(Decimal("0.0001"))
                if release > old_frozen:
                    raise ValueError("account frozen cash is below the intent reservation")
                self._connection.execute(
                    "UPDATE virtual_accounts SET cash=?,frozen_cash=?,updated_at=? WHERE account_id=?",
                    (
                        str((old_cash + release).quantize(Decimal("0.0001"))),
                        str((old_frozen - release).quantize(Decimal("0.0001"))),
                        now, intent["account_id"],
                    ),
                )
            attention = status in ATTENTION_REQUIRED_INTENT_STATUSES
            reason = (attention_reason or status) if attention else None
            self._connection.execute(
                "UPDATE intents SET status=?,attention_required=?,attention_reason=?,"
                "resolved_at=NULL,resolution_note=NULL,updated_at=? WHERE intent_id=?",
                (status, int(attention), reason, now, intent_id),
            )
            if release:
                generation = int(intent["reservation_generation"])
                release_identity = (
                    f"pte-release:{intent_id}" if generation == 1
                    else f"pte-release:{intent_id}:{generation}"
                )
                ledger_id = str(uuid5(NAMESPACE_URL, release_identity))
                self._connection.execute(
                    "INSERT INTO account_ledger(ledger_entry_id,account_id,entry_type,"
                    "order_id,fill_id,cash_delta,frozen_cash_delta,quantity_delta,fee,balance_after,"
                    "quantity_after,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        ledger_id, intent["account_id"], "INTENT_RELEASE",
                        None if order is None else order["channel_order_id"], None,
                        str(release), str(-release), 0, "0.0000",
                        str((old_cash + release).quantize(Decimal("0.0001"))),
                        int(account["quantity"]), now,
                    ),
                )
            if audit_event is not None:
                self._insert_audit_event(audit_event)
        result = self.account_intent(intent_id)
        assert result is not None
        return result

    def recover_future_planned_intent(
        self, intent_id: str, audit_event: AuditEvent | None = None,
    ) -> dict[str, Any]:
        """Requeue an unsubmitted future plan that an older clock comparison expired."""
        from decimal import Decimal

        now = _utc_now()
        with self._lock, self._connection:
            intent = self._connection.execute(
                "SELECT * FROM intents WHERE intent_id=?", (intent_id,),
            ).fetchone()
            if intent is None:
                raise KeyError(intent_id)
            if (
                intent["status"] != "EXPIRED"
                or not bool(intent["attention_required"])
                or intent["channel_order_id"] is not None
                or intent["attention_reason"] != "计划订单错过提交截止时间"
            ):
                raise ValueError("intent is not a recoverable future plan expiry")
            payload = json.loads(intent["payload"])
            if not payload.get("plan_mode"):
                raise ValueError("recoverable intent must belong to an execution plan")
            dependency = payload.get("dependency_intent_id")
            status = "PENDING_SUBMIT" if dependency is None else "WAITING_DEPENDENCY"
            account = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE account_id=?", (intent["account_id"],),
            ).fetchone()
            if account is None:
                raise KeyError(intent["account_id"])
            reserve = Decimal("0")
            generation = int(intent["reservation_generation"])
            if intent["side"] == "BUY":
                generation += 1
                fee = Decimal(str(payload.get("fee_rate", "0.0005")))
                reserve = (
                    Decimal(intent["limit_price"]) * int(intent["quantity"])
                    * (Decimal("1") + fee)
                ).quantize(Decimal("0.0001"))
                cash = Decimal(account["cash"])
                if reserve > cash:
                    raise ValueError("account cash is below the recovered intent reservation")
                self._connection.execute(
                    "UPDATE virtual_accounts SET cash=?,frozen_cash=?,updated_at=? WHERE account_id=?",
                    (
                        str((cash - reserve).quantize(Decimal("0.0001"))),
                        str((Decimal(account["frozen_cash"]) + reserve).quantize(Decimal("0.0001"))),
                        now, intent["account_id"],
                    ),
                )
                self._connection.execute(
                    "INSERT INTO account_ledger(ledger_entry_id,account_id,entry_type,order_id,"
                    "fill_id,cash_delta,frozen_cash_delta,quantity_delta,fee,balance_after,"
                    "quantity_after,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(uuid5(NAMESPACE_URL, f"pte-reserve:{intent_id}:{generation}")),
                        intent["account_id"], "INTENT_RESERVE", None, None,
                        str(-reserve), str(reserve), 0, "0.0000",
                        str((cash - reserve).quantize(Decimal("0.0001"))),
                        int(account["quantity"]), now,
                    ),
                )
            self._connection.execute(
                "UPDATE intents SET status=?,attention_required=0,attention_reason=NULL,"
                "resolved_at=?,resolution_note=?,reservation_generation=?,updated_at=? "
                "WHERE intent_id=?",
                (
                    status, now, "自动修复未来交易日时间窗误判", generation, now, intent_id,
                ),
            )
            if audit_event is not None:
                self._insert_audit_event(audit_event)
        result = self.account_intent(intent_id)
        assert result is not None
        return result

    def update_channel_order_report(
        self, channel_order_id: str, payload: dict[str, object],
    ) -> dict[str, Any]:
        """Persist the latest Futu order state, then release any unused reservation."""
        status = str(payload.get("status", "UNKNOWN"))
        now = _utc_now()
        with self._lock, self._connection:
            order = self._connection.execute(
                "SELECT * FROM orders WHERE channel_order_id=?", (channel_order_id,)
            ).fetchone()
            if order is None:
                raise KeyError(channel_order_id)
            intent = self._connection.execute(
                "SELECT status FROM intents WHERE intent_id=?", (order["intent_id"],)
            ).fetchone()
            self._connection.execute(
                "UPDATE orders SET payload=?,updated_at=? WHERE channel_order_id=?",
                (json.dumps(payload, ensure_ascii=False, default=str), now, channel_order_id),
            )
            intent_id = str(order["intent_id"])
            previous_status = str(intent["status"])
            if status not in TERMINAL_ORDER_STATUSES:
                self._connection.execute(
                    "UPDATE intents SET status=?,updated_at=? WHERE intent_id=?",
                    (status, now, intent_id),
                )
        if (
            status in TERMINAL_ORDER_STATUSES
            and previous_status not in TERMINAL_INTENT_STATUSES
        ):
            self.release_account_intent(intent_id, status)
        return self.account_order(channel_order_id)

    def account_order(self, channel_order_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM orders WHERE channel_order_id=?", (channel_order_id,)
            ).fetchone()
        if row is None:
            raise KeyError(channel_order_id)
        result = dict(row)
        payload = json.loads(result.pop("payload"))
        for key, value in payload.items():
            if key in {"created_at", "updated_at"} and not value:
                continue
            result[key] = value
        return result

    def account_orders(self, account_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT channel_order_id FROM orders"
        values: tuple[object, ...] = ()
        if account_id is not None:
            sql += " WHERE account_id=?"
            values = (account_id,)
        sql += " ORDER BY updated_at DESC"
        with self._lock:
            ids = [row[0] for row in self._connection.execute(sql, values).fetchall()]
        return [self.account_order(str(order_id)) for order_id in ids]

    def apply_fill_increment(
        self, channel_order_id: str, *, cumulative_quantity: int,
        average_price, occurred_at: str,
    ) -> dict[str, Any] | None:
        """Apply the newly reported cumulative Futu fill exactly once."""
        from decimal import Decimal

        if isinstance(cumulative_quantity, bool) or not isinstance(cumulative_quantity, int):
            raise ValueError("cumulative filled quantity must be an integer")
        with self._lock, self._connection:
            order = self._connection.execute(
                "SELECT * FROM orders WHERE channel_order_id=?", (channel_order_id,)
            ).fetchone()
            if order is None:
                raise KeyError(channel_order_id)
            previous = int(order["cumulative_filled_quantity"])
            if cumulative_quantity < previous:
                raise ValueError("cumulative filled quantity cannot decrease")
            if cumulative_quantity == previous:
                return None
            avg = Decimal(str(average_price))
            if not avg.is_finite() or avg <= 0:
                raise ValueError("average fill price must be positive and finite")
            intent = self._connection.execute(
                "SELECT * FROM intents WHERE intent_id=?", (order["intent_id"],)
            ).fetchone()
            if cumulative_quantity > int(intent["quantity"]):
                raise ValueError("cumulative fill exceeds intent quantity")
            account = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE account_id=?", (order["account_id"],)
            ).fetchone()
            order_payload = json.loads(order["payload"])
            previous_avg = Decimal(str(order_payload.get("average_fill_price", 0)))
            increment = cumulative_quantity - previous
            incremental_value = avg * cumulative_quantity - previous_avg * previous
            incremental_price = incremental_value / increment
            if (
                not incremental_value.is_finite()
                or incremental_value <= 0
                or not incremental_price.is_finite()
                or incremental_price <= 0
            ):
                raise ValueError("incremental fill value must be positive and finite")
            intent_payload = json.loads(intent["payload"])
            order_type = str(intent_payload.get("order_type", "LIMIT")).upper()
            limit_price = Decimal(intent["limit_price"])
            if order_type == "LIMIT":
                if intent["side"] == "BUY" and incremental_price > limit_price:
                    raise ValueError("buy fill price exceeds intent limit")
                if intent["side"] == "SELL" and incremental_price < limit_price:
                    raise ValueError("sell fill price is below intent limit")
            fee_rate = Decimal(intent_payload.get("fee_rate", "0.0005"))
            fee = (incremental_value * fee_rate).quantize(Decimal("0.0001"))
            old_cash = Decimal(account["cash"])
            old_frozen = Decimal(account["frozen_cash"])
            old_quantity = int(account["quantity"])
            old_cost = Decimal(account["average_cost"])
            if intent["side"] == "BUY":
                reserved = (
                    Decimal(intent["limit_price"]) * increment * (Decimal("1") + fee_rate)
                ).quantize(Decimal("0.0001"))
                if reserved > old_frozen:
                    raise ValueError("buy fill exceeds the account reservation")
                cash = old_cash + reserved - incremental_value - fee
                frozen = old_frozen - reserved
                quantity = old_quantity + increment
                cost = ((old_cost * old_quantity + incremental_value + fee) / quantity)
                realized = Decimal(account["realized_pnl"])
            else:
                cash = old_cash + incremental_value - fee
                frozen = old_frozen
                quantity = old_quantity - increment
                if quantity < 0:
                    raise ValueError("Futu sell fill exceeds owning account position")
                realized = Decimal(account["realized_pnl"]) + (
                    (incremental_price - old_cost) * increment - fee
                )
                cost = Decimal("0") if quantity == 0 else old_cost
            if (
                not cash.is_finite()
                or not frozen.is_finite()
                or cash < 0
                or frozen < 0
                or quantity < 0
            ):
                raise ValueError("fill would violate non-negative account balances")
            fill_id = str(uuid5(NAMESPACE_URL, f"pte-fill:{channel_order_id}:{cumulative_quantity}"))
            self._connection.execute(
                "INSERT INTO fills(fill_id,account_id,order_id,decision_id,channel_id,side,quantity,"
                "price,fee,realized_pnl,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    fill_id, order["account_id"], str(channel_order_id), order["decision_id"],
                    intent["channel_id"], intent["side"], increment, str(incremental_price), str(fee),
                    str((realized - Decimal(account["realized_pnl"])).quantize(Decimal("0.0001"))),
                    occurred_at,
                ),
            )
            cash = cash.quantize(Decimal("0.0001"))
            frozen = frozen.quantize(Decimal("0.0001"))
            cost = cost.quantize(Decimal("0.000000000001"))
            realized = realized.quantize(Decimal("0.0001"))
            total_assets = (
                cash + frozen + Decimal(quantity) * incremental_price
            ).quantize(Decimal("0.0001"))
            cycle_target = account["cycle_target"]
            if intent_payload.get("role") == "CORE_SETUP":
                # Earlier increments of this same setup order are already in
                # the account. The position before the order must be flat.
                if old_quantity != previous:
                    raise ValueError("core setup fill requires an initially flat account")
                if cumulative_quantity == int(intent["quantity"]):
                    cycle_target = quantity
            self._connection.execute(
                "UPDATE virtual_accounts SET cash=?,frozen_cash=?,quantity=?,average_cost=?,"
                "realized_pnl=?,total_assets=?,cycle_target=?,updated_at=? WHERE account_id=?",
                (
                    str(cash), str(frozen), quantity, str(cost), str(realized),
                    str(total_assets), cycle_target, _utc_now(), order["account_id"],
                ),
            )
            order_payload["cumulative_filled_quantity"] = cumulative_quantity
            order_payload["average_fill_price"] = float(avg)
            self._connection.execute(
                "UPDATE orders SET payload=?,cumulative_filled_quantity=?,updated_at=? "
                "WHERE channel_order_id=?",
                (json.dumps(order_payload, default=str), cumulative_quantity, _utc_now(), channel_order_id),
            )
            self._connection.execute(
                "INSERT INTO account_ledger(ledger_entry_id,account_id,entry_type,order_id,fill_id,"
                "cash_delta,frozen_cash_delta,quantity_delta,fee,balance_after,quantity_after,occurred_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid5(NAMESPACE_URL, f"pte-ledger:{fill_id}")), order["account_id"],
                    "BUY_FILL" if intent["side"] == "BUY" else "SELL_FILL",
                    str(channel_order_id), fill_id, str(cash - old_cash), str(frozen - old_frozen),
                    increment if intent["side"] == "BUY" else -increment, str(fee), str(cash),
                    quantity, occurred_at,
                ),
            )
        return self.account_fill(fill_id)

    def account_fill(self, fill_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM fills WHERE fill_id=?", (fill_id,)
            ).fetchone()
        if row is None:
            raise KeyError(fill_id)
        return dict(row)

    def account_fills(self, account_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM fills"
        values: tuple[object, ...] = ()
        if account_id is not None:
            sql += " WHERE account_id=?"
            values = (account_id,)
        sql += " ORDER BY occurred_at DESC"
        with self._lock:
            return [dict(row) for row in self._connection.execute(sql, values).fetchall()]

    def account_fills_after_rowid(self, rowid: int = 0) -> list[dict[str, Any]]:
        """Return append-only fills after a cash-reconciliation checkpoint."""
        if isinstance(rowid, bool) or not isinstance(rowid, int) or rowid < 0:
            raise ValueError("fill rowid checkpoint must be a non-negative integer")
        with self._lock:
            rows = self._connection.execute(
                "SELECT rowid AS fill_rowid,* FROM fills WHERE rowid>? ORDER BY rowid",
                (rowid,),
            ).fetchall()
        return [dict(row) for row in rows]

    def apply_broker_fee_reconciliation(
        self, account_id: str, adjustment, *, reference: str,
        treatment: str, occurred_at: str, event: AuditEvent,
        realized_fill_id: str | None = None,
    ) -> dict[str, Any]:
        """Apply one idempotent broker-cash fee correction to an owning account."""
        from decimal import Decimal

        amount = Decimal(str(adjustment)).quantize(Decimal("0.0001"))
        if not amount.is_finite() or amount == 0:
            raise ValueError("fee reconciliation adjustment must be finite and non-zero")
        if treatment not in {"COST_BASIS", "REALIZED"}:
            raise ValueError("fee reconciliation treatment is invalid")
        if not str(reference).strip():
            raise ValueError("fee reconciliation reference is required")
        if event.event_type != "BROKER_FEE_RECONCILED" or event.account_id != account_id:
            raise ValueError("fee reconciliation audit event does not match the account")
        ledger_id = str(uuid5(NAMESPACE_URL, f"pte-broker-fee:{reference}"))
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT 1 FROM account_ledger WHERE ledger_entry_id=?", (ledger_id,),
            ).fetchone()
            if existing is not None:
                return {
                    "applied": False, "ledger_entry_id": ledger_id,
                    "account": self.virtual_account(account_id),
                }
            account = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE account_id=?", (account_id,),
            ).fetchone()
            if account is None:
                raise KeyError(account_id)
            cash = (Decimal(account["cash"]) + amount).quantize(Decimal("0.0001"))
            total_assets = (
                Decimal(account["total_assets"]) + amount
            ).quantize(Decimal("0.0001"))
            if cash < 0 or total_assets < 0:
                raise ValueError("fee reconciliation would make account balances negative")
            quantity = int(account["quantity"])
            cost = Decimal(account["average_cost"])
            realized = Decimal(account["realized_pnl"])
            if treatment == "COST_BASIS":
                if quantity <= 0:
                    raise ValueError("cost-basis reconciliation requires an open position")
                cost = (cost - amount / quantity).quantize(Decimal("0.000000000001"))
                if cost < 0:
                    raise ValueError("fee reconciliation would make average cost negative")
            else:
                pnl_delta = amount
                if quantity == 0:
                    pnl_delta = (
                        cash - Decimal(account["initial_cash"]) - realized
                    ).quantize(Decimal("0.0001"))
                if realized_fill_id is None:
                    raise ValueError("realized reconciliation requires an owning sell fill")
                fill = self._connection.execute(
                    "SELECT account_id,side,realized_pnl FROM fills WHERE fill_id=?",
                    (realized_fill_id,),
                ).fetchone()
                if (
                    fill is None or fill["account_id"] != account_id
                    or str(fill["side"]).upper() != "SELL"
                ):
                    raise ValueError("realized reconciliation sell fill is invalid")
                realized = (realized + pnl_delta).quantize(Decimal("0.0001"))
                self._connection.execute(
                    "UPDATE fills SET realized_pnl=? WHERE fill_id=?",
                    (str((Decimal(fill["realized_pnl"]) + pnl_delta).quantize(
                        Decimal("0.0001")
                    )), realized_fill_id),
                )
            now = _utc_now()
            self._connection.execute(
                "UPDATE virtual_accounts SET cash=?,total_assets=?,average_cost=?,realized_pnl=?,"
                "updated_at=? WHERE account_id=?",
                (str(cash), str(total_assets), str(cost), str(realized), now, account_id),
            )
            self._connection.execute(
                "INSERT INTO account_ledger(ledger_entry_id,account_id,entry_type,order_id,fill_id,"
                "cash_delta,frozen_cash_delta,quantity_delta,fee,balance_after,quantity_after,"
                "occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ledger_id, account_id, "BROKER_FEE_RECONCILIATION", None, None,
                    str(amount), "0.0000", 0, str(-amount), str(cash), quantity, occurred_at,
                ),
            )
            self._insert_audit_event(event)
        return {
            "applied": True, "ledger_entry_id": ledger_id,
            "account": self.virtual_account(account_id),
        }

    def apply_channel_fee_variance(
        self, *, adjustment, reference: str, occurred_at: str, event: AuditEvent,
    ) -> dict[str, Any]:
        """Book a verified aggregate Futu fee variance only to the system account."""
        from decimal import Decimal

        amount = Decimal(str(adjustment)).quantize(Decimal("0.0001"))
        if not amount.is_finite() or amount == 0:
            raise ValueError("channel fee variance must be finite and non-zero")
        if event.event_type != "CHANNEL_FEE_VARIANCE_RECONCILED":
            raise ValueError("channel fee variance audit event is invalid")
        account = self.channel_reconciliation_account(FUTU_SIMULATE_CN_CHANNEL_ID)
        if account is None:
            raise ValueError("channel reconciliation account has not been initialized")
        if event.account_id != account["account_id"]:
            raise ValueError("channel fee variance audit account does not match")
        ledger_id = str(uuid5(NAMESPACE_URL, f"pte-channel-fee-variance:{reference}"))
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT 1 FROM account_ledger WHERE ledger_entry_id=?", (ledger_id,)
            ).fetchone()
            if existing is not None:
                return {"applied": False, "ledger_entry_id": ledger_id, "account": account}
            cash = (Decimal(account["cash"]) + amount).quantize(Decimal("0.0001"))
            total_assets = (Decimal(account["total_assets"]) + amount).quantize(Decimal("0.0001"))
            self._connection.execute(
                "UPDATE virtual_accounts SET cash=?,total_assets=?,updated_at=? WHERE account_id=?",
                (str(cash), str(total_assets), _utc_now(), account["account_id"]),
            )
            self._connection.execute(
                "INSERT INTO account_ledger(ledger_entry_id,account_id,entry_type,order_id,fill_id,"
                "cash_delta,frozen_cash_delta,quantity_delta,fee,balance_after,quantity_after,occurred_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (ledger_id, account["account_id"], "CHANNEL_FEE_VARIANCE", None, None,
                 str(amount), "0.0000", 0, str(-amount), str(cash), 0, occurred_at),
            )
            self._insert_audit_event(event)
        return {"applied": True, "ledger_entry_id": ledger_id, "account": self.virtual_account(account["account_id"])}

    def account_invariant_violations(self) -> list[dict[str, object]]:
        """Return ledger/account disagreements without mutating runtime state."""
        from decimal import Decimal

        violations: list[dict[str, object]] = []
        with self._lock:
            accounts = self._connection.execute(
                "SELECT account_id,initial_cash,cash,frozen_cash,quantity FROM virtual_accounts "
                "WHERE status!='RETIRED' ORDER BY account_id"
            ).fetchall()
            for account in accounts:
                entries = self._connection.execute(
                    "SELECT cash_delta,frozen_cash_delta,quantity_delta "
                    "FROM account_ledger WHERE account_id=?",
                    (account["account_id"],),
                ).fetchall()
                cash_delta = sum(
                    (Decimal(entry["cash_delta"]) for entry in entries), Decimal("0")
                )
                frozen_delta = sum(
                    (Decimal(entry["frozen_cash_delta"]) for entry in entries), Decimal("0")
                )
                quantity_delta = sum(int(entry["quantity_delta"]) for entry in entries)
                expected_cash = (
                    Decimal(account["initial_cash"]) + cash_delta
                ).quantize(Decimal("0.0001"))
                expected_frozen = frozen_delta.quantize(Decimal("0.0001"))
                expected_quantity = quantity_delta
                actual_cash = Decimal(account["cash"]).quantize(Decimal("0.0001"))
                actual_frozen = Decimal(account["frozen_cash"]).quantize(Decimal("0.0001"))
                actual_quantity = int(account["quantity"])
                if (
                    expected_cash != actual_cash
                    or expected_frozen != actual_frozen
                    or expected_quantity != actual_quantity
                ):
                    violations.append({
                        "account_id": account["account_id"],
                        "expected": {
                            "cash": str(expected_cash), "frozen_cash": str(expected_frozen),
                            "quantity": expected_quantity,
                        },
                        "actual": {
                            "cash": str(actual_cash), "frozen_cash": str(actual_frozen),
                            "quantity": actual_quantity,
                        },
                    })
        return violations

    def repair_released_intent_ledger(
        self, account_id: str, intent_id: str, audit_event: AuditEvent,
    ) -> dict[str, object]:
        """Append one missing release entry after proving the account was already unfrozen."""
        from decimal import Decimal

        with self._lock, self._connection:
            account = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE account_id=?", (account_id,)
            ).fetchone()
            intent = self._connection.execute(
                "SELECT * FROM intents WHERE intent_id=? AND account_id=?",
                (intent_id, account_id),
            ).fetchone()
            if account is None:
                raise KeyError(account_id)
            if intent is None:
                raise KeyError(intent_id)
            if (
                intent["side"] != "BUY"
                or intent["status"] not in TERMINAL_INTENT_STATUSES
            ):
                raise ValueError("ledger repair requires a terminal BUY intent")
            order = self._connection.execute(
                "SELECT * FROM orders WHERE intent_id=?", (intent_id,)
            ).fetchone()
            if order is not None or intent["channel_order_id"] is not None:
                raise ValueError("ledger repair is blocked when a channel order exists")

            generation = int(intent["reservation_generation"])
            if generation < 1:
                raise ValueError("ledger repair requires a persisted reservation generation")
            identity = (
                f"pte-release:{intent_id}" if generation == 1
                else f"pte-release:{intent_id}:{generation}"
            )
            ledger_id = str(uuid5(NAMESPACE_URL, identity))
            existing = self._connection.execute(
                "SELECT * FROM account_ledger WHERE ledger_entry_id=?", (ledger_id,)
            ).fetchone()
            violations = [
                row for row in self.account_invariant_violations()
                if row["account_id"] == account_id
            ]
            if existing is not None:
                if violations:
                    raise ValueError("release ledger entry exists but account invariant still fails")
                return {
                    "status": "ALREADY_REPAIRED", "account_id": account_id,
                    "intent_id": intent_id, "ledger_entry_id": ledger_id,
                }
            if not bool(intent["attention_required"]):
                raise ValueError("new ledger repair requires an intent awaiting operator review")
            if len(violations) != 1:
                raise ValueError("ledger repair requires exactly one account invariant violation")

            payload = json.loads(intent["payload"])
            fee_rate = Decimal(str(payload.get("fee_rate", "0.0005")))
            release = (
                Decimal(intent["limit_price"]) * int(intent["quantity"])
                * (Decimal("1") + fee_rate)
            ).quantize(Decimal("0.0001"))
            expected = violations[0]["expected"]
            actual = violations[0]["actual"]
            if not (
                Decimal(actual["cash"]) - Decimal(expected["cash"]) == release
                and Decimal(expected["frozen_cash"]) - Decimal(actual["frozen_cash"]) == release
                and Decimal(actual["frozen_cash"]) == 0
                and int(actual["quantity"]) == int(expected["quantity"])
            ):
                raise ValueError("account mismatch is not the exact missing intent release")
            now = _utc_now()
            self._connection.execute(
                "INSERT INTO account_ledger(ledger_entry_id,account_id,entry_type,order_id,fill_id,"
                "cash_delta,frozen_cash_delta,quantity_delta,fee,balance_after,quantity_after,"
                "occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ledger_id, account_id, "INTENT_RELEASE", None, None,
                    str(release), str(-release), 0, "0.0000", actual["cash"],
                    int(actual["quantity"]), now,
                ),
            )
            self._insert_audit_event(audit_event)
        return {
            "status": "REPAIRED", "account_id": account_id, "intent_id": intent_id,
            "ledger_entry_id": ledger_id, "cash_delta": str(release),
            "frozen_cash_delta": str(-release),
        }

    def account_snapshots(self, account_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT session,payload,created_at FROM account_snapshots "
                "WHERE account_id=? ORDER BY session", (account_id,)
            ).fetchall()
        return [
            {"account_id": account_id, "session": row["session"],
             **json.loads(row["payload"]), "created_at": row["created_at"]}
            for row in rows
        ]

    def save_account_snapshot(
        self, account_id: str, session: str, payload: dict[str, object],
        *, _in_transaction: bool = False,
    ) -> None:
        now = _utc_now()
        with self._lock, self._write_context(_in_transaction):
            if self._connection.execute(
                "SELECT 1 FROM virtual_accounts WHERE account_id=?", (account_id,)
            ).fetchone() is None:
                raise KeyError(account_id)
            self._connection.execute(
                "INSERT INTO account_snapshots(account_id,session,payload,created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(account_id,session) DO UPDATE SET payload=excluded.payload,created_at=excluded.created_at",
                (account_id, session, json.dumps(payload, ensure_ascii=False, default=str), now),
            )
            self._connection.execute(
                "UPDATE virtual_accounts SET total_assets=?,observation_start=COALESCE(observation_start,?),"
                "last_settlement_session=?,updated_at=? WHERE account_id=?",
                (str(payload["total_assets"]), session, session, now, account_id),
            )

    def save_snapshot(self, payload: dict[str, object]) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO snapshots(created_at, payload) VALUES(?, ?)",
                (_utc_now(), json.dumps(payload, ensure_ascii=False, default=str)),
            )

    def latest_snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return None if row is None else json.loads(row["payload"])

    def save_cancel_token(self, token: str, channel_order_id: str, expires_at: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO cancel_tokens(token, channel_order_id, expires_at) VALUES(?, ?, ?)",
                (token, channel_order_id, expires_at),
            )

    def consume_cancel_token(self, token: str, channel_order_id: str, now: str) -> str:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT channel_order_id, expires_at, used_at FROM cancel_tokens WHERE token=?",
                (token,),
            ).fetchone()
            if row is None or row["used_at"] is not None or str(row["expires_at"]) < now:
                return "invalid"
            if row["channel_order_id"] != channel_order_id:
                return "bound"
            self._connection.execute(
                "UPDATE cancel_tokens SET used_at=? WHERE token=?", (now, token)
            )
        return "ok"
