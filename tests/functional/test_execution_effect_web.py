"""Formal CN/US account snapshots expose EC effects without valuing accounts in PTE."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from execution_channels.futu.broker import BrokerOrder
from execution_channels.futu.lifecycle import IntentControlState
from execution_channels.futu.order_reports import apply_order_report
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.web_api import PteWebApi
from test_formal_v4_runtime import formal_v4 as formal_v4


def snapshot_api(store, engine):
    return PteWebApi(SimpleNamespace(store=store, virtual=engine, channel=None))


def test_formal_snapshot_pending_unknown_partial_and_valuation(formal_v4, monkeypatch):
    client, store, _, interval, candidate, _ = formal_v4
    before = interval.start
    prepared = client.prepare_interval('formal', interval, observed_at=before)
    engine = AccountEngine(store, client, now=lambda: before)
    engine.refresh_account('formal', prepared=prepared)
    api = snapshot_api(store, engine)
    monkeypatch.setattr('paper_trading_engine.web_api._now', lambda: before.isoformat())
    snapshot = api.virtual_account_snapshot('formal')
    decision = snapshot['decision']
    effect = decision['execution_effect']
    assert effect['availability'] == 'AVAILABLE'
    assert effect['scope'] == 'CURRENT_ACCOUNT_VS_DECISION'
    assert effect['status'] == 'WAITING' and not effect['terminal']
    assert effect['actual_weight'] == 0 and effect['target_weight'] == 1
    assert effect['valuation_source'] == 'DECISION_EXECUTION_REFERENCE'
    assert effect['price_basis'] == 'RAW'
    assert effect['valuation_price'] == str(decision['execution_reference_price'])
    assert effect['valuation_at'] == decision['equity_observed_through']
    assert effect['as_of'] == snapshot['as_of'] == before.isoformat()
    intent, = store.account_intents('formal')
    store.set_setting('channel_reconciliation_status', 'OK')
    store.set_setting('futu_cash_reconciliation_status', 'OK')
    assert store.claim_account_intent(intent['intent_id'], moment=interval.start)
    store.update_account_intent_status(intent['intent_id'], IntentControlState.SUBMISSION_UNCERTAIN)
    assert api.virtual_account_snapshot('formal')['decision']['execution_effect']['status'] == 'UNKNOWN'
    order = BrokerOrder('effect-fill', candidate.instrument.symbol, 'BUY', intent['quantity'],
                        float(intent['limit_price']), 'SUBMITTED', 0, 0., intent['intent_id'])
    store.bind_channel_order(intent['intent_id'], order.channel_order_id, asdict(order))
    count = candidate.definition.execution_spec.quantity_step
    apply_order_report(store, dict(asdict(order), status='FILLED_PART', cumulative_filled_quantity=count,
                                  average_fill_price=10.), occurred_at=(interval.start + timedelta(minutes=1)).isoformat())
    current = datetime.now(timezone.utc) + timedelta(seconds=1)
    monkeypatch.setattr('paper_trading_engine.web_api._now', lambda: current.isoformat())
    effect = api.virtual_account_snapshot('formal')['decision']['execution_effect']
    assert effect['availability'] == 'AVAILABLE' and effect['status'] == 'PARTIAL'
    assert effect['actual_quantity'] == count and effect['actual_weight'] > 0
    assert effect['weight_deviation'] == effect['actual_weight'] - effect['target_weight']
    assert effect['orders'][0]['filled_quantity'] == count
    assert effect['valuation_at'] == decision['equity_observed_through']


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
