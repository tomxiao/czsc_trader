"""EC17: immutable decisions become one atomic channel account mutation."""
import json
from decimal import Decimal
import pytest
from execution_channels.futu.adoption import AccountAdoption, DecisionAdoption
from execution_channels.futu.audit import AuditRecorder
from paper_trading_engine.contracts import OrderSpec
from pte_support import decision


@pytest.fixture
def adoption(memory_store):
    store = memory_store()
    store.create_virtual_account('strategy','strategy','v1','a'*64,100000,
        strategy_id='S001',strategy_name_snapshot='Fixture',strategy_version='v1',
        release_hash='b'*64,qualification_snapshot='PAPER_READY',selection_data_cutoff='2026-09-01')
    store.set_virtual_paused('strategy',False)
    payload = decision(OrderSpec('BUY',100,'LIMIT',1.68,'DAY')).to_store_payload()
    payload['available_cash'] = 100000
    return store,AccountAdoption(store,AuditRecorder(store)),payload


def request(payload):
    return DecisionAdoption('strategy',json.dumps(payload,default=str).encode())


def test_EC17_C01_decision_state_and_reservation_are_adopted_together(adoption):
    store,channel,payload = adoption
    result = channel.adopt(request(payload))
    assert result.account_id == 'strategy' and len(result.intent_ids) == 1
    account = store.virtual_account('strategy')
    assert account['last_decision_id'] == payload['decision_id']
    assert Decimal(account['cash']) == Decimal('99831.9160')
    assert Decimal(account['frozen_cash']) == Decimal('168.0840')
    assert store.account_decision('strategy',payload['decision_id'])['status'] == 'PENDING'
    assert len(store.account_snapshots('strategy')) == 1
    assert len(store.query_audit_events(event_type='DECISION_GENERATED')) == 1
    assert store.account_invariant_violations() == []


def test_EC17_C02_pause_after_prepare_refuses_adoption_without_mutation(adoption):
    store,channel,payload = adoption
    prepared = request(payload)
    store.set_virtual_paused('strategy',True)
    before = tuple(store._connection.iterdump())
    with pytest.raises(RuntimeError,match='RUNNING'):
        channel.adopt(prepared)
    assert tuple(store._connection.iterdump()) == before


def test_EC17_C03_second_intent_failure_rolls_back_decision_and_reservations(adoption,monkeypatch):
    store,channel,payload = adoption
    payload.update(target_quantity=200,delta_quantity=200,cycle_target_quantity=200)
    payload['orders'] = payload['orders']*2
    before = tuple(store._connection.iterdump())
    original = store._insert_audit_event
    def fail_second(event):
        if event.event_type == 'ORDER_INTENT_CREATED' and event.details['order_sequence'] == 1:
            raise RuntimeError('second intent write failed')
        return original(event)
    monkeypatch.setattr(store,'_insert_audit_event',fail_second)
    with pytest.raises(RuntimeError,match='second intent write failed'):
        channel.adopt(request(payload))
    assert tuple(store._connection.iterdump()) == before
    assert store.account_invariant_violations() == []


def test_EC17_C04_invalid_leg_window_rolls_back_before_order_creation(adoption):
    store,channel,payload = adoption
    order = payload['orders'][0]
    payload.update(orders=[],plan_legs=[dict(sequence=0,role='ENTRY',checkpoint='OPEN',
        submit_after='09:35:00',submit_before='09:30:00',dependency_sequence=None,
        dependency_required_status=None,order=order)])
    before = tuple(store._connection.iterdump())
    with pytest.raises(ValueError,match='window|time|submit'):
        channel.adopt(request(payload))
    assert tuple(store._connection.iterdump()) == before


def test_EC17_C05_foreign_release_identity_refuses_adoption(adoption):
    store,channel,payload = adoption
    payload['strategy']['release_hash'] = 'f'*64
    before = tuple(store._connection.iterdump())
    with pytest.raises(ValueError,match='strategy identity'):
        channel.adopt(request(payload))
    assert tuple(store._connection.iterdump()) == before
