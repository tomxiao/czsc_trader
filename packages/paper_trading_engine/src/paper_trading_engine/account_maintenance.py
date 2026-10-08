"""Offline, atomic replacement of account execution bindings."""

from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
from threading import RLock

from dataflows import DataSpace

from .account_binding import AccountBindingUpdate, AccountBindingUpdateResult, AccountBindingUpdateStatus
from .account_engine import AccountEngine
from .broker import TERMINAL_INTENT_STATUSES, TERMINAL_ORDER_STATUSES
from .channel import STRATEGY_ACCOUNT_TYPE, require_futu_simulate_cn
from .contracts import AdviceDecision
from .data_space import create_dataflows
from .lifecycle import RunState, DecisionState
from .runtime_config import PteRuntimeConfig
from .runtime_lock import RuntimeDatabaseLock
from .runtime_release import load_release
from .srt_advice_client import SrtAdviceClient
from .store import PaperStore, RUNTIME_DATABASE_SCHEMA_VERSION, _update_account_bindings


def update_account_bindings(
    runtime_root: Path, target_release_id: str, updates: tuple[AccountBindingUpdate, ...],
) -> AccountBindingUpdateResult:
    """Prepare every replacement before atomically switching paused accounts."""
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
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=rw", uri=True)
        connection.row_factory = sqlite3.Row
        # Use current business readers/writers without initialization or migration.
        store = PaperStore.__new__(PaperStore)
        store.path, store._connection = database, connection
        store._lock, store._atomic_decision_depth = RLock(), 1
        try:
            connection.execute("BEGIN")
            row = connection.execute("SELECT value FROM settings WHERE key='runtime_database_schema_version'").fetchone()
            if (row is None or int(row[0]) != RUNTIME_DATABASE_SCHEMA_VERSION
                    or int(row[0]) not in release.manifest["database_schema"]["compatible"]):
                raise ValueError("account binding update requires the current database schema")

            def snapshot(account_id):
                try:
                    account = store.virtual_account(account_id)
                except KeyError as exc:
                    raise ValueError(f"unknown account: {account_id}") from exc
                if account["account_type"] != STRATEGY_ACCOUNT_TYPE or account["run_state"] != RunState.PAUSED:
                    raise ValueError(f"{account_id}: binding update requires a paused strategy account")
                require_futu_simulate_cn(account["channel_id"])
                intents = store.account_intents(account_id)
                orders = store.account_orders(account_id)
                decisions = store.account_decisions(account_id)
                if any(x["attention_required"] or (x["status"] not in TERMINAL_INTENT_STATUSES
                       and (x["status"] not in {"PENDING_SUBMIT", "WAITING_DEPENDENCY"}
                            or x.get("channel_order_id"))) for x in intents):
                    raise ValueError(f"{account_id}: submitted or unresolved intents block binding update")
                if any(x["status"] not in TERMINAL_ORDER_STATUSES for x in orders):
                    raise ValueError(f"{account_id}: unfinished orders block binding update")
                if any(x["status"] == DecisionState.EXECUTING for x in decisions):
                    raise ValueError(f"{account_id}: executing decisions block binding update")
                active = [x for x in intents if x["status"] not in TERMINAL_INTENT_STATUSES]
                for intent in active:
                    try:
                        state = store.account_decision(account_id, intent["decision_id"])["status"]
                    except KeyError as exc:
                        raise ValueError(f"{account_id}: unsubmitted intent lacks its originating decision") from exc
                    if state != DecisionState.PENDING:
                        raise ValueError(f"{account_id}: unsubmitted intent lacks a pending decision")
                cash = AccountEngine._cash_after_replaceable_intents(account, active)
                if cash - Decimal(account["cash"]) != Decimal(account["frozen_cash"]):
                    raise ValueError(f"{account_id}: unexplained frozen cash blocks binding update")
                return account, intents, orders, decisions, cash

            snapshots = {account_id: snapshot(account_id) for account_id in account_ids}
            connection.rollback()  # SRT/data preparation must not hold a DB transaction.
            config = PteRuntimeConfig.load(shared / "config" / "pte.json")
            client = SrtAdviceClient(
                repo_root=release.release_root, data_dir=shared / "data",
                dataflows=create_dataflows(data_dir=shared / "data", space=DataSpace(config.data_space),
                                           config_root=shared / "config"),
            )
            signal_date = client.latest_completed_signal_date(datetime.now(timezone.utc))
            bindings = []
            for update in updates:
                account, _, _, _, cash = snapshots[update.account_id]
                if account["release_hash"] != update.expected_release_hash:
                    raise ValueError(f"{update.account_id}: current release hash differs from expected hash")
                binding = client.validate_account_binding(
                    strategy_id=account["strategy_id"], strategy_version=account["strategy_version"],
                    symbol=account["symbol"], asset=account["asset_type"],
                )
                if binding.release_hash != update.target_release_hash:
                    raise ValueError(f"{update.account_id}: target release hash differs from installed strategy")
                if (account["strategy_id"], account["strategy_version"], account["symbol"], account["selection_data_cutoff"], account["asset_type"]) != (
                        binding.strategy_id, binding.version, binding.symbol, binding.selection_data_cutoff.isoformat(), "etf"):
                    raise ValueError(f"{update.account_id}: strategy identity, symbol or selection cutoff differs")
                prepared = client.prepare_account_data(
                    account_id=update.account_id, strategy_id=binding.strategy_id,
                    strategy_version=binding.version, symbol=binding.symbol,
                    asset=account["asset_type"], signal_date=signal_date,
                )
                if prepared is None or prepared.available_through != signal_date:
                    raise ValueError(f"{update.account_id}: replacement data is unavailable for the completed session")
                if (prepared.strategy.reference_id, prepared.strategy.release_hash) != (f"{binding.strategy_id}-{binding.version}", binding.release_hash):
                    raise ValueError(f"{update.account_id}: prepared strategy differs from target binding")
                if prepared.tradable_window.start != prepared.tradable_window.end:
                    raise ValueError("replacement requires a single effective trading session")
                portfolio_revision = AccountEngine._effective_portfolio_revision(account, cash)
                state_revision = AccountEngine._state_revision(account)
                value = client.get_decision(
                    int(account["quantity"]), float(cash), total_assets=float(account["total_assets"]),
                    trading_date=prepared.tradable_window.start, portfolio_revision=portfolio_revision,
                    state_revision=state_revision, cycle_target_quantity=account["cycle_target"],
                    strategy_id=binding.strategy_id, strategy_version=binding.version,
                    account_id=update.account_id, symbol=binding.symbol, asset=account["asset_type"], prepared=prepared,
                )
                if type(value) is not AdviceDecision:
                    raise TypeError("replacement requires an AdviceDecision")
                if (value.strategy.get("strategy_id"), value.strategy.get("version"), value.strategy.get("release_hash"),
                        value.symbol, value.actual_quantity, value.portfolio_revision, value.state_revision,
                        value.signal_date, value.valid_session, Decimal(str(value.available_cash))) != (
                        binding.strategy_id, binding.version, binding.release_hash, binding.symbol, int(account["quantity"]),
                        portfolio_revision, state_revision, signal_date, prepared.tradable_window.start, cash):
                    raise ValueError(f"{update.account_id}: replacement decision differs from bound portfolio or preparation")
                value = AccountEngine(store, client)._assign_decision_id(update.account_id, None, value)
                bindings.append((update, binding, asdict(value)))
            if load_release(runtime_root, target_release_id).manifest_sha256 != release.manifest_sha256:
                raise ValueError("target release changed during account binding validation")
            connection.execute("BEGIN IMMEDIATE")
            for account_id in account_ids:
                if snapshot(account_id) != snapshots[account_id]:
                    raise ValueError(f"{account_id}: account or execution facts changed during preparation")
            _update_account_bindings(connection, tuple(bindings))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
    return AccountBindingUpdateResult(AccountBindingUpdateStatus.COMMITTED, account_ids)
