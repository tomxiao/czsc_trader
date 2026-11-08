"""Online driving requires the same running-account contract as the HTTP API."""
import pytest

from paper_trading_engine.online_verify import _validate


@pytest.mark.parametrize("state", ["RUNNING", "PAUSED"])
def test_dev_decision_verification_requires_running_account(state):
    plan = {
        "release": {"mode": "DEV", "repo_root": ".tmp/isolated"},
        "channels": {"cn": {"channel_id": "futu_simulate_cn", "market": "CN", "currency": "CNY"}},
        "accounts": {"one": {
            "channel_account_id": "cn", "release_hash": "a" * 64, "run_state": state,
            "decision": {"interval": {"start": "2026-11-06T09:30:00+08:00",
                                      "end": "2026-11-06T15:00:00+08:00"},
                         "action": "WAIT", "target_quantity": 0},
        }},
    }
    _validate(plan, False)  # Read-only checks may inspect paused accounts.
    if state == "RUNNING":
        _validate(plan, True)
    else:
        with pytest.raises(ValueError, match="running V4 accounts"):
            _validate(plan, True)
