"""V4 strategy state committed with the owning account's real business facts."""
from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal
import json

from ..instruments import TimeInterval
from ..state import AccountStrategyState
from ..contracts import PositionCycle, PositionFeedback, RecognizedAccountEvent, RecognizedEventKind
from ..state import CycleState, StateRecord
from ..contracts import CycleBudget


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def position_to_dict(value):
    if value is None:
        return None
    result = asdict(value)
    for key in ("entry_interval", "last_fill_interval"):
        interval = getattr(value, key)
        result[key] = {"start": interval.start.isoformat(), "end": interval.end.isoformat()}
    return result


def position_from_dict(value):
    if value is None:
        return None
    value = dict(value)
    for key in ("entry_interval", "last_fill_interval"):
        value[key] = TimeInterval(*(datetime.fromisoformat(value[key][part]) for part in ("start", "end")))
    return PositionCycle(**value)


def budget_to_dict(value):
    if value is None:
        return None
    return {key: str(item) if isinstance(item, Decimal) else item for key, item in asdict(value).items()}


def budget_from_dict(value):
    if value is None:
        return None
    value = dict(value)
    for key in ("allocation_fraction", "cash_budget", "buy_cost_including_fees"):
        value[key] = Decimal(value[key])
    from ..entry_cycle import EntryCyclePhase
    value["phase"] = EntryCyclePhase(value["phase"])
    return CycleBudget(**value)


def load_document(account, initial_account: StateRecord | None = None):
    raw = account.get("account_v4_json")
    if raw is None:
        if account["quantity"]:
            raise ValueError("V4 account state migration is required for an existing holding")
        if type(initial_account) is not StateRecord:
            raise TypeError("initial V4 state requires an explicit channel state record")
        return {"schema_version": 2,
                "state": AccountStrategyState(account=initial_account).to_dict(),
                "pending_cycle": None, "active": None, "latest_closed": None,
                "budget": None, "locked_quantity": None, "buy_locks": [], "last_interval": None, "last_inputs": None}
    result = json.loads(raw)
    validate_document(result)
    return result


def validate_document(value):
    fields = {"schema_version", "state", "pending_cycle", "active", "latest_closed", "budget",
              "buy_locks", "last_interval", "last_inputs", "locked_quantity"}
    if type(value) is not dict or set(value) != fields or value["schema_version"] != 2:
        raise ValueError("invalid V4 account state document")
    if value["locked_quantity"] is not None and (type(value["locked_quantity"]) is not int or value["locked_quantity"] <= 0):
        raise ValueError("invalid EC quantity lock")
    state = AccountStrategyState.from_dict(value["state"])
    active, closed = position_from_dict(value["active"]), position_from_dict(value["latest_closed"])
    PositionFeedback(active, closed)
    budget_from_dict(value["budget"])
    if (state.cycle is None) != (active is None):
        raise ValueError("V4 strategy cycle differs from actual position")
    if active is not None and (state.cycle.cycle_id != active.cycle_id or state.cycle.entry_at != active.entry_interval.start):
        raise ValueError("V4 cycle identity differs from actual fills")
    if value["pending_cycle"] is not None:
        StateRecord.from_dict(value["pending_cycle"])
    for lock in value["buy_locks"]:
        if set(lock) != {"at", "quantity"} or type(lock["quantity"]) is not int or lock["quantity"] < 0:
            raise ValueError("invalid V4 sellability lock")
        if datetime.fromisoformat(lock["at"]).utcoffset() is None:
            raise ValueError("V4 sellability requires aware time")
    return state


def save_document(store, account_id, value):
    validate_document(value)
    if getattr(store, "_inspection_permit", None) is None:
        account = store.virtual_account(account_id)
        if (store.equity_account_rules(account_id) is None
                or account['qualification_snapshot'] not in ('PAPER_READY', 'LIVE_READY')):
            raise ValueError('V4 account activation requires an admitted equity account')
    if not store._connection.in_transaction:
        raise RuntimeError("V4 state update requires the account transaction")
    store._connection.execute("INSERT INTO equity_strategy_state(account_id,payload) VALUES(?,?) "
                              "ON CONFLICT(account_id) DO UPDATE SET payload=excluded.payload",
                              (account_id, encode(value)))


def adopt_v4_decision(store, account, payload):
    transition = payload.get("v4_state_transition")
    if type(transition) is not dict or set(transition) != {"before", "after", "buy_sellable_at", "sell_remainder_policy"}:
        raise ValueError("V4 decision requires its explicit state transition")
    if transition["before"] != account.get("account_v4_json"):
        raise ValueError("V4 state changed before decision adoption")
    after = transition["after"]
    state = validate_document(after)
    before_revision = 0 if transition["before"] is None else validate_document(json.loads(transition["before"])).revision
    if state.revision != before_revision + 1 or state.binding is None:
        raise ValueError("V4 adoption must advance one bound state revision")
    from ..identity import equity_hash
    rules = store.equity_account_rules(account["account_id"])
    expected = equity_hash({'owner': account['account_id'] + ':' + account['release_hash'],
        'implementation': payload['runtime_sha256'], 'specification': rules.execution.fingerprint,
        'fee_rate': payload['fee_rate']})
    if state.binding != expected:
        raise ValueError("V4 state binding differs from the owning implementation and account")
    if bool(account["quantity"]) != (state.cycle is not None):
        raise ValueError("V4 decision cannot invent a confirmed holding cycle")
    if after["active"] is not None and after["active"]["quantity"] != account["quantity"]:
        raise ValueError("V4 state quantity differs from confirmed account")
    if transition["sell_remainder_policy"] not in {"STRICT_STEP", "FULL_LIQUIDATION"}:
        raise ValueError("V4 decision requires an explicit sell remainder policy")
    unlock = datetime.fromisoformat(transition["buy_sellable_at"])
    start = datetime.fromisoformat(payload["equity_execution_interval"]["start"])
    if unlock.utcoffset() is None or unlock < start:
        raise ValueError("V4 order requires a valid buy sellability time")
    save_document(store, account["account_id"], after)


def record_v4_fill(store, account_id, decision_id, fill_id, side, increment, value, fee, quantity, occurred_at):
    payload = store.account_decision(account_id, decision_id)["payload"]
    if payload.get("contract_version") != "advice.equity.v4":
        return
    document = load_document(store.virtual_account(account_id))
    state = validate_document(document)
    interval = TimeInterval(*(datetime.fromisoformat(payload["equity_execution_interval"][key]) for key in ("start", "end")))
    active = position_from_dict(document["active"])
    if side == "BUY" and active is None:
        if document["pending_cycle"] is None:
            raise ValueError("V4 entry fill requires pending cycle values")
        active = PositionCycle(fill_id, interval, interval, 0, 0., 0., 0., 0, 0)
    if active is None:
        raise ValueError("V4 fill has no owning confirmed position")
    active = replace(active, last_fill_interval=interval, quantity=quantity,
                     buy_cost=active.buy_cost + (float(value + fee) if side == "BUY" else 0.),
                     sell_income=active.sell_income + (float(value - fee) if side == "SELL" else 0.),
                     fees=active.fees + float(fee), buy_fills=active.buy_fills + int(side == "BUY"),
                     sell_fills=active.sell_fills + int(side == "SELL"))
    if side == "BUY":
        document["buy_locks"].append({"at": payload["v4_state_transition"]["buy_sellable_at"], "quantity": increment})
        budget = budget_from_dict(document["budget"])
        if budget is not None:
            budget = replace(budget, buy_cost_including_fees=budget.buy_cost_including_fees + value + fee)
            document["budget"] = budget_to_dict(budget)
    cycle = None
    if quantity:
        values = state.cycle.values if state.cycle is not None else StateRecord.from_dict(document["pending_cycle"])
        cycle = CycleState(active.cycle_id, active.entry_interval.start, values)
        document["active"] = position_to_dict(active)
    else:
        document["active"], document["latest_closed"] = None, position_to_dict(active)
        document["pending_cycle"], document["budget"], document["buy_locks"] = None, None, []
        document['locked_quantity'] = None
    document["state"] = replace(state, cycle=cycle).to_dict()
    save_document(store, account_id, document)


def record_v4_position_reconciliation(store, account_id, *, quantity_before, quantity_after, at):
    """Synchronize all EC-owned quantity state with one confirmed holding change."""
    account = store.virtual_account(account_id)
    if account.get("account_v4_json") is None:
        return
    document = load_document(account)
    state = validate_document(document)
    active = position_from_dict(document['active'])
    if active is None or active.quantity != quantity_before or account['quantity'] != quantity_after:
        raise ValueError('position reconciliation differs from confirmed V4 position')
    active = replace(active, quantity=quantity_after)
    if not quantity_after:
        document['active'], document['latest_closed'] = None, position_to_dict(active)
        document['pending_cycle'], document['budget'], document['buy_locks'] = None, None, []
        document['locked_quantity'] = None
        state = replace(state, cycle=None)
    else:
        from .equity_events import allocate_quantities
        document['active'] = position_to_dict(active)
        locks = [lock for lock in document['buy_locks'] if datetime.fromisoformat(lock['at']) > at]
        locked = sum(lock['quantity'] for lock in locks)
        if locked > quantity_before:
            raise ValueError('sellability locks exceed confirmed position')
        weights = {str(i): lock['quantity'] for i, lock in enumerate(locks)}
        weights['sellable'] = quantity_before - locked
        scaled = allocate_quantities(weights, quantity_after)
        document['buy_locks'] = [dict(at=lock['at'], quantity=scaled[str(i)])
            for i, lock in enumerate(locks) if scaled[str(i)]]
        budget = budget_from_dict(document['budget'])
        if budget is not None:
            document['budget'] = budget_to_dict(replace(budget,
                target_quantity=budget.target_quantity * quantity_after // quantity_before))
        if document['locked_quantity'] is not None:
            document['locked_quantity'] = document['locked_quantity'] * quantity_after // quantity_before
    document["state"] = state.to_dict()
    save_document(store, account_id, document)


def recognized_events(store, account_id, cursor, through):
    output, next_cursor = [], cursor
    metadata = {value.get("ledger_entry_id"): value for row in store._connection.execute(
        "SELECT payload FROM equity_account_events WHERE account_id=?", (account_id,))
        for value in (json.loads(row[0]),) if value.get("ledger_entry_id")}
    rows = store._connection.execute("SELECT rowid,* FROM account_ledger WHERE account_id=? AND rowid>? ORDER BY rowid", (account_id, cursor))
    for row in rows:
        kind = row["entry_type"]
        if kind not in {"POSITION_ADJUSTMENT", "SALE_SETTLEMENT"}:
            next_cursor = row["rowid"]
            continue
        stamp = datetime.fromisoformat(row["occurred_at"])
        if stamp > through:
            break
        next_cursor = row["rowid"]
        event = metadata.get(row["ledger_entry_id"])
        if event is None:
            raise ValueError("recognized V4 event lacks its explicit event source")
        actual_kind = event["recognized_kind"]
        output.append(RecognizedAccountEvent(row["ledger_entry_id"], RecognizedEventKind(actual_kind), stamp,
            row["quantity_after"] - row["quantity_delta"], row["quantity_after"], float(row["cash_delta"]),
            float(event["receivable_delta"]), event['reason']))
    return tuple(output), next_cursor
