"""Technical inputs cannot conceal identity changes or tolerate discrete facts."""
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from dataflows import DataRequest, Dataset, EvidenceParameters
from strategy_runtime import ExecutionPolicy, TradableWindow
from strategy_runtime.input_binding import _request_dict
from czsc_trader.application.inspection_inputs import portable_value, _provider_request_key
from czsc_trader.application.inspection_replay import (
    _run, _signal_difference, _signal_snapshot, technical_ledger_differences,
)


def evidence(**fields):
    return {"strategy_hash": "a" * 64, "content_hash": "", "data_hash": "b" * 64,
            "initial_cash": 10000., "execution_spec": {}, "evaluation_sessions": ["2026-10-21"],
            "decisions": [], "orders": [], "fills": [], "account_daily": [], "trades": [],
            "metrics": {}, "execution_daily": [], "execution_intraday": [], **fields}


@pytest.mark.parametrize("field", ["quantity", "quantity_before", "size", "holding_days", "target_position"])
def test_economic_tolerance_never_applies_to_discrete_or_target_fields(field):
    left = evidence(account_daily=[{field: 100}])
    right = evidence(account_daily=[{field: 101}])
    differences = technical_ledger_differences(left, right, tolerance=10.)
    assert differences == [{"path": f"replay.account_daily[0].{field}", "left": 100,
                            "right": 101, "tolerance": 0, "reason": "VALUE_DIFFERS"}]


def test_continuous_tolerance_is_output_only_and_retains_all_differences():
    left = evidence(account_daily=[{"cash": 100.}])
    right = evidence(account_daily=[{"cash": 100.01}])
    assert not technical_ledger_differences(left, right, .02)
    right["initial_cash"] = 10000.01
    assert technical_ledger_differences(left, right, .02)[0]["path"] == "replay.initial_cash"
    left = evidence(account_daily=[{"quantity": 100}] * 35)
    right = evidence(account_daily=[{"quantity": 101}] * 35)
    assert len(technical_ledger_differences(left, right, 100)) == 35


def test_only_runtime_identities_are_normalized():
    left = evidence(decisions=[{"decision_id": "left", "side": "BUY"}],
                    orders=[{"decision_id": "left", "order_id": "o1", "cycle_id": "c1", "quantity": 100}])
    right = evidence(strategy_hash="c" * 64, decisions=[{"decision_id": "right", "side": "BUY"}],
                     orders=[{"decision_id": "right", "order_id": "o2", "cycle_id": "c2", "quantity": 100}])
    assert not technical_ledger_differences(left, right, 0)
    right["decisions"][0]["side"] = "SELL"
    assert technical_ledger_differences(left, right, 100)


def test_portable_request_only_normalizes_declared_physical_root(tmp_path):
    request = DataRequest(Dataset.STRATEGY_FEATURE_EVIDENCE, "588080.SH", "2026-10-20", "2026-10-21",
                          "2026-10-21", parameters=EvidenceParameters(tmp_path, "seed.json", "a" * 64))
    raw = _request_dict(request)
    value = portable_value({"binding": {"requests": {"seed": raw}}, "ordinary": {"repository_root": "keep"}})
    assert value["binding"]["requests"]["seed"]["parameters"] == {
        "repository_root": "$REPOSITORY", "source_path": "seed.json", "source_sha256": "a" * 64}
    assert value["ordinary"] == {"repository_root": "keep"}
    assert raw["parameters"]["repository_root"] == str(tmp_path)


def test_offline_provider_matches_source_selection_without_removing_asset_identity():
    request = DataRequest(Dataset.ETF_SHARE_SIZE, "588080.SH", "2026-10-20", "2026-10-21", "2026-10-21")
    assert _provider_request_key(request) == _provider_request_key(replace(request, required_cutoff=None))
    for changed in (replace(request, symbol="510500.SH"), replace(request, end="2026-10-22"),
                    replace(request, dataset=Dataset.ETF_OHLCV)):
        assert _provider_request_key(request) != _provider_request_key(changed)


def test_signal_values_and_serialized_signal_facts_preserve_exact_levels():
    left = pd.DataFrame({"target_position": [0.5, 1.0]}, index=pd.to_datetime(["2026-10-20", "2026-10-21"]))
    right = left.copy()
    right.iloc[0, 0] = .5000000001
    assert _signal_difference(left, right)
    assert _signal_snapshot(left) != _signal_snapshot(right)
    assert _signal_snapshot(left)["index"] == ["2026-10-20T00:00:00", "2026-10-21T00:00:00"]


def test_candidate_replay_passes_original_binding_to_authentication(tmp_path):
    original = SimpleNamespace(plan=SimpleNamespace(tradable_window=TradableWindow(date(2026, 10, 20), date(2026, 10, 21))))
    replay = SimpleNamespace(input_binding=original, one_way_cost=.001,
                             execution_data=SimpleNamespace(pricing=None))
    class StopAtAuthentication(Exception):
        pass
    class Instance:
        identity = "different candidate identity"
        def prepare_data(self, *, binding):
            assert binding is original
            raise StopAtAuthentication()
    class Runtime:
        def describe(self, *args, **kwargs):
            return SimpleNamespace(execution=ExecutionPolicy("FROZEN_RULE", {"capital": {}}))
        def create(self, request):
            return Instance()
    # StrategyInit validates pricing before the fake instance receives the binding.
    from strategy_runtime import ExecutionPricing
    replay.execution_data.pricing = ExecutionPricing()
    with pytest.raises(StopAtAuthentication):
        _run(Runtime(), object(), replay, Path(tmp_path))
