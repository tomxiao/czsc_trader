"""Evidence and atomic adoption for a safe V4 decision replacement."""

from dataclasses import dataclass, replace
from datetime import datetime
import json

from .adoption import AccountAdoption, DecisionAdoption
from .broker import TERMINAL_INTENT_STATUSES, TERMINAL_ORDER_STATUSES
from .equity_account_state import encode, save_document, validate_document
from .lifecycle import DecisionState
from .execution_adoptions import adoption_window
from ..instruments import TimeInterval
from .store import _utc_now


_LOCAL_OPEN = {"PENDING_SUBMIT", "WAITING_DEPENDENCY"}
_LOCAL_ENDED = {"CANCELLED", "EXPIRED", "SKIPPED_DEPENDENCY"}


class DecisionReplacementConflict(RuntimeError):
    """The accepted account or execution facts do not permit replacement."""


@dataclass(frozen=True, slots=True)
class ReplacementSnapshot:
    account_id: str
    decision_id: str
    valid_session: str
    evidence: str
    local_intent_ids: tuple[str, ...]
    before: str | None
    event_cursor: int


def capture_replacement(store, account_id: str, decision_id: str, initial: dict | None = None) -> ReplacementSnapshot:
    with store._lock:
        account = store.virtual_account(account_id)
        decision = store.account_decision(account_id, decision_id)
        payload = decision["payload"]
        valid_session = decision["valid_session"]
        start, end = adoption_window(payload)
        current = (store.adopted_execution_decision(account_id,
            TimeInterval(datetime.fromisoformat(start), datetime.fromisoformat(end))) if start else None)
        later = store._connection.execute(
            "SELECT 1 FROM decision_adoptions WHERE account_id=? AND "
            "(valid_session>? OR (valid_session=? AND window_start>?)) LIMIT 1",
            (account_id, valid_session, valid_session, start),
        ).fetchone()
        all_intents = store.account_intents(account_id)
        orders = {row["channel_order_id"]: dict(row) for row in store._connection.execute(
            "SELECT * FROM orders WHERE account_id=? AND decision_id=?", (account_id, decision_id),
        )}
        fills = store.account_fills(account_id)
    if (account["run_state"] != "RUNNING" or account["health"] != "OK" or later is not None
            or current is None or current["decision_id"] != decision_id
            or account["last_decision_id"] not in (None, decision_id)
            or payload.get("contract_version") != "advice.equity.v4"):
        raise DecisionReplacementConflict("current V4 decision or account state changed")

    intents = [row for row in all_intents if row["decision_id"] == decision_id]
    if any(row["decision_id"] == decision_id for row in fills):
        raise DecisionReplacementConflict("the current decision has confirmed fills")
    if any(row["decision_id"] != decision_id and row["status"] not in TERMINAL_INTENT_STATUSES
           for row in all_intents):
        raise DecisionReplacementConflict("another decision still has an active intent")
    local = []
    confirmed = set()
    for row in intents:
        order_id = row["channel_order_id"]
        if row["attention_required"]:
            raise DecisionReplacementConflict("a current order intent requires reconciliation")
        if order_id:
            order = orders.get(order_id)
            report = json.loads(order["payload"]) if order is not None else {}
            if (order is None or report.get("status") not in TERMINAL_ORDER_STATUSES
                    or report["status"] == "FILLED_ALL" or order["cumulative_filled_quantity"] != 0
                    or type(report.get("cumulative_filled_quantity")) is not int or report["cumulative_filled_quantity"] != 0
                    or not report.get("report_applied_at")
                    or row["status"] != report["status"]):
                raise DecisionReplacementConflict("a channel order has not terminated with zero fills")
            confirmed.add(order_id)
        elif row["status"] in _LOCAL_OPEN:
            local.append(row["intent_id"])
        elif row["status"] not in _LOCAL_ENDED:
            raise DecisionReplacementConflict("a current order intent may already have been submitted")
    if set(orders) != confirmed:
        raise DecisionReplacementConflict("channel orders differ from the recorded intents")

    transition = payload["v4_state_transition"]
    raw = account.get("account_v4_json")
    if raw is None:
        raise DecisionReplacementConflict("current V4 state is unavailable")
    state = json.loads(raw)
    before = transition["before"]
    after = transition["after"]
    old_hash = payload["strategy"]["release_hash"]
    if account["release_hash"] != old_hash:
        events = store.query_audit_events(account_id=account_id, event_type="ACCOUNT_STRATEGY_BOUND", limit=1)
        if (not events or events[0]["release_hash"] != account["release_hash"]
                or events[0]["details"].get("previous_release_hash") != old_hash
                or events[0]["details"].get("state_treatment") not in {
                    "V4StateContinuation", "EquityStateContinuation"}):
            raise DecisionReplacementConflict("the old decision state has no verified continuation into the bound release")
        live = state["state"]
        after = {**after, "state": {**after["state"], "binding": live["binding"], "revision": live["revision"]}}
        baseline = json.loads(before) if before is not None else initial
        if baseline is None:
            raise DecisionReplacementConflict("the original initial state is unavailable")
        baseline = {**baseline, "state": {
            **baseline["state"], "binding": live["binding"], "revision": live["revision"] - 1,
        }}
        validate_document(baseline)
        before = encode(baseline)
    cleared_entry = (not account["quantity"]
                     and all(row["status"] in TERMINAL_INTENT_STATUSES for row in all_intents)
                     and state == {**after, "budget": None, "pending_cycle": None})
    if (state != after and not cleared_entry) or account["quantity"] != payload["actual_quantity"]:
        raise DecisionReplacementConflict("account facts advanced after the current decision was adopted")
    if decision["status"] not in {DecisionState.PENDING, DecisionState.COMPLETED, DecisionState.INCOMPLETE, DecisionState.CANCELLED}:
        raise DecisionReplacementConflict("current decision has unresolved execution")
    evidence = encode({"account": account, "decision": decision, "intents": all_intents, "orders": orders, "fills": fills})
    return ReplacementSnapshot(account_id, decision_id, valid_session, evidence, tuple(local), before,
                               transition["after"]["state"]["event_cursor"])


def replace_decision(store, audit, snapshot: ReplacementSnapshot, request: DecisionAdoption, *, initial=None, clock=None):
    payload = json.loads(request.document)
    prior = json.loads(snapshot.evidence)["decision"]["payload"]
    account_id, old_id, new_id = snapshot.account_id, snapshot.decision_id, payload["decision_id"]
    if (request.account_id != account_id or old_id == new_id or payload["valid_session"] != snapshot.valid_session
            or payload["equity_execution_interval"] != prior["equity_execution_interval"]
            or prior.get("decision_cycle", payload["decision_cycle"]) != payload["decision_cycle"]
            or payload["v4_state_transition"]["before"] != snapshot.before):
        raise ValueError("replacement does not match the reviewed decision")
    with store.atomic_decision_update():
        if capture_replacement(store, account_id, old_id, initial) != snapshot:
            raise DecisionReplacementConflict("account or order facts changed during the rerun")
        now = request.observed_at if clock is None else clock()
        validity = payload["decision_cycle"]["validity"]
        if not datetime.fromisoformat(validity["start"]) <= now < datetime.fromisoformat(validity["end"]):
            raise DecisionReplacementConflict("the current decision cycle ended before replacement")
        scope = {"source": "account_engine", "account_id": account_id, "decision_id": old_id,
                 **store.decision_audit_identity(account_id, old_id),
                 "symbol": prior["symbol"], "correlation_id": new_id}
        for intent_id in snapshot.local_intent_ids:
            store.release_account_intent(intent_id, "SUPERSEDED", _in_transaction=True,
                audit_event=audit.build("ORDER_INTENT_SUPERSEDED", **scope,
                    details={"intent_id": intent_id, "superseded_by": new_id}))
        store._append_decision_state(account_id, old_id, DecisionState.SUPERSEDED, "PLAN_REPLACED", new_id)
        store._connection.execute(
            "UPDATE decisions SET superseded_by=?,superseded_at=? WHERE account_id=? AND decision_id=?",
            (new_id, _utc_now(), account_id, old_id),
        )
        if snapshot.before is None:
            store._connection.execute("DELETE FROM equity_strategy_state WHERE account_id=?", (account_id,))
        else:
            save_document(store, account_id, json.loads(snapshot.before))
        AccountAdoption(store, audit).adopt(replace(request, observed_at=now), in_transaction=True)
        audit.record("DECISION_SUPERSEDED", **scope, details={
            "superseded_by": new_id, "superseded_intent_ids": list(snapshot.local_intent_ids),
        })
