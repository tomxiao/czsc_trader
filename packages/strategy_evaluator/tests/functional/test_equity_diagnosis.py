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


def test_orders_are_partitioned_once_by_market_session_for_a_diagnostic_slice(monkeypatch):
    from strategy_evaluator import equity_diagnosis as diagnosis

    days = ("2026-11-12", "2026-11-13", "2026-11-16", "2026-11-17")
    # UTC end times retain the New York session, including an evening order
    # whose UTC date has already rolled over to the next calendar day.
    orders = [
        {"order_id": "later", "valid_end": "2026-11-17T21:00:00+00:00"},
        {"order_id": "evening", "valid_end": "2026-11-14T00:30:00+00:00"},
        {"order_id": "first", "valid_end": "2026-11-13T21:00:00+00:00"},
        {"order_id": "next", "valid_end": "2026-11-16T21:00:00+00:00"},
        {"order_id": "earlier", "valid_end": "2026-11-12T21:00:00+00:00"},
    ]
    ledger = {
        "initial_cash": 10000., "specification": {"market": {"rule_version": "US_EQUITY_V1"}},
        "fills": [], "trades": [], "orders": orders,
        "account_points": [
            {"time": day + "T21:00:00+00:00", "session": day, "close": 10.,
             "equity": 10000., "cash": 10000., "quantity": 0, "decision_id": "D" + day}
            for day in days
        ],
    }
    session = diagnosis._session
    visits = []

    def observed_session(stamp, timezone):
        visits.append(stamp)
        return session(stamp, timezone)

    monkeypatch.setattr(diagnosis, "_session", observed_session)
    result = diagnose_equity_accounts(
        ledger, "a" * 64, date(2026, 11, 13), date(2026, 11, 16), symbol="TEST",
    )
    daily = result.pnl_breakdown[0].daily
    assert [(row.session, row.order_ids) for row in daily] == [
        ("2026-11-13", ("evening", "first")), ("2026-11-16", ("next",)),
    ]
    assert visits == [row["valid_end"] for row in orders]
