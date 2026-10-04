from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import gzip
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

from czsc_trader.research_tools import EvaluationBenchmark, NextOpenBuyHold
from dataflows import Dataflows, Dataset, DataSpace, ProviderConfig, ProviderBinding, PreparePolicy

from strategy_runtime import (
    RuntimeCompatibilityError,
    RuntimeContractError,
    StrategyCandidate,
    StrategyInit,
    StrategyRelease,
    StrategyRuntime,
    TradableWindow,
    canonical_sha256,
)
from strategy_runtime import implementation_identity
from strategy_runtime.loader import StrategyLoader
from trading_execution_engine import HistoricalExecutor


def _install_candidate_dataflows(monkeypatch, flow, daily, *, base_dir=None, space=None):
    market = daily.rename(
        columns={
            "dt": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "vol": "Volume",
            "amount": "Amount",
        }
    ).copy()
    for column, value in (
        ("High", market[["Open", "Close"]].max(axis=1)),
        ("Low", market[["Open", "Close"]].min(axis=1)),
        ("Volume", 1000.0),
        ("Amount", 1000.0),
    ):
        if column not in market:
            market[column] = value

    def fetch(request):
        dataset = str(request.dataset)
        if dataset == Dataset.TRADING_CALENDAR.value:
            dates = pd.date_range(request.start, request.end)
            return pd.DataFrame({"Date": dates, "IsOpen": (dates.weekday < 5).astype(int)}), {
                "vendor": "test"
            }
        if dataset == Dataset.ETF_SHARE_SIZE.value and request.symbol == "588080.SH":
            frame = flow.copy()
            frame["TotalShare"] = frame["Flow"]
        elif dataset == Dataset.ETF_SHARE_SIZE.value:
            frame = pd.DataFrame({"Date": market["Date"], "TotalShare": range(1, len(market) + 1)})
        else:
            frame = market.copy()
            if request.frequency == "30m":
                pieces = []
                for hour, minute in ((10, 0), (10, 30), (11, 0), (11, 30),
                                     (13, 30), (14, 0), (14, 30), (15, 0)):
                    piece = frame.copy()
                    piece["Date"] = pd.to_datetime(piece["Date"]).dt.normalize() + pd.Timedelta(hours=hour, minutes=minute)
                    piece["Volume"] = piece["Volume"] / 8
                    piece["Amount"] = piece["Amount"] / 8
                    pieces.append(piece)
                frame = pd.concat(pieces).sort_values("Date").reset_index(drop=True)
        values = pd.to_datetime(frame["Date"])
        end = pd.Timestamp(request.end)
        if len(request.end) == 10:
            end += pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        frame = frame.loc[
            values.between(pd.Timestamp(request.start), end)
        ].reset_index(drop=True)
        metadata = {"vendor": "test"}
        if dataset == Dataset.ETF_SHARE_SIZE.value:
            metadata["vendor_symbol"] = request.symbol
        if dataset == Dataset.ETF_UNADJUSTED_DAILY.value:
            metadata["adjustment"] = "none"
        return frame, metadata

    from czsc_trader.temp_workspace import create_temporary_directory
    root = base_dir if base_dir is not None else create_temporary_directory(Path.cwd(), "test-dataflows")
    flows = Dataflows(
        base_dir=root, space=space if space is not None else DataSpace(Path("data/backtest")),
        providers=ProviderConfig(bindings={dataset: ProviderBinding("synthetic", "v1", fetch)
            for dataset in (Dataset.ETF_SHARE_SIZE, Dataset.ETF_OHLCV,
                            Dataset.ETF_UNADJUSTED_DAILY, Dataset.TRADING_CALENDAR)}),
    )
    def create_flows(repository_root, *, read_only=False):
        if Path(repository_root).resolve() == Path(root).resolve() and not read_only:
            return flows
        return Dataflows(
            base_dir=repository_root, space=DataSpace(Path("data/backtest")),
            providers=ProviderConfig(bindings={} if read_only else {
                dataset: ProviderBinding("synthetic", "v1", fetch)
                for dataset in (Dataset.ETF_SHARE_SIZE, Dataset.ETF_OHLCV,
                                Dataset.ETF_UNADJUSTED_DAILY, Dataset.TRADING_CALENDAR)
            }),
        )
    monkeypatch.setattr("czsc_trader.backtesting._dataflows.create_backtest_dataflows", create_flows)
    return flows



def _execution_data(flows, root, sessions):
    from czsc_trader.backtesting.execution_data import _prepare_backtest_execution_data
    return _prepare_backtest_execution_data(
        repository_root=root, symbol="588080.SH", asset_type="etf",
        start=sessions[1].date(), end=sessions[-1].date(), dataflows=flows,
    )


def test_tdr_candidate_replay_uses_srt_prepared_data_and_txe_without_rule_parser(
    candidate_payload,
    tmp_path,
    monkeypatch,
):
    from czsc_trader.backtesting.srt_bridge import build_srt_signal_replay, replay_srt_account
    from czsc_trader.backtesting.strategy_source import resolve_candidate_snapshot
    from czsc_trader.backtesting.service import BacktestRequest, _run_backtest
    from czsc_trader.application.context import RepositoryContext
    import json

    payload, package = candidate_payload
    payload["rule"] = {"entry_threshold": 0.5, "exit_threshold": 0.5}
    candidate = StrategyCandidate("S001", "C0001", payload, package)
    strategy = StrategyLoader().load_candidate(candidate)
    definition = strategy.definition
    sessions = pd.bdate_range("2026-09-14", periods=5)
    inputs = pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8, 0.2, 0.9, 0.0]})
    daily = pd.DataFrame(
        {
            "dt": sessions,
            "open": 1.0,
            "close": 1.0,
            "high": 1.0,
            "low": 1.0,
            "vol": 1000.0,
            "amount": 1000.0,
        }
    )
    daily["symbol"] = "588080.SH"
    flows = _install_candidate_dataflows(monkeypatch, inputs, daily, base_dir=tmp_path)
    execution_data = _execution_data(flows, tmp_path, sessions)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test-replay'\n", encoding="utf-8")
    (tmp_path / "src" / "czsc_trader").mkdir(parents=True)
    context = RepositoryContext.discover(tmp_path, explicit_root=tmp_path)
    snapshot = resolve_candidate_snapshot(
        context,
        candidate.reference_id,
        payload,
        canonical_sha256(payload),
        "fixture",
        runtime_root=package,
    )
    assert snapshot.source_hash == candidate.runtime_identity_sha256
    with pytest.raises(ValueError, match="content hash differs"):
        resolve_candidate_snapshot(context, candidate.reference_id, payload, "0" * 64, "fixture")
    with pytest.raises(ValueError, match="family-qualified"):
        resolve_candidate_snapshot(context, "C0001", payload, canonical_sha256(payload), "fixture")
    with pytest.raises(RuntimeContractError):
        resolve_candidate_snapshot(
            context, candidate.reference_id, {"rule": {}}, canonical_sha256({"rule": {}}), "fixture"
        )
    loaded, signals = build_srt_signal_replay(
        snapshot=snapshot,
        execution_data=execution_data,
        start=sessions[1],
        end=sessions[-1],
        repository_root=tmp_path,
        dataflows=flows,
    )
    replay = replay_srt_account(
        strategy=loaded,
        signals=signals,
        execution_data=execution_data,
        initial_cash=100_000,
        dataflows=flows,
    )
    stress = replay_srt_account(
        strategy=loaded,
        signals=signals,
        execution_data=execution_data,
        initial_cash=100_000,
        dataflows=flows,
        fee_rate_override=0.003,
    )
    assert stress.fills["fees"].tolist() == pytest.approx(
        (stress.fills["quantity"] * stress.fills["price"] * 0.003).tolist()
    )
    assert stress.orders.loc[stress.orders["side"].eq("BUY"), "quantity"].sum() <= (
        replay.orders.loc[replay.orders["side"].eq("BUY"), "quantity"].sum()
    )
    _, direct = _execute(candidate, tmp_path / "direct", monkeypatch)
    flows = _install_candidate_dataflows(monkeypatch, inputs, daily, base_dir=tmp_path)
    assert_frame_equal(replay.account_daily, direct.account_daily, check_exact=True)
    assert len(replay.fills) == 3
    assert signals.support_data["runtime_sha256"] == definition.runtime_sha256
    summary = _run_backtest(
        snapshot=snapshot,
        request=BacktestRequest(
            "588080.SH", "etf", sessions[1].date(), sessions[-1].date(), 100_000, 100
        ),
        outputs_root=tmp_path / "outputs",
        run_date=sessions[-1].date(),
        repository_root=tmp_path,
        execution_data=execution_data,
    )
    assert summary.manifest["strategy"]["kind"] == "CANDIDATE"
    assert summary.output_dir.name == f"{sessions[-1]:%m%d}_01_S001-C0001"
    assert summary.manifest["application"]["runtime_engine"] == "srt"
    assert summary.manifest["audit"]["status"] == "PASS"
    published_account = pd.read_csv(summary.output_dir / "account_daily.csv")
    assert published_account["equity"].tolist() == pytest.approx(
        replay.account_daily["equity"].tolist()
    )
    assert "S001-C0001" in (summary.output_dir / "chart.html").read_text(encoding="utf-8")
    assert json.loads((summary.output_dir / "audit.json").read_text())["status"] == "PASS"
    from czsc_trader.application import run_backtest

    monkeypatch.setattr(
        "czsc_trader.backtesting.service._prepare_backtest_execution_data",
        lambda **kwargs: execution_data,
    )
    api_result = run_backtest(
        context,
        candidate,
        BacktestRequest("588080.SH", "etf", sessions[1].date(), sessions[-1].date(), 100_000, 100),
        run_date=sessions[-1].date(),
    )
    assert api_result.status == "PASS"
    assert api_result.result["audit_status"] == "PASS"
    api_output = Path(api_result.artifacts["output_dir"])
    assert pd.read_csv(api_output / "account_daily.csv")["equity"].tolist() == pytest.approx(
        replay.account_daily["equity"].tolist()
    )
    assert "S001-C0001" in (api_output / "chart.html").read_text(encoding="utf-8")
    assert not context.strategy_root.exists()
    for invalid, end, message in (
        (replace(snapshot, source_hash="0" * 64), sessions[-1], "release hashes differ"),
        (replace(snapshot, content_hash="0" * 64), sessions[-1], "content hash differs"),
        (snapshot, sessions[-1] + pd.offsets.BDay(), "exceeds the published cutoff"),
    ):
        with pytest.raises(RuntimeContractError, match=message):
            build_srt_signal_replay(
                snapshot=invalid,
                execution_data=execution_data,
                start=sessions[1],
                end=end,
                repository_root=tmp_path,
        dataflows=flows,
            )
    changed = deepcopy(payload)
    changed["parameters"]["threshold"] = 0.9
    with pytest.raises(RuntimeContractError, match="release hashes"):
        build_srt_signal_replay(
            snapshot=replace(snapshot, strategy_payload=changed),
            execution_data=execution_data,
            start=sessions[1],
            end=sessions[-1],
            repository_root=tmp_path,
        dataflows=flows,
        )


def _execute(
    source: StrategyCandidate | StrategyRelease,
    data_dir,
    monkeypatch,
    *,
    source_root=None,
    runtime_binding=None,
):
    sessions = pd.bdate_range("2026-09-14", periods=5)
    inputs = {"flow": pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8, 0.2, 0.9, 0.0]})}
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "close": 1.0})
    flows = _install_candidate_dataflows(monkeypatch, inputs["flow"], daily)
    runtime = StrategyRuntime(dataflows=flows)
    strategy = runtime.create(
        StrategyInit(
            source,
            TradableWindow(sessions[1].date(), sessions[-1].date()),
            data_dir,
            source_root=source_root,
            runtime_binding=runtime_binding,
        )
    )
    strategy.prepare_data(policy=PreparePolicy.REUSE)
    channel = HistoricalExecutor(
        strategy_reference=strategy.definition.release_id,
        symbol=strategy.identity.symbol,
        execution_daily=daily,
        execution_intraday=pd.DataFrame(columns=["dt", "open", "high", "low", "close"]),
        evaluation_start=sessions[1],
        evaluation_end=sessions[-1],
        initial_cash=100_000,
        execution_policy=strategy.definition.execution,
        order_types=strategy.definition.capabilities.order_types,
    )
    history = strategy.inspect_signals()
    return history, strategy.run_window(executor=channel)


def test_candidate_runtime_keeps_reference_etfs_out_of_tradable_identity(
    candidate_payload,
    tmp_path,
    monkeypatch,
):
    payload, package = candidate_payload
    payload["parameters"]["reference_symbols"] = [
        "510050.SH",
        "510300.SH",
        "159915.SZ",
    ]
    candidate = StrategyCandidate("S900", "C0002", payload, package)
    sessions = pd.bdate_range("2026-09-14", periods=5)
    flow = pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8, 0.2, 0.9, 0.0]})
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "close": 1.0})
    flows = _install_candidate_dataflows(monkeypatch, flow, daily, base_dir=tmp_path)

    strategy = StrategyRuntime(dataflows=flows).create(
        StrategyInit(
            candidate,
            TradableWindow(sessions[1].date(), sessions[-1].date()),
            tmp_path / "multi-reference",
        )
    )
    strategy.prepare_data(policy=PreparePolicy.REUSE)

    assert strategy.identity.symbol == "588080.SH"
    assert strategy.definition.tradable_symbol == "588080.SH"
    assert len(strategy.definition.inputs.requirements) == 7


def test_parameter_search_and_release_use_one_implementation_and_isolated_txe(
    candidate_payload,
    tmp_path,
    monkeypatch,
):
    payload, package = candidate_payload
    candidate = StrategyCandidate("S900", "C0001", payload, package)
    loader = StrategyLoader()
    first = loader.load_candidate(candidate)
    changed = deepcopy(payload)
    changed["parameters"]["threshold"] = 1.0
    second_source = StrategyCandidate("S900", "C0001", changed, package)
    second = loader.load_candidate(second_source)
    assert first.definition.version is None
    assert first.definition.identity_kind == "CANDIDATE"
    assert first.definition.runtime_sha256 != second.definition.runtime_sha256
    history, ledger = _execute(candidate, tmp_path / "candidate", monkeypatch)
    _, other = _execute(second_source, tmp_path / "other", monkeypatch)
    assert len(ledger.fills) == 3
    assert other.fills.empty
    _, repeat = _execute(candidate, tmp_path / "repeat", monkeypatch)
    assert_frame_equal(ledger.account_daily, repeat.account_daily, check_exact=True)

    # Prospective release and candidate exercise the same current implementation.
    frozen_source = StrategyRelease._from_runtime_identity(
        strategy_family_id="S900", version="v1", release_id="S900-v1",
        release_hash="a" * 64, payload=payload,
    )
    from strategy_runtime import RuntimeBinding, RuntimeBindingSpec
    runtime_binding = RuntimeBinding(frozen_source.release_id, frozen_source.release_hash,
        RuntimeBindingSpec(tuple(payload['runtime']['source_files']), payload['runtime']['source_sha256'],
                           tuple(payload['runtime']['source_files']), first.definition.observation.sha256))
    frozen = loader.load(
        frozen_source,
        source_root=package,
        runtime_binding=runtime_binding,
    )
    frozen_history, frozen_ledger = _execute(
        frozen_source,
        tmp_path / "frozen",
        monkeypatch,
        source_root=package,
        runtime_binding=runtime_binding,
    )
    assert frozen.definition.identity_kind == "RELEASE"
    assert frozen.definition.implementation == first.definition.implementation
    assert frozen.definition.parameters == first.definition.parameters
    assert_frame_equal(history, frozen_history, check_exact=True)
    assert_frame_equal(ledger.account_daily, frozen_ledger.account_daily, check_exact=True)
    for table in ("orders", "fills", "trades"):
        expected, actual = getattr(ledger, table), getattr(frozen_ledger, table)
        economics = [name for name in expected.columns if not name.endswith("_id")]
        assert_frame_equal(expected[economics], actual[economics], check_exact=True)
    with pytest.raises(RuntimeCompatibilityError, match="validated StrategyRelease"):
        loader.load(candidate)
    with pytest.raises(RuntimeContractError, match="no frozen version"):
        replace(first.definition, version="v1")
    with pytest.raises(TypeError):
        candidate.payload["parameters"]["threshold"] = 99


def test_candidate_load_fails_closed_on_source_and_parameter_identity_errors(
    candidate_payload, monkeypatch
):
    payload, package = candidate_payload
    loader = StrategyLoader()
    original = StrategyCandidate("S900", "C0001", payload, package)
    valid = loader.load_candidate(original)
    daily = pd.DataFrame({"dt": pd.to_datetime(["2026-09-17"]), "open": [1.0], "close": [1.0]})
    execution = dict(
        strategy_reference=valid.definition.release_id,
        symbol="588080.SH",
        execution_daily=daily,
        execution_intraday=pd.DataFrame(columns=["dt", "high", "low"]),
        evaluation_start=pd.Timestamp("2026-09-17"),
        evaluation_end=pd.Timestamp("2026-09-17"),
        initial_cash=100_000,
        execution_policy=valid.definition.execution,
        order_types=valid.definition.capabilities.order_types,
    )
    for changes, reason in (
        ({"initial_cash": float("nan")}, "positive and finite"),
        ({"execution_daily": pd.concat([daily, daily])}, "unique"),
        ({"execution_daily": daily.assign(close=float("nan"))}, "positive and finite"),
        ({"evaluation_end": pd.Timestamp("2026-09-18")}, "do not cover"),
    ):
        with pytest.raises(RuntimeContractError, match=reason):
            HistoricalExecutor(**{**execution, **changes})
    with pytest.raises(TypeError, match="fee_rate_override"):
        HistoricalExecutor(**execution, fee_rate_override=0.003)
    bad_parameters = deepcopy(payload)
    bad_parameters["parameters"]["threshold"] = 0.9
    factory = type(valid.implementation)
    create = factory.from_parameters
    monkeypatch.setattr(factory, "from_parameters", lambda _: valid.implementation)
    with pytest.raises(RuntimeCompatibilityError, match="runtime parameters"):
        loader.load_candidate(StrategyCandidate("S900", "C0001", bad_parameters, package))
    monkeypatch.setattr(factory, "from_parameters", create)
    wrong_closure = deepcopy(payload)
    wrong_closure["runtime"]["source_files"] = ["../secrets.py"]
    with pytest.raises(RuntimeCompatibilityError, match="unsafe path"):
        loader.load_candidate(StrategyCandidate("S900", "C0001", wrong_closure, package))
    missing = deepcopy(payload)
    missing["runtime"].pop("source_files")
    with pytest.raises(RuntimeCompatibilityError, match="incomplete"):
        loader.load_candidate(StrategyCandidate("S900", "C0001", missing, package))
    path = package / "strategies/candidate_fixture.py"
    path.write_bytes(path.read_bytes() + b"\n# changed after submission\n")
    with pytest.raises(RuntimeCompatibilityError, match="source hash differs"):
        loader.load_candidate(original)
    changed = deepcopy(payload)
    changed["runtime"]["source_sha256"] = implementation_identity.implementation_sha256(
        ("strategies/candidate_fixture.py",),
        source_root=package,
    )
    with pytest.raises(RuntimeCompatibilityError, match="fresh process"):
        loader.load_candidate(StrategyCandidate("S900", "C0001", changed, package))


def test_candidate_evaluation_and_se_use_identical_txe_ledgers(
    candidate_payload, tmp_path, monkeypatch
):
    from strategy_evaluator import (
        AuditStatus,
        ChampionAuditRequest,
        ReplayEvidence,
        audit_provisional_champion,
        hash_execution_evidence,
        hash_return_matrix,
        hash_audit_data,
    )
    from czsc_trader.research_tools import (
        CandidateEvaluationContext,
        EvaluationCost,
        EvaluationRequest,
        EvaluationWindow,
        evaluate_strategy,
    )
    from czsc_trader.candidate_evaluation import evaluate_candidate_payloads
    from czsc_trader.research_tools import build_champion_audit_request

    payload, package = candidate_payload
    sessions = pd.bdate_range("2026-09-14", periods=6)
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "close": 1.0})
    # First buy cannot fill; next day the unchanged target must retry and fill.
    daily.loc[2, "open"] = 1.1
    inputs = pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8, 0.8, 0.1, 0.0, 0.0]})
    flows = _install_candidate_dataflows(monkeypatch, inputs, daily, base_dir=tmp_path)
    payloads = []
    for candidate_id, threshold in (("C0000", 1.0), ("C0001", 0.5)):
        parameters = deepcopy(payload)
        parameters["parameters"]["threshold"] = threshold
        payloads.append(
            {
                "candidate_id": candidate_id,
                "strategy_id": "S900",
                "strategy_payload": parameters,
                "is_incumbent": candidate_id == "C0000",
            }
        )

    execution_data = _execution_data(flows, tmp_path, sessions)
    monkeypatch.setattr(
        "czsc_trader.research_tools.evaluation._prepare_backtest_execution_data",
        lambda **kw: execution_data,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("evaluation must not invoke the old simple backtest")

    # Reject legacy execution without importing its unrelated vectorbt/Numba stack.
    import sys

    monkeypatch.setitem(
        sys.modules, "czsc_trader.research_backtest",
        SimpleNamespace(run_period_backtests=forbidden),
    )
    context = CandidateEvaluationContext(
        SimpleNamespace(root=tmp_path),
        "588080.SH",
        "etf",
        (("full", (sessions[1], sessions[-1])),),
        0.001,
        100_000,
        frequency_window_days=3,
        family_id="S900",
        candidate_runtime_roots={"C0000": package, "C0001": package},
    )
    protocol = SimpleNamespace(
        development_cutoff="2026-09-21",
        incumbent_id="C0000",
        experiment_id="TEST",
        execution_policy_hash="e" * 64,
        standard_version="opc-v3",
    )
    payloads = tuple(payloads)
    screening = evaluate_candidate_payloads(
        context, protocol, payloads, ("C0001", "C0000"), "SCREENING"
    )
    formal = evaluate_candidate_payloads(context, protocol, payloads, ("C0001", "C0000"), "FORMAL")
    candidate = StrategyCandidate("S900", "C0001", payloads[1]["strategy_payload"], package)
    harness_request = EvaluationRequest(
        repository_root=tmp_path,
        experiment_id="TEST",
        strategy=candidate,
        runtime_binding={
            "candidate_id": candidate.reference_id,
            "source_files": list(payload["runtime"]["source_files"]),
            "implementation_sha256": payload["runtime"]["source_sha256"],
        },
        symbol="588080.SH",
        asset_type="etf",
        windows=(EvaluationWindow("full", sessions[1].date(), sessions[-1].date()),),
        data_cutoff=sessions[-1].date(),
        initial_cash=100_000,
        costs=(EvaluationCost("standard", 0.001),),
        execution_data=execution_data,
        frequency_window_days=3,
        benchmark=EvaluationBenchmark(NextOpenBuyHold(100)),
    )
    harness = evaluate_strategy(harness_request)
    assert harness.observations == (formal[0],)
    assert len(harness.runs) == 1
    assert harness.runs[0].signals.data_identity
    assert not harness.runs[0].execution.account_daily.empty
    assert harness.runs[0].observation is harness.observations[0]
    assert harness.runs[0].buyhold is not None
    assert not harness.runs[0].buyhold.account_daily.empty
    assert set(harness.runs[0].buyhold.metrics) >= {
        "calmar",
        "max_drawdown",
        "return",
    }
    assert len(harness.request_hash) == len(harness.result_hash) == 64
    assert harness.strategy_identity == candidate.runtime_identity_sha256
    assert harness.data_identity == execution_data.fingerprint
    with pytest.raises(ValueError, match="only FULL execution"):
        evaluate_strategy(replace(harness_request, execution_mode="ACCELERATED"))
    with pytest.raises(ValueError, match="binding belongs to another"):
        evaluate_strategy(
            replace(
                harness_request,
                runtime_binding={
                    **harness_request.runtime_binding,
                    "candidate_id": "S900-C0999",
                },
            )
        )
    assert tuple(replace(row, measurement_tier="FORMAL") for row in screening) == formal
    assert formal[0].closed_trades == 1
    assert (
        evaluate_candidate_payloads(
            replace(context, workers=2), protocol, payloads, ("C0001", "C0000"), "FORMAL"
        )
        == formal
    )
    stressed = evaluate_candidate_payloads(
        context, protocol, payloads, ("C0001",), "STRESS", ("total_cost_20bp",)
    )
    assert stressed[0].total_return < formal[0].total_return
    assert stressed[0].cost_drag > formal[0].cost_drag
    audit_request = build_champion_audit_request(
        run_context=context,
        protocol=protocol,
        manifest={},
        payloads=payloads,
        candidates=(),
        trials=(),
        ranking=SimpleNamespace(champion_id="C0001", profiles=()),
        screening_profiles=(),
        formal=formal,
        repeated=(formal[0],),
        stress=stressed,
        search_candidate_ids=("C0001",),
    )
    assert isinstance(audit_request.execution, ReplayEvidence)
    evidence = audit_request.execution
    assert [row["status"] for row in evidence.orders] == ["UNFILLED", "FILLED", "FILLED"]
    assert len(evidence.fills) == 2
    assert len(evidence.trades) == 1
    assert audit_request.search_returns.returns == tuple(
        (row[0],) for row in audit_request.comparison_returns.returns
    )
    assert (
        1 + pd.Series([row[0] for row in audit_request.search_returns.returns])
    ).prod() - 1 == pytest.approx(formal[0].total_return)
    restored = ChampionAuditRequest.from_dict(audit_request.to_dict())
    assert restored.to_dict() == audit_request.to_dict()
    audit = audit_provisional_champion(restored)
    execution = next(item for item in audit.findings if item.audit_id == "execution")
    assert execution.status is AuditStatus.PASS, execution.reason_codes

    # Individually hash-valid matrices must still agree with the audited ledger.
    mismatched = replace(
        audit_request.comparison_returns,
        returns=tuple(
            (row[0] + 0.01, *row[1:]) for row in audit_request.comparison_returns.returns
        ),
    )
    mismatched = replace(mismatched, content_hash=hash_return_matrix(mismatched))
    bad_request = replace(
        audit_request,
        comparison_returns=mismatched,
        identity=replace(
            audit_request.identity,
            data_hash=hash_audit_data(audit_request.search_returns, mismatched),
        ),
    )
    assert "CHAMPION_LEDGER_RETURN_MISMATCH" in audit_provisional_champion(bad_request).reason_codes

    # A ledger defect must fail the real replay audit even with a freshly computed hash.
    broken = replace(evidence, fills=({**evidence.fills[0], "fees": 999.0}, *evidence.fills[1:]))
    broken = replace(broken, content_hash=hash_execution_evidence(broken))
    failed = audit_provisional_champion(replace(audit_request, execution=broken))
    assert (
        next(item for item in failed.findings if item.audit_id == "execution").status
        is AuditStatus.FAIL
    )
    with pytest.raises(ValueError, match="price-slippage"):
        evaluate_candidate_payloads(
            context, protocol, payloads, ("C0001",), "STRESS", ("slippage_15bp",)
        )
    with pytest.raises(ValueError, match="invalid cost"):
        evaluate_candidate_payloads(context, protocol, payloads, ("C0001",), "STRESS", ("fee_xnan",))


def test_research_evaluate_api_publishes_complete_hashed_evidence(
    candidate_payload, minimal_repo, monkeypatch, capsys
):
    import json
    import shutil

    from dataclasses import asdict
    from czsc_trader.application import RepositoryContext, evaluate_research_request

    payload, source_root = candidate_payload
    sessions = pd.bdate_range("2026-09-14", periods=6)
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "close": 1.0})
    inputs = pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8, 0.8, 0.1, 0.0, 0.0]})
    _install_candidate_dataflows(monkeypatch, inputs, daily, base_dir=minimal_repo)

    experiment = minimal_repo / "experiments" / "S900" / "EXPLICIT01"
    runtime_root = experiment / "runtime" / "strategy_runtime"
    shutil.copytree(source_root, runtime_root)
    binding = {
        "candidate_id": "S900-C0001",
        "source_files": list(payload["runtime"]["source_files"]),
        "implementation_sha256": payload["runtime"]["source_sha256"],
    }
    (experiment / "runtime_binding.json").write_text(
        json.dumps(binding, indent=2) + "\n", encoding="utf-8"
    )
    request = {
        "schema_version": 2,
        "experiment_id": experiment.name,
        "strategy": {
            "strategy_id": "S900",
            "candidate_id": "C0001",
            "strategy_payload": payload,
            "runtime_root": "runtime/strategy_runtime",
            "runtime_binding": "runtime_binding.json",
        },
        "market": {
            "symbol": "588080.SH",
            "asset_type": "etf",
            "data_cutoff": sessions[-1].date().isoformat(),
        },
        "windows": [
            {
                "window_id": "full",
                "start": sessions[1].date().isoformat(),
                "end": sessions[-1].date().isoformat(),
            }
        ],
        "capital": {"initial_cash": 100_000},
        "costs": [
            {
                "scenario_id": "standard",
                "one_way_cost": 0.001,
                "measurement_tier": "FORMAL",
            },
            {
                "scenario_id": "pressure_20bp",
                "one_way_cost": 0.002,
                "measurement_tier": "STRESS",
            },
        ],
        "benchmark": EvaluationBenchmark(NextOpenBuyHold(100)).to_dict(),
        "execution": {
            "mode": "FULL",
            "workers": 2,
            "frequency_window_days": 3,
        },
    }
    request_path = experiment / "evaluation_request.json"
    request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    context = RepositoryContext.discover(minimal_repo)
    first = asdict(evaluate_research_request(context, request_path))
    assert first["status"] == "PASS"
    assert first["command"] == "research.evaluate"
    assert first["result"]["run_count"] == 2
    assert first["result"]["execution_mode"] == "FULL"
    second = asdict(evaluate_research_request(context, request_path))
    assert second["result"] == first["result"]

    output = experiment / "artifacts" / "evaluation"
    document = json.loads((output / "evaluation_result.json").read_text(encoding="utf-8"))
    assert document["request_hash"] == first["result"]["request_hash"]
    assert document["result_hash"] == first["result"]["result_hash"]
    assert len(document["files"]) == 20
    assert (output / "full" / "standard" / "account_daily.csv").is_file()
    assert (output / "full" / "pressure_20bp" / "buyhold_metrics.json").is_file()


def test_review_data_republication_is_offline_isolated_and_fails_closed(
    candidate_payload, tmp_path, monkeypatch
):
    from hashlib import sha256
    from czsc_trader.application.review_data import (
        publish_review_dataset,
        load_review_dataset,
        verify_review_dataset,
    )
    from czsc_trader.research_tools import CandidateEvaluationContext
    from czsc_trader.candidate_evaluation import evaluate_candidate_payloads

    payload, package = candidate_payload
    payload["parameters"]["with_calendar"] = True
    sessions = pd.bdate_range("2026-09-14", periods=6)
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0})
    pool = tmp_path / "data" / "raw"
    pool.mkdir(parents=True)

    flow = pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8, 0.8, 0.1, 0, 0]})
    flows = _install_candidate_dataflows(monkeypatch, flow, daily, base_dir=tmp_path)
    execution_data = _execution_data(flows, tmp_path, sessions)
    monkeypatch.setattr(
        "czsc_trader.research_tools.evaluation._prepare_backtest_execution_data",
        lambda **kw: execution_data,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("review publication must not access remote adapters")

    monkeypatch.setattr("dataflows.facade._default_providers", forbidden)
    context = SimpleNamespace(root=tmp_path, research_data_root=pool)
    sources = []
    for name, dataset, symbol, frame in (
        (
            "flow.csv",
            Dataset.ETF_SHARE_SIZE.value,
            "588080.SH",
            pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8, 0.8, 0.1, 0, 0]}),
        ),
        (
            "calendar.csv",
            "calendar.trading_sessions",
            "SSE",
            pd.DataFrame(
                {"Date": pd.date_range(sessions[0], sessions[-1] + pd.Timedelta(days=20))}
            ).assign(IsOpen=lambda frame: (frame.Date.dt.dayofweek < 5).astype(int)),
        ),
    ):
        path = pool / name
        frame.to_csv(path, index=False)
        sources.append(
            {
                "dataset": dataset,
                "symbol": symbol,
                "frequency": "daily",
                "path": name,
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
        )
    raw_protocol = {"development_cutoff": "2026-09-21"}
    protocol = SimpleNamespace(**raw_protocol, to_dict=lambda: raw_protocol)
    manifest = {
        "strategy_id": "S900",
        "symbol": "588080.SH",
        "asset_type": "etf",
        "windows": {"full": {"start": "2026-09-15", "end": "2026-09-21"}},
        "candidates": [{"candidate_id": "C0001", "strategy_payload": payload}],
        "review_data_sources": sources,
    }
    directory = tmp_path / "data" / "review" / "SGC-TEST" / ("a" * 64)
    published = publish_review_dataset(
        context,
        manifest,
        protocol,
        directory,
        candidate_runtime_roots={"C0001": package},
    )
    restored = load_review_dataset(directory, published["snapshot_hash"])
    stored_tables = tuple(directory.glob("*.csv.gz"))
    assert stored_tables
    for path in stored_tables:
        assert b"\r" not in gzip.decompress(path.read_bytes())
    assert_frame_equal(restored.execution_daily, execution_data.execution_daily)
    assert_frame_equal(restored.adjusted_daily, execution_data.adjusted_daily)
    assert restored.root != pool
    run = CandidateEvaluationContext(
        context,
        "588080.SH",
        "etf",
        (("full", (sessions[1], sessions[-1])),),
        0.001,
        100_000,
        family_id="S900",
        review_data_root=directory,
        review_data_hash=published["snapshot_hash"],
        candidate_runtime_roots={"C0001": package},
    )
    rows = evaluate_candidate_payloads(
        run, protocol, tuple(manifest["candidates"]), ("C0001",), "FORMAL"
    )
    assert rows[0].closed_trades == 1

    # Source changes after publication cannot change already sealed review results.
    original = (pool / "flow.csv").read_bytes()
    (pool / "flow.csv").write_bytes(original + b"\n")
    monkeypatch.setattr(
        "czsc_trader.research_tools.evaluation._prepare_backtest_execution_data", forbidden
    )
    with pytest.raises(ValueError, match="unsealed review dataset already exists"):
        publish_review_dataset(
            context,
            manifest,
            protocol,
            directory,
            candidate_runtime_roots={"C0001": package},
        )
    assert (
        evaluate_candidate_payloads(
            run, protocol, tuple(manifest["candidates"]), ("C0001",), "FORMAL"
        )
        == rows
    )
    with pytest.raises(ValueError, match="sealed snapshot"):
        load_review_dataset(directory, "0" * 64)
    changed = deepcopy(manifest)
    changed["candidates"][0]["strategy_payload"]["parameters"]["threshold"] = 0.7
    with pytest.raises(ValueError, match="unsealed review dataset already exists"):
        publish_review_dataset(
            context,
            changed,
            protocol,
            directory,
            candidate_runtime_roots={"C0001": package},
        )

    # A new preparation fails atomically when SRT cannot prepare its own inputs.
    monkeypatch.setattr(
        "czsc_trader.research_tools.evaluation._prepare_backtest_execution_data",
        lambda **kw: execution_data,
    )
    failed_directory = directory.parent / ("b" * 64)
    monkeypatch.setattr(flows, "prepare", forbidden)
    with pytest.raises(AssertionError, match="must not access remote"):
        publish_review_dataset(
            context,
            manifest,
            protocol,
            failed_directory,
            candidate_runtime_roots={"C0001": package},
        )
    assert not failed_directory.exists()

    snapshot_file = directory / "execution_daily.csv.gz"
    snapshot_file.write_bytes(snapshot_file.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="file hash mismatch"):
        verify_review_dataset(directory, published["snapshot_hash"])
    with pytest.raises(ValueError, match="file hash mismatch"):
        evaluate_candidate_payloads(
            run, protocol, tuple(manifest["candidates"]), ("C0001",), "FORMAL"
        )


def test_missing_parameter_factory_is_rejected_before_runtime_creation(candidate_payload):
    from copy import deepcopy
    from strategy_runtime import StrategyCandidate, RuntimeCompatibilityError
    from strategy_runtime.loader import StrategyLoader
    from strategy_runtime.implementation_identity import implementation_sha256

    payload, package = candidate_payload
    source = package / "strategies/candidate_fixture.py"
    source.write_text(source.read_text(encoding="utf-8").replace(
        "def from_parameters(cls, parameters: ParameterSet):", "def from_candidate(cls, parameters: ParameterSet):"
    ), encoding="utf-8")
    payload = deepcopy(payload)
    payload["runtime"]["source_sha256"] = implementation_sha256(
        tuple(payload["runtime"]["source_files"]), source_root=package
    )
    with pytest.raises(RuntimeCompatibilityError, match="from_parameters"):
        StrategyLoader().load_candidate(StrategyCandidate("S900", "C0001", payload, package))
