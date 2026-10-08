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
from .lifecycle import (RunState, DecisionState, IntentControlState, TERMINAL_DECISION_STATES,
                        validate_transition, planned_orders, execution_state)
from .account_binding import AccountBindingUpdate, AccountStrategyBinding
from .account_retirement import (
    AccountRetirementRequest, AccountRetirementResult, AccountRetirementStatus, CapitalPoolBalance,
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
RUNTIME_DATABASE_SCHEMA_VERSION = 4
RUNTIME_DATABASE_COMPATIBLE_VERSIONS = (1, 2, 3, 4)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_account_bindings(
    connection: sqlite3.Connection,
    bindings: tuple[tuple[AccountBindingUpdate, AccountStrategyBinding, dict[str, object]], ...],
) -> None:
    """Switch validated bindings and adopt prepared replacements in one transaction."""
    from .audit import AuditRecorder

    if not connection.in_transaction:
        raise RuntimeError("account binding update requires a transaction")
    store = PaperStore.__new__(PaperStore)
    store._connection, store._lock, store._atomic_decision_depth = connection, RLock(), 1
    audit = AuditRecorder(store)
    for update, binding, payload in bindings:
        account_id = update.account_id
        account = store.virtual_account(account_id)
        if account["run_state"] != RunState.PAUSED or account["release_hash"] != update.expected_release_hash:
            raise ValueError(f"{account_id}: paused account binding changed concurrently")
        pending = [row for row in store.account_decisions(account_id) if row["status"] == DecisionState.PENDING]
        if any(row["status"] == DecisionState.EXECUTING for row in store.account_decisions(account_id)):
            raise ValueError(f"{account_id}: executing decision blocks binding update")
        for row in pending:
            event = audit.build(
                "DECISION_SUPERSEDED", source="account_maintenance", actor_type="OPERATOR",
                account_id=account_id, decision_id=row["decision_id"],
                details={"replacement_decision_id": payload["decision_id"], "reason": "STRATEGY_UPGRADE"},
            )
            store.supersede_account_decision(account_id, row["decision_id"], str(payload["decision_id"]),
                                            audit_event=event, _in_transaction=True)
        for intent in store.account_intents(account_id):
            if intent["status"] in TERMINAL_INTENT_STATUSES:
                continue
            if intent["status"] not in {"PENDING_SUBMIT", "WAITING_DEPENDENCY"} or intent.get("channel_order_id"):
                raise ValueError(f"{account_id}: submitted intent blocks binding update")
            store.release_account_intent(
                intent["intent_id"], "SUPERSEDED", _in_transaction=True,
                audit_event=audit.build("ORDER_INTENT_SUPERSEDED", source="account_maintenance",
                    actor_type="OPERATOR", account_id=account_id, decision_id=intent["decision_id"],
                    details={"intent_id": intent["intent_id"], "replacement_decision_id": payload["decision_id"]}),
            )
        changed = connection.execute(
            "UPDATE virtual_accounts SET release_hash=?,strategy_name_snapshot=?,qualification_snapshot=?,updated_at=? "
            "WHERE account_id=? AND release_hash=? AND run_state='PAUSED'",
            (binding.release_hash, binding.name, binding.qualification.value, _utc_now(), account_id, update.expected_release_hash),
        ).rowcount
        if changed != 1:
            raise ValueError(f"{account_id}: account binding changed concurrently")
        store.save_account_decision(account_id, payload, _in_transaction=True)
        audit.record("ACCOUNT_STRATEGY_BOUND", source="account_maintenance", actor_type="OPERATOR",
                     account_id=account_id, release_hash=binding.release_hash, decision_id=str(payload["decision_id"]),
                     details={"previous_release_hash": update.expected_release_hash, "reason": "STRATEGY_UPGRADE"})
        audit.record("DECISION_GENERATED", source="account_maintenance", actor_type="OPERATOR",
                     account_id=account_id, release_hash=binding.release_hash, decision_id=str(payload["decision_id"]),
                     details={"signal_date": str(payload["signal_date"]), "valid_session": str(payload["valid_session"]),
                              "action": payload["action"], "reason": "STRATEGY_UPGRADE"})
        connection.executemany(
            "DELETE FROM settings WHERE key=?",
            [(f"{prefix}:{account_id}",) for prefix in (
                "last_account_decision_date", "last_account_schedule_skip_date", "last_prepared_data_id",
                "last_data_prepare_date", "last_data_preparation", "data_preparation_error",
            )],
        )


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


def backup_runtime_database(path: Path, *, retention: int = 1) -> Path | None:
    """Create a consistent pre-start SQLite backup; retain only the latest by default."""
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
    @classmethod
    def open_readonly(cls, path: Path) -> "PaperStore":
        """Read a consistent current-schema snapshot without creating or migrating it."""
        store = cls.__new__(cls)
        store.path = Path(path)
        store._lock = RLock()
        store._atomic_decision_depth = 0
        store._readonly = True
        store._connection = sqlite3.connect(
            store.path.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False,
        )
        store._connection.row_factory = sqlite3.Row
        try:
            store._connection.execute("PRAGMA query_only=ON")
            store._connection.execute("BEGIN")
            row = store._connection.execute(
                "SELECT value FROM settings WHERE key='runtime_database_schema_version'"
            ).fetchone()
            if row is None or row[0] != str(RUNTIME_DATABASE_SCHEMA_VERSION):
                raise RuntimeError("read-only access requires the current PTE database schema")
        except BaseException:
            store._connection.close()
            raise
        return store

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._atomic_decision_depth = 0
        self._readonly = False
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        try:
            _validate_database_schema(self._connection)
        except Exception:
            self._connection.close()
            raise
        stored_schema = self._connection.execute(
            "SELECT value FROM settings WHERE key='runtime_database_schema_version'"
        ).fetchone()
        if stored_schema is not None and int(stored_schema[0]) in {3, 4}:
            self._initialize_lifecycle()
            return
        self._connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS account_retirements (
                account_id TEXT PRIMARY KEY,
                release_hash TEXT NOT NULL,
                initial_cash TEXT NOT NULL,
                released_cash TEXT NOT NULL,
                retired_at TEXT NOT NULL
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
        self._initialize_lifecycle()

    def _initialize_lifecycle(self):
        from .lifecycle_migration import migrate_lifecycle
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            migrate_lifecycle(self._connection, _utc_now())
            self._connection.execute(
                "INSERT INTO settings(key,value) VALUES('runtime_database_schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(RUNTIME_DATABASE_SCHEMA_VERSION),),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            self._connection.close()
            raise

    @contextmanager
    def atomic_decision_update(self):
        """Serialize and atomically commit one decision and its local order intents."""
        with self._lock:
            if getattr(self, "_readonly", False):
                raise sqlite3.OperationalError("attempt to write a readonly database")
            if self._connection.in_transaction:
                raise RuntimeError("nested store transaction is not supported")
            self._connection.execute("BEGIN IMMEDIATE")
            self._atomic_decision_depth += 1
            try:
                yield
                self._validate_decision_relations()
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()
            finally:
                self._atomic_decision_depth -= 1

    def _write_context(self, in_transaction: bool):
        if in_transaction or self._atomic_decision_depth:
            if not self._connection.in_transaction:
                raise RuntimeError("business write requires the caller's transaction")
            return nullcontext()
        return self.atomic_decision_update()

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
        with self._lock, self._write_context(False):
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
        with self.atomic_decision_update():
            if cash > self.capital_pool_balance().unallocated_cash:
                raise ValueError("initial cash exceeds unallocated capital pool cash")
            self._connection.execute(
                "INSERT INTO virtual_accounts(account_id,name,baseline_version,baseline_sha256,"
                "strategy_id,strategy_name_snapshot,strategy_version,release_hash,"
                "selection_data_cutoff,qualification_snapshot,symbol,asset_type,initial_cash,cash,total_assets,"
                "channel_id,account_type,run_state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    account_id, name, baseline_version, baseline_sha256, strategy_id,
                    strategy_name_snapshot, strategy_version, release_hash,
                    selection_data_cutoff, qualification_snapshot, symbol.upper(), asset_type,
                    str(cash), str(cash), str(cash),
                    FUTU_SIMULATE_CN_CHANNEL_ID, STRATEGY_ACCOUNT_TYPE, RunState.PAUSED, now, now,
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
        with self._lock, self._write_context(False):
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
                "symbol,asset_type,initial_cash,cash,total_assets,channel_id,account_type,run_state,"
                "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (account_id, "Futu模拟盘CN渠道平账账户", "channel_reconciliation.v1", baseline,
                 "CASH.CN", "cash", "0.0000", "0.0000", "0.0000",
                 FUTU_SIMULATE_CN_CHANNEL_ID, CHANNEL_RECONCILIATION_ACCOUNT_TYPE, None, now, now),
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
        with self._lock, self._write_context(False):
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
        with self._lock, self._write_context(False):
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
        with self._lock, self._write_context(False):
            source = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE account_id=?", (old_account_id,)
            ).fetchone()
            if source is None:
                raise KeyError(old_account_id)
            if source["run_state"] == "RETIRED":
                raise ValueError("retired account cannot be renamed")
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
        with self._lock, self._write_context(False):
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
        result = dict(row)
        result.pop("legacy_status", None)
        result.pop("legacy_paused", None)
        return result

    def virtual_accounts(self):
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM virtual_accounts ORDER BY created_at, account_id"
            ).fetchall()
        return [self.virtual_account(row["account_id"]) for row in rows]

    def strategy_virtual_accounts(self):
        return [
            row for row in self.virtual_accounts()
            if row.get("account_type", STRATEGY_ACCOUNT_TYPE) == STRATEGY_ACCOUNT_TYPE
        ]

    def capital_pool_balance(self) -> CapitalPoolBalance:
        from decimal import Decimal

        with self._lock:
            registered = Decimal(self._setting("futu_capital_pool"))
            allocated = sum((Decimal(row[0]) for row in self._connection.execute(
                "SELECT initial_cash FROM virtual_accounts WHERE (run_state IS NULL OR run_state<>'RETIRED')"
            )), Decimal("0"))
            recovered = sum((Decimal(row[1]) - Decimal(row[0]) for row in self._connection.execute(
                "SELECT initial_cash,released_cash FROM account_retirements"
            )), Decimal("0"))
        return CapitalPoolBalance(registered, allocated, recovered)

    def _retirement_cash(self, account_id: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT released_cash FROM account_retirements WHERE account_id=?", (account_id,),
            ).fetchone()
        return None if row is None else str(row[0])

    def _retire_account(self, request: AccountRetirementRequest) -> AccountRetirementResult:
        from decimal import Decimal

        with self.atomic_decision_update():
            account = self.virtual_account(request.account_id)
            if account["account_type"] != STRATEGY_ACCOUNT_TYPE or account["run_state"] != RunState.PAUSED:
                raise ValueError("retirement requires a paused strategy account")
            if account["release_hash"] != request.expected_release_hash:
                raise ValueError("retirement release hash differs from account")
            if account["run_state"] != RunState.PAUSED:
                raise ValueError("pause the account before retirement")
            if account["quantity"] != 0 or Decimal(account["frozen_cash"]) != 0:
                raise ValueError("retirement requires no position or frozen cash")
            if account["health"] == "BLOCKED":
                raise ValueError("blocked account cannot retire")
            if any(row["status"] not in TERMINAL_INTENT_STATUSES or row["attention_required"]
                   for row in self.account_intents(request.account_id)):
                raise ValueError("unfinished or unresolved intents block retirement")
            if any(row["status"] not in TERMINAL_ORDER_STATUSES
                   for row in self.account_orders(request.account_id)):
                raise ValueError("unfinished orders block retirement")
            if any(self._setting(key) != "OK" for key in (
                "channel_reconciliation_status", "futu_cash_reconciliation_status",
            )) or self.account_invariant_violations():
                raise ValueError("successful channel and ledger reconciliation required")
            cash = Decimal(account["cash"])
            if not cash.is_finite() or cash < 0:
                raise ValueError("retirement requires finite nonnegative cash")
            now = _utc_now()
            self._connection.execute(
                "INSERT INTO account_retirements VALUES(?,?,?,?,?)",
                (request.account_id, request.expected_release_hash, account["initial_cash"], str(cash), now),
            )
            self._connection.execute(
                "INSERT INTO account_ledger(ledger_entry_id,account_id,entry_type,cash_delta,"
                "frozen_cash_delta,quantity_delta,fee,balance_after,quantity_after,occurred_at) "
                "VALUES(?,?,'CAPITAL_RETURN',?,'0.0000',0,'0.0000','0.0000',0,?)",
                (f"retirement:{request.account_id}", request.account_id, str(-cash), now),
            )
            self._connection.execute(
                "UPDATE virtual_accounts SET run_state='RETIRED',cash='0.0000',total_assets='0.0000',"
                "cycle_target=NULL,last_decision_id=NULL,last_decision_payload=NULL,updated_at=? "
                "WHERE account_id=?", (now, request.account_id),
            )
            for decision in self.account_decisions(request.account_id):
                if decision["status"] == DecisionState.PENDING:
                    self._transition_decision(request.account_id, decision["decision_id"],
                                              DecisionState.CANCELLED, "ACCOUNT_RETIRED")
            self._insert_audit_event(self._new_audit_event(
                "ACCOUNT_RETIRED", source="account_retirement", actor_type="OPERATOR",
                correlation_id=f"retirement:{request.account_id}", account_id=request.account_id,
                strategy_id=account["strategy_id"], strategy_version=account["strategy_version"],
                release_hash=request.expected_release_hash,
                details={"released_cash": str(cash), "reason": request.reason, "actor": request.actor},
            ))
            remaining = self._connection.execute(
                "SELECT COUNT(*) FROM virtual_accounts WHERE strategy_id=? AND strategy_version=? "
                "AND run_state<>'RETIRED'",
                (account["strategy_id"], account["strategy_version"]),
            ).fetchone()[0]
        return AccountRetirementResult(AccountRetirementStatus.RETIRED, request.account_id, cash, remaining)

    def channel_reconciliation_account(self, channel_id: str = FUTU_SIMULATE_CN_CHANNEL_ID):
        require_futu_simulate_cn(channel_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM virtual_accounts WHERE channel_id=? AND account_type=?",
                (channel_id, CHANNEL_RECONCILIATION_ACCOUNT_TYPE),
            ).fetchone()
        return None if row is None else dict(row)

    def set_virtual_paused(self, account_id: str, paused: bool):
        if type(paused) is not bool:
            raise TypeError("pause requires a boolean")
        target = RunState.PAUSED if paused else RunState.RUNNING
        with self._lock, self._write_context(False):
            account = self.virtual_account(account_id)
            if account["account_type"] != STRATEGY_ACCOUNT_TYPE:
                raise ValueError("system reconciliation account has no strategy lifecycle")
            if account["run_state"] == RunState.RETIRED:
                raise ValueError("retired account cannot be paused or resumed")
            if target == RunState.RUNNING and (
                account["health"] == "BLOCKED"
                or account["qualification_snapshot"] not in {"PAPER_READY", "LIVE_READY"}
                or self.unresolved_account_intents(account_id)
                or self.attention_account_intents(account_id)
                or self.account_invariant_violations()
            ):
                raise ValueError("account enable checks failed; resolve health and execution gaps first")
            self._connection.execute(
                "UPDATE virtual_accounts SET run_state=?,updated_at=? WHERE account_id=?",
                (target, _utc_now(), account_id),
            )
        return self.virtual_account(account_id)

    def set_virtual_health(self, account_id: str, health: str, error: str | None = None):
        with self._lock, self._write_context(False):
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
        with self._lock, self._write_context(False):
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
        with self._lock, self._write_context(False):
            self._connection.execute(
                "INSERT INTO operation_failures(operation,payload,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(operation) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                (operation, json.dumps(payload, ensure_ascii=False, default=str), _utc_now()),
            )

    def clear_operation_failure(self, operation: str) -> None:
        with self._lock, self._write_context(False):
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
        with self._lock, self._write_context(False):
            self._require_execution_eligible(account_id, decision_id, symbol, valid_session)
            self._require_planned_orders(account_id, decision_id, [{"sequence": order_sequence,
                "side": side, "quantity": quantity, "order_type": order_type, "limit_price": price}])
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
            self._require_execution_portfolio(account_id, decision_id, creating=True)
            if account["run_state"] != "RUNNING":
                raise ValueError("virtual account status does not allow order intents")
            if account["health"] == "BLOCKED":
                raise ValueError("blocked virtual account cannot create order intents")
            if account["run_state"] == RunState.PAUSED:
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
            self._require_execution_eligible(account_id, decision_id, symbol, valid_session)
            self._require_planned_orders(account_id, decision_id, legs, complete=True)
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
            self._require_execution_portfolio(account_id, decision_id, creating=True)
            if account["run_state"] != "RUNNING":
                raise ValueError("virtual account status does not allow execution plans")
            if account["health"] == "BLOCKED":
                raise ValueError("blocked virtual account cannot create execution plans")
            if account["run_state"] == RunState.PAUSED:
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
            self._require_execution_eligible(account_id, decision_id, symbol, valid_session)
            self._require_planned_orders(account_id, decision_id, normalized, complete=True)
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
            self._require_execution_portfolio(account_id, decision_id, creating=True)
            if account["run_state"] != "RUNNING":
                raise ValueError("virtual account status does not allow order intents")
            if account["health"] == "BLOCKED":
                raise ValueError("blocked virtual account cannot create order intents")
            if account["run_state"] == RunState.PAUSED:
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

    def _decision_events(self, account_id: str, decision_id: str):
        rows = self._connection.execute(
            "SELECT * FROM decision_state_events WHERE account_id=? AND decision_id=? ORDER BY sequence",
            (account_id, decision_id),
        ).fetchall()
        return [{**dict(row), "evidence": json.loads(row["evidence"])} for row in rows]

    def _append_decision_state(self, account_id, decision_id, state: DecisionState,
                               reason: str, related_decision_id=None, evidence=None):
        if type(state) is not DecisionState or not reason:
            raise TypeError("decision state requires an enum and a nonempty reason")
        sequence = self._connection.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM decision_state_events WHERE account_id=? AND decision_id=?",
            (account_id, decision_id),
        ).fetchone()[0]
        self._connection.execute(
            "INSERT INTO decision_state_events(account_id,decision_id,sequence,state,reason,"
            "related_decision_id,occurred_at,evidence) VALUES(?,?,?,?,?,?,?,?)",
            (account_id, decision_id, sequence, state, reason, related_decision_id,
             _utc_now(), json.dumps(evidence or {}, ensure_ascii=False, default=str)),
        )

    def _validate_decision_relations(self):
        missing = self._connection.execute(
            "SELECT e.decision_id FROM decision_state_events e LEFT JOIN decisions d "
            "ON d.account_id=e.account_id AND d.decision_id=e.related_decision_id "
            "WHERE e.state='SUPERSEDED' AND (e.related_decision_id IS NULL OR d.decision_id IS NULL) LIMIT 1"
        ).fetchone()
        if missing is not None:
            raise ValueError("superseded decision requires an existing replacement in the same commit")

    def _transition_decision(self, account_id, decision_id, state: DecisionState,
                             reason: str, related_decision_id=None):
        events = self._decision_events(account_id, decision_id)
        if not events:
            raise ValueError("decision has no lifecycle evidence")
        previous = DecisionState(events[-1]["state"])
        validate_transition(previous, state, reason=reason, related_decision_id=related_decision_id)
        if state in {DecisionState.SUPERSEDED, DecisionState.CANCELLED}:
            if any(row.get("channel_order_id") or row["status"] in UNRESOLVED_INTENT_STATUSES
                   for row in self.account_intents(account_id, decision_id)):
                raise ValueError("submitted decision cannot be superseded or cancelled")
        self._append_decision_state(account_id, decision_id, state, reason, related_decision_id)

    def _refresh_decision_state(self, account_id, decision_id):
        events = self._decision_events(account_id, decision_id)
        if not events:
            raise ValueError("execution fact has no originating decision")
        previous = DecisionState(events[-1]["state"])
        decision = self.account_decision(account_id, decision_id)
        target = DecisionState(decision["status"])
        if target == previous:
            return
        if previous == DecisionState.PENDING and target == DecisionState.COMPLETED:
            self._transition_decision(account_id, decision_id, DecisionState.EXECUTING, "CHANNEL_EXECUTION")
        self._transition_decision(account_id, decision_id, target, decision["state_reason"])

    def _require_execution_eligible(self, account_id, decision_id, symbol, valid_session,
                                    *, moment=None, submitting=False):
        account = self.virtual_account(account_id)
        require_futu_simulate_cn(account["channel_id"])
        if account["account_type"] != STRATEGY_ACCOUNT_TYPE or account["run_state"] != RunState.RUNNING:
            raise ValueError("only a running strategy account may execute a decision")
        if account["health"] not in {"READY", "OK"}:
            raise ValueError("blocked virtual account cannot execute decisions")
        decision = self.account_decision(account_id, decision_id)
        if decision["status"] not in {DecisionState.PENDING, DecisionState.EXECUTING}:
            raise ValueError("terminal decision cannot create or submit order intents")
        adopted = self._connection.execute(
            "SELECT decision_id FROM decision_adoptions WHERE account_id=? AND valid_session=?",
            (account_id, valid_session),
        ).fetchone()
        if adopted is None or adopted[0] != decision_id:
            raise ValueError("decision is not the adopted plan for its effective session")
        payload = decision["payload"]
        identity = payload["strategy"]
        if (identity.get("strategy_id"), identity.get("version"), identity.get("release_hash"),
            payload.get("symbol"), decision["valid_session"]) != (
            account["strategy_id"], account["strategy_version"], account["release_hash"],
            symbol.upper(), valid_session,
        ) or account["symbol"] != symbol.upper():
            raise ValueError("decision identity or effective session differs from account")
        if self.get_setting("channel_reconciliation_status") == "BLOCKED" or self.get_setting("futu_cash_reconciliation_status") == "BLOCKED":
            raise ValueError("channel or cash reconciliation blocks execution")
        if submitting:
            from .trading_window import is_submission_window
            from datetime import timedelta
            if moment is None or moment.tzinfo is None:
                raise ValueError("submission requires an aware execution clock")
            if moment.astimezone(timezone(timedelta(hours=8))).date().isoformat() != valid_session or not is_submission_window(moment):
                raise ValueError("decision is outside its execution session")
            if any(self.get_setting(key) != "OK" for key in ("channel_reconciliation_status", "futu_cash_reconciliation_status")):
                raise ValueError("successful channel and cash reconciliation required before submission")
        return decision

    def _require_planned_orders(self, account_id, decision_id, requests, *, complete=False):
        from decimal import Decimal
        decision = self.account_decision(account_id, decision_id)
        plan = planned_orders(decision["payload"])
        if complete and len(requests) != len(plan):
            raise ValueError("intent count differs from immutable plan")
        for request in requests:
            sequence = request["sequence"]
            if type(sequence) is not int or not 0 <= sequence < len(plan):
                raise ValueError("intent sequence does not exist in immutable plan")
            expected = plan[sequence]
            if (str(request["side"]).upper(), int(request["quantity"]), str(request["order_type"]).upper(),
                Decimal(str(request["limit_price"])).quantize(Decimal("0.0001"))) != (
                expected["side"], expected["quantity"], expected["order_type"],
                Decimal(str(expected["limit_price"])).quantize(Decimal("0.0001")),
            ):
                raise ValueError("intent order differs from immutable plan")
            legs = decision["payload"].get("plan_legs") or []
            if legs:
                leg = legs[sequence]
                for key in ("submit_after", "submit_before", "dependency_sequence"):
                    if str(request.get(key)) != str(leg.get(key)):
                        raise ValueError("intent execution window or dependency differs from immutable plan")

    def _require_execution_portfolio(self, account_id, decision_id, *, creating=False):
        from decimal import Decimal
        account = self.virtual_account(account_id)
        decision = self.account_decision(account_id, decision_id)
        if creating and decision["status"] != DecisionState.PENDING:
            raise ValueError("executing decision cannot add new order intents")
        payload = decision["payload"]
        fills = [row for row in self.account_fills(account_id) if row["decision_id"] == decision_id]
        quantity = int(payload["actual_quantity"])
        cash = Decimal(str(payload["available_cash"]))
        for fill in fills:
            direction = 1 if fill["side"] == "BUY" else -1
            quantity += direction * fill["quantity"]
            cash -= direction * Decimal(fill["price"]) * fill["quantity"] + Decimal(fill["fee"])
        if quantity != account["quantity"] or cash.quantize(Decimal("0.0001")) != (
            Decimal(account["cash"]) + Decimal(account["frozen_cash"])
        ).quantize(Decimal("0.0001")):
            raise ValueError("account portfolio differs from the adopted plan and its fills")
        if any(row["decision_id"] != decision_id and row["status"] not in TERMINAL_INTENT_STATUSES
               for row in self.account_intents(account_id)):
            raise ValueError("another decision still owns execution intents")

    def save_account_decision(
        self, account_id: str, payload: dict[str, object], *, _in_transaction: bool = False,
    ) -> dict[str, Any]:
        decision_id = str(payload["decision_id"])
        if not any(key in payload for key in ("plan_legs", "orders", "order")):
            raise ValueError("decision requires explicit immutable order-plan evidence")
        signal_date = str(payload["signal_date"])
        valid_session = str(payload["valid_session"])
        date.fromisoformat(signal_date)
        if date.fromisoformat(valid_session) <= date.fromisoformat(signal_date):
            raise ValueError("decision effective session must follow its signal date")
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
        cycle_target = int(payload.get("cycle_target_quantity") or 0) or None
        if payload.get("plan_mode") == "CORE_SETUP":
            cycle_target = None
        with self._lock, self._write_context(_in_transaction):
            account = self.virtual_account(account_id)
            if account["run_state"] == RunState.RETIRED or account["account_type"] != STRATEGY_ACCOUNT_TYPE:
                raise ValueError("inactive account cannot save decisions")
            identity = payload["strategy"]
            if (identity.get("strategy_id"), identity.get("version"), identity.get("release_hash"), payload.get("symbol")) != (
                account["strategy_id"], account["strategy_version"], account["release_hash"], account["symbol"],
            ):
                raise ValueError("decision strategy identity differs from account")
            existing = self._connection.execute(
                "SELECT payload FROM decisions WHERE account_id=? AND decision_id=?", (account_id, decision_id),
            ).fetchone()
            if existing is not None:
                previous = json.loads(existing["payload"])
                current = json.loads(encoded)
                runtime_fields = {"source_decision_id", "actual_quantity", "delta_quantity", "available_cash",
                                  "portfolio_revision", "state_revision", "execution_disposition"}
                if not previous.get("plan_identity"):
                    runtime_fields.update({"signal_identity", "plan_identity"})
                if {k:v for k,v in previous.items() if k not in runtime_fields} != {k:v for k,v in current.items() if k not in runtime_fields}:
                    raise ValueError("existing decision differs from the idempotent request")
                if self.account_decision(account_id, decision_id)["status"] in {DecisionState.CANCELLED, DecisionState.INCOMPLETE, DecisionState.SUPERSEDED}:
                    raise ValueError("terminal decision cannot become active again")
            else:
                prior_decision = None
                adopted = self._connection.execute(
                    "SELECT decision_id FROM decision_adoptions WHERE account_id=? AND valid_session=?",
                    (account_id, valid_session),
                ).fetchone()
                if adopted is not None:
                    previous = self.account_decision(account_id, adopted[0])
                    if previous["status"] in {DecisionState.PENDING, DecisionState.EXECUTING}:
                        raise ValueError("adopted pending decision requires an explicit atomic replacement")
                    prior_decision = previous
                self._connection.execute(
                    "INSERT INTO decisions(account_id,decision_id,payload,signal_date,valid_session,generated_at,legacy_status) VALUES(?,?,?,?,?,?,'NOT_APPLICABLE')",
                    (account_id, decision_id, encoded, signal_date, valid_session, _utc_now()),
                )
                self._append_decision_state(
                    account_id, decision_id,
                    DecisionState.PENDING if planned_orders(json.loads(encoded)) else DecisionState.COMPLETED,
                    "PLAN_GENERATED" if planned_orders(json.loads(encoded)) else "NO_ORDER",
                    related_decision_id=prior_decision["decision_id"] if prior_decision else None,
                    evidence={"relation": "RECOMPUTED_FROM", "prior_state": prior_decision["status"]} if prior_decision else None,
                )
            self._connection.execute(
                "INSERT INTO decision_adoptions(account_id,valid_session,decision_id) VALUES(?,?,?) "
                "ON CONFLICT(account_id,valid_session) DO UPDATE SET decision_id=excluded.decision_id",
                (account_id, valid_session, decision_id),
            )
            if existing is None:
                self._connection.execute(
                    "UPDATE virtual_accounts SET last_decision_id=?,last_decision_payload=?,cycle_target=?,updated_at=? WHERE account_id=?",
                    (decision_id, encoded, cycle_target, _utc_now(), account_id),
                )
            else:
                self._connection.execute(
                    "UPDATE virtual_accounts SET last_decision_id=?,last_decision_payload=?,updated_at=? WHERE account_id=?",
                    (decision_id, existing["payload"], _utc_now(), account_id),
                )
        return self.account_decision(account_id, decision_id)

    def supersede_account_decision(self, account_id: str, decision_id: str, superseded_by: str,
                                   *, audit_event: AuditEvent | None = None, _in_transaction=False):
        if decision_id == superseded_by or not superseded_by:
            raise ValueError("a decision requires a distinct replacement")
        with self._lock, self._write_context(_in_transaction):
            self._transition_decision(account_id, decision_id, DecisionState.SUPERSEDED, "PLAN_REPLACED", superseded_by)
            self._connection.execute(
                "UPDATE decisions SET superseded_by=?,superseded_at=? WHERE account_id=? AND decision_id=?",
                (superseded_by, _utc_now(), account_id, decision_id),
            )
            if audit_event is not None:
                self._insert_audit_event(audit_event)
        return self.account_decision(account_id, decision_id)

    def account_decision(self, account_id: str, decision_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM decisions WHERE account_id=? AND decision_id=?", (account_id, decision_id)).fetchone()
            if row is None:
                raise KeyError((account_id, decision_id))
            result = dict(row)
            result["payload"] = json.loads(result["payload"])
            events = self._decision_events(account_id, decision_id)
            if not events:
                raise ValueError("decision has no lifecycle evidence")
            baseline = DecisionState(events[-1]["state"])
            if baseline in TERMINAL_DECISION_STATES:
                state, reason = baseline, "TERMINAL"
            else:
                intents = self.account_intents(account_id, decision_id)
                orders = [row for row in self.account_orders(account_id) if row["decision_id"] == decision_id]
                fills = [row for row in self.account_fills(account_id) if row["decision_id"] == decision_id]
                state, reason = execution_state(result["payload"], baseline, intents, orders, fills)
            result.update(status=state, state_reason=events[-1]["reason"] if reason in {"TERMINAL", "AWAITING_EXECUTION", "NO_ORDER"} else reason,
                          state_changed_at=events[-1]["occurred_at"],
                          state_events=[{key: event[key] for key in ("sequence", "state", "reason", "occurred_at", "related_decision_id")} for event in events])
            return result

    def account_decisions(self, account_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT account_id,decision_id FROM decisions"
        values = ()
        if account_id is not None:
            sql += " WHERE account_id=?"
            values = (account_id,)
        sql += " ORDER BY generated_at DESC,decision_id"
        with self._lock:
            keys = [tuple(row) for row in self._connection.execute(sql, values).fetchall()]
        return [self.account_decision(str(account), str(decision)) for account, decision in keys]

    def expire_unsubmitted_decisions(self, moment: datetime) -> None:
        """Close elapsed observation plans without backfilling historical orders."""
        from datetime import timedelta, time
        if moment.tzinfo is None:
            raise ValueError("expiry requires an aware clock")
        local = moment.astimezone(timezone(timedelta(hours=8)))
        with self._lock, self._write_context(False):
            for row in self.account_decisions():
                if row["status"] != DecisionState.PENDING or self.account_intents(row["account_id"], row["decision_id"]):
                    continue
                past = row["valid_session"] < local.date().isoformat()
                legs = row["payload"].get("plan_legs") or []
                missed_deadline = bool(legs) and row["valid_session"] == local.date().isoformat() and all(
                    local.time().replace(tzinfo=None) > time.fromisoformat(leg["submit_before"]) for leg in legs
                )
                if past or missed_deadline:
                    self._transition_decision(row["account_id"], row["decision_id"], DecisionState.INCOMPLETE, "EXECUTION_WINDOW_PASSED")

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

    def update_account_intent_status(self, intent_id: str, status: IntentControlState) -> dict[str, Any]:
        from .broker import ACTIVE_ORDER_STATUSES
        if type(status) is not IntentControlState:
            raise TypeError("local intent control requires IntentControlState")
        with self._lock, self._write_context(False):
            previous = self.account_intent(intent_id)
            if previous is None:
                raise KeyError(intent_id)
            if previous["status"] in TERMINAL_INTENT_STATUSES and status != previous["status"]:
                raise ValueError("terminal intent cannot be reactivated")
            if status == IntentControlState.SUBMISSION_UNCERTAIN and previous["status"] not in {"SUBMITTING", "SUBMITTED", "SUBMISSION_UNCERTAIN"}:
                raise ValueError("uncertain outcome requires an existing submission attempt")
            if status == IntentControlState.CANCELLING_ALL and (
                not previous.get("channel_order_id") or previous["status"] not in ACTIVE_ORDER_STATUSES
            ):
                raise ValueError("cancellation requires a known active channel order")
            changed = self._connection.execute(
                "UPDATE intents SET status=?,updated_at=? WHERE intent_id=?",
                (status, _utc_now(), intent_id),
            ).rowcount
            self._refresh_decision_state(previous["account_id"], previous["decision_id"])
        if not changed:
            raise KeyError(intent_id)
        result = self.account_intent(intent_id)
        assert result is not None
        return result

    def claim_account_intent(self, intent_id: str, *, moment: datetime) -> bool:
        """Recheck the adopted plan and grant one submitter ownership atomically."""
        with self._lock, self._write_context(False):
            row = self.account_intent(intent_id)
            if row is None:
                raise KeyError(intent_id)
            if row["status"] != "PENDING_SUBMIT":
                return False
            self._require_execution_eligible(row["account_id"], row["decision_id"], row["symbol"],
                                             row["valid_session"], moment=moment, submitting=True)
            plan_payload = self.account_decision(row["account_id"], row["decision_id"])["payload"]
            all_intents = self.account_intents(row["account_id"], row["decision_id"])
            if sorted(item["order_sequence"] for item in all_intents) != list(range(len(planned_orders(plan_payload)))):
                raise ValueError("all plan intents must be persisted before channel submission")
            legs = plan_payload.get("plan_legs") or []
            self._require_planned_orders(row["account_id"], row["decision_id"], [{
                "sequence": row["order_sequence"], "side": row["side"], "quantity": row["quantity"],
                "order_type": row["payload"].get("order_type", "LIMIT"), "limit_price": row["limit_price"],
                "submit_after": row["payload"].get("submit_after"), "submit_before": row["payload"].get("submit_before"),
                "dependency_sequence": legs[row["order_sequence"]].get("dependency_sequence") if legs else None,
            }])
            self._require_execution_portfolio(row["account_id"], row["decision_id"])
            from datetime import time, timedelta
            clock = moment.astimezone(timezone(timedelta(hours=8))).time().replace(tzinfo=None)
            payload = row["payload"]
            if (payload.get("submit_after") and clock < time.fromisoformat(payload["submit_after"])) or (payload.get("submit_before") and clock > time.fromisoformat(payload["submit_before"])):
                raise ValueError("plan leg is outside its submission window")
            self._connection.execute("UPDATE intents SET status='SUBMITTING',updated_at=? WHERE intent_id=?", (_utc_now(), intent_id))
            self._refresh_decision_state(row["account_id"], row["decision_id"])
        return True

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
        with self._lock, self._write_context(False):
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
        with self._lock, self._write_context(False):
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
        with self._lock, self._write_context(False):
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

    def account_intents(self, account_id: str | None = None, decision_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM intents"
        values: tuple[object, ...] = ()
        if account_id is not None:
            sql += " WHERE account_id=?"
            values = (account_id,)
        if decision_id is not None:
            if account_id is None:
                raise ValueError("decision intents require an account")
            sql += " AND decision_id=?"
            values += (decision_id,)
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
        with self._lock, self._write_context(False):
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
            self._refresh_decision_state(intent["account_id"], intent["decision_id"])
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
            if status != "SUPERSEDED":
                self._refresh_decision_state(intent["account_id"], intent["decision_id"])
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
        with self._lock, self._write_context(False):
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
                if previous_status in TERMINAL_INTENT_STATUSES:
                    raise ValueError("terminal channel intent cannot be reactivated")
                self._connection.execute(
                    "UPDATE intents SET status=?,updated_at=? WHERE intent_id=?",
                    (status, now, intent_id),
                )
            if status in TERMINAL_ORDER_STATUSES and previous_status not in TERMINAL_INTENT_STATUSES:
                self.release_account_intent(intent_id, status, _in_transaction=True)
            else:
                self._refresh_decision_state(order["account_id"], order["decision_id"])
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
        """Commit the new cumulative Futu fill, ledger and audit event atomically."""
        from decimal import Decimal

        if isinstance(cumulative_quantity, bool) or not isinstance(cumulative_quantity, int):
            raise ValueError("cumulative filled quantity must be an integer")
        with self._lock, self._write_context(False):
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
            self._insert_audit_event(self._new_audit_event(
                "ORDER_FILLED" if cumulative_quantity >= int(intent["quantity"])
                else "ORDER_PARTIALLY_FILLED",
                source="futu_execution", account_id=order["account_id"],
                strategy_id=account["strategy_id"], channel=intent["channel_id"],
                decision_id=order["decision_id"], order_id=str(channel_order_id),
                correlation_id=order["decision_id"],
                details={
                    "side": intent["side"], "quantity": increment,
                    "cumulative_quantity": cumulative_quantity,
                    "average_fill_price": float(avg),
                },
            ))
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
        with self._lock, self._write_context(False):
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
        with self._lock, self._write_context(False):
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
                "WHERE (run_state IS NULL OR run_state!='RETIRED') ORDER BY account_id"
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

        with self._lock, self._write_context(False):
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
        with self._lock, self._write_context(False):
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
        with self._lock, self._write_context(False):
            self._connection.execute(
                "INSERT INTO cancel_tokens(token, channel_order_id, expires_at) VALUES(?, ?, ?)",
                (token, channel_order_id, expires_at),
            )

    def consume_cancel_token(self, token: str, channel_order_id: str, now: str) -> str:
        with self._lock, self._write_context(False):
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
