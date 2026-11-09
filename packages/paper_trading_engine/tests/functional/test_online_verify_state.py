"""Explicit online acceptance keeps driving and read-only verification distinct."""

from datetime import datetime, timezone
import pytest
from paper_trading_engine import online_verify


@pytest.fixture
def verification(monkeypatch):
    plan = {
        "release": {"mode": "DEV", "repo_root": ".tmp/isolated"},
        "channels": {"cn": {"channel_id": "futu_simulate_cn", "market": "CN", "currency": "CNY"}},
        "accounts": {
            "one": {
                "channel_account_id": "cn",
                "release_hash": "a" * 64,
                "run_state": "RUNNING",
                "decision": {
                    "interval": {
                        "start": "2026-11-06T09:30:00+08:00",
                        "end": "2026-11-06T15:00:00+08:00",
                    },
                    "action": "WAIT",
                    "target_quantity": 0,
                },
            }
        },
    }
    state = {"outcome": "DECISION_COMPLETED", "conflict": False}
    calls = []

    def request(port, path, *, post=False):
        calls.append((path, post))
        expected = plan["accounts"]["one"]
        if path == "/api/health":
            return {
                "release": plan["release"],
                "runtime": "RUNNING",
                "watchdog_healthy": True,
                "scheduler_heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "instance_id": "instance",
            }
        if path == "/api/channel-accounts/cn/snapshot":
            return {
                **plan["channels"]["cn"],
                "scope": {"channel_account_id": "cn"},
                "reconciliation_status": "OK",
                "broker_cash": 100,
                "environment": "SIMULATE",
                "alerts": [],
                "scheduler_failures": [],
            }
        if path.endswith("/decision"):
            if state["conflict"]:
                raise online_verify._HttpError(409, "no eligible interval")
            return {
                "status": state["outcome"],
                "decision_id": "D1",
                "release_hash": "a" * 64,
                "prepared_data_identity": "P1",
            }
        if path.endswith("/snapshot"):
            return {
                "scope": {"account_id": "one"},
                "account": {
                    "channel_account_id": "cn",
                    "release_hash": "a" * 64,
                    "run_state": expected["run_state"],
                    "decision_contract": "V4",
                    "health": "OK",
                },
                "decision": {
                    "decision_id": "D1",
                    "equity_execution_interval": expected.get("decision", {}).get("interval"),
                    "action": "WAIT",
                    "target_quantity": 0,
                    "strategy": {"release_hash": "a" * 64},
                    "prepared_data_identity": "P1",
                },
            }
        if "MARKET_DATA_PREPARED" in path:
            return {
                "events": [
                    {
                        "id": 1,
                        "details": {
                            "data_identity": "P1",
                            "interval": expected["decision"]["interval"],
                        },
                    }
                ]
            }
        if "DECISION_GENERATED" in path:
            return {"events": [{"id": 2, "release_hash": "a" * 64}]}
        raise AssertionError(path)

    monkeypatch.setattr(online_verify, "_request", request)
    return plan, state, calls


def test_PTE15_C01_readonly_paused_account_never_drives(verification):
    plan, _, calls = verification
    plan["accounts"]["one"]["run_state"] = "PAUSED"
    del plan["accounts"]["one"]["decision"]
    result = online_verify.verify(1, plan)
    assert result["status"] == "PASS" and result["mode"] == "READ_ONLY"
    assert not any(post for _, post in calls)


def test_PTE15_C02_driving_paused_account_rejected_before_http(verification):
    plan, _, calls = verification
    plan["accounts"]["one"]["run_state"] = "PAUSED"
    with pytest.raises(ValueError, match="running V4 accounts"):
        online_verify.verify(1, plan, drive_dev=True)
    assert calls == []


def test_PTE15_C03_driving_production_rejected_before_http(verification):
    plan, _, calls = verification
    plan["release"] = {
        "mode": "PTE",
        "release_id": "v0.7.2",
        "git_commit": "b" * 40,
        "manifest_sha256": "c" * 64,
    }
    with pytest.raises(ValueError, match="isolated DEV"):
        online_verify.verify(1, plan, drive_dev=True)
    assert calls == []


def test_PTE15_C04_fresh_expectation_rejects_reused_decision(verification):
    plan, state, calls = verification
    plan["accounts"]["one"]["decision"]["fresh"] = True
    state["outcome"] = "DECISION_REUSED"
    result = online_verify.verify(1, plan, drive_dev=True)
    assert result["status"] == "FAIL"
    failed = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert [c["check"] for c in failed] == ["account.one.drive_outcome"]
    assert sum(post for _, post in calls) == 1


def test_PTE15_C05_http_conflict_is_blocked(verification):
    plan, state, calls = verification
    state["conflict"] = True
    result = online_verify.verify(1, plan, drive_dev=True)
    assert result["status"] == "BLOCKED"
    blocked = [c for c in result["checks"] if c["status"] == "BLOCKED"]
    assert [c["check"] for c in blocked] == ["account.one.drive"]
    assert blocked[0]["actual"]["http_status"] == 409
    assert sum(post for _, post in calls) == 1
