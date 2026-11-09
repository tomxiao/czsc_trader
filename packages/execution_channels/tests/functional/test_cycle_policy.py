"""EC01/EC05: cycle-budget rules at the EC boundary, with no SRT/DFLS setup."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import pytest
from execution_channels.planning.session import build_execution_plan
from execution_channels.policy import ExecutionPolicy
from execution_channels.errors import RuntimeContractError
from execution_channels.entry_cycle import CycleTarget, EntryCyclePhase, EntryCyclePlanStatus

SETTINGS = {
    "capital": {"fee_rate": .001, "mode": "signal_cash_fraction", "target_scope": "entry_cycle"},
    "entry": {"limit_parameter": .01, "order_type": "LIMIT"},
    "exit": {"limit_ratio": .1, "order_type": "MARKET"},
    "instrument": {"lot_size": 100, "maximum_order_quantity": 1000000,
                   "price_limit_ratio": .1, "price_tick": .001},
}


def plan(fraction, *, state=None, cash=Decimal("100000"), quantity=0, price=10.):
    target = CycleTarget(fraction is not None, fraction)
    return build_execution_plan(
        deployment_settings={"cycle_target_quantity": None if state is None else state.target_quantity},
        available_cash=cash, position_quantity=quantity, target_position=float(target.active),
        policy=ExecutionPolicy("FROZEN_RULE", SETTINGS), signal_reference_price=price,
        execution_reference_price=price, cycle_target=target, entry_cycle=state,
        opening_signal_identity="1"*64, account_id="test-cycle",
    )


def test_EC05_C01_initial_half_budget_does_not_follow_later_full_signal():
    first = plan(Decimal(".5"))
    state = first["entry_cycle_after"]
    assert state.cash_budget == 50000 and state.target_quantity == 4900
    assert first["cycle_status"] is EntryCyclePlanStatus.OPEN
    # Unfilled first order: new signal requests full size, but the original .5 lock wins.
    retry = plan(Decimal(1), state=state, price=20.)
    assert retry["entry_cycle_after"] == state
    assert retry["target_quantity"] == 2400
    assert retry["capital_rule"]["allocation_fraction"] == "0.5"


def test_EC05_C02_retry_deducts_confirmed_cost_from_original_budget():
    state = plan(Decimal('.5'))['entry_cycle_after']
    partial = replace(state, buy_cost_including_fees=Decimal('20020'))
    retry = plan(Decimal('.75'), state=partial, quantity=2000,cash=Decimal('79980'))
    assert retry['target_quantity'] == 4900
    assert sum(o['quantity'] for o in retry['orders']) == 2900
    assert retry['entry_cycle_after'].cash_budget == Decimal('50000')
    capped = replace(partial,buy_cost_including_fees=Decimal('49999'))
    blocked = plan(Decimal(1),state=capped,quantity=2000)
    assert blocked['orders'] == [] and blocked['cycle_status'] is EntryCyclePlanStatus.BUDGET_LIMIT


def test_EC05_C07_exit_is_sticky_until_confirmed_flat():
    state = plan(Decimal(".5"))["entry_cycle_after"]
    exit_plan = plan(None, state=state, quantity=4900)
    exiting = exit_plan["entry_cycle_after"]
    assert exiting.phase is EntryCyclePhase.EXITING
    assert plan(Decimal(1), state=exiting, quantity=4900)["action"] == "SELL"
    assert plan(None, state=exiting)["entry_cycle_after"] == exiting


@pytest.mark.parametrize("change", [{"allocation_fraction": .5}, {"target_scope": "decision"}], ids=["EC05-C08","EC05-C09"])
def test_signal_allocation_policy_rejects_ambiguous_size_source(change):
    settings = deepcopy(SETTINGS)
    settings["capital"].update(change)
    with pytest.raises(RuntimeContractError, match="signal-owned"):
        ExecutionPolicy("FROZEN_RULE", settings)
