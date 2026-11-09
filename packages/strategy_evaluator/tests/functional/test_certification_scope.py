"""Exact content and contract, never object identity, authorize audit reuse."""
from copy import deepcopy
import pickle

import pytest

from strategy_evaluator import equity_assessment as ea
from equity_facts_support import manual_ledger, order


@pytest.fixture
def source():
    return {**manual_ledger([dict(orders=(order("BUY", 100, 10.1),)),
                            dict(orders=(order("SELL", 100),), target=0.)]), "account_contract": 4}


@pytest.mark.risk_cases('SE-31-C03')
def test_SE_31_C03_identical_bytes_and_contract_reuse_actual_audit(source):
    with ea.EquityCertificationScope() as scope:
        first = ea.certify_equity_ledger(source)
        second = ea.certify_equity_ledger(deepcopy(source))
    assert first == second
    assert first.fees == 2.
    assert first.total_return == pytest.approx(-.0002)
    assert (scope.audit_count, scope.reused_count) == (1, 1)


@pytest.mark.risk_cases('SE-31-C04')
def test_SE_31_C04_different_contract_cannot_reuse_certificate(source, monkeypatch):
    real = ea.audit_equity_account
    calls = []
    def counted(**kwargs):
        calls.append(kwargs["decision_contract"])
        return real(**kwargs)
    monkeypatch.setattr(ea, "audit_equity_account", counted)
    with ea.EquityCertificationScope() as scope:
        ea.certify_equity_ledger(source)
        with pytest.raises(ValueError, match="FORMAL_V4"):
            ea.certify_equity_ledger(source, decision_contract="FORMAL_V3")
    assert calls == ["FORMAL_V4", "FORMAL_V3"]
    assert scope.reused_count == 0


@pytest.mark.risk_cases('SE-31-C05')
def test_SE_31_C05_changed_content_requires_new_audit(source):
    with ea.EquityCertificationScope() as scope:
        first = ea.certify_equity_ledger(source)
        source["bars"][0]["Volume"] += 1.
        assert ea.certify_equity_ledger(source) == first
        assert (scope.audit_count, scope.reused_count) == (2, 0)
        source["account_points"][0]["cash"] += 1.
        with pytest.raises(ValueError, match="cash"):
            ea.certify_equity_ledger(source)
    assert scope.reused_count == 0


@pytest.mark.risk_cases('SE-31-C06')
def test_SE_31_C06_scope_is_not_persistable_authority():
    with pytest.raises(TypeError, match="cannot cross"):
        pickle.dumps(ea.EquityCertificationScope())
