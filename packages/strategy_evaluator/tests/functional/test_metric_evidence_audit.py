"""Metric boundaries owned by SE's public evidence audits."""
from dataclasses import replace

import pytest
from strategy_evaluator import AuditStatus, ReplayEvidence, audit_benchmark_replay, audit_replay
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
        tuple({"date": day, "open": 1., "close": 1.} for day in dates), (),
    )


@pytest.mark.parametrize("kind", ["strategy", "benchmark"])
@pytest.mark.parametrize("field,value", [
    ("win_rate", True), ("win_rate", -.1), ("win_rate", 1.1), ("win_rate", .5),
    ("closed_trades", False), ("closed_trades", -1), ("return", float("nan")),
    ("max_drawdown", .1), ("win_loss_ratio", -1), ("calmar", float("inf")),
])
def test_public_audit_rejects_invalid_metric_evidence(kind, field, value):
    evidence, audit = (_replay(), audit_replay) if kind == "strategy" else (
        _buyhold_evidence(), audit_benchmark_replay,
    )
    assert audit(evidence).status is AuditStatus.PASS
    invalid = replace(evidence, metrics={**evidence.metrics, field: value})
    result = audit(invalid)
    assert result.status is AuditStatus.FAIL
    assert ("METRIC_MISMATCH" if kind == "strategy" else "BENCHMARK_METRIC_MISMATCH") in result.reason_codes


@pytest.mark.parametrize("kind", ["strategy", "benchmark"])
@pytest.mark.parametrize("field", ["win_rate", "calmar", "sharpe", "win_loss_ratio"])
def test_public_audit_requires_all_metric_fields(kind, field):
    evidence, audit = (_replay(), audit_replay) if kind == "strategy" else (
        _buyhold_evidence(), audit_benchmark_replay,
    )
    result = audit(replace(evidence, metrics={key: value for key, value in evidence.metrics.items() if key != field}))
    assert result.status is AuditStatus.FAIL


@pytest.mark.parametrize("kind", ["strategy", "benchmark"])
def test_public_metric_audit_preserves_finite_numeric_tolerance(kind):
    evidence, audit = (_replay(), audit_replay) if kind == "strategy" else (
        _buyhold_evidence(), audit_benchmark_replay,
    )
    value = evidence.metrics["return"]
    near = replace(evidence, metrics={**evidence.metrics, "return": value + 1e-8})
    far = replace(evidence, metrics={**evidence.metrics, "return": value + 1e-5})
    assert audit(near).status is AuditStatus.PASS
    assert audit(far).status is AuditStatus.FAIL
