from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import sys
from types import SimpleNamespace

import pandas as pd
from pandas.testing import assert_frame_equal
import pytest
from dataflows import Dataflows, Dataset

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


def _install_candidate_dataflows(monkeypatch, flow, daily):
    market = daily.rename(
        columns={
            "dt": "Date", "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "vol": "Volume", "amount": "Amount",
        }
    ).copy()
    for column, value in (
        ("High", market[["Open", "Close"]].max(axis=1)),
        ("Low", market[["Open", "Close"]].min(axis=1)),
        ("Volume", 1000.0), ("Amount", 1000.0),
    ):
        if column not in market:
            market[column] = value

    def fetch(request):
        dataset = str(request.dataset)
        if dataset == Dataset.TRADING_CALENDAR.value:
            dates = pd.date_range(request.start, request.end)
            return pd.DataFrame(
                {"Date": dates, "IsOpen": (dates.weekday < 5).astype(int)}
            ), {"vendor": "test"}
        if dataset == "etf.share":
            frame = flow.copy()
        elif dataset == Dataset.ETF_SHARE_SIZE.value:
            frame = pd.DataFrame(
                {"Date": market["Date"], "TotalShare": range(1, len(market) + 1)}
            )
        else:
            frame = market.copy()
        values = pd.to_datetime(frame["Date"])
        frame = frame.loc[
            values.between(pd.Timestamp(request.start), pd.Timestamp(request.end))
        ].reset_index(drop=True)
        metadata = {"vendor": "test"}
        if dataset == Dataset.ETF_SHARE_SIZE.value:
            metadata["vendor_symbol"] = request.symbol
        if dataset == Dataset.ETF_UNADJUSTED_DAILY.value:
            metadata["adjustment"] = "none"
        return frame, metadata

    flows = Dataflows(
        {
            "etf.share": fetch,
            Dataset.ETF_SHARE_SIZE.value: fetch,
            Dataset.ETF_OHLCV.value: fetch,
            Dataset.ETF_UNADJUSTED_DAILY.value: fetch,
            Dataset.TRADING_CALENDAR.value: fetch,
        }
    )
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: flows)


def test_tdr_candidate_replay_uses_srt_prepared_data_and_txe_without_rule_parser(
    candidate_payload, tmp_path, monkeypatch,
):
    from functional_support import ReplayFixture, execution_data_from_replay
    from czsc_trader.backtesting.srt_bridge import build_srt_signal_replay, replay_srt_account
    from czsc_trader.backtesting.strategy_source import resolve_candidate_snapshot
    from czsc_trader.backtesting.service import BacktestRequestV2, run_backtest_v2
    from czsc_trader.application.context import RepositoryContext
    from czsc_trader.data import MarketData
    import json

    payload, package = candidate_payload
    charts = package / "charts"
    charts.mkdir()
    (charts / "__init__.py").write_text("", encoding="utf-8")
    chart_module = "strategy_runtime.charts.candidate_runtime_execution_fixture"
    (charts / "candidate_runtime_execution_fixture.py").write_text(
        "class CandidateFixtureCharts:\n"
        "    def render_backtest(self, context):\n"
        "        return '<html>S001-C001 candidate chart</html>'\n",
        encoding="utf-8",
    )
    chart_files = ("charts/candidate_runtime_execution_fixture.py",)
    chart_descriptor = {
        "module": chart_module,
        "qualname": "CandidateFixtureCharts",
        "contract_version": 1,
        "source_files": list(chart_files),
        "source_sha256": implementation_identity.implementation_sha256(
            chart_files, source_root=package
        ),
    }
    monkeypatch.delitem(sys.modules, chart_module, raising=False)
    # Use an existing family presenter; strategy calculation remains the test SRT.
    payload["rule"] = {"entry_threshold": .5, "exit_threshold": .5}
    candidate = StrategyCandidate("S001", "C001", payload, package)
    strategy = StrategyLoader().load_candidate(candidate)
    definition = strategy.definition
    sessions = pd.bdate_range("2026-09-14", periods=5)
    inputs = pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8, 0.2, 0.9, 0.0]})
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "close": 1.0, "high": 1.0, "low": 1.0, "vol": 1000.0, "amount": 1000.0})
    daily["symbol"] = "588080.SH"
    _install_candidate_dataflows(monkeypatch, inputs, daily)
    replay_data = ReplayFixture(
        tmp_path,
        MarketData(daily.copy(), daily.copy(), daily.copy(), {}, "588080.SH", "etf"),
        daily, pd.DataFrame(columns=["dt", "high", "low"]), "d" * 64, sessions[-1].date(),
    )
    execution_data = execution_data_from_replay(
        replay_data, start=sessions[1], end=sessions[-1]
    )
    context = RepositoryContext.discover(tmp_path)
    snapshot = resolve_candidate_snapshot(
        context,
        candidate.reference_id,
        payload,
        canonical_sha256(payload),
        "fixture",
        runtime_root=package,
        chart_descriptor=chart_descriptor,
    )
    assert snapshot.source_hash == candidate.runtime_identity_sha256
    with pytest.raises(ValueError, match="content hash differs"):
        resolve_candidate_snapshot(context, candidate.reference_id, payload, "0" * 64, "fixture")
    with pytest.raises(ValueError, match="family-qualified"):
        resolve_candidate_snapshot(context, "C001", payload, canonical_sha256(payload), "fixture")
    with pytest.raises(RuntimeContractError):
        resolve_candidate_snapshot(context, candidate.reference_id, {"rule": {}}, canonical_sha256({"rule": {}}), "fixture")
    loaded, signals = build_srt_signal_replay(
        snapshot=snapshot, execution_data=execution_data,
        start=sessions[1], end=sessions[-1],
        repository_root=tmp_path,
    )
    replay = replay_srt_account(
        strategy=loaded, signals=signals, execution_data=execution_data,
        initial_cash=100_000,
    )
    _, direct = _execute(candidate, tmp_path / "direct", monkeypatch)
    assert_frame_equal(replay.account_daily, direct.account_daily, check_exact=True)
    assert len(replay.fills) == 3
    assert signals.support_data["runtime_sha256"] == definition.runtime_sha256
    summary = run_backtest_v2(
        snapshot=snapshot,
        request=BacktestRequestV2(
            "588080.SH", "etf", sessions[1].date(), sessions[-1].date(), 100_000
        ),
        srt_data_root=tmp_path,
        outputs_root=tmp_path / "outputs", run_date=sessions[-1].date(),
        repository_root=tmp_path, execution_data=execution_data,
    )
    assert summary.manifest["strategy"]["kind"] == "CANDIDATE"
    assert summary.manifest["application"]["runtime_engine"] == "srt"
    assert summary.manifest["audit"]["status"] == "PASS"
    published_account = pd.read_csv(summary.output_dir / "account_daily.csv")
    assert published_account["equity"].tolist() == pytest.approx(replay.account_daily["equity"].tolist())
    assert "S001-C001" in (summary.output_dir / "chart.html").read_text(encoding="utf-8")
    assert json.loads((summary.output_dir / "audit.json").read_text())["status"] == "PASS"
    for invalid, end, message in (
        (replace(snapshot, source_hash="0" * 64), sessions[-1], "release hashes differ"),
        (replace(snapshot, content_hash="0" * 64), sessions[-1], "content hash differs"),
        (snapshot, sessions[-1] + pd.offsets.BDay(), "exceeds the published cutoff"),
    ):
        with pytest.raises(RuntimeContractError, match=message):
            build_srt_signal_replay(
                snapshot=invalid, execution_data=execution_data,
                start=sessions[1], end=end,
                repository_root=tmp_path,
            )
    changed = deepcopy(payload)
    changed["parameters"]["threshold"] = 0.9
    with pytest.raises(RuntimeContractError, match="release hashes"):
        build_srt_signal_replay(
            snapshot=replace(snapshot, strategy_payload=changed),
            execution_data=execution_data,
            start=sessions[1], end=sessions[-1], repository_root=tmp_path,
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
    runtime = StrategyRuntime()
    strategy = runtime.create(
        StrategyInit(
            source,
            TradableWindow(sessions[1].date(), sessions[-1].date()),
            data_dir,
            source_root=source_root,
            runtime_binding=runtime_binding,
        )
    )
    _install_candidate_dataflows(monkeypatch, inputs["flow"], daily)
    strategy.prepare_data()
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
    candidate_payload, tmp_path, monkeypatch,
):
    payload, package = candidate_payload
    payload["parameters"]["reference_symbols"] = [
        "510050.SH",
        "510300.SH",
        "159915.SZ",
    ]
    candidate = StrategyCandidate("S900", "MULTIREF", payload, package)
    sessions = pd.bdate_range("2026-09-14", periods=5)
    flow = pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8, 0.2, 0.9, 0.0]})
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "close": 1.0})
    _install_candidate_dataflows(monkeypatch, flow, daily)

    strategy = StrategyRuntime().create(
        StrategyInit(
            candidate,
            TradableWindow(sessions[1].date(), sessions[-1].date()),
            tmp_path / "multi-reference",
        )
    )
    strategy.prepare_data()

    assert strategy.identity.symbol == "588080.SH"
    assert strategy.definition.tradable_symbol == "588080.SH"
    assert len(strategy.definition.inputs.requirements) == 7


def test_parameter_search_and_release_use_one_implementation_and_isolated_txe(
    candidate_payload, tmp_path, monkeypatch,
):
    payload, package = candidate_payload
    candidate = StrategyCandidate("S900", "C001", payload, package)
    loader = StrategyLoader()
    first = loader.load_candidate(candidate)
    changed = deepcopy(payload)
    changed["parameters"]["threshold"] = 1.0
    second_source = StrategyCandidate("S900", "C001", changed, package)
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

    # A real frozen identity binds the same source and parameters without a v1 Python wrapper.
    raw = {
        "schema_version": 3,
        "strategy_id": "S900",
        "version": "v1",
        "release_id": "S900-v1",
        "strategy_payload": payload,
    }
    raw["release_hash"] = canonical_sha256(raw)
    frozen_source = StrategyRelease.from_mapping(raw)
    runtime_binding = {
        "release_id": frozen_source.release_id,
        "release_hash": frozen_source.release_hash,
        "source_files": payload["runtime"]["source_files"],
        "implementation_sha256": payload["runtime"]["source_sha256"],
    }
    frozen = loader.load(
        frozen_source, source_root=package, runtime_binding=runtime_binding,
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
    original = StrategyCandidate("S900", "C001", payload, package)
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
        ({"fee_rate_override": float("nan")}, "fee_rate_override"),
        ({"fee_rate_override": -0.01}, "fee_rate_override"),
        ({"fee_rate_override": 1.0}, "fee_rate_override"),
        ({"execution_daily": pd.concat([daily, daily])}, "unique"),
        ({"execution_daily": daily.assign(close=float("nan"))}, "positive and finite"),
        ({"evaluation_end": pd.Timestamp("2026-09-18")}, "do not cover"),
    ):
        with pytest.raises(RuntimeContractError, match=reason):
            HistoricalExecutor(**{**execution, **changes})
    bad_parameters = deepcopy(payload)
    bad_parameters["parameters"]["threshold"] = 0.9
    factory = type(valid)
    create = factory.from_candidate
    monkeypatch.setattr(factory, "from_candidate", lambda _: valid)
    with pytest.raises(RuntimeCompatibilityError, match="candidate identity"):
        loader.load_candidate(
            StrategyCandidate("S900", "C001", bad_parameters, package)
        )
    monkeypatch.setattr(factory, "from_candidate", create)
    wrong_closure = deepcopy(payload)
    wrong_closure["runtime"]["source_files"] = ["../secrets.py"]
    with pytest.raises(RuntimeCompatibilityError, match="unsafe path"):
        loader.load_candidate(
            StrategyCandidate("S900", "C001", wrong_closure, package)
        )
    missing = deepcopy(payload)
    missing["runtime"].pop("source_files")
    with pytest.raises(RuntimeCompatibilityError, match="incomplete"):
        loader.load_candidate(StrategyCandidate("S900", "C001", missing, package))
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
        loader.load_candidate(StrategyCandidate("S900", "C001", changed, package))


def test_candidate_evaluation_and_se_use_identical_txe_ledgers(candidate_payload, tmp_path, monkeypatch):
    from strategy_evaluator import (
        AuditStatus, ChampionAuditRequest, ReplayEvidence, audit_provisional_champion,
        hash_execution_evidence, hash_return_matrix, hash_audit_data,
    )
    from functional_support import ReplayFixture
    from czsc_trader.research_tools import (
        CandidateEvaluationContext,
        EvaluationCost,
        EvaluationRequest,
        EvaluationWindow,
        evaluate_strategy,
    )
    from czsc_trader.candidate_evaluation import evaluate_candidate_payloads
    from czsc_trader.application.evaluation_evidence import build_champion_audit_request

    payload, package = candidate_payload
    sessions = pd.bdate_range("2026-09-14", periods=6)
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "close": 1.0})
    # First buy cannot fill; next day the unchanged target must retry and fill.
    daily.loc[2, "open"] = 1.1
    inputs = pd.DataFrame({"Date": sessions, "Flow": [.1, .8, .8, .1, .0, .0]})
    _install_candidate_dataflows(monkeypatch, inputs, daily)
    payloads = []
    for candidate_id, threshold in (("C000", 1.0), ("C001", .5)):
        parameters = deepcopy(payload)
        parameters["parameters"]["threshold"] = threshold
        payloads.append({"candidate_id": candidate_id, "strategy_id": "S900",
                         "strategy_payload": parameters, "is_incumbent": candidate_id == "C000"})
    replay_data = ReplayFixture(
        tmp_path, SimpleNamespace(daily=daily, symbol="588080.SH", asset_type="etf"),
        daily, pd.DataFrame(columns=["dt", "high", "low"]), "d" * 64, sessions[-1].date(),
    )
    from functional_support import execution_data_from_replay
    execution_data = execution_data_from_replay(
        replay_data, start=sessions[1], end=sessions[-1]
    )
    monkeypatch.setattr(
        "czsc_trader.research_tools.evaluation.prepare_backtest_execution_data",
        lambda **kw: execution_data,
    )
    def forbidden(*args, **kwargs):
        raise AssertionError("evaluation must not invoke the old simple backtest")

    monkeypatch.setattr("czsc_trader.research_backtest.run_period_backtests", forbidden)
    context = CandidateEvaluationContext(
        SimpleNamespace(root=tmp_path), "588080.SH", "etf",
        (("full", (sessions[1], sessions[-1])),), .001, 100_000, frequency_window_days=3,
        family_id="S900",
        candidate_runtime_roots={"C000": package, "C001": package},
    )
    protocol = SimpleNamespace(development_cutoff="2026-09-21", incumbent_id="C000",
                               experiment_id="TEST", execution_policy_hash="e" * 64, standard_version="opc-v3")
    payloads = tuple(payloads)
    screening = evaluate_candidate_payloads(context, protocol, payloads, ("C001", "C000"), "SCREENING")
    formal = evaluate_candidate_payloads(context, protocol, payloads, ("C001", "C000"), "FORMAL")
    candidate = StrategyCandidate("S900", "C001", payloads[1]["strategy_payload"], package)
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
        windows=(
            EvaluationWindow("full", sessions[1].date(), sessions[-1].date()),
        ),
        development_cutoff=sessions[-1].date(),
        initial_cash=100_000,
        costs=(EvaluationCost("standard", .001),),
        execution_data=execution_data,
        frequency_window_days=3,
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
        "calmar", "max_drawdown", "return",
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
                    "candidate_id": "S900-C999",
                },
            )
        )
    assert tuple(replace(row, measurement_tier="FORMAL") for row in screening) == formal
    assert formal[0].closed_trades == 1
    assert evaluate_candidate_payloads(replace(context, workers=2), protocol, payloads, ("C001", "C000"), "FORMAL") == formal
    stressed = evaluate_candidate_payloads(context, protocol, payloads, ("C001",), "STRESS", ("total_cost_20bp",))
    assert stressed[0].total_return < formal[0].total_return
    assert stressed[0].cost_drag > formal[0].cost_drag
    audit_request = build_champion_audit_request(
        run_context=context, protocol=protocol, manifest={}, payloads=payloads, candidates=(), trials=(),
        ranking=SimpleNamespace(champion_id="C001", profiles=()), screening_profiles=(),
        formal=formal, repeated=(formal[0],), stress=stressed, search_candidate_ids=("C001",),
    )
    assert isinstance(audit_request.execution, ReplayEvidence)
    evidence = audit_request.execution
    assert [row["status"] for row in evidence.orders] == ["UNFILLED", "FILLED", "FILLED"]
    assert len(evidence.fills) == 2
    assert len(evidence.trades) == 1
    assert audit_request.search_returns.returns == tuple((row[0],) for row in audit_request.comparison_returns.returns)
    assert (1 + pd.Series([row[0] for row in audit_request.search_returns.returns])).prod() - 1 == pytest.approx(formal[0].total_return)
    restored = ChampionAuditRequest.from_dict(audit_request.to_dict())
    assert restored.to_dict() == audit_request.to_dict()
    audit = audit_provisional_champion(restored)
    execution = next(item for item in audit.findings if item.audit_id == "execution")
    assert execution.status is AuditStatus.PASS, execution.reason_codes

    # Individually hash-valid matrices must still agree with the audited ledger.
    mismatched = replace(audit_request.comparison_returns,
                         returns=tuple((row[0] + .01, *row[1:]) for row in audit_request.comparison_returns.returns))
    mismatched = replace(mismatched, content_hash=hash_return_matrix(mismatched))
    bad_request = replace(audit_request, comparison_returns=mismatched,
                          identity=replace(audit_request.identity, data_hash=hash_audit_data(audit_request.search_returns, mismatched)))
    assert "CHAMPION_LEDGER_RETURN_MISMATCH" in audit_provisional_champion(bad_request).reason_codes

    # A ledger defect must fail the real replay audit even with a freshly computed hash.
    broken = replace(evidence, fills=({**evidence.fills[0], "fees": 999.0}, *evidence.fills[1:]))
    broken = replace(broken, content_hash=hash_execution_evidence(broken))
    failed = audit_provisional_champion(replace(audit_request, execution=broken))
    assert next(item for item in failed.findings if item.audit_id == "execution").status is AuditStatus.FAIL
    with pytest.raises(ValueError, match="price-slippage"):
        evaluate_candidate_payloads(context, protocol, payloads, ("C001",), "STRESS", ("slippage_15bp",))
    with pytest.raises(ValueError, match="invalid cost"):
        evaluate_candidate_payloads(context, protocol, payloads, ("C001",), "STRESS", ("fee_xnan",))


def test_research_evaluate_cli_publishes_complete_hashed_evidence(
    candidate_payload, functional_repo, monkeypatch, capsys
):
    import json
    import shutil

    from czsc_trader.cli.main import main
    from functional_support import ReplayFixture, execution_data_from_replay

    payload, source_root = candidate_payload
    sessions = pd.bdate_range("2026-09-14", periods=6)
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "close": 1.0})
    inputs = pd.DataFrame({"Date": sessions, "Flow": [.1, .8, .8, .1, .0, .0]})
    _install_candidate_dataflows(monkeypatch, inputs, daily)
    replay = ReplayFixture(
        functional_repo / "data" / "backtest",
        SimpleNamespace(daily=daily, symbol="588080.SH", asset_type="etf"),
        daily,
        pd.DataFrame(columns=["dt", "high", "low"]),
        "f" * 64,
        sessions[-1].date(),
    )
    execution_data = execution_data_from_replay(
        replay, start=sessions[1], end=sessions[-1]
    )
    monkeypatch.setattr(
        "czsc_trader.application.research_evaluation_service.prepare_backtest_execution_data",
        lambda **kwargs: execution_data,
    )

    experiment = functional_repo / "experiments" / "S900" / "EXPLICIT01"
    runtime_root = experiment / "runtime" / "strategy_runtime"
    shutil.copytree(source_root, runtime_root)
    binding = {
        "candidate_id": "S900-C001",
        "source_files": list(payload["runtime"]["source_files"]),
        "implementation_sha256": payload["runtime"]["source_sha256"],
    }
    (experiment / "runtime_binding.json").write_text(
        json.dumps(binding, indent=2) + "\n", encoding="utf-8"
    )
    request = {
        "schema_version": 1,
        "experiment_id": experiment.name,
        "strategy": {
            "strategy_id": "S900",
            "candidate_id": "C001",
            "strategy_payload": payload,
            "runtime_root": "runtime/strategy_runtime",
            "runtime_binding": "runtime_binding.json",
        },
        "market": {
            "symbol": "588080.SH",
            "asset_type": "etf",
            "development_cutoff": sessions[-1].date().isoformat(),
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
                "one_way_cost": .001,
                "measurement_tier": "FORMAL",
            },
            {
                "scenario_id": "pressure_20bp",
                "one_way_cost": .002,
                "measurement_tier": "STRESS",
            },
        ],
        "benchmark": {"benchmark_id": "BuyHold", "kind": "BUYHOLD"},
        "execution": {
            "mode": "FULL",
            "workers": 2,
            "frequency_window_days": 3,
        },
    }
    request_path = experiment / "evaluation_request.json"
    request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    arguments = [
        "research", "evaluate", "--input",
        request_path.relative_to(functional_repo).as_posix(),
        "--repo-root", str(functional_repo),
    ]

    assert main(arguments) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "PASS"
    assert first["command"] == "research.evaluate"
    assert first["result"]["run_count"] == 2
    assert first["result"]["execution_mode"] == "FULL"
    assert main(arguments) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["result"] == first["result"]

    output = experiment / "artifacts" / "evaluation"
    document = json.loads((output / "evaluation_result.json").read_text(encoding="utf-8"))
    assert document["request_hash"] == first["result"]["request_hash"]
    assert document["result_hash"] == first["result"]["result_hash"]
    assert len(document["files"]) == 20
    assert (output / "full" / "standard" / "account_daily.csv").is_file()
    assert (output / "full" / "pressure_20bp" / "buyhold_metrics.json").is_file()


def test_review_data_republication_is_offline_isolated_and_fails_closed(candidate_payload, tmp_path, monkeypatch):
    from hashlib import sha256
    from czsc_trader.application.review_data import (
        publish_review_dataset, load_review_dataset, verify_review_dataset,
    )
    from functional_support import ReplayFixture, replay_fingerprint
    from czsc_trader.research_tools import CandidateEvaluationContext
    from czsc_trader.candidate_evaluation import evaluate_candidate_payloads
    from czsc_trader.data import MarketData

    payload, package = candidate_payload
    payload["parameters"]["with_calendar"] = True
    sessions = pd.bdate_range("2026-09-14", periods=6)
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0})
    market = MarketData(daily.copy(), daily.copy(), daily.copy(), {}, "588080.SH", "etf")
    pool = tmp_path / "data" / "raw"
    pool.mkdir(parents=True)
    replay = ReplayFixture(
        pool, market, daily, daily.copy(),
        replay_fingerprint(market.daily, daily, daily), sessions[-1].date(),
    )
    from functional_support import execution_data_from_replay
    execution_data = execution_data_from_replay(
        replay, start=sessions[1], end=sessions[-1]
    )
    monkeypatch.setattr(
        "czsc_trader.research_tools.evaluation.prepare_backtest_execution_data",
        lambda **kw: execution_data,
    )
    def forbidden(*args, **kwargs):
        raise AssertionError("review publication must not access remote adapters")
    monkeypatch.setattr("dataflows.facade._default_providers", forbidden)
    context = SimpleNamespace(root=tmp_path, research_data_root=pool)
    sources = []
    for name, dataset, symbol, frame in (
        ("flow.csv", "etf.share", "588080.SH", pd.DataFrame({"Date": sessions, "Flow": [.1, .8, .8, .1, 0, 0]})),
        ("calendar.csv", "calendar.trading_sessions", "SSE",
         pd.DataFrame({"Date": pd.date_range(sessions[0], sessions[-1] + pd.Timedelta(days=20))}).assign(
             IsOpen=lambda frame: (frame.Date.dt.dayofweek < 5).astype(int))),
    ):
        path = pool / name
        frame.to_csv(path, index=False)
        sources.append({"dataset": dataset, "symbol": symbol, "frequency": "daily", "path": name,
                        "sha256": sha256(path.read_bytes()).hexdigest()})
    _install_candidate_dataflows(
        monkeypatch,
        pd.read_csv(pool / "flow.csv"),
        daily,
    )
    raw_protocol = {"development_cutoff": "2026-09-21"}
    protocol = SimpleNamespace(**raw_protocol, to_dict=lambda: raw_protocol)
    manifest = {
        "strategy_id": "S900", "symbol": "588080.SH", "asset_type": "etf",
        "windows": {"full": {"start": "2026-09-15", "end": "2026-09-21"}},
        "candidates": [{"candidate_id": "C001", "strategy_payload": payload}],
        "review_data_sources": sources,
    }
    directory = tmp_path / "data" / "review" / "SGC-TEST" / ("a" * 64)
    published = publish_review_dataset(
        context,
        manifest,
        protocol,
        directory,
        candidate_runtime_roots={"C001": package},
    )
    restored = load_review_dataset(directory, published["snapshot_hash"])
    assert_frame_equal(restored.execution_daily, daily)
    assert_frame_equal(restored.adjusted_daily, daily)
    assert restored.root != pool
    run = CandidateEvaluationContext(
        context, "588080.SH", "etf", (("full", (sessions[1], sessions[-1])),),
        .001, 100_000, family_id="S900", review_data_root=directory,
        review_data_hash=published["snapshot_hash"],
        candidate_runtime_roots={"C001": package},
    )
    rows = evaluate_candidate_payloads(run, protocol, tuple(manifest["candidates"]), ("C001",), "FORMAL")
    assert rows[0].closed_trades == 1

    # Source changes after publication cannot change already sealed review results.
    original = (pool / "flow.csv").read_bytes()
    (pool / "flow.csv").write_bytes(original + b"\n")
    monkeypatch.setattr(
        "czsc_trader.research_tools.evaluation.prepare_backtest_execution_data", forbidden
    )
    with pytest.raises(ValueError, match="unsealed review dataset already exists"):
        publish_review_dataset(
            context,
            manifest,
            protocol,
            directory,
            candidate_runtime_roots={"C001": package},
        )
    assert evaluate_candidate_payloads(run, protocol, tuple(manifest["candidates"]), ("C001",), "FORMAL") == rows
    with pytest.raises(ValueError, match="sealed snapshot"):
        load_review_dataset(directory, "0" * 64)
    changed = deepcopy(manifest)
    changed["candidates"][0]["strategy_payload"]["parameters"]["threshold"] = .7
    with pytest.raises(ValueError, match="unsealed review dataset already exists"):
        publish_review_dataset(
            context,
            changed,
            protocol,
            directory,
            candidate_runtime_roots={"C001": package},
        )

    # A new preparation fails atomically when SRT cannot prepare its own inputs.
    monkeypatch.setattr(
        "czsc_trader.research_tools.evaluation.prepare_backtest_execution_data",
        lambda **kw: execution_data,
    )
    failed_directory = directory.parent / ("b" * 64)
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", forbidden)
    with pytest.raises(AssertionError, match="must not access remote"):
        publish_review_dataset(
            context,
            manifest,
            protocol,
            failed_directory,
            candidate_runtime_roots={"C001": package},
        )
    assert not failed_directory.exists()

    snapshot_file = directory / "execution_daily.csv.gz"
    snapshot_file.write_bytes(snapshot_file.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="file hash mismatch"):
        verify_review_dataset(directory, published["snapshot_hash"])
    with pytest.raises(ValueError, match="file hash mismatch"):
        evaluate_candidate_payloads(run, protocol, tuple(manifest["candidates"]), ("C001",), "FORMAL")


def test_real_evaluation_consumes_review_snapshot_and_emits_se_report(candidate_payload, tmp_path, monkeypatch):
    """Synthetic economics; only raw-pool loading is stubbed, all assessment runs."""
    from hashlib import sha256
    import json
    import numpy as np
    from czsc_trader.application.evaluation_service import evaluate_experiment
    from czsc_trader.application.context import RepositoryContext
    from czsc_trader.application.runtime_acceptance import _runtime_report
    from czsc_trader.application.review_data import publish_review_dataset
    from functional_support import ReplayFixture, replay_fingerprint
    from czsc_trader.data import MarketData
    from strategy_evaluator import EvaluationProtocol

    payload, package = candidate_payload
    sessions = pd.bdate_range("2026-01-05", periods=132)
    changes = np.array([.02 if i % 2 else -.02 for i in range(len(sessions))])
    changes[::14] = .015
    changes[13::14] = -.015
    closes = 2 * np.cumprod(1 + changes)
    daily = pd.DataFrame({"dt": sessions, "open": np.r_[2.0, closes[:-1]], "close": closes})
    daily["high"] = daily[["open", "close"]].max(axis=1)
    daily["low"] = daily[["open", "close"]].min(axis=1)
    market = MarketData(daily.copy(), daily.copy(), daily.copy(), {}, "588080.SH", "etf")
    pool = tmp_path / "data" / "raw"
    pool.mkdir(parents=True)
    replay = ReplayFixture(
        pool, market, daily, daily.copy(),
        replay_fingerprint(market.daily, daily, daily), sessions[-1].date()
    )
    from functional_support import execution_data_from_replay
    execution_data = execution_data_from_replay(
        replay, start=sessions[1], end=sessions[-1]
    )
    monkeypatch.setattr(
        "czsc_trader.research_tools.evaluation.prepare_backtest_execution_data",
        lambda **kw: execution_data,
    )
    context = RepositoryContext(
        root=tmp_path, research_root=tmp_path / "research",
        research_registry_root=tmp_path / "research" / "registrations", raw_dir=pool,
        research_data_root=pool, tdr_srt_root=tmp_path / "data/backtest",
        strategy_root=tmp_path / "strategies", experiments_root=tmp_path / "experiments",
        outputs_root=tmp_path / "outputs",
    )
    cutoff = sessions[-1].date().isoformat()
    # Distinct decision paths provide actual search dispersion and ten neighbors.
    flow_values = np.array([
        .51 + .02 * ((i // 2) % 10) if i % 2 == 0 else .49 - .02 * ((i // 2) % 10)
        for i in range(len(sessions))
    ])
    sources = []
    for name, dataset, symbol, frame in (
        ("flow.csv", "etf.share", "588080.SH", pd.DataFrame({"Date": sessions, "Flow": flow_values})),
        ("calendar.csv", "calendar.trading_sessions", "SSE",
         pd.DataFrame({"Date": pd.date_range(sessions[0], sessions[-1] + pd.Timedelta(days=20))}).assign(
             IsOpen=lambda frame: (frame.Date.dt.dayofweek < 5).astype(int))),
    ):
        path = pool / name
        frame.to_csv(path, index=False)
        sources.append({"dataset": dataset, "symbol": symbol, "path": name,
                        "sha256": sha256(path.read_bytes()).hexdigest()})
    _install_candidate_dataflows(
        monkeypatch,
        pd.read_csv(pool / "flow.csv"),
        daily,
    )
    candidates = []
    points = [("C000", .5), ("C001", .5)] + [
        (f"C{i:03d}", threshold)
        for i, threshold in enumerate((.40, .42, .44, .46, .48, .52, .54, .56, .58, .60), start=2)
    ]
    for identity, threshold in points:
        params = deepcopy(payload)
        params["parameters"] = {"threshold": threshold, "with_calendar": True, "entry_premium": .01}
        if identity == "C000":
            params["parameters"]["invert"] = True
        strategy = StrategyLoader().load_candidate(
            StrategyCandidate("S900", identity, params, package)
        )
        candidates.append({"candidate_id": identity, "strategy_id": "S900", "strategy_payload": params,
                           "strategy_hash": canonical_sha256(params),
                           "execution_policy_hash": _runtime_report(strategy.definition)["execution_policy_sha256"],
                           "parameter_distance": abs(threshold - .5),
                           "behavior_hash": canonical_sha256(
                               ((flow_values <= threshold) if identity == "C000" else (flow_values > threshold)).tolist()
                           ), "is_incumbent": identity == "C000"})
    protocol = EvaluationProtocol.from_dict({
        "schema_version": 1, "standard_version": "opc-v3", "experiment_id": "REVIEW",
        "research_objective": "isolated integration fixture", "development_cutoff": cutoff,
        "incumbent_id": "C000", "incumbent_hash": candidates[0]["strategy_hash"],
        "decision_windows": ["full"], "target_windows": ["full"],
        "execution_policy_hash": candidates[0]["execution_policy_hash"], "tightened_margins": {},
        "shortlist_limit": 5, "target_requirements": [
            {"metric": "full_return", "direction": "maximize", "minimum_improvement": 0.0}],
        "candidate_manifest": "candidate_manifest.json",
    })
    manifest = {
        "strategy_id": "S900", "symbol": "588080.SH", "fee_rate": .001, "init_cash": 100_000,
        "windows": {"full": {"start": sessions[1].date().isoformat(), "end": cutoff}},
        "forward_start": (sessions[-1] + pd.offsets.BDay()).date().isoformat(),
        "candidates": candidates, "review_data_sources": sources,
        "trials": [{"trial_id": item["candidate_id"], "candidate_id": item["candidate_id"],
                    "strategy_hash": item["strategy_hash"], "behavior_hash": item["behavior_hash"],
                    "status": "COMPLETED"} for item in candidates],
    }
    experiment = context.experiments_root / "S900" / "REVIEW"
    experiment.mkdir(parents=True)
    (experiment / "evaluation_protocol.json").write_text(json.dumps(protocol.to_dict()), encoding="utf-8")
    (experiment / "candidate_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    directory = tmp_path / "data" / "review" / "fixture"
    published = publish_review_dataset(
        context,
        manifest,
        protocol,
        directory,
        candidate_runtime_roots={item["candidate_id"]: package for item in candidates},
    )
    def forbidden(*args, **kwargs):
        raise AssertionError("review computation must not read the mutable research pool")
    monkeypatch.setattr(
        "czsc_trader.research_tools.evaluation.prepare_backtest_execution_data", forbidden
    )
    result = evaluate_experiment(
        context, "REVIEW", allow_artifact_reuse=False, use_cached_result=False,
        review_data_root=directory, review_data_hash=published["snapshot_hash"],
        candidate_runtime_roots={item["candidate_id"]: package for item in candidates},
    )
    assert result.result["formal_evaluation_contract"]["review_data_hash"] == published["snapshot_hash"]
    assert result.result["formal_evaluation_contract"]["execution_engine"] == "TXE-v1"
    assert "machine_evaluation" in result.result, (
        result.result, (experiment / "artifacts" / "screening_decisions.csv").read_text(),
        (experiment / "artifacts" / "screening_metrics.csv").read_text(),
    )
    assert result.result["machine_evaluation"]["checks"]
    assert (experiment / "artifacts" / "machine_evaluation.json").is_file()

    # Exercise all three human gates with the real evaluator and real ledgers.
    from test_strategy_governance import _hashed, _mandate_for_contract_test, _write_json
    from czsc_trader.application.research_governance_service import create_research_batch
    from czsc_trader.application.freeze_review_service import (
        open_freeze_review, evaluate_freeze_review, freeze_review_candidate,
    )
    from czsc_trader.application.errors import ValidationError
    from strategy_manager import StrategyRegistry
    create_research_batch(context, _write_json(tmp_path / "batch.json", {
        "strategy_id": "S900", "name": "隔离验收", "scope": ["588080.SH"],
        "research_intent": {"objective": "synthetic acceptance only"},
    }), actor="tester", reason="test gate 1")
    candidate = candidates[1]
    metrics = pd.read_csv(experiment / "artifacts" / "formal_metrics.csv")
    claimed_return = float(metrics.loc[metrics.candidate_id == "C001", "net_cagr"].iloc[0])
    ready = _runtime_report(
        StrategyLoader().load_candidate(
            StrategyCandidate("S900", "C001", candidate["strategy_payload"], package)
        ).definition
    )
    snapshot = _hashed({
        "schema_version": 1, "strategy_id": "S900", "candidate_id": "C001",
        "source_experiment": "experiments/S900/REVIEW", "strategy_payload": candidate["strategy_payload"],
        "data_contract": {"symbol": "588080.SH", "asset_type": "etf",
                          "requirements": ready["input_contract"]["requirements"]},
        "execution_policy": ready["execution_policy"], "research_claims": {"annual_return": {"value": claimed_return, "tolerance": 1e-10}},
    }, "candidate_hash")
    mandate = _mandate_for_contract_test(
        strategy_id="S900", mandate_id="EM-S900-C001-001", development_cutoff=cutoff,
        evaluation_windows=manifest["windows"], benchmark={"type": "strategy", "id": "C000"},
        forward_start=manifest["forward_start"], evidence_seen_through=cutoff,
    )
    _write_json(experiment / "artifacts" / "external_validation.json", {
        "candidate_id": "C001", "candidate_hash": snapshot["candidate_hash"], "replays": [],
    })
    _write_json(experiment / "artifacts" / "monitoring_plan.json", {
        "status": "APPROVED", "rules": [{"metric": "drawdown", "operator": "<", "value": -.2}],
    })
    source_before = {path.name: sha256(path.read_bytes()).hexdigest() for path in (experiment / "artifacts").iterdir()}
    open_freeze_review(
        context, credential_id="SGC-S900-001", candidate_path=_write_json(tmp_path / "candidate.json", snapshot),
        mandate_path=_write_json(tmp_path / "mandate.json", mandate.to_dict()), actor="tester", reason="test gate 2",
        runtime_root=package,
    )
    monkeypatch.setattr(
        "czsc_trader.research_tools.evaluation.prepare_backtest_execution_data",
        lambda **kw: execution_data,
    )
    reviewed = evaluate_freeze_review(
        context, "S900", "SGC-S900-001", runtime_root=package,
    )
    report = reviewed.result["adjudication_report"]
    assert {path.name: sha256(path.read_bytes()).hexdigest() for path in (experiment / "artifacts").iterdir()} == source_before
    registry = StrategyRegistry(context.strategy_root)
    assert registry.versions("S900") == ()
    assert report["blocking_findings"] == []
    assert all(audit["status"] == "PASS" for audit in report["audit_results"].values())
    assert evaluate_freeze_review(
        context, "S900", "SGC-S900-001", runtime_root=package,
    ).result["idempotent_replay"] is True
    # A cached eligible report cannot conceal later evidence damage.
    review_metrics = context.root / reviewed.artifacts["source_experiment"] / "artifacts" / "formal_metrics.csv"
    original_metrics = review_metrics.read_bytes()
    try:
        review_metrics.write_bytes(original_metrics + b"\n")
        with pytest.raises(ValidationError, match="evidence changed after review"):
            evaluate_freeze_review(
                context, "S900", "SGC-S900-001", runtime_root=package,
            )
        with pytest.raises(ValidationError, match="evidence changed after review"):
            freeze_review_candidate(
                context,
                "S900",
                "SGC-S900-001",
                actor="tester",
                reason="test gate 3",
                change_summary="test",
                runtime_root=package,
            )
        assert registry.versions("S900") == ()
        assert registry.get_governance_credential("S900", "SGC-S900-001").stage.value == "TDR_ADJUDICATED"
    finally:
        review_metrics.write_bytes(original_metrics)
    frozen = freeze_review_candidate(
        context, "S900", "SGC-S900-001", actor="tester", reason="test gate 3", change_summary="test",
        runtime_root=package,
    )
    assert frozen.result["version"]["release_id"] == "S900-v1"
    assert frozen.result["pte_deployment"] == "NOT_REQUESTED"
    repeated = freeze_review_candidate(
        context, "S900", "SGC-S900-001", actor="tester", reason="test gate 3", change_summary="test",
        runtime_root=package,
    )
    assert repeated.result["idempotent_replay"] is True
    assert len(registry.versions("S900")) == 1
    credential = registry.get_governance_credential("S900", "SGC-S900-001")
    assert [seal.stage.value for seal in credential.seals] == [
        "RESEARCH_INITIATED", "CANDIDATE_SUBMITTED", "TDR_ADJUDICATED", "FREEZE_APPROVED", "VERSION_FROZEN",
    ]
    release = StrategyRelease.from_mapping(registry.get_version("S900", "v1").to_dict())
    release_binding = {
        "release_id": release.release_id,
        "release_hash": release.release_hash,
        "source_files": candidate["strategy_payload"]["runtime"]["source_files"],
        "implementation_sha256": candidate["strategy_payload"]["runtime"]["source_sha256"],
    }
    frozen_strategy = StrategyLoader().load(
        release, source_root=package, runtime_binding=release_binding,
    )
    frozen_runtime = _runtime_report(frozen_strategy.definition)
    for field in (
        "input_contract", "execution_policy", "implementation", "parameters_sha256",
        "decision_contract", "state_mode", "capabilities_sha256", "monitoring_sha256",
    ):
        assert frozen_runtime[field] == ready[field]
    candidate_strategy = StrategyLoader().load_candidate(
        StrategyCandidate("S900", "C001", candidate["strategy_payload"], package)
    )
    history_inputs = {"flow": pd.DataFrame({"Date": sessions, "Flow": flow_values})}
    assert_frame_equal(
        candidate_strategy.calculate_history(history_inputs, sessions),
        frozen_strategy.calculate_history(history_inputs, sessions), check_exact=True,
    )
