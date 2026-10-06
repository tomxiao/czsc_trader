"""Candidate and frozen-release risks owned by SRT's public runtime."""

from dataclasses import replace
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import shutil
import subprocess
import sys

import pandas as pd
from pandas.testing import assert_frame_equal
import pytest
from dataflows import Dataflows, DataSpace, Dataset, ProviderBinding, ProviderConfig, PreparePolicy
from dataflows.ohlcv_quality import bind_quality_frame, build_quality_evidence, verify_daily_sessions
from strategy_runtime import (
    RuntimeBinding, RuntimeBindingSpec, RuntimeCompatibilityError, RuntimeContractError,
    StrategyCandidate, StrategyInit, StrategyRelease, StrategyRuntime, TradableWindow,
    canonical_sha256, implementation_sha256,
)
from trading_execution_engine import HistoricalExecutor


@pytest.fixture
def candidate(tmp_path):
    root = tmp_path / "source/strategy_runtime"
    (root / "strategies").mkdir(parents=True)
    name = "strategies/tdr_migrated_fixture.py"
    shutil.copyfile(Path(__file__).parents[4] / "tests/fixtures/candidate_runtime.py", root / name)
    return StrategyCandidate("S900", "C0001", {
        "runtime": {"module": "strategy_runtime.strategies.tdr_migrated_fixture", "qualname": "CandidateFixture",
            "contract_version": 1, "source_files": [name], "source_sha256": implementation_sha256((name,), source_root=root)},
        "parameters": {"threshold": .5},
    }, root)


def flows(root):
    sessions = pd.bdate_range("2026-09-14", periods=5)
    daily = pd.DataFrame({"dt": sessions, "open": 1., "close": 1.})
    def provider(request):
        if str(request.dataset) == Dataset.TRADING_CALENDAR.value:
            days = pd.date_range(request.start, request.end)
            return pd.DataFrame({"Date": days, "IsOpen": (days.weekday < 5).astype(int)}), {"vendor": "synthetic"}
        frame = pd.DataFrame({"Date": sessions, "Open": 1., "Close": 1., "High": 1., "Low": 1.,
            "Volume": 1000., "Amount": 1000., "Flow": [.1, .8, .2, .9, 0.], "TotalShare": [.1, .8, .2, .9, 0.]})
        metadata = {"vendor": "synthetic"}
        if str(request.dataset) == Dataset.ETF_SHARE_SIZE.value:
            metadata["vendor_symbol"] = request.symbol
        frame = frame.loc[frame.Date.between(pd.Timestamp(request.start), pd.Timestamp(request.end))].copy()
        if request.dataset in {Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY}:
            metadata["adjustment"] = "none" if request.dataset == Dataset.ETF_UNADJUSTED_DAILY else "hfq"
            pro = SimpleNamespace(
                fund_basic=lambda **kwargs: pd.DataFrame({
                    "ts_code": [request.symbol], "list_date": [sessions[0].strftime("%Y%m%d")],
                }),
                trade_cal=lambda **kwargs: pd.DataFrame({
                    "cal_date": pd.date_range(kwargs["start_date"], kwargs["end_date"]).strftime("%Y%m%d"),
                    "is_open": (pd.date_range(kwargs["start_date"], kwargs["end_date"]).weekday < 5).astype(int),
                }),
            )
            coverage = verify_daily_sessions(pro, request.symbol, frame, start=request.start, end=request.end)
            quality = build_quality_evidence(frame, expected_dates=coverage["expected_dates"])
            metadata.update(daily_session_coverage=coverage,
                ohlcv_quality_evidence=bind_quality_frame(quality, frame,
                    adjustment=metadata["adjustment"]))
            frame.attrs = {key: metadata[key] for key in ("daily_session_coverage", "ohlcv_quality_evidence")}
        return frame, metadata
    return Dataflows(base_dir=root, space=DataSpace(Path("data")), providers=ProviderConfig({
        dataset: ProviderBinding("synthetic", "1", provider) for dataset in (
            Dataset.TRADING_CALENDAR, Dataset.ETF_SHARE_SIZE, Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY)
    })), daily


def release(candidate):
    raw = {"schema_version": 5, "strategy_id": "S900", "version": "v1", "release_id": "S900-v1",
        "parent_version": None, "change_summary": "synthetic public SRT fixture",
        "source_experiment": "20261001_S900_EX01", "source_candidate": "C0001",
        "selection_data_cutoff": "2026-09-21", "forward_start": "2026-09-22",
        "strategy_payload": json.loads(json.dumps(candidate.payload, default=dict))}
    return {**raw, "release_hash": canonical_sha256(raw)}


def execute(candidate, root, *, source_root=None, runtime_binding=None):
    dataflows, daily = flows(root)
    strategy = StrategyRuntime(dataflows=dataflows).create(StrategyInit(candidate,
        TradableWindow(date(2026, 9, 15), date(2026, 9, 18)), root / "context",
        source_root=source_root, runtime_binding=runtime_binding))
    strategy.prepare_data(policy=PreparePolicy.REUSE)
    executor = HistoricalExecutor(strategy_reference=strategy.definition.release_id, symbol=strategy.identity.symbol,
        execution_daily=daily, execution_intraday=pd.DataFrame(columns=["dt", "open", "high", "low", "close"]),
        evaluation_start=pd.Timestamp("2026-09-15"), evaluation_end=pd.Timestamp("2026-09-18"), initial_cash=100_000,
        execution_policy=strategy.definition.execution, order_types=strategy.definition.capabilities.order_types)
    return strategy, strategy.inspect_signals(), strategy.run_window(executor=executor)


def test_reference_symbols_do_not_change_tradable_identity(candidate, tmp_path):
    payload = json.loads(json.dumps(candidate.payload, default=dict))
    payload["parameters"]["reference_symbols"] = ["510050.SH", "510300.SH", "159915.SZ"]
    instance = StrategyRuntime().create(StrategyInit(replace(candidate, payload=payload),
        TradableWindow(date(2026, 9, 15), date(2026, 9, 18)), tmp_path / "context"))
    assert instance.identity.symbol == instance.definition.tradable_symbol == "588080.SH"
    assert len(instance.definition.inputs.requirements) == 7


def test_candidate_release_parameters_and_executors_are_independent(candidate, tmp_path):
    first, history, ledger = execute(candidate, tmp_path / "candidate")
    payload = json.loads(json.dumps(candidate.payload, default=dict))
    payload["parameters"]["threshold"] = 1.
    other, _, other_ledger = execute(replace(candidate, payload=payload), tmp_path / "other")
    assert first.definition.identity_kind == "CANDIDATE" and first.definition.version is None
    assert first.definition.runtime_sha256 != other.definition.runtime_sha256
    assert len(ledger.fills) == 3 and other_ledger.fills.empty
    _, _, repeated = execute(candidate, tmp_path / "repeat")
    assert_frame_equal(ledger.account_daily, repeated.account_daily, check_exact=True)
    frozen = StrategyRelease.from_mapping(release(candidate))
    descriptor = candidate.payload["runtime"]
    binding = RuntimeBinding(frozen.release_id, frozen.release_hash, RuntimeBindingSpec(
        tuple(descriptor["source_files"]), descriptor["source_sha256"], tuple(descriptor["source_files"]),
        first.definition.observation.sha256))
    instance, frozen_history, frozen_ledger = execute(frozen, tmp_path / "frozen",
        source_root=candidate.source_root, runtime_binding=binding)
    assert instance.definition.identity_kind == "RELEASE"
    assert instance.definition.implementation == first.definition.implementation
    assert instance.definition.parameters == first.definition.parameters
    assert_frame_equal(history, frozen_history, check_exact=True)
    assert_frame_equal(ledger.account_daily, frozen_ledger.account_daily, check_exact=True)
    for table in ("orders", "fills", "trades"):
        expected, actual = getattr(ledger, table), getattr(frozen_ledger, table)
        economics = [name for name in expected.columns if not name.endswith("_id")]
        assert_frame_equal(expected[economics], actual[economics], check_exact=True)
    with pytest.raises(RuntimeContractError, match="no frozen version"):
        replace(first.definition, version="v1")
    with pytest.raises(TypeError):
        candidate.payload["parameters"]["threshold"] = 99


@pytest.mark.parametrize("fault", ["parameters", "unsafe_closure", "incomplete", "source_hash", "cached_source", "missing_factory"])
def test_public_runtime_rejects_candidate_identity_faults(candidate, tmp_path, fault):
    payload = json.loads(json.dumps(candidate.payload, default=dict))
    source = candidate.source_root / payload["runtime"]["source_files"][0]
    runtime = StrategyRuntime()
    reasons = {"parameters": "runtime parameters", "unsafe_closure": "unsafe path", "incomplete": "incomplete",
        "source_hash": "source hash differs", "cached_source": "fresh process", "missing_factory": "from_parameters"}
    if fault == "unsafe_closure":
        payload["runtime"]["source_files"] = ["../secrets.py"]
    elif fault == "incomplete":
        payload["runtime"].pop("source_files")
    elif fault == "parameters":
        source.write_text(source.read_text(encoding="utf-8").replace("return cls(parameters)", 'return cls(ParameterSet({"threshold": 0.5}))'), encoding="utf-8")
        payload["parameters"]["threshold"] = .9
    elif fault == "missing_factory":
        source.write_text(source.read_text(encoding="utf-8").replace("def from_parameters(cls, parameters: ParameterSet):", "def from_candidate(cls, parameters: ParameterSet):"), encoding="utf-8")
    else:
        runtime.describe(candidate)
        source.write_bytes(source.read_bytes() + b"\n# changed after startup\n")
    if fault in {"parameters", "missing_factory", "cached_source"}:
        payload["runtime"]["source_sha256"] = implementation_sha256(tuple(payload["runtime"]["source_files"]), source_root=candidate.source_root)
    with pytest.raises(RuntimeCompatibilityError, match=reasons[fault]):
        runtime.create(StrategyInit(replace(candidate, payload=payload),
            TradableWindow(date(2026, 9, 15), date(2026, 9, 18)), tmp_path / "context"))


@pytest.mark.parametrize("loaded", [False, True])
def test_frozen_source_forgery_is_rejected_in_fresh_and_loaded_processes(candidate, tmp_path, loaded):
    raw = release(candidate)
    definition = StrategyRuntime().describe(candidate)
    strategy_root = tmp_path / "strategies"
    package = strategy_root / "S900/releases/v1"
    source = package / "src/strategy_runtime"
    shutil.copytree(candidate.source_root, source)
    descriptor = candidate.payload["runtime"]
    binding = RuntimeBinding(raw["release_id"], raw["release_hash"], RuntimeBindingSpec(
        tuple(descriptor["source_files"]), descriptor["source_sha256"], tuple(descriptor["source_files"]), definition.observation.sha256))
    (package / "runtime_binding.json").write_text(json.dumps(binding.to_dict()), encoding="utf-8")
    manifest = {"schema_version": 1, "strategy_version_id": raw["release_id"], "strategy_version_hash": raw["release_hash"],
        "source_candidate_id": "S900-C0001", "candidate_package_hash": "a" * 64,
        "runtime_root": "src/strategy_runtime", "runtime_binding": "runtime_binding.json",
        "files": {p.relative_to(package).as_posix(): sha256(p.read_bytes()).hexdigest() for p in package.rglob("*") if p.is_file()}}
    manifest["package_hash"] = canonical_sha256(manifest)
    (package / "release_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    version = strategy_root / "S900/versions/v1.json"
    version.parent.mkdir(parents=True)
    version.write_text(json.dumps(raw), encoding="utf-8")
    receipt = {"schema_version": 1, "strategy_version_id": raw["release_id"], "strategy_version_hash": raw["release_hash"],
        "release_package": "S900/releases/v1", "package_hash": manifest["package_hash"]}
    receipt["receipt_hash"] = canonical_sha256(receipt)
    deployments = strategy_root / "deployments"
    deployments.mkdir()
    (deployments / "S900-v1.json").write_text(json.dumps(receipt), encoding="utf-8")
    script = '''
import json,sys
from pathlib import Path
from strategy_runtime import StrategyRelease,StrategyRuntime,RuntimeCompatibilityError,implementation_sha256
root=Path(sys.argv[1]); runtime=StrategyRuntime(root)
release=StrategyRelease.from_mapping(json.loads((root/'S900/versions/v1.json').read_text(encoding='utf-8')))
if sys.argv[2]=='True': runtime.describe(release)
package=root/'S900/releases/v1'; source=package/'src/strategy_runtime'
file=source/'strategies/tdr_migrated_fixture.py'
file.write_bytes(file.read_bytes()+b'\\n# changed after startup\\n')
path=package/'runtime_binding.json'; binding=json.loads(path.read_text(encoding='utf-8'))
binding['implementation_sha256']=implementation_sha256(tuple(binding['source_files']),source_root=source)
path.write_text(json.dumps(binding),encoding='utf-8')
try: runtime.describe(release)
except RuntimeCompatibilityError as exc: assert 'file differs' in str(exc),str(exc)
else: raise AssertionError('changed runtime was accepted')
'''
    result = subprocess.run([sys.executable, "-B", "-c", script, str(strategy_root), str(loaded)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
