from dataclasses import replace
from datetime import date
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import sys

import pandas as pd
import pytest
from dataflows import (
    Dataflows,
    DataSpace,
    Dataset,
    DataRequest,
    EvidenceParameters,
    ProviderBinding,
    ProviderConfig,
    PreparePolicy,
)
from dataflows.local_strategy_data import fetch_strategy_feature_evidence
from strategy_runtime import (
    CalculationScope,
    CutoffRule,
    InputContract,
    InputRequirement,
    RuntimeContractError,
    StrategyIdentity,
    StrategyInputBinding,
    TradableWindow,
)
from strategy_runtime.preparation import acquire_binding, prepare_inputs


def test_hash_pinned_evidence_can_move_with_release_without_refetch(tmp_path, monkeypatch):
    source_root = tmp_path / "candidate"
    source_root.mkdir()
    data = b"Date,Feature\n2026-01-01,1.25\n"
    (source_root / "evidence.csv").write_bytes(data)
    source = {
        "package": "strategy_runtime",
        "path": "evidence.csv",
        "sha256": sha256(data).hexdigest(),
    }
    module = SimpleNamespace(__file__=str(source_root / "strategies" / "fixture.py"))
    monkeypatch.setitem(sys.modules, "srt_binding_evidence_fixture", module)
    first, second = date(2026, 1, 1), date(2026, 1, 2)
    window = TradableWindow(second, second)
    definition = SimpleNamespace(
        tradable_symbol="588080.SH",
        parameters=SimpleNamespace(values={"rule": {"data_source": source}}),
        implementation=SimpleNamespace(module="srt_binding_evidence_fixture"),
        inputs=InputContract(
            (
                InputRequirement(
                    "calendar",
                    Dataset.TRADING_CALENDAR.value,
                    "SSE",
                    "daily",
                    0,
                    CutoffRule.LATEST_AVAILABLE,
                ),
                InputRequirement(
                    "feature",
                    Dataset.STRATEGY_FEATURE_EVIDENCE.value,
                    "feature",
                    "daily",
                    1,
                    CutoffRule.SIGNAL_SESSION,
                ),
            )
        ),
    )
    algorithm = SimpleNamespace(
        definition=definition,
        calendar_request=lambda _: DataRequest(
            Dataset.TRADING_CALENDAR,
            "SSE",
            first.isoformat(),
            second.isoformat(),
            second.isoformat(),
        ),
        derive_calculation_scope=lambda _, dates: CalculationScope(
            window,
            (second,),
            {second: first},
            (first,),
            {
                "feature": DataRequest(
                    Dataset.STRATEGY_FEATURE_EVIDENCE,
                    "feature",
                    first.isoformat(),
                    first.isoformat(),
                    first.isoformat(),
                    parameters=EvidenceParameters(
                        Path(module.__file__).parent.parent, source["path"], source["sha256"]
                    ),
                )
            },
        ),
    )
    strategy = StrategyIdentity("S900", "S900-C0001", "a" * 64, "b" * 64, "588080.SH")
    flows = Dataflows(
        base_dir=tmp_path,
        space=DataSpace(Path("assets")),
        providers=ProviderConfig(
            {
                Dataset.TRADING_CALENDAR: ProviderBinding(
                    "test",
                    "1",
                    lambda request: (
                        pd.DataFrame(
                            {"Date": pd.date_range(request.start, request.end), "IsOpen": [1, 1]}
                        ),
                        {"vendor": "test"},
                    ),
                ),
                Dataset.STRATEGY_FEATURE_EVIDENCE: ProviderBinding(
                    "repository", "1", fetch_strategy_feature_evidence
                ),
            }
        ),
    )
    original = acquire_binding(
        strategy=strategy,
        algorithm=algorithm,
        tradable_window=window,
        dataflows=flows,
        policy=PreparePolicy.REFRESH,
    )
    release = replace(
        strategy, reference_id="S900-v1", release_hash="c" * 64, runtime_sha256="d" * 64
    )
    binding = StrategyInputBinding(replace(original.plan, strategy=release), original.prepared)
    # The materialized location deliberately does not exist: consumption uses
    # the original pinned data-space object, not the new physical source path.
    module.__file__ = str(tmp_path / "release" / "strategies" / "fixture.py")
    offline = Dataflows(
        base_dir=tmp_path, space=DataSpace(Path("assets")), providers=ProviderConfig({})
    )
    prepared = prepare_inputs(
        strategy=release,
        algorithm=algorithm,
        tradable_window=window,
        dataflows=offline,
        binding=binding,
    )
    assert prepared.results["feature"].dataframe.Feature.tolist() == [1.25]
    assert prepared.requests["feature"].parameters.repository_root == source_root
    for field, changed in (("sha256", "0" * 64), ("path", "another.csv")):
        saved = source[field]
        source[field] = changed
        with pytest.raises(RuntimeContractError, match="calculation plan differs"):
            prepare_inputs(
                strategy=release,
                algorithm=algorithm,
                tradable_window=window,
                dataflows=offline,
                binding=binding,
            )
        source[field] = saved
