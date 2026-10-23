"""Independent arithmetic checks for the pure retained-account diagnostic."""

from dataclasses import replace
from datetime import date

import pytest

from strategy_evaluator.account_diagnosis import (
    AccountDiagnosisStatus,
    diagnose_account_replays,
)
from strategy_evaluator.replay_audit import ReplayEvidence


def account(*, open_end=False, cash_only=False):
    sessions = ("2025-12-30", "2025-12-31", "2026-01-01", "2026-01-02")
    cash = (1000.0, 899.0, 899.0, 899.0 if open_end else 1008.0)
    quantities = (0, 10, 10, 10 if open_end else 0)
    if cash_only:
        cash, quantities = (1000.0,) * 4, (0,) * 4
    closes = (10.0, 11.0, 12.0, 11.0)
    fills = (
        ()
        if cash_only
        else (
            {
                "fill_id": "buy",
                "order_id": "buy-order",
                "decision_id": "buy-decision",
                "cycle_id": "cycle",
                "side": "BUY",
                "fill_time": sessions[1],
                "quantity": 10,
                "price": 10.0,
                "fees": 1.0,
            },
        )
    )
    if not open_end and not cash_only:
        fills += (
            {
                "fill_id": "sell",
                "order_id": "sell-order",
                "decision_id": "sell-decision",
                "cycle_id": "cycle",
                "side": "SELL",
                "fill_time": sessions[3],
                "quantity": 10,
                "price": 11.0,
                "fees": 1.0,
            },
        )
    rows = tuple(
        {
            "date": day,
            "cash_before": 1000.0 if i == 0 else cash[i - 1],
            "quantity_before": 0 if i == 0 else quantities[i - 1],
            "cash": cash[i],
            "quantity": quantities[i],
            "close": closes[i],
            "target_position": int(quantities[i] > 0),
            "equity": cash[i] + quantities[i] * closes[i],
        }
        for i, day in enumerate(sessions)
    )
    return ReplayEvidence(
        "a" * 64, "b" * 64, 1000.0, sessions, {}, (), (), fills, rows, (), {}, (), ()
    )


def calculate(replay, **kwargs):
    return diagnose_account_replays(
        replay, "eval", date(2025, 12, 30), date(2026, 1, 2), symbol="ETF", **kwargs
    )


def test_exclusive_pnl_reconciles_across_years_with_each_year_own_capital():
    result = calculate(account())
    assert result.status is AccountDiagnosisStatus.COMPUTED
    daily = result.pnl_breakdown[0].daily
    assert [(d.entry, d.holding, d.exit, d.fees) for d in daily] == [
        (0, 0, 0, 0),
        (10, 0, 0, -1),
        (0, 10, 0, 0),
        (0, 0, -10, -1),
    ]
    assert [d.equity_change for d in daily] == [0, 9, 10, -11]
    first, second = result.pnl_breakdown[0].annual
    assert (first.opening_equity, second.opening_equity) == (1000, 1009)
    assert second.holding_contribution == pytest.approx(10 / 1009)
    assert second.exit_contribution == pytest.approx(-10 / 1009)
    assert second.fee_contribution == pytest.approx(-1 / 1009)
    sliced = diagnose_account_replays(
        account(), "eval", date(2026, 1, 1), date(2026, 1, 2), symbol="ETF"
    )
    assert sliced.pnl_breakdown[0].daily[0].opening_equity == 1009
    assert sliced.pnl_breakdown[0].daily[0].cycle_id == "cycle"


@pytest.mark.parametrize(
    "replay,expected", [(account(open_end=True), 9.0), (account(cash_only=True), 0.0)]
)
def test_open_position_and_no_trade_account_have_complete_decomposition(replay, expected):
    result = calculate(replay)
    assert result.status is AccountDiagnosisStatus.COMPUTED
    assert sum(d.equity_change for d in result.pnl_breakdown[0].daily) == expected
    assert all(d.residual == 0 for d in result.pnl_breakdown[0].daily)


def test_scaling_is_unsupported_and_unexplained_cash_is_invalid():
    replay = account()
    extra = dict(replay.fills[0], fill_id="another", fill_time="2026-01-01")
    assert (
        calculate(replace(replay, fills=replay.fills + (extra,))).status
        is AccountDiagnosisStatus.UNSUPPORTED
    )
    changed = tuple(
        dict(r, equity=r["equity"] + 1) if i == 2 else r for i, r in enumerate(replay.account_daily)
    )
    assert (
        calculate(replace(replay, account_daily=changed)).status
        is AccountDiagnosisStatus.INVALID_EVIDENCE
    )


def test_dynamic_cycle_allocation_is_explicitly_unsupported_even_for_one_full_buy():
    replay = account()
    result = calculate(replace(replay, execution_spec={
        "capital_mode": "signal_cash_fraction", "target_scope": "entry_cycle",
        "allocation_fraction": 1.0,
    }))
    assert result.status is AccountDiagnosisStatus.UNSUPPORTED
    assert "signal-owned cycle allocation" in result.issues[0]


def test_paths_use_unique_entry_session_and_preserve_open_exit_unknown():
    result = calculate(account(), alternative=account(open_end=True), alternative_id="other")
    assert result.status is AccountDiagnosisStatus.COMPUTED
    (path,) = result.path_comparison
    assert path.entry_session == "2025-12-31"
    assert path.baseline_cycle_id == path.alternative_cycle_id == "cycle"
    assert path.baseline_exit_session == "2026-01-02"
    assert path.alternative_exit_session is None
    assert result.daily_paths[-1].equity_difference == 1
