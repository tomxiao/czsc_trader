"""Pure comparison regressions; never load market inputs or execute accounts."""

from copy import deepcopy
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys

import pandas as pd
import pytest

from dataflows import Dataset


SCRIPT = Path(__file__).resolve().parents[1] / "src/verify_frozen_market.py"
SPEC = importlib.util.spec_from_file_location("verify_frozen_market_pure", SCRIPT)
DRIVER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DRIVER
SPEC.loader.exec_module(DRIVER)


@dataclass
class Ledger:
    decisions: pd.DataFrame
    orders: pd.DataFrame
    fills: pd.DataFrame
    account_daily: pd.DataFrame
    trades: pd.DataFrame


def result(prefix):
    return Ledger(
        decisions=pd.DataFrame({"decision_id": [prefix + "D"], "target_position": [1.]}),
        orders=pd.DataFrame({"decision_id": [prefix + "D"], "order_id": [prefix + "O"],
                             "cycle_id": [prefix + "C"], "quantity": [100]}),
        fills=pd.DataFrame({"decision_id": [prefix + "D"], "order_id": [prefix + "O"],
                            "fill_id": [prefix + "F"], "cycle_id": [prefix + "C"], "price": [10.]}),
        account_daily=pd.DataFrame({"cash": [89999.], "quantity": [100], "equity": [99999.]}),
        trades=pd.DataFrame({"cycle_id": [prefix + "C"], "net_return": [0.]}),
    )


def test_linked_identity_changes_preserve_economic_equality():
    checked = DRIVER.compare_ledgers(result("old"), result("new"))
    assert len(checked["checks"]) == 5
    assert checked["identity_bijections"] == {
        "decision_id": 1, "order_id": 1, "cycle_id": 1, "fill_id": 1
    }


def test_cross_ledger_dangling_identity_fails():
    new = result("new")
    new.fills.loc[0, "cycle_id"] = "unexpected-cycle"
    with pytest.raises(AssertionError, match="linkage"):
        DRIVER.compare_ledgers(result("old"), new)


def test_tiny_economic_difference_fails_with_no_tolerance():
    new = result("new")
    new.fills.loc[0, "price"] = 10. + 1e-12
    with pytest.raises(AssertionError, match="price"):
        DRIVER.compare_ledgers(result("old"), new)


def test_missing_value_and_coverage_differences_fail():
    left = pd.DataFrame({"state": [float("nan"), 1.]})
    DRIVER.assert_frame_exact(left, left.copy(), name="missing")
    right = left.copy()
    right.loc[0, "state"] = 0.
    with pytest.raises(AssertionError, match="missing"):
        DRIVER.assert_frame_exact(left, right, name="missing")
    with pytest.raises(AssertionError, match="row count"):
        DRIVER.assert_frame_exact(left, left.iloc[:1], name="coverage")


def test_plan_comparison_ignores_only_content_identity_fields():
    old = {"strategy": {"reference": "old"}, "signal_identity": "s1", "plan_identity": "p1",
           "orders": [{"quantity": 600, "limit_price": "10.00"}],
           "actual_quantity": 200, "cycle_target_quantity": 600,
           "input_identities": {"market": "a" * 64}, "price_identities": {"raw": "b" * 64}}
    new = deepcopy(old)
    new.update(strategy={"reference": "new"}, signal_identity="s2", plan_identity="p2")
    DRIVER.compare_plans(old, new)
    new["orders"][0]["quantity"] = 500
    with pytest.raises(AssertionError, match="orders"):
        DRIVER.compare_plans(old, new)


def test_evidence_normalization_keeps_source_hash_and_path():
    class Plan:
        def __init__(self, root):
            self.root = root

        def to_dict(self):
            return {"requests": {"seed": {"parameter_type": "EvidenceParameters",
                "parameters": {"repository_root": self.root, "source_path": "evidence/seed.csv",
                               "source_sha256": "c" * 64}}}}

    assert DRIVER.comparable_requests(Plan("old")) == DRIVER.comparable_requests(Plan("new"))
    altered = DRIVER.comparable_requests(Plan("new"))
    altered["seed"]["parameters"]["source_sha256"] = "d" * 64
    assert altered != DRIVER.comparable_requests(Plan("old"))


def test_raw_execution_request_accepts_daily_and_intraday_but_refuses_adjusted():
    for dataset, frequency in ((Dataset.ETF_UNADJUSTED_DAILY, "daily"),
                               (Dataset.ETF_UNADJUSTED_INTRADAY, "30m"),
                               (Dataset.ETF_UNADJUSTED_INTRADAY, "5m")):
        actual = DRIVER.execution_request({"dataset": dataset.value, "symbol": "588080.SH",
            "start": "2026-06-01", "end": "2026-06-30", "required_cutoff": "2026-06-30",
            "frequency": frequency})
        assert actual.dataset is dataset
        assert actual.frequency == frequency
    with pytest.raises(ValueError, match="raw ETF"):
        DRIVER.execution_request({"dataset": Dataset.ETF_OHLCV.value, "symbol": "588080.SH",
            "start": "2026-06-01", "end": "2026-06-30", "required_cutoff": "2026-06-30"})


def test_execution_quote_name_enforces_dataset_and_frequency():
    raw = {"dataset": Dataset.ETF_UNADJUSTED_INTRADAY.value, "symbol": "588080.SH",
           "start": "2026-06-01", "end": "2026-06-30", "required_cutoff": "2026-06-30",
           "frequency": "30m"}
    DRIVER.execution_request(raw, name="intraday")
    with pytest.raises(ValueError, match="five_minute requires"):
        DRIVER.execution_request(raw, name="five_minute")
    with pytest.raises(ValueError, match="daily requires"):
        DRIVER.execution_request(raw, name="daily")


def test_overlay_invalid_partial_core_is_boundary_not_positive_success():
    assert DRIVER.probe_coverage("INTRADAY_OVERLAY", {600: 2, 200: 0}, 3, 3)
    assert not DRIVER.probe_coverage("INTRADAY_OVERLAY", {600: 0, 200: 0}, 3, 3)
    assert not DRIVER.probe_coverage("INTRADAY_OVERLAY", {600: 2, 200: 0}, 2, 3)
    assert not DRIVER.probe_coverage("FROZEN_RULE", {600: 2, 200: 0}, 3, 3)
    assert DRIVER.probe_coverage("FROZEN_RULE", {600: 2, 200: 1}, 0, 3)
