"""Event-time boundaries must follow the certified account revision order."""
from datetime import date

import pytest

from strategy_evaluator.equity import audit_equity_account
from strategy_evaluator.equity_diagnosis import diagnose_equity_accounts
from test_equity_assessment import ledger


def test_contiguous_bar_split_dividend_stay_in_their_account_revision():
    value = ledger(days=2)
    audit_equity_account(**value, decision_contract="FORMAL_V4")
    assert value["actions"][0]["time"] == value["account_points"][0]["time"]
    result = diagnose_equity_accounts(value, "a" * 64, date(2026, 10, 1), date(2026, 10, 2), symbol="TEST")
    assert result.status == "COMPUTED"
    for index, row in enumerate(result.pnl_breakdown[0].daily):
        assert (row.entry, row.holding, row.exit, row.fees) == pytest.approx((-20., 22., 20., 0.))
        assert row.residual == pytest.approx(0.)
        assert row.cycle_id == value["trades"][index]["cycle_id"]
    sliced = diagnose_equity_accounts(value, "a" * 64, date(2026, 10, 2), date(2026, 10, 2), symbol="TEST")
    assert sliced.pnl_breakdown[0].daily[0].opening_equity == 10022.
    assert sliced.pnl_breakdown[0].daily[0].closing_equity == 10044.
