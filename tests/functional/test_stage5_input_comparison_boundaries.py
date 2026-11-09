# Risk ownership: TDR-19
"""Technical inputs cannot conceal identity changes or tolerate discrete facts."""

import pytest

from czsc_trader.application.inspection_replay import (
    technical_ledger_differences,
)


def evidence(**fields):
    return {"strategy_hash": "a" * 64, "content_hash": "", "data_hash": "b" * 64,
            "initial_cash": 10000., "execution_spec": {}, "evaluation_sessions": ["2026-10-21"],
            "decisions": [], "orders": [], "fills": [], "account_daily": [], "trades": [],
            "metrics": {}, "execution_daily": [], "execution_intraday": [], **fields}


@pytest.mark.parametrize('field,left_value,right_value', [
    pytest.param('target_position', 0, 1, id='TDR-19-C01'),
])
def test_economic_tolerance_never_applies_to_discrete_or_target_fields(field, left_value, right_value):
    left = evidence(account_daily=[{field: left_value}])
    right = evidence(account_daily=[{field: right_value}])
    differences = technical_ledger_differences(left, right, tolerance=10.)
    assert differences == [{"path": f"replay.account_daily[0].{field}", "left": left_value,
                            "right": right_value, "tolerance": 0, "reason": "VALUE_DIFFERS"}]


def test_TDR_19_C03_continuous_tolerance_is_output_only_and_retains_all_differences():
    left = evidence(account_daily=[{"cash": 100.}])
    right = evidence(account_daily=[{"cash": 100.01}])
    assert not technical_ledger_differences(left, right, .02)
    right["initial_cash"] = 10000.01
    assert technical_ledger_differences(left, right, .02)[0]["path"] == "replay.initial_cash"
    left = evidence(account_daily=[{"quantity": 100}] * 35)
    right = evidence(account_daily=[{"quantity": 101}] * 35)
    assert len(technical_ledger_differences(left, right, 100)) == 35


def test_TDR_19_C04_only_runtime_identities_are_normalized():
    left = evidence(decisions=[{"decision_id": "left", "side": "BUY"}],
                    orders=[{"decision_id": "left", "order_id": "o1", "cycle_id": "c1", "quantity": 100}])
    right = evidence(strategy_hash="c" * 64, decisions=[{"decision_id": "right", "side": "BUY"}],
                     orders=[{"decision_id": "right", "order_id": "o2", "cycle_id": "c2", "quantity": 100}])
    assert not technical_ledger_differences(left, right, 0)
    right["decisions"][0]["side"] = "SELL"
    assert technical_ledger_differences(left, right, 100)
