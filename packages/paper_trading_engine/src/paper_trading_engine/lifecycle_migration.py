"""Evidence-based, transaction-owned migration of legacy PTE lifecycle facts."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
import json
import sqlite3
from zoneinfo import ZoneInfo

from .broker import TERMINAL_INTENT_STATUSES, UNRESOLVED_INTENT_STATUSES


class LifecycleMigrationError(RuntimeError):
    """Legacy evidence does not establish a safe lifecycle baseline."""


def _rows(connection: sqlite3.Connection, sql: str) -> list[dict]:
    cursor = connection.execute(sql)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _plan(payload: dict) -> list[dict]:
    if not any(key in payload for key in ("plan_legs", "orders", "order")):
        raise LifecycleMigrationError("immutable payload has no explicit order-plan evidence")
    value = payload.get("plan_legs") or payload.get("orders") or (
        [payload["order"]] if payload.get("order") else []
    )
    if not isinstance(value, list):
        raise LifecycleMigrationError("immutable order plan is not a list")
    result = []
    for sequence, leg in enumerate(value):
        order = leg.get("order", leg)
        if (
            not isinstance(order, dict) or order.get("side") not in {"BUY", "SELL"}
            or order.get("order_type") not in {"LIMIT", "MARKET"}
            or not isinstance(order.get("quantity"), int) or order["quantity"] <= 0
        ):
            raise LifecycleMigrationError("immutable order plan has invalid order semantics")
        result.append({**order, "sequence": int(leg.get("sequence", sequence))})
    if [leg["sequence"] for leg in result] != list(range(len(result))):
        raise LifecycleMigrationError("immutable plan sequence is not consecutive")
    return result


def _matches_plan(intent: dict, expected: dict) -> bool:
    payload = json.loads(intent["payload"])
    return (
        intent["side"] == expected["side"]
        and int(intent["quantity"]) == expected["quantity"]
        and payload.get("order_type", "LIMIT") == expected["order_type"]
        and (
            expected["order_type"] != "LIMIT"
            or Decimal(str(expected["limit_price"])) == Decimal(intent["limit_price"])
        )
    )


def _complete_fill(intent: dict, orders: dict, fills: dict) -> bool:
    order = orders.get(intent["intent_id"])
    if order is None or not intent.get("channel_order_id"):
        return False
    quantity = int(intent["quantity"])
    channel_payload = json.loads(order["payload"])
    intent_payload = json.loads(intent["payload"])
    return (
        order["channel_order_id"] == intent["channel_order_id"]
        and order["account_id"] == intent["account_id"]
        and order["decision_id"] == intent["decision_id"]
        and int(order["cumulative_filled_quantity"]) == quantity
        and channel_payload.get("side", intent["side"]) == intent["side"]
        and int(channel_payload.get("quantity", quantity)) == quantity
        and ("order_type" not in channel_payload
             or channel_payload["order_type"] == intent_payload.get("order_type", "LIMIT"))
        and fills[(intent["account_id"], intent["decision_id"], intent["channel_order_id"], intent["side"])] == quantity
    )


def _baseline(decision: dict, linked: list[dict], orders: dict, fills: dict,
              audits: list[dict], decision_keys: set[tuple[str, str]], as_of: str) -> tuple[str, str, str | None, dict]:
    payload = json.loads(decision["payload"])
    plan = _plan(payload)
    replacement_events = [event for event in audits if event["event_type"] == "DECISION_SUPERSEDED"]
    replacement = decision.get("superseded_by")
    for event in replacement_events:
        details = json.loads(event["payload"])
        event_replacement = details.get("replacement_decision_id") or details.get("superseded_by") or details.get("new_decision_id")
        if replacement and event_replacement and replacement != event_replacement:
            raise LifecycleMigrationError("replacement column and audit disagree")
        replacement = replacement or event_replacement
    if replacement and (decision["account_id"], replacement) not in decision_keys:
        raise LifecycleMigrationError("replacement decision does not exist")
    evidence = {
        "migration": "pte_lifecycle.v4", "legacy_status": decision["status"],
        "generated_at": decision["generated_at"], "valid_session": decision["valid_session"],
        "legacy_superseded_by": decision.get("superseded_by"),
        "legacy_superseded_at": decision.get("superseded_at"),
        "intent_facts": linked, "audit_facts": audits,
    }
    if not plan:
        if payload.get("action") and payload["action"] not in {"HOLD", "WAIT"}:
            raise LifecycleMigrationError("executable action has no immutable order plan")
        if linked:
            raise LifecycleMigrationError("explicit no-order decision has execution intents")
        if decision["status"] == "SUPERSEDED" and not replacement:
            raise LifecycleMigrationError("legacy no-order replacement has no related decision")
        if replacement:
            evidence["legacy_relations"] = [{"kind": "replacement_of_no_order_conclusion", "decision_id": replacement}]
        return "COMPLETED", "MIGRATION_NO_ORDER", None, evidence
    submitted = any(intent.get("channel_order_id") or intent["intent_id"] in orders
                    or intent["status"] in UNRESOLVED_INTENT_STATUSES for intent in linked)
    if any(intent["status"] in UNRESOLVED_INTENT_STATUSES for intent in linked):
        return "EXECUTING", "MIGRATION_SUBMISSION_UNCERTAIN", None, evidence
    exact_plan = len(linked) == len(plan) and {int(intent["order_sequence"]) for intent in linked} == set(range(len(plan))) and all(
        0 <= int(intent["order_sequence"]) < len(plan)
        and _matches_plan(intent, plan[int(intent["order_sequence"])]) for intent in linked
    )
    if linked and all(intent["status"] == "FILLED_ALL" for intent in linked):
        if not exact_plan or not all(_complete_fill(intent, orders, fills) for intent in linked):
            raise LifecycleMigrationError("filled labels do not establish completion of immutable plan")
        return "COMPLETED", "MIGRATION_ALL_PLANNED_ORDERS_FILLED", None, evidence
    retries = []
    for event in audits:
        if event["event_type"] == "ORDER_INTENT_CREATED":
            details = json.loads(event["payload"])
            if details.get("retry_of"):
                retries.append(details)
    if retries:
        originals = [intent for intent in linked if intent["status"] == "REJECTED" and not intent.get("channel_order_id")]
        compensated = [intent for intent in linked if intent["status"] == "FILLED_ALL"]
        proven = len(plan) == len(originals) == len(compensated) == len(retries) == 1 and len(linked) == 2
        if proven:
            original, retry = originals[0], compensated[0]
            proven = (
                retries[0]["retry_of"] == original["intent_id"]
                and int(retries[0]["order_sequence"]) == int(retry["order_sequence"])
                and retries[0]["side"] == retry["side"]
                and int(retries[0]["quantity"]) == int(retry["quantity"])
                and retries[0]["order_type"] == json.loads(retry["payload"]).get("order_type", "LIMIT")
                and _matches_plan(original, plan[0])
                and original["side"] == retry["side"]
                and int(original["quantity"]) == int(retry["quantity"])
                and json.loads(retry["payload"]).get("order_type", "LIMIT") != plan[0]["order_type"]
                and _complete_fill(retry, orders, fills)
            )
        if not proven:
            raise LifecycleMigrationError("operator retry requires individual evidence review")
        evidence["legacy_relations"] = [{"kind": "operator_retry_with_changed_order_type",
            "original_intent": original["intent_id"], "retry_intent": retry["intent_id"],
            "compensating_fill_quantity": int(retry["quantity"])}]
        return "INCOMPLETE", "MIGRATION_ORIGINAL_PLAN_REJECTED_OPERATOR_COMPENSATION", None, evidence
    if not submitted and replacement:
        if linked and (not exact_plan or not all(intent["status"] == "SUPERSEDED" for intent in linked)):
            raise LifecycleMigrationError("replacement has inconsistent unsubmitted intent evidence")
        return "SUPERSEDED", "MIGRATION_UNSUBMITTED_REPLACEMENT", replacement, evidence
    if linked and all(intent["status"] in TERMINAL_INTENT_STATUSES for intent in linked):
        if not exact_plan:
            raise LifecycleMigrationError("terminal intent facts do not match immutable plan")
        if any(intent["status"] == "FILLED_ALL" and not _complete_fill(intent, orders, fills) for intent in linked):
            raise LifecycleMigrationError("terminal partial plan has unverified filled leg")
        return "INCOMPLETE", "MIGRATION_ALL_INTENTS_ENDED", None, evidence
    if submitted:
        if not exact_plan:
            raise LifecycleMigrationError("submitted intent facts do not match immutable plan")
        return "EXECUTING", "MIGRATION_SUBMITTED_WORK_REMAINS", None, evidence
    if decision["valid_session"] < as_of:
        if linked and (not exact_plan or not all(intent["status"] in {"PENDING_SUBMIT", "WAITING_DEPENDENCY"} for intent in linked)):
            raise LifecycleMigrationError("expired unsubmitted plan has inconsistent intent evidence")
        return "INCOMPLETE", "MIGRATION_VALID_SESSION_PASSED", None, evidence
    if not linked or (exact_plan and all(intent["status"] in {"PENDING_SUBMIT", "WAITING_DEPENDENCY"} for intent in linked)):
        return "PENDING", "MIGRATION_UNSUBMITTED_PLAN", None, evidence
    raise LifecycleMigrationError("legacy evidence does not establish a decision state")


def migrate_lifecycle(connection: sqlite3.Connection, now: str) -> None:
    """Migrate v3 facts inside caller's transaction; never commit or alter money."""
    if not connection.in_transaction:
        raise RuntimeError("lifecycle migration requires an existing transaction")
    instant = datetime.fromisoformat(now)
    if instant.tzinfo is None:
        raise ValueError("migration time must include a timezone")
    as_of = instant.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    account_columns = _columns(connection, "virtual_accounts")
    if {"run_state", "legacy_status", "legacy_paused"} <= account_columns:
        required = {"decision_state_events", "decision_adoptions"}
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required <= tables or "legacy_status" not in _columns(connection, "decisions"):
            raise LifecycleMigrationError("partially migrated lifecycle schema")
        return
    if not {"status", "paused"} <= account_columns or "status" not in _columns(connection, "decisions"):
        raise LifecycleMigrationError("unsupported lifecycle source schema")
    accounts = _rows(connection, "SELECT * FROM virtual_accounts")
    decisions = _rows(connection, "SELECT * FROM decisions ORDER BY account_id,generated_at,decision_id")
    known_accounts = {account["account_id"] for account in accounts}
    if any(decision["account_id"] not in known_accounts for decision in decisions):
        raise LifecycleMigrationError("decision account does not exist")
    decision_keys = {(decision["account_id"], decision["decision_id"]) for decision in decisions}
    intents = defaultdict(list)
    for intent in _rows(connection, "SELECT * FROM intents ORDER BY account_id,decision_id,order_sequence"):
        if (intent["account_id"], intent["decision_id"]) not in decision_keys:
            raise LifecycleMigrationError("execution intent has no originating decision")
        intents[(intent["account_id"], intent["decision_id"])].append(intent)
    orders = {order["intent_id"]: order for order in _rows(connection, "SELECT * FROM orders")}
    intent_rows = {intent["intent_id"]: intent for linked in intents.values() for intent in linked}
    for order in orders.values():
        intent = intent_rows.get(order["intent_id"])
        if intent is None or (order["account_id"], order["decision_id"]) != (intent["account_id"], intent["decision_id"]):
            raise LifecycleMigrationError("channel order has no verified originating intent and decision")
    by_order_id = {order["channel_order_id"]: order for order in orders.values()}
    fills = defaultdict(int)
    for fill in _rows(connection, "SELECT * FROM fills"):
        order = by_order_id.get(fill["order_id"])
        if order is None or (fill["account_id"], fill["decision_id"]) != (order["account_id"], order["decision_id"]):
            raise LifecycleMigrationError("fill has no verified originating order and decision")
        fills[(fill["account_id"], fill["decision_id"], fill["order_id"], fill["side"])] += int(fill["quantity"])
    audits = defaultdict(list)
    for event in _rows(connection, "SELECT * FROM events WHERE event_type IN ('DECISION_SUPERSEDED','ORDER_INTENT_CREATED')"):
        audits[(event["account_id"], event["decision_id"])].append(event)
    baselines = []
    for decision in decisions:
        key = (decision["account_id"], decision["decision_id"])
        try:
            state, reason, related, evidence = _baseline(decision, intents[key], orders, fills, audits[key], decision_keys, as_of)
        except (KeyError, TypeError, ValueError, LifecycleMigrationError) as exc:
            raise LifecycleMigrationError(f"{key[0]}/{key[1]}: {exc}") from exc
        baselines.append((*key, state, reason, related, json.dumps(evidence, ensure_ascii=False, sort_keys=True)))
    run_states = []
    adoption_rows = []
    by_key = {(decision["account_id"], decision["decision_id"]): decision for decision in decisions}
    for account in accounts:
        state = None
        if account["account_type"] == "STRATEGY":
            if account["status"] not in {"RUNNING", "RETIRED"} or account["paused"] not in {0, 1}:
                raise LifecycleMigrationError(f"{account['account_id']}: invalid legacy account state")
            state = "RETIRED" if account["status"] == "RETIRED" else "PAUSED" if account["paused"] else "RUNNING"
        run_states.append((state, account["account_id"]))
        if account.get("last_decision_id"):
            decision = by_key.get((account["account_id"], account["last_decision_id"]))
            if decision is None:
                raise LifecycleMigrationError(f"{account['account_id']}: adopted decision is missing")
            adoption_rows.append((account["account_id"], decision["valid_session"], decision["decision_id"]))
    connection.execute("DROP INDEX IF EXISTS uq_decisions_active_signal_date")
    connection.execute("ALTER TABLE virtual_accounts RENAME COLUMN status TO legacy_status")
    connection.execute("ALTER TABLE virtual_accounts RENAME COLUMN paused TO legacy_paused")
    connection.execute("ALTER TABLE virtual_accounts ADD COLUMN run_state TEXT CHECK(run_state IS NULL OR run_state IN ('PAUSED','RUNNING','RETIRED'))")
    connection.execute("ALTER TABLE decisions RENAME COLUMN status TO legacy_status")
    connection.execute("""CREATE TABLE decision_state_events (
        account_id TEXT NOT NULL, decision_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK(sequence>=1),
        state TEXT NOT NULL CHECK(state IN ('PENDING','EXECUTING','COMPLETED','SUPERSEDED','CANCELLED','INCOMPLETE')),
        reason TEXT NOT NULL CHECK(length(reason)>0), related_decision_id TEXT, occurred_at TEXT NOT NULL,
        evidence TEXT NOT NULL, PRIMARY KEY(account_id,decision_id,sequence))""")
    connection.execute("""CREATE TABLE decision_adoptions (
        account_id TEXT NOT NULL, valid_session TEXT NOT NULL, decision_id TEXT NOT NULL,
        PRIMARY KEY(account_id,valid_session))""")
    connection.executemany("UPDATE virtual_accounts SET run_state=? WHERE account_id=?", run_states)
    connection.executemany("INSERT INTO decision_state_events(account_id,decision_id,sequence,state,reason,related_decision_id,occurred_at,evidence) VALUES(?,?,1,?,?,?,?,?)",
                           [(account, decision, state, reason, related, now, evidence)
                            for account, decision, state, reason, related, evidence in baselines])
    connection.executemany("INSERT INTO decision_adoptions(account_id,valid_session,decision_id) VALUES(?,?,?)", adoption_rows)
    connection.execute("""CREATE TRIGGER decision_content_immutable
        BEFORE UPDATE OF payload,signal_date,valid_session,generated_at,account_id,decision_id ON decisions
        BEGIN SELECT RAISE(ABORT,'decision content is immutable'); END""")
    connection.execute("""CREATE TRIGGER decision_state_events_no_update BEFORE UPDATE ON decision_state_events
        BEGIN SELECT RAISE(ABORT,'decision state events are append-only'); END""")
    connection.execute("""CREATE TRIGGER decision_state_events_no_delete BEFORE DELETE ON decision_state_events
        BEGIN SELECT RAISE(ABORT,'decision state events are append-only'); END""")
    connection.execute("""CREATE TRIGGER retired_instance_irreversible BEFORE UPDATE OF run_state ON virtual_accounts
        WHEN OLD.run_state='RETIRED' AND NEW.run_state IS NOT 'RETIRED'
        BEGIN SELECT RAISE(ABORT,'retired strategy instance cannot reactivate'); END""")
