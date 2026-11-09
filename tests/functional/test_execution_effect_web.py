"""Formal CN/US account snapshots expose EC effects without valuing accounts in PTE."""
from types import SimpleNamespace
import pytest
from dataflows import MarketId

from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.web_api import PteWebApi
from test_formal_v4_runtime import formal_v4 as formal_v4


def snapshot_api(store, engine):
    return PteWebApi(SimpleNamespace(store=store, virtual=engine, channel=None))


@pytest.mark.parametrize('formal_v4', [MarketId.US], indirect=True, ids=['PTE14-C02'])
def test_formal_blocked_snapshot_is_not_no_order_success(formal_v4, monkeypatch):
    client, store, _, interval, _, evaluation = formal_v4
    store.migrate_pristine_virtual_account_capital('formal',
        expected_initial_cash=str(evaluation.initial_cash), new_initial_cash='1')
    prepared = client.prepare_interval('formal', interval, observed_at=interval.start)
    engine = AccountEngine(store, client, now=lambda: interval.start)
    engine.refresh_account('formal', prepared=prepared)
    # Identical retained no-order decisions are idempotent; no terminal order is reopened.
    engine.refresh_account('formal', prepared=prepared)
    monkeypatch.setattr('paper_trading_engine.web_api._now', lambda: interval.start.isoformat())
    api = snapshot_api(store, engine)
    snapshot = api.virtual_account_snapshot('formal')
    decision = snapshot['decision']
    effect = decision['execution_effect']
    assert snapshot['account']['health'] == 'OK'
    assert decision['status'] == 'INCOMPLETE' and decision['state_reason'] == 'PLANNING_BLOCKED'
    assert effect['availability'] == 'AVAILABLE' and effect['status'] == 'NOT_EXECUTED'
    assert effect['planning_status'] == 'BLOCKED' and effect['constraint_reasons']
    assert effect['actual_quantity'] == 0 and effect['orders'] == []
    # Missing retained evidence has an explicit unavailable result, never guessed weights.
    from paper_trading_engine.web_api import _decision_execution_effect
    missing = dict(decision, strategy_output=None)
    unavailable = _decision_execution_effect(store, 'formal', missing, interval.start)
    assert unavailable['availability'] == 'UNAVAILABLE'
    assert unavailable['reason'] == 'MISSING_PLANNING_EVIDENCE'
    assert 'actual_weight' not in unavailable
    missing_reference = dict(decision, execution_reference_price=None)
    unavailable = _decision_execution_effect(store, 'formal', missing_reference, interval.start)
    assert unavailable['reason'] == 'MISSING_EXECUTION_REFERENCE'
