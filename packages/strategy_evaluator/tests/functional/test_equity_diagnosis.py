"""HFQ fill attribution and session slices follow certified account revisions."""
from datetime import date

import pytest

from strategy_evaluator.equity_diagnosis import diagnose_equity_accounts




@pytest.mark.risk_cases('SE-32-C03')
def test_SE_32_C03_same_bar_scaling_is_one_position_cycle():
    from test_equity_v4 import ledger as scaling_ledger
    value = {**scaling_ledger(), "account_contract": 4}
    result = diagnose_equity_accounts(value, "a" * 64, date(2026, 10, 8), date(2026, 10, 8), symbol="TEST")
    assert result.status == "COMPUTED"
    assert len(value["trades"]) == 1
    daily = result.pnl_breakdown[0].daily
    assert len(daily) == 1
    assert daily[0].equity_change == pytest.approx(-6.)
    assert daily[0].fees == pytest.approx(-6.)
    assert daily[0].entry + daily[0].holding + daily[0].exit == pytest.approx(0.)
    assert daily[0].residual == pytest.approx(0.)
