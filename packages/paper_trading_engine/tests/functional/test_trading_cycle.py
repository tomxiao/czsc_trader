from dataclasses import replace
from datetime import date, time
from time import monotonic, sleep
from types import SimpleNamespace
import pytest

from execution_channels.futu.lifecycle import AccountHealth
from paper_trading_engine.account_engine import (
    AccountDecisionBlockedError,
    AccountEngine,
    ActiveOrderPendingError,
)
from paper_trading_engine.account_strategy_cycle import AccountStrategyCycle
from execution_channels.futu.broker import TERMINAL_INTENT_STATUSES
from paper_trading_engine.coordinator import PteCoordinator
from paper_trading_engine.contracts import AdviceDecision, OrderSpec, PlanLegSpec
from pte_support import FakeAdvice, decision, preparation, claim_test_intent


def _wait_until(predicate, timeout=2.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.01)
    assert predicate()


def _operator_coordinator(accounts, store):
    class Preparer:
        @staticmethod
        def latest_completed_signal_date(at):
            del at
            return date(2026, 9, 1)

        @staticmethod
        def prepare(account, *, signal_date):
            del account
            return SimpleNamespace(
                available_through=signal_date,
                data_identity="c" * 64,
                data_reference={"space_id": "11111111-1111-1111-1111-111111111111",
                                "preparation_id": "22222222-2222-2222-2222-222222222222",
                                "manifest_sha256": "a" * 64},
                tradable_window=SimpleNamespace(
                    start=date(2026, 9, 2), end=date(2026, 9, 2)
                ),
            )

    cycle = AccountStrategyCycle(accounts, Preparer(), store)
    return PteCoordinator(accounts, object(), strategy_cycle=cycle)


# Independent risk: EC17; responsibility-level assertions.


# Independent risk: EC17; responsibility-level assertions.


def intraday_setup_decision(strategy: dict[str, str]) -> AdviceDecision:
    return AdviceDecision(
        contract_version="advice.v5", decision_id="DEC-CORE-SETUP",
        symbol="510500.SH", signal_date=date(2026, 9, 1),
        valid_session=date(2026, 9, 2), actual_quantity=0,
        target_quantity=1000, cycle_target_quantity=1000, delta_quantity=1000,
        action="BUY", strategy=strategy, signal_reference_price=1.70,
        execution_reference_price=1.70, data_cutoff=date(2026, 9, 1),
        order=None, signal_identity="1" * 64, plan_identity="2" * 64,
        portfolio_revision=0, state_revision=0, orders=(),
        available_cash=100_000, fee_rate=0.0005,
        plan_mode="CORE_SETUP",
        plan_legs=(PlanLegSpec(
            0, "CORE_SETUP", "OPEN", time(9, 30), time(9, 35),
            None, None, OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY"),
        ),),
    )


# Independent risk: PTE09; responsibility-level assertions.
def test_PTE09_C01_operator_can_drive_one_account_decision_with_explicit_result_and_audit(memory_store):
    store = memory_store()
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    advice = FakeAdvice(decision())
    accounts = AccountEngine(store, advice)
    coordinator = _operator_coordinator(accounts, store)

    first = coordinator.drive_virtual_account_decision("s001-v1")
    store.set_setting("last_data_prepare_date", "2026-09-01")
    repeated = coordinator.drive_virtual_account_decision("s001-v1")

    assert first == {
        "status": "DECISION_COMPLETED", "account_id": "s001-v1",
        "decision_id": first["decision_id"], "signal_date": "2026-09-01",
        "valid_session": "2026-09-02", "action": "WAIT",
        "target_quantity": 0, "execution_reference_price": 1.68,
        "reused_decision": False,
    }
    assert repeated["decision_id"] == first["decision_id"]
    assert repeated["status"] == "DECISION_REUSED"
    assert repeated["reused_decision"] is True
    assert len(advice.calls) == 2
    advice.value = replace(
        decision(), decision_id="DEC-TWO", source_decision_id="DEC-TWO",
        signal_identity="7" * 64,
    )
    superseded = coordinator.drive_virtual_account_decision("s001-v1")
    assert superseded["status"] == "DECISION_COMPLETED"
    assert superseded["reused_decision"] is False
    decisions = store.account_decisions("s001-v1")
    assert {row["decision_id"]: row["status"] for row in decisions} == {
        first["decision_id"]: "COMPLETED",
        superseded["decision_id"]: "COMPLETED",
    }
    events = store.query_audit_events(
        event_type="ACCOUNT_DECISION_DRIVEN", account_id="s001-v1",
    )
    assert len(events) == 3
    assert all(row["actor_type"] == "OPERATOR" for row in events)
    store.set_virtual_health("s001-v1", AccountHealth.BLOCKED, "等待人工处理")
    with pytest.raises(AccountDecisionBlockedError, match="已阻塞"):
        coordinator.drive_virtual_account_decision("s001-v1")
    failed = store.query_audit_events(
        event_type="ACCOUNT_DECISION_DRIVE_FAILED", account_id="s001-v1",
    )
    assert len(failed) == 1
    assert failed[0]["outcome"] == "FAILURE"
    assert failed[0]["details"]["error_type"] == "AccountDecisionBlockedError"
    store.set_virtual_paused("s001-v1", True)
    previous_calls = len(advice.calls)
    with pytest.raises(RuntimeError, match="running account"):
        coordinator.drive_virtual_account_decision("s001-v1")
    assert len(advice.calls) == previous_calls
    store.close()


# Independent risk: PTE09; responsibility-level assertions.
def test_PTE09_C02_operator_supersedes_unsubmitted_intents_and_releases_reservations(memory_store):
    store = memory_store()
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    advice = FakeAdvice(decision(OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY")))
    coordinator = _operator_coordinator(AccountEngine(store, advice), store)
    first = coordinator.drive_virtual_account_decision("s001-v1")
    old_intent = store.account_intents("s001-v1")[0]
    assert store.virtual_account("s001-v1")["frozen_cash"] != "0.0000"

    advice.value = replace(
        decision(OrderSpec("BUY", 2000, "LIMIT", 1.67, "DAY")),
        decision_id="DEC-TWO", source_decision_id="DEC-TWO",
    )
    result = coordinator.drive_virtual_account_decision("s001-v1")

    assert result["status"] == "DECISION_AND_INTENTS_SUPERSEDED"
    assert advice.calls[-1][1] == pytest.approx(100_000)
    assert result["superseded_decision_id"] == first["decision_id"]
    assert result["superseded_intent_ids"] == [old_intent["intent_id"]]
    assert store.account_intent(old_intent["intent_id"])["status"] == "SUPERSEDED"
    current_intents = [
        row for row in store.account_intents("s001-v1")
        if row["status"] not in TERMINAL_INTENT_STATUSES
    ]
    assert len(current_intents) == 1
    assert current_intents[0]["decision_id"] == result["decision_id"]
    assert current_intents[0]["quantity"] == 2000
    account = store.virtual_account("s001-v1")
    assert float(account["cash"]) + float(account["frozen_cash"]) == pytest.approx(100_000)
    assert float(account["frozen_cash"]) == pytest.approx(3341.67)
    assert len(store.query_audit_events(event_type="DECISION_SUPERSEDED")) == 1
    assert len(store.query_audit_events(event_type="ORDER_INTENT_SUPERSEDED")) == 1
    store.close()


# Independent risk: PTE09; responsibility-level assertions.
def test_PTE09_C03_operator_supersession_calculation_failure_preserves_old_reservation(memory_store):
    store = memory_store()
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    advice = FakeAdvice(decision(OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY")))
    accounts = AccountEngine(store, advice)
    accounts.drive_account_decision(
        "s001-v1", prepared=preparation(advice.value)
    )
    old_intent = store.account_intents("s001-v1")[0]
    before = store.virtual_account("s001-v1")

    class FailingAdvice:
        def get_decision(self, *_args, **_kwargs):
            raise RuntimeError("simulated calculation failure")

    accounts.advice = FailingAdvice()
    with pytest.raises(RuntimeError, match="simulated calculation failure"):
        accounts.drive_account_decision(
            "s001-v1", prepared=preparation(advice.value)
        )

    after = store.virtual_account("s001-v1")
    assert after["cash"] == before["cash"]
    assert after["frozen_cash"] == before["frozen_cash"]
    assert store.account_intent(old_intent["intent_id"])["status"] == "PENDING_SUBMIT"
    assert len(store.account_decisions("s001-v1")) == 1
    store.close()


# Independent risk: PTE09; responsibility-level assertions.
def test_PTE09_C04_operator_supersession_rejects_intent_claimed_during_calculation(new_store, tmp_path):
    store = new_store(tmp_path / "supersession-concurrent-claim.db")
    store.create_virtual_account(
        "s001-v1", "S001-v1模拟账户", "legacy", "a" * 64, 100_000,
        strategy_id="S001", strategy_name_snapshot="综合基线策略",
        strategy_version="v1", release_hash="b" * 64,
        qualification_snapshot="PAPER_READY", selection_data_cutoff="2026-09-01",
    )
    store.set_virtual_paused("s001-v1", False)
    advice = FakeAdvice(decision(OrderSpec("BUY", 1000, "LIMIT", 1.68, "DAY")))
    accounts = AccountEngine(store, advice)
    accounts.drive_account_decision(
        "s001-v1", prepared=preparation(advice.value)
    )
    old_intent = store.account_intents("s001-v1")[0]

    class ClaimingAdvice(FakeAdvice):
        def get_decision(self, *args, **kwargs):
            value = super().get_decision(*args, **kwargs)
            assert claim_test_intent(store, old_intent["intent_id"])
            return value

    accounts.advice = ClaimingAdvice(replace(
        decision(OrderSpec("BUY", 2000, "LIMIT", 1.67, "DAY")),
        decision_id="DEC-TWO", source_decision_id="DEC-TWO",
    ))
    with pytest.raises(ActiveOrderPendingError, match="状态已变化"):
        accounts.drive_account_decision(
            "s001-v1", prepared=preparation(accounts.advice.value)
        )

    assert store.account_intent(old_intent["intent_id"])["status"] == "SUBMITTING"
    assert len(store.account_decisions("s001-v1")) == 1
    store.close()


# Independent risk: EC17; responsibility-level assertions.
