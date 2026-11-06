"""Offline V4 rebinding of durable accounts and their confirmed positions."""

from collections import Counter
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
import sqlite3
from threading import RLock

from dataflows import BarFrequency, TimeInterval
from strategy_manager import Qualification, StrategyRegistry
from strategy_runtime import AccountStrategyState, EntryCycleState, canonical_sha256
from strategy_runtime.account_strategy import PositionCycle
from strategy_runtime.equity import equity_hash
from strategy_runtime.equity_replay import CycleState, StateRecord
from strategy_runtime.replay_contracts import CycleBudget

from .account_binding import AccountBindingUpdateResult, AccountBindingUpdateStatus, AccountStrategyBinding, V4StateContinuation
from .broker import TERMINAL_INTENT_STATUSES, TERMINAL_ORDER_STATUSES
from .channel import STRATEGY_ACCOUNT_TYPE, channel_profile
from .equity_account_state import (budget_to_dict, load_document, position_from_dict,
                                   position_to_dict, save_document, validate_document)
from .formal_v4_advice import FormalV4AdviceClient
from .lifecycle import DecisionState, RunState
from .runtime_lock import RuntimeDatabaseLock
from .store import PaperStore, RUNTIME_DATABASE_SCHEMA_VERSION, _utc_now


def _facts(store, account_id):
    account = store.virtual_account(account_id)
    tables = ("decisions", "decision_state_events", "decision_adoptions", "intents", "orders",
              "fills", "account_ledger", "equity_account_events")
    rows = {table: [dict(row) for row in store._connection.execute(
        f"SELECT rowid,* FROM {table} WHERE account_id=? ORDER BY rowid", (account_id,),
    )] for table in tables}
    channel = next(row for row in store.channel_accounts()
                   if row["channel_account_id"] == account["channel_account_id"])
    return {"account": account, "channel": channel, "rows": rows,
            "active_binding": store.v4_runtime_binding(account_id)}


def account_binding_facts_sha256(store: PaperStore, account_id: str) -> str:
    """Fingerprint a paused account's local ledger and execution facts in one snapshot."""
    connection = store._connection
    with store._lock:
        started = not connection.in_transaction
        if started:
            connection.execute("BEGIN")
        try:
            return canonical_sha256(_facts(store, account_id))
        finally:
            if started:
                connection.rollback()


def _interval_dict(interval):
    return {"start": interval.start.isoformat(), "end": interval.end.isoformat()}


def _plan_identity(release, updates):
    def state_identity(state):
        value = {"source_runtime_release_id": state.source_runtime_release_id, "evidence": state.evidence}
        if type(state) is not V4StateContinuation:
            for name in ("account_values", "cycle_values", "pending_cycle_values"):
                record = getattr(state, name)
                value[name] = None if record is None else record.to_dict()
        return value

    return canonical_sha256({"runtime_manifest": release.manifest_sha256, "updates": [
        {"binding": asdict(update.binding), "channel_account_id": update.channel_account_id,
         "expected_facts_sha256": update.expected_facts_sha256, "rules": update.rules.to_dict(),
         "effective_interval": _interval_dict(update.effective_interval), "inputs": update.inputs.to_dict(),
         "state_kind": type(update.state).__name__, "state": state_identity(update.state)}
        for update in sorted(updates, key=lambda item: item.account_id)
    ]})


def _validate_execution(facts, decisions):
    rows = facts["rows"]
    if any(row["attention_required"] or row["status"] not in TERMINAL_INTENT_STATUSES for row in rows["intents"]):
        raise ValueError("unresolved intents block V4 binding update")
    fills = Counter()
    for row in rows["fills"]:
        fills[row["order_id"]] += row["quantity"]
    for row in rows["orders"]:
        report = json.loads(row["payload"])
        if (report["status"] not in TERMINAL_ORDER_STATUSES
                or int(report["cumulative_filled_quantity"]) != row["cumulative_filled_quantity"]
                or row["cumulative_filled_quantity"] != fills.pop(row["channel_order_id"], 0)):
            raise ValueError("unfinished or unreconciled orders block V4 binding update")
    if fills or any(row["status"] == DecisionState.EXECUTING for row in decisions):
        raise ValueError("unreconciled execution blocks V4 binding update")
    if Decimal(facts["account"]["frozen_cash"]) != 0:
        raise ValueError("unexplained frozen cash blocks V4 binding update")


def _validate_cutover(facts, version, update, document):
    start = update.effective_interval.start
    first_day = start.astimezone(update.rules.timezone).date()
    last_day = (update.effective_interval.end - timedelta(microseconds=1)).astimezone(update.rules.timezone).date()
    if (first_day != last_day or first_day < date.fromisoformat(version.forward_start)
            or first_day <= date.fromisoformat(version.selection_data_cutoff)):
        raise ValueError("V4 cutover must be in one session after the selection cutoff and within the forward window")
    if document.get("last_interval") and start < datetime.fromisoformat(document["last_interval"]["end"]):
        raise ValueError("V4 cutover overlaps the last adopted interval")
    prior_binding = facts["active_binding"]
    if prior_binding is not None and start < datetime.fromisoformat(prior_binding["effective_interval"]["start"]):
        raise ValueError("V4 cutover cannot move backwards")
    adopted = {row["decision_id"] for row in facts["rows"]["decision_adoptions"]}
    for row in facts["rows"]["decisions"]:
        if row["decision_id"] not in adopted:
            continue
        interval = json.loads(row["payload"]).get("equity_execution_interval")
        if ((interval is None and date.fromisoformat(row["valid_session"]) >= first_day)
                or (interval is not None and datetime.fromisoformat(interval["end"]) > start)):
            raise ValueError("V4 cutover must follow previously adopted decisions")
    if any(datetime.fromisoformat(row["occurred_at"]).astimezone(update.rules.timezone).date() >= first_day
           for row in facts["rows"]["fills"] if not facts["account"]["equity_rules_json"]):
        raise ValueError("legacy fills on or after the cutover session block V4 binding update")


def _legacy_document(facts, treatment, update):
    account, rows = facts["account"], facts["rows"]
    if type(treatment) is V4StateContinuation:
        raise ValueError("legacy accounts require an explicit V4 state mapping")
    if (rows["equity_account_events"] or Decimal(account["receivable"]) != 0
            or any(row["entry_type"] in {"SPLIT", "CASH_DIVIDEND", "EQUITY_PAYMENT"} for row in rows["account_ledger"])):
        raise ValueError("legacy equity actions or outstanding receivables require resolved ledger evidence")
    fills = {row["fill_id"]: row for row in rows["fills"]}
    active = closed = None
    quantity = 0
    for row in rows["account_ledger"]:
        delta = row["quantity_delta"]
        if not delta:
            continue
        fill = fills.pop(row["fill_id"], None)
        side = "BUY" if delta > 0 else "SELL"
        if (fill is None or fill["side"] != side or fill["quantity"] != abs(delta)
                or row["entry_type"] != f"{side}_FILL" or row["order_id"] != fill["order_id"]
                or Decimal(row["fee"]) != Decimal(fill["fee"])):
            raise ValueError("legacy position quantity is not supported by confirmed fills and ledger")
        occurred_at = datetime.fromisoformat(fill["occurred_at"])
        # Legacy fills have a confirmed timestamp rather than a V4 execution interval.
        interval = TimeInterval(occurred_at, occurred_at + timedelta(microseconds=1))
        quantity += delta
        if quantity < 0 or quantity != row["quantity_after"] or (active is None and delta < 0):
            raise ValueError("legacy fill chronology disagrees with account quantity")
        if active is None:
            active = PositionCycle(fill["fill_id"], interval, interval, 0, 0., 0., 0., 0, 0)
        net_cash = Decimal(row["cash_delta"]) + Decimal(row["frozen_cash_delta"])
        active = replace(active, quantity=quantity, last_fill_interval=interval,
                         buy_cost=active.buy_cost + float(-net_cash if delta > 0 else 0),
                         sell_income=active.sell_income + float(net_cash if delta < 0 else 0),
                         fees=active.fees + float(Decimal(fill["fee"])),
                         buy_fills=active.buy_fills + int(delta > 0), sell_fills=active.sell_fills + int(delta < 0))
        if quantity == 0:
            closed, active = active, None
    if fills or quantity != account["quantity"]:
        raise ValueError("legacy fills and ledger do not reconcile to confirmed holdings")
    previous = json.loads(account["last_decision_payload"]) if account["last_decision_payload"] else {}
    if "fee_rate" in previous and Decimal(str(previous["fee_rate"])) != Decimal(str(update.inputs.fee_rate)):
        raise ValueError("V4 migration cannot change the account model fee")
    if (active is None) != (treatment.cycle_values is None):
        raise ValueError("legacy strategy cycle mapping must match confirmed holdings")
    cycle = None if active is None else CycleState(active.cycle_id, active.entry_interval.start, treatment.cycle_values)
    entry_cycle = account["entry_cycle_json"]
    budget = None
    if entry_cycle is not None:
        old = EntryCycleState.from_dict(json.loads(entry_cycle))
        if old.target_quantity != account["cycle_target"]:
            raise ValueError("legacy cycle budget differs from account target")
        budget = CycleBudget(old.cycle_id, old.target_quantity, old.allocation_fraction, old.cash_budget,
                             old.buy_cost_including_fees, old.phase)
        if active is None and treatment.pending_cycle_values is None:
            raise ValueError("unfilled legacy budget requires an explicit pending cycle mapping")
    if budget is None and treatment.pending_cycle_values is not None:
        raise ValueError("legacy pending state requires a confirmed cycle budget")
    cursor = max((row["rowid"] for row in rows["account_ledger"]), default=0)
    state = AccountStrategyState(account=treatment.account_values, cycle=cycle, event_cursor=cursor)
    return {"schema_version": 1, "state": state.to_dict(), "active": position_to_dict(active),
            "latest_closed": position_to_dict(closed), "budget": budget_to_dict(budget), "buy_locks": [],
            "pending_cycle": None if treatment.pending_cycle_values is None else treatment.pending_cycle_values.to_dict(),
            "last_interval": None, "last_inputs": None}


def _state_binding(account_id, release_hash, candidate, fee_rate):
    return equity_hash({"owner": f"{account_id}:{release_hash}", "implementation": candidate.implementation_hash,
                        "specification": candidate.execution_spec_hash, "fee_rate": fee_rate})


def _v4_document(store, facts, update, candidate, runtime_root, load_release, data_dir):
    account, treatment = facts["account"], update.state
    if treatment.source_runtime_release_id is None:
        raise ValueError("existing V4 state requires an exact source runtime release")
    source_runtime = load_release(runtime_root, treatment.source_runtime_release_id)
    source_client = FormalV4AdviceClient(repo_root=source_runtime.release_root, store=store,
                                         dataflows=None, data_dir=data_dir)
    _, old_release, old_candidate = source_client._account_release(update.account_id)
    old_inputs = source_client.inputs(update.account_id)
    old_inputs.validate_candidate(old_release.release_hash, old_candidate)
    if old_inputs.fee_rate != update.inputs.fee_rate:
        raise ValueError("V4 rebinding cannot change the model fee or use inputs for another release")
    document = load_document(account, old_candidate.definition)
    old_state = validate_document(document)
    old_binding = _state_binding(update.account_id, old_release.release_hash, old_candidate, old_inputs.fee_rate)
    if old_state.binding != old_binding and (old_state.revision or old_state.binding is not None):
        raise ValueError("current V4 state binding differs from the source release")
    active = position_from_dict(document["active"])
    if (active.quantity if active is not None else 0) != account["quantity"]:
        raise ValueError("current V4 position does not match the confirmed account holdings")
    same_rules = store.equity_account_rules(update.account_id) == update.rules
    if not same_rules and (active is not None or document["budget"] is not None
                           or document["buy_locks"] or Decimal(account["receivable"]) != 0):
        raise ValueError("active positions, budgets or settlement require compatible execution rules")
    if type(treatment) is V4StateContinuation:
        if not same_rules or candidate.definition.state_schema != old_candidate.definition.state_schema:
            raise ValueError("state or execution contract changed, explicit V4 mapping is required")
        return document
    if (old_state.cycle is None) != (treatment.cycle_values is None):
        raise ValueError("V4 strategy cycle mapping must match the current position cycle")
    if (document["pending_cycle"] is None) != (treatment.pending_cycle_values is None):
        raise ValueError("V4 pending cycle mapping must preserve current pending state")
    cycle = None if old_state.cycle is None else replace(old_state.cycle, values=treatment.cycle_values)
    document["state"] = replace(old_state, account=treatment.account_values, cycle=cycle).to_dict()
    if treatment.pending_cycle_values is not None:
        document["pending_cycle"] = treatment.pending_cycle_values.to_dict()
    return document


def _prepare(store, facts, update, release, runtime_root, load_release, data_dir):
    account = facts["account"]
    channel = facts["channel"]
    profile = channel_profile(account["channel_id"])
    if (account["account_type"] != STRATEGY_ACCOUNT_TYPE or account["run_state"] != RunState.PAUSED
            or account["channel_account_id"] != update.channel_account_id
            or account["channel_id"] != channel["channel_id"] or channel["market"] != profile.market
            or channel["currency"] != profile.currency or update.rules.instrument.market.value != profile.market
            or update.rules.execution.account.currency != profile.currency):
        raise ValueError("V4 binding update requires a paused strategy account in its declared channel and market")
    if account["release_hash"] != update.binding.expected_release_hash:
        raise ValueError("current release hash differs from the expected hash")
    if canonical_sha256(facts) != update.expected_facts_sha256:
        raise ValueError("current account facts differ from the reviewed snapshot")
    decisions = store.account_decisions(update.account_id)
    _validate_execution(facts, decisions)
    client = FormalV4AdviceClient(repo_root=release.release_root, store=store, dataflows=None, data_dir=data_dir)
    target, candidate, identity = client.load_release(account["strategy_id"], update.binding.target_version)
    if (target.release_hash != update.binding.target_release_hash or candidate.instrument != update.rules.instrument
            or update.rules.execution != candidate.definition.execution_spec or candidate.instrument.symbol != account["symbol"]
            or candidate.instrument.asset_class.value.lower() != account["asset_type"]):
        raise ValueError("target qualified release differs from the V4 binding request")
    definition = candidate.definition
    if definition.execution_spec.decision_clock is not BarFrequency.DAILY:
        raise ValueError("V4 forward recipe requires a daily frozen execution clock")
    update.inputs.validate_candidate(target.release_hash, candidate)
    version = StrategyRegistry(release.release_root / "strategies").get_version(account["strategy_id"], target.version)
    binding = AccountStrategyBinding(version.strategy_id, version.version, target.release_hash, identity["name"],
        Qualification(identity["qualification"]), date.fromisoformat(version.selection_data_cutoff),
        account["symbol"], update.inputs.fee_rate, instrument=candidate.instrument)
    if account["strategy_version"] == binding.version and account["selection_data_cutoff"] != version.selection_data_cutoff:
        raise ValueError("same-version binding cannot change its selection cutoff")
    document = (_v4_document(store, facts, update, candidate, runtime_root, load_release, data_dir)
                if account["equity_rules_json"] else _legacy_document(facts, update.state, update))
    _validate_cutover(facts, version, update, document)
    state = validate_document(document)
    definition.state_schema.validate_record(state.account, scope="account")
    if state.cycle is not None:
        definition.state_schema.validate_record(state.cycle.values, scope="cycle")
    if document["pending_cycle"] is not None:
        definition.state_schema.validate_record(StateRecord.from_dict(document["pending_cycle"]), scope="cycle")
    document["state"] = replace(state, revision=state.revision + 1,
        binding=_state_binding(update.account_id, binding.release_hash, candidate, update.inputs.fee_rate)).to_dict()
    pending = tuple(row["decision_id"] for row in decisions if row["status"] == DecisionState.PENDING)
    return binding, version, document, pending


def _apply(store, update, prepared, plan_sha256):
    binding, version, document, pending = prepared
    account_id = update.account_id
    old = store.virtual_account(account_id)
    previous_runtime = store.v4_runtime_binding(account_id)
    if previous_runtime is not None:
        legacy_actions_before = previous_runtime.get("legacy_actions_before")
    else:
        legacy_actions_before = None if old["equity_rules_json"] else update.effective_interval.start.isoformat()
    for decision_id in pending:
        store._transition_decision(account_id, decision_id, DecisionState.CANCELLED, "V4_BINDING_CUTOVER")
    changed = store._connection.execute(
        "UPDATE virtual_accounts SET strategy_version=?,release_hash=?,strategy_name_snapshot=?,qualification_snapshot=?,"
        "selection_data_cutoff=?,equity_rules_json=?,entry_cycle_json=NULL,last_decision_id=NULL,last_decision_payload=NULL,updated_at=? "
        "WHERE account_id=? AND release_hash=? AND run_state='PAUSED'",
        (binding.version, binding.release_hash, binding.name, binding.qualification.value, version.selection_data_cutoff,
         json.dumps(update.rules.to_dict(), sort_keys=True), _utc_now(), account_id, update.binding.expected_release_hash),
    ).rowcount
    if changed != 1:
        raise ValueError("account binding changed concurrently")
    save_document(store, account_id, document)
    record = {"inputs": update.inputs.to_dict(), "forward": True,
              "effective_interval": _interval_dict(update.effective_interval), "plan_sha256": plan_sha256,
              "legacy_actions_before": legacy_actions_before}
    store._save_v4_runtime_binding(account_id, record)
    store._insert_audit_event(store._new_audit_event(
        "ACCOUNT_STRATEGY_BOUND", source="account_maintenance", actor_type="OPERATOR", account_id=account_id,
        strategy_id=binding.strategy_id, strategy_version=binding.version, release_hash=binding.release_hash,
        correlation_id=plan_sha256, details={"reason": "V4_BINDING_CUTOVER", "previous_version": old["strategy_version"],
        "previous_release_hash": old["release_hash"], "state_treatment": type(update.state).__name__,
        "state_evidence": update.state.evidence, "inputs_sha256": canonical_sha256(record["inputs"]),
        "effective_interval": record["effective_interval"], "legacy_actions_before": legacy_actions_before},
    ))
    store._connection.executemany("DELETE FROM settings WHERE key=?", [
        (store._setting_key(f"{prefix}:{account_id}"),) for prefix in (
            "last_account_decision_date", "last_account_schedule_skip_date", "last_prepared_data_id",
            "last_data_prepare_date", "last_data_preparation", "data_preparation_error",
        )
    ])


def update_v4_account_bindings(runtime_root, target_release_id, updates, *, load_release):
    release = load_release(runtime_root, target_release_id)
    shared = release.runtime_root / "shared"
    database = shared / "state" / "runtime.db"
    if not database.is_file():
        raise ValueError("account binding update requires an existing runtime database")
    plan_sha256 = _plan_identity(release, updates)
    ids = tuple(update.account_id for update in updates)
    with RuntimeDatabaseLock(database):
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=rw", uri=True)
        connection.row_factory = sqlite3.Row
        store = PaperStore.__new__(PaperStore)
        store.path, store._connection = database, connection
        store._lock, store._atomic_decision_depth = RLock(), 1
        try:
            connection.execute("BEGIN")
            schema = connection.execute("SELECT value FROM settings WHERE key='runtime_database_schema_version'").fetchone()
            if (schema is None or int(schema[0]) != RUNTIME_DATABASE_SCHEMA_VERSION
                    or int(schema[0]) not in release.manifest["database_schema"]["compatible"]):
                raise ValueError("account binding update requires the current database schema")
            facts = {account_id: _facts(store, account_id) for account_id in ids}
            already = [(facts[item.account_id]["active_binding"] or {}).get("plan_sha256") == plan_sha256
                       and facts[item.account_id]["account"]["release_hash"] == item.binding.target_release_hash
                       for item in updates]
            if all(already):
                return AccountBindingUpdateResult(AccountBindingUpdateStatus.ALREADY_APPLIED, ids)
            if any(already):
                raise ValueError("V4 binding batch has an inconsistent applied identity")
            scoped = {item.account_id: store.scope(facts[item.account_id]["account"]["channel_account_id"])
                      for item in updates}
            prepared = {item.account_id: _prepare(scoped[item.account_id], facts[item.account_id], item, release,
                         runtime_root, load_release, shared / "data") for item in updates}
            connection.rollback()
            if load_release(runtime_root, target_release_id).manifest_sha256 != release.manifest_sha256:
                raise ValueError("target release changed during account binding validation")
            connection.execute("BEGIN IMMEDIATE")
            for account_id in ids:
                if _facts(store, account_id) != facts[account_id]:
                    raise ValueError(f"{account_id}: account or execution facts changed during preparation")
            for item in updates:
                _apply(scoped[item.account_id], item, prepared[item.account_id], plan_sha256)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
    return AccountBindingUpdateResult(AccountBindingUpdateStatus.COMMITTED, ids)
