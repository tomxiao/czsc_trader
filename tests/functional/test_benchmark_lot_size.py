from types import SimpleNamespace
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from strategy_evaluator import AuditStatus, audit_benchmark_replay

from czsc_trader.backtesting.audit_adapter import build_benchmark_evidence
from czsc_trader.backtesting.benchmarks import replay_benchmarks


@pytest.mark.parametrize("initial_cash,lot_size", [(500, 100), (1100, 100), (1100, 1)])
def test_benchmark_quantities_cash_signal_timing_and_independent_audit(initial_cash, lot_size):
    dates = pd.bdate_range("2026-01-01", periods=65)
    close = np.r_[np.linspace(10, 12, 25), np.linspace(12, 9, 20), np.linspace(9, 12, 20)]
    prices = pd.DataFrame({"dt": dates, "open": close, "close": close + .1})
    data = SimpleNamespace(execution_daily=prices, adjusted_daily=prices)
    signals = SimpleNamespace(
        evaluation_start=dates[25], evaluation_end=dates[-1],
        support_data={"mode": "srt_input_contract", "execution_policy": {
            "policy_type": "FROZEN_RULE", "settings": {"capital": {"fee_rate": .001}},
        }},
    )
    result = replay_benchmarks(signals, data, initial_cash, lot_size=lot_size)
    evidence = build_benchmark_evidence(result, signals, data, initial_cash, lot_size=lot_size)
    for name, item in evidence.items():
        audit = audit_benchmark_replay(item)
        assert audit.status is AuditStatus.PASS, (name, audit.reason_codes)
        actual = item.metrics['win_rate']
        for invalid in (True, -0.1, 1.1, 0.5 if actual != 0.5 else 0.):
            altered = replace(item, metrics={**item.metrics, 'win_rate': invalid})
            assert 'BENCHMARK_METRIC_MISMATCH' in audit_benchmark_replay(altered).reason_codes
        account = pd.DataFrame(item.account_daily)
        assert (account.quantity % lot_size == 0).all()
        assert (account.cash >= 0).all()
        assert account.equity.tolist() == pytest.approx(
            (account.cash + account.quantity * account.close).tolist(),
        )
        for order in item.orders:
            execution_date = pd.Timestamp(order["execution_date"])
            assert pd.Timestamp(order["signal_date"]) == dates[dates.get_loc(execution_date) - 1]
            assert order["size"] > 0 and order["size"] % lot_size == 0
        if initial_cash == 500:
            assert not item.orders
            assert account.equity.eq(initial_cash).all()
