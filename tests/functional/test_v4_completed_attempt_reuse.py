"""A confirmed partial attempt is not rearmed by reevaluating its V4 input."""
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal

import pytest

from dataflows import TimeInterval
from execution_channels.futu.broker import BrokerOrder
from execution_channels.futu.order_reports import apply_order_report
from paper_trading_engine.account_engine import AccountEngine
from test_formal_v4_runtime import formal_v4 as formal_v4


def test_formal_partial_attempt_same_input_is_reused_but_next_interval_advances(formal_v4, monkeypatch):
    client, store, _, interval, candidate, _ = formal_v4
    clock = [interval.start]
    prepared = client.prepare_interval('formal', interval, observed_at=clock[0])
    proposals = []
    get_decision = client.get_decision

    def capture_real_proposal(*args, **kwargs):
        result = get_decision(*args, **kwargs)
        proposals.append(result)
        return result

    monkeypatch.setattr(client, 'get_decision', capture_real_proposal)
    accounts = AccountEngine(store, client, now=lambda: clock[0])
    accounts.refresh_account('formal', prepared=prepared)
    original, = store.account_decisions('formal')
    intent, = store.account_intents('formal')
    store.set_setting('channel_reconciliation_status', 'OK')
    store.set_setting('futu_cash_reconciliation_status', 'OK')
    assert store.claim_account_intent(intent['intent_id'], moment=interval.start)
    order = BrokerOrder('partial-v4', candidate.instrument.symbol, 'BUY', intent['quantity'],
        float(intent['limit_price']), 'SUBMITTED', 0, 0., intent['intent_id'])
    store.bind_channel_order(intent['intent_id'], order.channel_order_id, asdict(order))
    count = candidate.definition.execution_spec.quantity_step
    assert 0 < count < intent['quantity']
    # A confirmed exchange expiry at the prepared deadline needs no invented cancel request.
    report = dict(asdict(order), status='CANCELLED_PART', cumulative_filled_quantity=count,
        average_fill_price=10., cumulative_notional=Decimal(10 * count), updated_at=interval.end.isoformat())
    apply_order_report(store, report, occurred_at=interval.end.isoformat())
    ended = store.account_decision('formal', original['decision_id'])
    assert (ended['status'], ended['state_reason']) == ('INCOMPLETE', 'NORMAL_PARTIAL')
    before = store.virtual_account('formal')
    fills = store.account_fills('formal')
    assert before['health'] == 'OK' and before['quantity'] == count
    assert Decimal(before['frozen_cash']) == 0 and len(fills) == 1
    clock[0] = interval.end

    accounts.refresh_account('formal', prepared=prepared)
    accounts.refresh_account('formal', prepared=prepared)
    # Confirmed fills happened after this decision point: a repeated read must
    # reuse the terminal attempt before asking SRT to recalculate the past.
    assert len(proposals) == 1
    assert store.virtual_account('formal') == before
    assert store.account_fills('formal') == fills
    assert len(store.account_decisions('formal')) == len(store.account_intents('formal')) == 1
    assert store.account_decision('formal', original['decision_id']) == ended

    last_row = prepared.history.index[-1]
    original_close = prepared.history.loc[last_row, 'Close']
    try:
        prepared.history.loc[last_row, 'Close'] = original_close + 1
        with pytest.raises(ValueError, match='history changed after authentication'):
            accounts.refresh_account('formal', prepared=prepared)
    finally:
        prepared.history.loc[last_row, 'Close'] = original_close
    assert len(proposals) == 1
    assert store.virtual_account('formal') == before
    assert len(store.account_decisions('formal')) == len(store.account_intents('formal')) == 1

    following = TimeInterval(interval.start + timedelta(days=1), interval.end + timedelta(days=1))
    clock[0] = following.start
    next_prepared = client.prepare_interval('formal', following, observed_at=clock[0])
    accounts.refresh_account('formal', prepared=next_prepared)
    assert len(proposals) == 2
    latest = store.virtual_account('formal')['last_decision_id']
    assert latest != original['decision_id']
    next_record = store.account_decision('formal', latest)
    assert next_record['payload']['equity_execution_interval']['start'] == following.start.isoformat()
    assert next_record['status'] == 'PENDING'
    assert len(store.account_intents('formal')) == 2
    assert store.account_fills('formal') == fills
    assert store.virtual_account('formal')['quantity'] == count
    assert store.virtual_account('formal')['health'] == 'OK'
    assert store.account_invariant_violations() == []
