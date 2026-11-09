from copy import deepcopy
from dataclasses import replace

import pytest
from strategy_evaluator import (
    LedgerComparisonMode as Mode,
    LedgerComparisonRequest,
    LedgerComparisonStatus as Status,
    ReplayEvidence,
    compare_ledgers,
    hash_replay_evidence,
)


def _evidence(prefix="a"):
    return ReplayEvidence(
        strategy_hash=prefix * 64,
        data_hash="d" * 64,
        initial_cash=100,
        evaluation_sessions=("2026-01-05", "2026-01-06"),
        execution_spec={"lot_size": 1, "fee_rate": 0.001},
        decisions=tuple(
            {"decision_id": f"{prefix}d{i}", "target_position": 1 - i} for i in range(2)
        ),
        orders=tuple(
            {
                "decision_id": f"{prefix}d{i}",
                "order_id": f"{prefix}o{i}",
                "cycle_id": f"{prefix}c",
                "quantity": 10,
            }
            for i in range(2)
        ),
        fills=tuple(
            {
                "decision_id": f"{prefix}d{i}",
                "order_id": f"{prefix}o{i}",
                "fill_id": f"{prefix}f{i}",
                "cycle_id": f"{prefix}c",
                "quantity": 10,
                "fees": 0.1,
            }
            for i in range(2)
        ),
        account_daily=(
            {"date": "2026-01-05", "equity": 100.0},
            {"date": "2026-01-06", "equity": 110.0},
        ),
        trades=({"cycle_id": f"{prefix}c", "net_return": 0.1},),
        metrics={"return": 0.1},
        execution_daily=(),
        execution_intraday=(),
    )


@pytest.mark.risk_cases('SE-30-C01')
def test_strict_and_economic_comparison_preserve_original_evidence():
    left, right = _evidence(), _evidence("b")
    originals = deepcopy((left.to_dict(), right.to_dict()))
    for mode, tolerance in ((Mode.STRICT, 0), (Mode.ECONOMIC, 0), (Mode.ECONOMIC, .001)):
        same = compare_ledgers(LedgerComparisonRequest(left, left, mode, tolerance))
        separate = compare_ledgers(
            LedgerComparisonRequest(left, deepcopy(left), mode, tolerance)
        )
        assert same == separate
        assert same.status is Status.EQUIVALENT
        assert same.left_hash == same.right_hash == hash_replay_evidence(left)
    assert compare_ledgers(LedgerComparisonRequest(left, right)).status is Status.DIFFERENT
    result = compare_ledgers(LedgerComparisonRequest(left, right, Mode.ECONOMIC))
    assert result.status is Status.EQUIVALENT
    assert result.left_hash != result.right_hash
    assert result.to_dict()["status"] == "EQUIVALENT"
    assert (left.to_dict(), right.to_dict()) == originals


@pytest.mark.parametrize('change', [
    pytest.param({"initial_cash": 101}, id='SE-30-C04'),
    pytest.param({"execution_spec": {"lot_size": 1, "fee_rate": .001, "price_basis": "RAW"}}, id='SE-30-C05'),
    pytest.param({"execution_spec": {"lot_size": 1, "fee_rate": .002}}, id='SE-30-C06'),
])
@pytest.mark.risk_cases('SE-30-C04', 'SE-30-C05', 'SE-30-C06')
def test_different_execution_context_is_incomparable(change):
    left = _evidence()
    result = compare_ledgers(LedgerComparisonRequest(left, replace(left, **change), Mode.ECONOMIC))
    assert result.status is Status.INCOMPARABLE


@pytest.mark.risk_cases('SE-30-C02')
def test_identity_normalization_does_not_hide_changed_relationship():
    left = _evidence()
    right = _evidence("b")
    orders = [dict(row) for row in right.orders]
    fills = [dict(row) for row in right.fills]
    orders[0]["decision_id"] = fills[0]["decision_id"] = "bd1"
    right = replace(right, orders=tuple(orders), fills=tuple(fills))
    result = compare_ledgers(LedgerComparisonRequest(left, right, Mode.ECONOMIC))
    assert result.status is Status.DIFFERENT
    assert any("decision_id" in item.path for item in result.differences)


@pytest.mark.risk_cases('SE-31-C01')
def test_invalid_evidence_cannot_compare_equal_to_itself():
    kind = "dangling"
    value = _evidence()
    if kind == "duplicate":
        value = replace(value, decisions=(value.decisions[0], value.decisions[0]))
    elif kind == "dangling":
        value = replace(value, fills=({**value.fills[0], "order_id": "missing"},))
    elif kind == "inconsistent":
        value = replace(value, fills=({**value.fills[0], "decision_id": "ad1"},))
    elif kind == "missing_account":
        value = replace(value, account_daily=value.account_daily[:1])
    else:
        value = replace(value, content_hash="0" * 64)
    same = compare_ledgers(LedgerComparisonRequest(value, value, Mode.ECONOMIC))
    assert same.status is Status.INVALID
    assert same == compare_ledgers(
        LedgerComparisonRequest(value, deepcopy(value), Mode.ECONOMIC)
    )


@pytest.mark.risk_cases('SE-31-C02')
def test_repeated_comparison_validates_current_evidence_contents():
    evidence = _evidence()
    first = compare_ledgers(LedgerComparisonRequest(evidence, evidence, Mode.ECONOMIC))
    evidence.metrics["return"] = .2
    changed = compare_ledgers(LedgerComparisonRequest(evidence, evidence, Mode.ECONOMIC))
    assert changed.status is Status.EQUIVALENT
    assert changed.left_hash == changed.right_hash == hash_replay_evidence(evidence)
    assert changed.left_hash != first.left_hash
    assert changed.economic_sha256 != first.economic_sha256
    evidence.fills[0]["order_id"] = "missing"
    assert compare_ledgers(LedgerComparisonRequest(evidence, evidence)).status is Status.INVALID


@pytest.mark.risk_cases('SE-30-C03')
def test_explicit_tolerance_and_business_field_differences():
    left = _evidence()
    right = replace(left, fills=({**left.fills[0], "fees": 0.10001}, left.fills[1]))
    assert compare_ledgers(LedgerComparisonRequest(left, right)).status is Status.DIFFERENT
    assert (
        compare_ledgers(LedgerComparisonRequest(left, right, tolerance=0.001)).status
        is Status.EQUIVALENT
    )
    assert compare_ledgers(LedgerComparisonRequest(left, right, Mode.ECONOMIC, .001)).economic_sha256 is None
    extra = replace(left, fills=({**left.fills[0], "hidden_fee": 2}, left.fills[1]))
    assert (
        compare_ledgers(LedgerComparisonRequest(left, extra, Mode.ECONOMIC)).status
        is Status.DIFFERENT
    )
    bound = replace(left, content_hash=hash_replay_evidence(left))
    assert compare_ledgers(LedgerComparisonRequest(bound, left)).status is Status.EQUIVALENT
