"""EC05/EC17: PTE account allocation: adoption, real fill increments, recovery and release."""


from dataclasses import asdict, replace


from datetime import date, timedelta


from decimal import Decimal


import json


import pytest


from paper_trading_engine.contracts import OrderSpec


from strategy_runtime import CycleTarget, EntryCycleState, EntryCyclePhase, EntryCyclePlanStatus, canonical_sha256


from pte_support import decision


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


def test_EC05_C06_cycle_owner_cannot_be_forged_on_matching_account(memory_store):
    store = memory_store()
    _account(store)
    opening = _plan(store,'open',date(2026,9,2))
    opening['entry_cycle_after']['cycle_id'] = 'f'*64
    before = tuple(store._connection.iterdump())
    with pytest.raises(ValueError,match='another account'):
        store.save_account_decision('cycle',opening)
    assert tuple(store._connection.iterdump()) == before
    assert _state(store) is None
