"""PTE account allocation: adoption, real fill increments, recovery and release."""

from dataclasses import asdict, replace
from datetime import date, timedelta
from decimal import Decimal
import json
import sqlite3

import pytest

from paper_trading_engine.contracts import OrderSpec
from paper_trading_engine.store import PaperStore
from strategy_runtime import CycleTarget, EntryCycleState, EntryCyclePhase, EntryCyclePlanStatus, canonical_sha256
from pte_support import decision, claim_test_intent, adopt_test_decision


def _account(store):
    store.create_virtual_account(
        "cycle", "周期资金测试", "legacy", "a" * 64, 10_000,
        strategy_id="S001", strategy_name_snapshot="周期资金测试", strategy_version="v1",
        release_hash="b" * 64, qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("cycle", False)


def _state(store):
    value = store.virtual_account("cycle")["entry_cycle_json"]
    return None if value is None else EntryCycleState.from_dict(json.loads(value))


def _plan(store, name, day, *, fraction=Decimal("0.5"), before=None, side="BUY", quantity=1000, price=4):
    account = store.virtual_account("cycle")
    active = side != "SELL"
    target = CycleTarget(active, fraction if active else None)
    signal = canonical_sha256({"signal": name})
    if before is None:
        after = EntryCycleState(
            canonical_sha256({"account": "cycle", "opening_signal": signal}), signal, fraction,
            Decimal(account["cash"]) * fraction, quantity, Decimal(0), EntryCyclePhase.ACTIVE,
        )
        status = EntryCyclePlanStatus.OPEN
    else:
        after = replace(before, phase=EntryCyclePhase.ACTIVE if active else EntryCyclePhase.EXITING)
        status = EntryCyclePlanStatus.HOLD if active else EntryCyclePlanStatus.EXIT
    order = OrderSpec(side, quantity, "LIMIT" if active else "MARKET", price, "DAY")
    result = replace(
        decision(order), contract_version="advice.v6", decision_id=name,
        signal_date=day - timedelta(days=1), valid_session=day, data_cutoff=day - timedelta(days=1),
        actual_quantity=account["quantity"], target_quantity=account["quantity"] + (quantity if active else -quantity),
        cycle_target_quantity=after.target_quantity, delta_quantity=quantity if active else -quantity,
        available_cash=float(account["cash"]), capital_mode="signal_cash_fraction",
        allocation_fraction=float(after.allocation_fraction), signal_identity=signal,
        plan_identity=name.encode().hex().ljust(64, "0")[:64],
        cycle_target=target, entry_cycle_before=before, entry_cycle_after=after, cycle_status=status,
    )
    return asdict(result)


def _submit(store, payload):
    store.save_account_decision("cycle", payload)
    order = payload["orders"][0]
    intent = store.create_account_intent(
        account_id="cycle", decision_id=payload["decision_id"], order_sequence=0,
        symbol="588080.SH", side=order["side"], quantity=order["quantity"],
        limit_price=order["limit_price"], order_type=order["order_type"],
        valid_session=payload["valid_session"].isoformat(), fee_rate="0.0005",
    )
    assert claim_test_intent(store, intent["intent_id"])
    order_id = payload["decision_id"] + "-order"
    store.bind_channel_order(intent["intent_id"], order_id, {
        "status": "SUBMITTED", "cumulative_filled_quantity": 0,
        "symbol": "588080.SH", "side": order["side"], "quantity": order["quantity"], "remark": intent["intent_id"],
    })
    return order_id


def _fill(store, order_id, quantity, price):
    return store.apply_fill_increment(order_id, cumulative_quantity=quantity, average_price=price,
                                      occurred_at="2026-09-02T10:00:00+08:00")


def _report(store, order_id, quantity, price, status):
    store.update_channel_order_report(order_id, {"status": status, "cumulative_filled_quantity": quantity,
                                               "average_fill_price": price})


def test_entry_cycle_survives_retry_restart_and_releases_only_after_terminal_exit(new_store, tmp_path):
    path = tmp_path / "cycle.db"
    store = new_store(path)
    _account(store)
    opening = _plan(store, "open", date(2026, 9, 2))
    assert _state(store) is None  # Merely preparing a plan cannot acquire a budget.
    buy = _submit(store, opening)
    locked = _state(store)
    assert locked.cash_budget == Decimal("5000")
    store.save_account_decision("cycle", opening)
    assert _state(store) == locked
    _fill(store, buy, 400, 4)
    assert _state(store).buy_cost_including_fees == Decimal("1600.8000")
    assert _fill(store, buy, 400, 4) is None
    _report(store, buy, 400, 4, "CANCELLED_PART")
    # The market order is explicitly terminated; the entry allocation is not.
    assert _state(store).phase == EntryCyclePhase.ACTIVE
    store.close()
    store = PaperStore(path)
    restored = _state(store)
    retry = _plan(store, "retry", date(2026, 9, 3), fraction=Decimal(1), before=restored, quantity=600, price=5)
    second = _submit(store, retry)
    assert _state(store).allocation_fraction == Decimal("0.5")
    _fill(store, second, 600, 5)
    _report(store, second, 600, 5, "FILLED_ALL")
    assert _state(store).buy_cost_including_fees == Decimal("4602.3000")
    exit_plan = _plan(store, "exit", date(2026, 9, 4), before=_state(store), side="SELL", quantity=1000, price=6)
    sell = _submit(store, exit_plan)
    with pytest.raises(ValueError, match="applied first"):
        _report(store, sell, 1000, 6, "FILLED_ALL")
    assert _state(store).phase == EntryCyclePhase.EXITING
    _fill(store, sell, 1000, 6)
    assert store.virtual_account("cycle")["quantity"] == 0
    assert _state(store).phase == EntryCyclePhase.EXITING
    _report(store, sell, 1000, 6, "UNKNOWN")
    assert _state(store) is not None
    _report(store, sell, 1000, 6, "FILLED_ALL")
    assert _state(store) is None
    assert store.virtual_account("cycle")["cycle_target"] is None
    # Replaying an already accepted exit never restores its old cycle snapshot.
    store.save_account_decision("cycle", exit_plan)
    assert _state(store) is None
    next_plan = _plan(store, "next", date(2026, 9, 7), fraction=Decimal(1))
    store.save_account_decision("cycle", next_plan)
    assert _state(store).allocation_fraction == 1
    assert _state(store).cash_budget == Decimal("11394.7000")
    store.close()


def test_entry_cycle_adoption_rejects_stale_state_and_budget_tampering_atomically(new_store, tmp_path):
    store = new_store(tmp_path / "stale.db")
    _account(store)
    opening = _plan(store, "open", date(2026, 9, 2))
    buy = _submit(store, opening)
    before_fill = _state(store)
    _fill(store, buy, 400, 4)
    _report(store, buy, 400, 4, "CANCELLED_PART")
    stale = _plan(store, "stale", date(2026, 9, 3), before=before_fill, quantity=600)
    with pytest.raises(ValueError, match="changed before"):
        store.save_account_decision("cycle", stale)
    actual = _state(store)
    over_budget = _plan(store, "expensive", date(2026, 9, 3), before=actual, quantity=600, price=6)
    with pytest.raises(ValueError, match="budget"):
        store.save_account_decision("cycle", over_budget)
    assert _state(store) == actual
    assert len(store.account_decisions("cycle")) == 1
    store.close()


def test_signal_allocation_cannot_adopt_a_legacy_cycle(new_store, tmp_path):
    store = new_store(tmp_path / "legacy.db")
    _account(store)
    adopt_test_decision(store, account_id="cycle", decision_id="legacy", valid_session="2026-09-02",
                        orders=[{"side": "BUY", "quantity": 1000, "order_type": "LIMIT", "limit_price": 4}])
    incoming = _plan(store, "new", date(2026, 9, 3))
    with pytest.raises(ValueError, match="empty account"):
        store.save_account_decision("cycle", incoming)
    assert _state(store) is None
    store.close()


def test_v5_database_adds_empty_cycle_state_without_reinterpreting_legacy_target(new_store, tmp_path):
    path = tmp_path / "migration.db"
    store = new_store(path)
    _account(store)
    adopt_test_decision(store, account_id="cycle", decision_id="legacy", valid_session="2026-09-02",
                        orders=[{"side": "BUY", "quantity": 1000, "order_type": "LIMIT", "limit_price": 4}])
    previous = store.virtual_account("cycle")
    store.close()
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE virtual_accounts DROP COLUMN entry_cycle_json")
        connection.execute("UPDATE settings SET value='5' WHERE key='runtime_database_schema_version'")
    store = PaperStore(path)
    current = store.virtual_account("cycle")
    assert current["entry_cycle_json"] is None
    assert current["cycle_target"] == 1000
    assert current == previous
    store.close()


@pytest.mark.parametrize("mutation", ["active_sell", "forced_exit", "foreign_cycle"])
def test_entry_cycle_adoption_rejects_invalid_direction_phase_and_owner(new_store, tmp_path, mutation):
    store = new_store(tmp_path / "semantic.db")
    _account(store)
    opening = _plan(store, "open", date(2026, 9, 2))
    if mutation == "foreign_cycle":
        opening["entry_cycle_after"]["cycle_id"] = "f" * 64
        with pytest.raises(ValueError, match="another account"):
            store.save_account_decision("cycle", opening)
        assert _state(store) is None
    else:
        order = _submit(store, opening)
        _fill(store, order, 1000, 4)
        _report(store, order, 1000, 4, "FILLED_ALL")
        state = _state(store)
        invalid = _plan(store, "invalid", date(2026, 9, 3), before=state, side="SELL", quantity=1000)
        invalid["cycle_target"] = CycleTarget(True, Decimal("0.5")).to_dict()
        if mutation == "active_sell":
            invalid["entry_cycle_after"]["phase"] = "ACTIVE"
            invalid["cycle_status"] = "HOLD"
        with pytest.raises(ValueError):
            store.save_account_decision("cycle", invalid)
        assert _state(store) == state
        assert len(store.account_decisions("cycle")) == 1
    store.close()
