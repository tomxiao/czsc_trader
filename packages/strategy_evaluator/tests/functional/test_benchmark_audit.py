from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from strategy_evaluator import AuditStatus, BenchmarkEvidence, audit_benchmark_replay


def _buyhold_evidence() -> BenchmarkEvidence:
    initial_cash = 100.0
    fee_rate = 0.01
    shares = 9
    cash = initial_cash - shares * 10 * (1 + fee_rate)
    equity = pd.Series([cash + shares * 11.0, cash + shares * 12.0])
    prior = equity.shift(1)
    prior.iloc[0] = initial_cash
    returns = equity.div(prior).sub(1.0)
    sharpe = float(np.sqrt(252.0) * returns.mean() / returns.std(ddof=1))
    return BenchmarkEvidence(
        "BUYHOLD",
        initial_cash,
        fee_rate,
        ("2026-01-05", "2026-01-06"),
        (
            {"date": "2026-01-05", "open": 10.0, "close": 11.0},
            {"date": "2026-01-06", "open": 12.0, "close": 12.0},
        ),
        (),
        (
            {"date": "2026-01-05", "target_position": 1.0, "equity": equity.iloc[0], "cash": cash, "quantity": shares},
            {"date": "2026-01-06", "target_position": 1.0, "equity": equity.iloc[1], "cash": cash, "quantity": shares},
        ),
        (
            {
                "signal_date": "2026-01-02",
                "execution_date": "2026-01-05",
                "side": "Buy",
                "size": shares,
                "price": 10.0,
                "fees": shares * 10.0 * fee_rate,
            },
        ),
        (),
        {
            "return": float(equity.iloc[-1] / initial_cash - 1.0),
            "max_drawdown": 0.0,
            "calmar": None,
            "sharpe": sharpe,
            "win_loss_ratio": None,
            "win_loss_ratio_status": "NO_CLOSED_TRADES",
            "closed_trades": 0,
        },
        lot_size=1,
    )


def test_benchmark_audit_rejects_missing_account_session() -> None:
    evidence = _buyhold_evidence()
    assert audit_benchmark_replay(evidence).status is AuditStatus.PASS

    result = audit_benchmark_replay(
        replace(evidence, account_daily=evidence.account_daily[:1])
    )
    assert result.status is AuditStatus.FAIL
    assert "INCOMPLETE_BENCHMARK_ACCOUNT_COVERAGE" in result.reason_codes


@pytest.mark.parametrize("field", ["cash", "quantity"])
def test_benchmark_audit_rejects_tampered_account_even_with_correct_equity(field):
    evidence = _buyhold_evidence()
    rows = [dict(row) for row in evidence.account_daily]
    rows[0][field] += 1
    result = audit_benchmark_replay(replace(evidence, account_daily=tuple(rows)))
    assert result.status is AuditStatus.FAIL
    assert "BENCHMARK_LEDGER_MISMATCH" in result.reason_codes


def test_benchmark_lot_size_changes_hash_and_audit():
    evidence = _buyhold_evidence()
    first = audit_benchmark_replay(evidence)
    changed = audit_benchmark_replay(replace(evidence, lot_size=100))
    assert changed.evidence_hash != first.evidence_hash
    assert changed.status is AuditStatus.FAIL
    assert "BENCHMARK_ORDER_MISMATCH" in changed.reason_codes


@pytest.mark.parametrize("value", [None, True, 1.5, "100", 0, -1])
def test_benchmark_lot_size_is_strict(value):
    with pytest.raises((TypeError, ValueError), match="lot_size"):
        replace(_buyhold_evidence(), lot_size=value)
