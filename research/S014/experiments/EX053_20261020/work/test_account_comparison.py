"""Check exact comparison and cross-ledger identity linkage failure semantics."""

from copy import deepcopy

import pytest

from compare_full_account import compare


def minimal_results():
    signal = {"decision_id": "old-D1", "target_position": 1,
              "signal_date": "2026-01-02", "valid_session": "2026-01-05"}
    order = {"decision_id": "old-D1", "order_id": "old-O1", "cycle_id": "old-C1",
             "quantity": 100, "status": "FILLED"}
    old = {
        "runs": [{"candidate_id": "C9521", "scenario_id": "baseline", "window_id": "full",
                  "signal_window": {"start": "2026-01-05", "end": "2026-01-05"},
                  "signals": {"data": [signal]},
                  "ledgers": {"orders": {"data": [order]}},
                  "observation": {"candidate_id": "C9521", "total_return": .1}}],
        "assessment_evidence": [{"initial_cash": 100000, "opening_cash": 100000,
                                 "opening_quantity": 0, "frequency_window_days": 60,
                                 "account": [{"cash": 99000, "quantity": 100}],
                                 "fills": [{"cycle_id": "old-C1", "price": 10.0}],
                                 "closed_cycles": []}],
    }
    new = deepcopy(old)
    new["runs"][0]["candidate_id"] = "C9522"
    new["runs"][0]["observation"]["candidate_id"] = "C9522"
    new["runs"][0]["signals"]["data"][0]["decision_id"] = "new-D1"
    new["runs"][0]["ledgers"]["orders"]["data"][0].update(
        decision_id="new-D1", order_id="new-O1", cycle_id="new-C1"
    )
    new["assessment_evidence"][0]["fills"][0]["cycle_id"] = "new-C1"
    return old, new


def test_exact_values_with_new_linked_identities_pass():
    old, new = minimal_results()
    assert compare(old, new)["status"] == "PASS_EXACT_BUSINESS_BEHAVIOR"


def test_changed_cash_fails_without_tolerance():
    old, new = minimal_results()
    new["assessment_evidence"][0]["account"][0]["cash"] += .000000001
    with pytest.raises(AssertionError, match="cash"):
        compare(old, new)


def test_changed_signal_and_dangling_linkage_fail():
    old, new = minimal_results()
    new["runs"][0]["signals"]["data"][0]["target_position"] = 0
    with pytest.raises(AssertionError, match="target_position"):
        compare(old, new)
    old, new = minimal_results()
    new["assessment_evidence"][0]["fills"][0]["cycle_id"] = "new-C2"
    with pytest.raises(AssertionError, match="bijective"):
        compare(old, new)


def test_c9523_must_be_selected_explicitly():
    old, new = minimal_results()
    new["runs"][0]["candidate_id"] = "C9523"
    new["runs"][0]["observation"]["candidate_id"] = "C9523"
    with pytest.raises(AssertionError, match="candidate identity"):
        compare(old, new)
    assert compare(old, new, expected_candidate="C9523")["status"] == "PASS_EXACT_BUSINESS_BEHAVIOR"
