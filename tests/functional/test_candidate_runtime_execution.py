from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from czsc_trader.research_tools import EvaluationBenchmark, NextOpenBuyHold
from dataflows import Dataflows, Dataset, DataSpace, ProviderConfig, ProviderBinding, PreparePolicy

from strategy_runtime import (
    StrategyCandidate,
    StrategyInit,
    StrategyRelease,
    StrategyRuntime,
    TradableWindow,
)
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
        ("Amount", market["Close"] * market.get("Volume", 1000.0)),
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
        if dataset in {Dataset.ETF_UNADJUSTED_DAILY.value, Dataset.ETF_UNADJUSTED_INTRADAY.value}:
            metadata["adjustment"] = "none"
        if dataset == Dataset.ETF_UNADJUSTED_INTRADAY.value:
            from dataflows.contract import ETF_INTRADAY_OBSERVATION_RULE

            frame["AvailableDate"] = frame["Date"]
            metadata.update(
                availability_time_field="AvailableDate", available_at=ETF_INTRADAY_OBSERVATION_RULE,
                availability_basis="MARKET_BAR_CLOSE_ASSUMPTION",
                source_publication_timestamp_verified=False,
                historical_revision_history_verified=False, live_feed_latency_verified=False,
            )
        if dataset in {Dataset.ETF_OHLCV.value, Dataset.ETF_UNADJUSTED_DAILY.value,
                       Dataset.ETF_UNADJUSTED_INTRADAY.value}:
            from functional_support import synthetic_ohlcv_evidence

            metadata.update(synthetic_ohlcv_evidence(request, frame, market))
        return frame, metadata

    from czsc_trader.temp_workspace import create_temporary_directory
    root = base_dir if base_dir is not None else create_temporary_directory(Path.cwd(), "test-dataflows")
    flows = Dataflows(
        base_dir=root, space=space if space is not None else DataSpace(Path("data/backtest")),
        providers=ProviderConfig(bindings={dataset: ProviderBinding("synthetic", "v1", fetch)
            for dataset in (Dataset.ETF_SHARE_SIZE, Dataset.ETF_OHLCV,
                            Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY,
                            Dataset.TRADING_CALENDAR)}),
    )
    def create_flows(repository_root, *, read_only=False):
        if Path(repository_root).resolve() == Path(root).resolve() and not read_only:
            return flows
        return Dataflows(
            base_dir=repository_root, space=DataSpace(Path("data/backtest")),
            providers=ProviderConfig(bindings={} if read_only else {
                dataset: ProviderBinding("synthetic", "v1", fetch)
                for dataset in (Dataset.ETF_SHARE_SIZE, Dataset.ETF_OHLCV,
                                Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY,
                                Dataset.TRADING_CALENDAR)
            }),
        )
    monkeypatch.setattr("czsc_trader.backtesting._dataflows.create_backtest_dataflows", create_flows)
    return flows



def _execution_data(flows, root, sessions):
    from czsc_trader.backtesting.execution_data import _prepare_backtest_execution_data
    return _prepare_backtest_execution_data(
        repository_root=root, symbol="588080.SH", asset_type="etf",
        start=sessions[1].date(), end=sessions[-1].date(), dataflows=flows,
        intraday_frequencies=("30m",),
    )


def test_tdr_candidate_replay_uses_srt_prepared_data_and_txe_without_rule_parser(candidate_payload, tmp_path, monkeypatch):
    from czsc_trader.application import BacktestRequest, RepositoryContext, run_backtest
    from czsc_trader.application.errors import ExecutionError

    payload, package = candidate_payload
    payload["rule"] = {"entry_threshold": 0.5, "exit_threshold": 0.5}
    candidate = StrategyCandidate("S001", "C0001", payload, package)
    sessions = pd.bdate_range("2026-09-14", periods=5)
    inputs = pd.DataFrame({"Date": sessions, "Flow": [.1, .8, .2, .9, 0.]})
    daily = pd.DataFrame({"dt": sessions, "open": 1., "close": 1., "high": 1., "low": 1., "vol": 1000., "amount": 1000.})
    flows = _install_candidate_dataflows(monkeypatch, inputs, daily, base_dir=tmp_path)
    execution_data = _execution_data(flows, tmp_path, sessions)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test-replay'\n", encoding="utf-8")
    (tmp_path / "src/czsc_trader").mkdir(parents=True)
    context = RepositoryContext.discover(tmp_path)
    # Only the external procurement boundary is replaced; the public API parses,
    # prepares, executes, audits and publishes the actual candidate replay.
    monkeypatch.setattr("czsc_trader.backtesting.service._prepare_backtest_execution_data", lambda **kwargs: execution_data)
    request = BacktestRequest("588080.SH", "etf", sessions[1].date(), sessions[-1].date(), 100_000, 100)
    result = run_backtest(context, candidate, request, run_date=sessions[-1].date())
    assert result.status == "PASS" and result.command == "backtest.run"
    assert result.result["audit_status"] == "PASS" and result.result["runtime_engine"] == "srt"
    output = Path(result.artifacts["output_dir"])
    _, direct = _execute(candidate, tmp_path / "direct", monkeypatch)
    account = pd.read_csv(output / "account_daily.csv")
    assert account["equity"].tolist() == pytest.approx(direct.account_daily["equity"].tolist())
    assert len(direct.fills) == 3
    assert "S001-C0001" in (output / "chart.html").read_text(encoding="utf-8")
    import json
    assert json.loads((output / "audit.json").read_text(encoding="utf-8"))["status"] == "PASS"
    assert not context.strategy_root.exists()
    # Refuse a real stale procurement result at the public business boundary.
    with pytest.raises(ExecutionError, match="exceeds the published cutoff"):
        run_backtest(context, candidate, replace(request, end=(sessions[-1] + pd.offsets.BDay()).date()))
    changed = deepcopy(payload)
    changed["runtime"]["source_sha256"] = "0" * 64
    with pytest.raises(ExecutionError, match="source hash differs"):
        run_backtest(context, StrategyCandidate("S001", "C0001", changed, package), request)


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








def test_candidate_evaluation_and_se_use_identical_txe_ledgers(managed_evaluation, monkeypatch):
    import shutil
    from czsc_trader.research_tools import EvaluationCost, build_assessment_evidence, evaluate_strategy, create_formal_experiment_context
    from research_experiment import ExperimentResources, ExperimentWorkspace
    from strategy_evaluator import assess_candidates, ResearchMetric
    from test_assessment_delivery import assessment_request

    previous, request = managed_evaluation
    root = request.repository_root / "retry-ledger"
    package = root / "runtime/strategy_runtime"
    shutil.copytree(request.strategy.source_root, package)
    candidate = replace(request.strategy, source_root=package)
    sessions = pd.bdate_range("2026-09-14", periods=6)
    daily = pd.DataFrame({"dt": sessions, "open": 1., "close": 1.})
    daily.loc[2, "open"] = 1.1  # First LIMIT cannot fill; unchanged target must retry.
    inputs = pd.DataFrame({"Date": sessions, "Flow": [.1, .8, .8, .1, 0., 0.]})
    flows = _install_candidate_dataflows(monkeypatch, inputs, daily, base_dir=root)
    data = _execution_data(flows, root, sessions)
    context = create_formal_experiment_context(previous.definition, repository_root=root,
        resources=ExperimentResources(1, 1), workspace=ExperimentWorkspace(root / ".tmp/managed", root),
        data_space=DataSpace(Path("data/research")))
    request = replace(request, repository_root=root, strategy=candidate, execution_data=data,
        input_bindings={}, frequency_window_days=3)
    result = context.evaluation.evaluate(request)
    run = result.runs[0]
    assert [value for value in run.execution.orders["status"]] == ["UNFILLED", "FILLED", "FILLED"]
    assert len(run.execution.fills) == 2 and run.observation.closed_trades == 1
    assert run.signals.data_identity and result.data_identity == data.fingerprint
    assert run.observation is result.observations[0]
    assert run.buyhold is not None and not run.buyhold.account_daily.empty
    assert set(run.buyhold.metrics) >= {"calmar", "max_drawdown", "return"}
    assert len(result.request_hash) == len(result.result_hash) == 64
    assert result.strategy_identity == request.strategy.runtime_identity_sha256
    evidence = build_assessment_evidence(request, result)
    panel = assess_candidates(assessment_request(evidence))
    equity = run.execution.account_daily["equity"]
    expected = float(equity.div(equity.cummax().clip(lower=request.initial_cash)).sub(1.).min())
    assert run.observation.max_drawdown == pytest.approx(expected)
    observed = next(item for item in panel.rows[0].diagnostics if item.metric is ResearchMetric.DRAWDOWN_MAGNITUDE)
    assert observed.value == pytest.approx(abs(expected))
    assert len(evidence[0].fills) == len(run.execution.fills)
    for fact, actual in zip(evidence[0].account, run.execution.account_daily.itertuples()):
        assert fact.equity == pytest.approx(actual.equity)
        assert fact.cash == pytest.approx(actual.cash)
    flexible = evaluate_strategy(replace(request, costs=(
        EvaluationCost("custom_high", .002, "FORMAL"), EvaluationCost("custom_low", .0005, "SCREENING"),
        EvaluationCost("standard", .001, "STRESS"))))
    assert [(item.scenario_id, item.observation.measurement_tier) for item in flexible.runs] == [
        ("custom_high", "FORMAL"), ("custom_low", "SCREENING"), ("standard", "STRESS")]
    assert flexible.runs[0].observation.cost_drag > flexible.runs[1].observation.cost_drag
    assert flexible.runs[0].observation.total_return < run.observation.total_return
    assert flexible.runs[2].observation.total_return == pytest.approx(run.observation.total_return)
    with pytest.raises(ValueError, match="only FULL execution"):
        evaluate_strategy(replace(request, execution_mode="ACCELERATED"))
    with pytest.raises(ValueError, match="binding belongs to another"):
        evaluate_strategy(replace(request, runtime_binding={**request.runtime_binding, "candidate_id": "S900-C0999"}))
    with pytest.raises(ValueError, match="scenario identities must be unique"):
        evaluate_strategy(replace(request, costs=(EvaluationCost("same", .001), EvaluationCost("same", .002))))
    with pytest.raises(ValueError, match="finite"):
        EvaluationCost("fee_xnan", float("nan"))
    for name in ("", "../escape", "NUL", "trailing.", "bad\nname"):
        with pytest.raises(ValueError, match="scenario_id"):
            EvaluationCost(name, .001)
    for fee in (-.001, 1., True):
        with pytest.raises(ValueError, match="cost"):
            EvaluationCost("valid", fee)
    with pytest.raises(ValueError, match="tier"):
        EvaluationCost("valid", .001, "UNKNOWN")


@pytest.fixture
def evaluation_json(candidate_payload, minimal_repo):
    import json
    import shutil

    from czsc_trader.application import RepositoryContext

    payload, source_root = candidate_payload
    sessions = pd.bdate_range("2026-09-14", periods=6)

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
                "scenario_id": "research_case",
                "one_way_cost": 0.001,
                "measurement_tier": "FORMAL",
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
    return context, request_path, request


@pytest.mark.parametrize("section, field, invalid", [
    ("execution", "workers", True),
    ("execution", "workers", 1.5),
    ("execution", "workers", "2"),
    ("execution", "frequency_window_days", True),
    ("execution", "frequency_window_days", 1.5),
    ("capital", "initial_cash", True),
    ("capital", "initial_cash", "100000"),
    ("costs", "one_way_cost", False),
    ("costs", "one_way_cost", "0.001"),
    ("costs", "scenario_id", 123),
    ("windows", "window_id", True),
    (None, "schema_version", 2.0),
])
def test_evaluation_json_rejects_coercion_before_execution(evaluation_json, monkeypatch, section, field, invalid):
    import json
    from czsc_trader.application import evaluate_research_request, ValidationError

    context, path, request = evaluation_json
    target = request[section][0] if section in {"costs", "windows"} else request[section] if section else request
    target[field] = invalid
    path.write_text(json.dumps(request), encoding="utf-8")
    def forbidden(*args, **kwargs):
        pytest.fail("invalid JSON must be rejected before execution or data preparation")
    monkeypatch.setattr("czsc_trader.application.research_evaluation_service.evaluate_strategy", forbidden)
    with pytest.raises(ValidationError, match=field if section else "schema"):
        evaluate_research_request(context, path)
    assert not (path.parent / "artifacts").exists()


def _publication_flows(monkeypatch, root):
    sessions = pd.bdate_range("2026-09-14", periods=6)
    daily = pd.DataFrame({"dt": sessions, "open": 1.0, "close": 1.0})
    inputs = pd.DataFrame({"Date": sessions, "Flow": [0.1, 0.8, 0.8, 0.1, 0.0, 0.0]})
    _install_candidate_dataflows(monkeypatch, inputs, daily, base_dir=root)


@pytest.fixture
def published_evaluation(request, frozen_seed_root, monkeypatch):
    import pickle
    import json
    from czsc_trader.application import evaluate_research_request
    from czsc_trader.research_tools._evaluation_workers import pack
    from czsc_trader.application import research_evaluation_service as service

    seed = frozen_seed_root / "published-evaluation.pkl"
    if not seed.exists():
        context, request_path, _ = request.getfixturevalue("evaluation_json")
        _publication_flows(monkeypatch, context.root)
        evaluate = service.evaluate_strategy
        captured = []
        def record(request):
            result = evaluate(request)
            captured.append(result)
            return result
        with monkeypatch.context() as patch:
            patch.setattr(service, "evaluate_strategy", record)
            first = evaluate_research_request(context, request_path)
        output = request_path.parent / "artifacts/evaluation"
        document = json.loads((output / "evaluation_result.json").read_text(encoding="utf-8"))
        seed.write_bytes(pack((context, request_path, first, captured[0], document)))
    return pickle.loads(seed.read_bytes())


def test_research_evaluate_api_publishes_complete_hashed_evidence(published_evaluation, tmp_path, monkeypatch):
    import json
    from dataclasses import asdict
    from hashlib import sha256
    from czsc_trader.application import evaluate_research_request

    context, request_path, command, result, document = published_evaluation
    _publication_flows(monkeypatch, context.root)
    first = asdict(command)
    assert first["status"] == "PASS"
    assert first["command"] == "research.evaluate"
    assert first["result"]["run_count"] == 1
    assert first["result"]["execution_mode"] == "FULL"
    assert first["artifacts"] == {"directory": "experiments/S900/EXPLICIT01/artifacts/evaluation"}
    second = asdict(evaluate_research_request(context, request_path.relative_to(context.root)))
    assert second["result"] == first["result"]

    output = request_path.parent / "artifacts/evaluation"
    assert document["request_hash"] == first["result"]["request_hash"]
    assert document["result_hash"] == first["result"]["result_hash"]
    assert len(document["files"]) == 10
    assert {name: sha256((output / name).read_bytes()).hexdigest()
            for name in document["files"]} == document["files"]
    assert (output / "full" / "research_case" / "account_daily.csv").is_file()
    assert (output / "full" / "research_case" / "buyhold_metrics.json").is_file()
    legacy = tmp_path / "legacy.csv"
    result.runs[0].execution.account_daily.to_csv(legacy, index=False, encoding="utf-8", lineterminator="\n")
    assert (output / "full/research_case/account_daily.csv").read_bytes() == legacy.read_bytes()
    expected_json = json.dumps(result.runs[0].buyhold.metrics, ensure_ascii=False, indent=2, default=str) + "\n"
    assert (output / "full/research_case/buyhold_metrics.json").read_bytes() == expected_json.encode("utf-8")


@pytest.mark.parametrize("mutation", ["missing_file", "missing_entry", "empty_manifest", "extra_file", "changed_hash", "forged_hash"])
def test_repeated_publication_rejects_changed_evidence(published_evaluation, tmp_path, monkeypatch, mutation):
    import json
    import shutil
    from hashlib import sha256
    from czsc_trader.application import RepositoryContext, ValidationError, evaluate_research_request

    context, request_path, _, result, current = published_evaluation
    # Each fault owns its directory and unpickled result/manifest, while the
    # real public-entry evaluation and immutable publication are created once.
    owner = tmp_path / "publication"
    shutil.copytree(context.root, owner)
    copied_request = owner / request_path.relative_to(context.root)
    copied = copied_request.parent / "artifacts/evaluation"
    copied_context = RepositoryContext.discover(owner)
    _publication_flows(monkeypatch, owner)
    name = "full/research_case/account_daily.csv"
    if mutation in {"missing_file", "missing_entry", "empty_manifest"}:
        (copied / name).unlink()
    if mutation == "missing_entry":
        del current["files"][name]
    elif mutation == "empty_manifest":
        current["files"] = {}
    elif mutation == "extra_file":
        (copied / "unexpected.csv").write_text("unexpected")
    elif mutation in {"changed_hash", "forged_hash"}:
        (copied / name).write_bytes((copied / name).read_bytes() + b" ")
        if mutation == "forged_hash":
            current["files"][name] = sha256((copied / name).read_bytes()).hexdigest()
    (copied / "evaluation_result.json").write_text(json.dumps(current), encoding="utf-8")
    with pytest.raises(ValidationError, match="file set|hash differs") as refused:
        evaluate_research_request(copied_context, copied_request.relative_to(owner))
    assert refused.value.code == "research_evaluation_failed"






@pytest.fixture
def managed_evaluation(candidate_payload, tmp_path, monkeypatch):
    from test_research_contract_upgrade import managed_evaluation as prepare_managed
    return prepare_managed.__wrapped__(candidate_payload, tmp_path, monkeypatch)
