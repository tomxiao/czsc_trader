"""Metric boundaries owned by SE's public evidence audits."""
from dataclasses import replace
from math import sqrt

import pytest
from strategy_evaluator import AuditStatus, ReplayEvidence, audit_replay
from test_benchmark_audit import _buyhold_evidence


def _replay():
    dates = ("2026-01-05", "2026-01-06")
    return ReplayEvidence(
        "a" * 64, "b" * 64, 100., dates,
        {"instrument": {"lot_size": 100, "price_tick": .001, "price_limit_ratio": .1},
         "fee_rate": .001, "entry_limit_parameter": 0., "exit_limit_ratio": .1},
        (), (), (),
        tuple({"date": day, "cash_before": 100., "quantity_before": 0,
               "cash": 100., "quantity": 0, "equity": 100., "close": 1.} for day in dates),
        (), {"return": 0., "max_drawdown": 0., "calmar": None, "sharpe": None,
             "closed_trades": 0, "win_rate": None, "win_loss_ratio": None,
             "win_loss_ratio_status": "NO_CLOSED_TRADES"},
        tuple({"date": day, "open": 1., "close": 1., "unadjusted_close": 1., "price_scale": 1.}
              for day in dates), (),
    )


def _finite_benchmark():
    """Buy-and-hold with an initial drawdown and a finite Calmar ratio."""
    evidence = _buyhold_evidence()
    cash = 9.1
    first, last = 90.1, 99.1
    returns = (first / 100. - 1., last / first - 1.)
    mean = sum(returns) / 2
    std = sqrt(sum((value - mean) ** 2 for value in returns))
    return replace(
        evidence,
        execution_prices=(
            {"date": "2026-01-05", "open": 10., "close": 9.},
            {"date": "2026-01-06", "open": 10., "close": 10.},
        ),
        account_daily=tuple(
            {**row, "cash": cash, "equity": equity}
            for row, equity in zip(evidence.account_daily, (first, last), strict=True)
        ),
        metrics={**evidence.metrics, "return": -.009, "max_drawdown": -.099,
                 "calmar": ((last / 100.) ** 126 - 1.) / .099,
                 "sharpe": sqrt(252.) * mean / std},
    )


@pytest.mark.parametrize('defect', [
    pytest.param("unavailable", id='SE-29-C04'),
    pytest.param("finite", id='SE-29-C05'),
    pytest.param("missing", id='SE-37-C05'),
])
@pytest.mark.risk_cases('SE-29-C04', 'SE-29-C05', 'SE-37-C05')
def test_metric_state_value_and_required_field_are_authenticated(defect):
    evidence = _replay()
    metrics = dict(evidence.metrics)
    if defect == 'unavailable':
        metrics['win_loss_ratio_status'] = 'VALID'
    elif defect == 'finite':
        metrics['return'] += .01
    else:
        del metrics['calmar']
    result = audit_replay(replace(evidence, metrics=metrics))
    assert result.status is AuditStatus.FAIL
    assert result.reason_codes == ('METRIC_MISMATCH',)
