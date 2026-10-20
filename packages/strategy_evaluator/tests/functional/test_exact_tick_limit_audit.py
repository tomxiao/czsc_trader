"""Exact audit must compare canonical tick prices, without widening tolerance."""

from dataclasses import replace

import pytest

from strategy_evaluator import AuditStatus, ReplayEvidence, audit_replay


def _unfilled_upper_guard_account():
    dates = ("2026-08-03", "2026-08-04")
    return ReplayEvidence(
        strategy_hash="a" * 64, data_hash="b" * 64, initial_cash=100000.,
        evaluation_sessions=dates,
        execution_spec={
            "decision_coverage": "COMPLETE", "entry_limit_parameter": .2,
            "exit_limit_ratio": .2, "entry_order_type": "LIMIT", "exit_order_type": "MARKET",
            "fee_rate": .001, "capital_mode": "full_available_cash", "allocation_fraction": 1.,
            "instrument": {"lot_size": 100, "price_tick": .001,
                           "price_limit_ratio": .2, "maximum_order_quantity": 1000000},
            "market_rules": {"contract_version": "DAILY_RANGE_V3", "symbol": "588080.SH",
                "suspended_sessions": [], "suspension_information": "NOT_PROVIDED",
                "sessions": [{"session": day, "down_limit": 1.341, "up_limit": 2.011,
                              "price_tick": .001} for day in dates]},
        },
        decisions=tuple({"decision_id": f"D{i}", "signal_date": prior, "valid_session": day,
                         "target_position": 1. if i == 0 else 0., "action": "BUY" if i == 0 else "SELL"}
                        for i, (prior, day) in enumerate(zip(("2026-07-31", dates[0]), dates, strict=True))),
        orders=({"order_id": "BUY", "decision_id": "D0", "cycle_id": "C0",
                 "signal_date": "2026-07-31", "execution_date": dates[0], "side": "BUY",
                 "quantity": 1000, "order_type": "LIMIT", "limit_price": 2.01,
                 "status": "UNFILLED", "reason": "DAILY_RANGE_NOT_REACHED"},),
        fills=(), trades=(),
        account_daily=tuple({"date": day, "cash_before": 100000., "quantity_before": 0,
                             "cash": 100000., "quantity": 0, "close": 2.011, "equity": 100000.,
                             "trading_status": None} for day in dates),
        metrics={"return": 0., "max_drawdown": 0., "calmar": None, "sharpe": None,
                 "closed_trades": 0, "win_rate": None, "win_loss_ratio": None,
                 "win_loss_ratio_status": "NO_CLOSED_TRADES"},
        execution_daily=tuple({"date": day, "open": price, "high": price, "low": price,
                               "close": price, "unadjusted_close": price, "price_scale": 1.}
                              for day, price in (("2026-07-31", 1.676), (dates[0], 2.011), (dates[1], 2.011))),
        execution_intraday=(),
    )


def test_valid_201_limit_passes_full_public_audit_with_zero_tolerance():
    evidence = _unfilled_upper_guard_account()
    # Reproduce the binary subtraction that must be canonicalized to .001.
    assert 2.011 - .001 != 2.01
    checked = audit_replay(evidence, tolerance=0.)
    assert checked.status is AuditStatus.PASS, checked.reason_codes


@pytest.mark.parametrize("wrong_limit", [2.009, 2.011])
def test_one_tick_wrong_limit_remains_rejected_with_zero_tolerance(wrong_limit):
    evidence = _unfilled_upper_guard_account()
    changed = replace(evidence, orders=({**evidence.orders[0], "limit_price": wrong_limit},))
    checked = audit_replay(changed, tolerance=0.)
    assert checked.status is AuditStatus.FAIL
    assert "ORDER_LIMIT_MISMATCH" in checked.reason_codes
