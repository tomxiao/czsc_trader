from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from dataflows import Dataflows, Dataset, DataSpace, ProviderConfig, ProviderBinding, PreparePolicy

from strategy_runtime import (
    StrategyCandidate,
    StrategyInit,
    StrategyRelease,
    StrategyRuntime,
    TradableWindow,
)
from trading_execution_engine import HistoricalExecutor


def _install_candidate_dataflows(monkeypatch, flow, daily, *, base_dir=None, space=None, hfq_factors=None):
    from dataflows.ohlcv_quality import (
        bind_quality_frame, build_quality_evidence, verify_daily_sessions,
    )

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
    ):
        if column not in market:
            market[column] = value
    if "Amount" not in market:
        market["Amount"] = market["Volume"] * (market["High"] + market["Low"]) / 2

    class SyntheticCalendar:
        """Declared weekday calendar and lifecycle for this synthetic provider."""

        def fund_basic(self, *, ts_code, fields):
            listed = pd.to_datetime(market["Date"]).min().strftime("%Y%m%d")
            return pd.DataFrame({"ts_code": [ts_code], "list_date": [listed]})

        def trade_cal(self, *, exchange, start_date, end_date):
            dates = pd.date_range(start_date, end_date)
            return pd.DataFrame({"cal_date": dates.strftime("%Y%m%d"),
                                 "is_open": (dates.weekday < 5).astype(int)})

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
            if dataset == Dataset.ETF_OHLCV.value and hfq_factors is not None:
                for column in ("Open", "High", "Low", "Close"):
                    frame[column] = frame[column] * hfq_factors
                frame["Volume"] = frame["Volume"] / hfq_factors
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
        if dataset == Dataset.ETF_OHLCV.value and hfq_factors is not None:
            metadata["adjustment"] = "hfq"
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
            start_day = pd.Timestamp(request.start).normalize()
            end_day = pd.Timestamp(request.end).normalize()
            anchor_dates = pd.to_datetime(market["Date"]).dt.normalize()
            anchor = market.loc[anchor_dates.between(start_day, end_day)].reset_index(drop=True)
            if dataset == Dataset.ETF_OHLCV.value and hfq_factors is not None:
                anchor = frame.copy()
            calendar = verify_daily_sessions(
                SyntheticCalendar(), request.symbol, anchor,
                start=start_day.date().isoformat(), end=end_day.date().isoformat(),
            )
            evidence = build_quality_evidence(
                anchor, intraday=frame if request.frequency == "30m" else None,
                frequency=request.frequency, expected_dates=calendar["expected_dates"],
            )
            metadata.update(
                daily_session_coverage=calendar,
                ohlcv_quality_evidence=bind_quality_frame(evidence, frame,
                    adjustment=metadata.get("adjustment", "none")),
            )
            frame.attrs.update({key: deepcopy(metadata[key]) for key in (
                "daily_session_coverage", "ohlcv_quality_evidence",
            )})
        return frame, metadata

    from czsc_trader.temp_workspace import create_temporary_directory
    root = base_dir if base_dir is not None else create_temporary_directory(Path.cwd(), "test-dataflows")
    flows = Dataflows(
        base_dir=root, space=space if space is not None else DataSpace(Path("research/S900/assets/data")),
        providers=ProviderConfig(bindings={dataset: ProviderBinding("synthetic", "v1", fetch)
            for dataset in (Dataset.ETF_SHARE_SIZE, Dataset.ETF_OHLCV,
                            Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY,
                            Dataset.TRADING_CALENDAR)}),
    )
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
    from dataflows import canonical_frame_sha256

    payload, package = candidate_payload
    payload["rule"] = {"entry_threshold": 0.5, "exit_threshold": 0.5}
    candidate = StrategyCandidate("S001", "C0001", payload, package)
    sessions = pd.bdate_range("2026-09-14", periods=5)
    inputs = pd.DataFrame({"Date": sessions, "Flow": [.1, .8, .2, .9, 0.]})
    daily = pd.DataFrame({"dt": sessions, "open": 1., "close": 1., "high": 1., "low": 1., "vol": 1000., "amount": 1000.})
    flows = _install_candidate_dataflows(monkeypatch, inputs, daily, base_dir=tmp_path,
        space=DataSpace(Path("research/S001/assets/data")))
    execution_data = _execution_data(flows, tmp_path, sessions)
    execution_frames = (
        ("execution_daily", execution_data.execution_daily),
        ("execution_30m", execution_data.execution_intraday),
    )
    originals = []
    for _, frame in execution_frames:
        assert frame.attrs["daily_session_coverage"]["expected_dates"]
        assert frame.attrs["ohlcv_quality_evidence"]["sessions"]
        originals.append((deepcopy(frame.attrs), canonical_frame_sha256(frame)))
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test-replay'\n", encoding="utf-8")
    (tmp_path / "src/czsc_trader").mkdir(parents=True)
    repository = RepositoryContext.discover(tmp_path)
    from czsc_trader.research_tools.context import ResearchContext, ResearchBatchRef
    from czsc_trader.research_tools.evaluation_access import EvaluationAccess
    context = ResearchContext(ResearchBatchRef("S001"), repository, flows, StrategyRuntime(dataflows=flows), EvaluationAccess(dataflows=flows, strategy_id="S001"))
    # Only the external procurement boundary is replaced; the public API parses,
    # prepares, executes, audits and publishes the actual candidate replay.
    monkeypatch.setattr("czsc_trader.backtesting.service._prepare_backtest_execution_data", lambda **kwargs: execution_data)
    request = BacktestRequest("588080.SH", "etf", sessions[1].date(), sessions[-1].date(), 100_000, 100)
    result = run_backtest(context, candidate, request)
    from czsc_trader.application import BacktestEvaluation
    assert type(result) is BacktestEvaluation
    assert result.manifest["audit"]["status"] == "PASS"
    assert result.manifest["application"]["runtime_engine"] == "srt"
    _, direct = _execute(candidate, tmp_path / "direct", monkeypatch)
    assert result.result.account_daily["equity"].tolist() == pytest.approx(direct.account_daily["equity"].tolist())
    assert len(direct.fills) == 3
    assert not list((tmp_path / "research/S001").rglob("account_daily.csv"))
    for (_, frame), (attrs, digest) in zip(execution_frames, originals):
        assert frame.attrs == attrs
        assert canonical_frame_sha256(frame) == digest
    assert not repository.strategy_root.exists()
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
    flows = _install_candidate_dataflows(monkeypatch, inputs["flow"], daily,
        space=DataSpace(Path("research") / source.strategy_family_id / "data"))
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
    from czsc_trader.research_tools import EvaluationCost, build_assessment_evidence, ResearchContext, ResearchBatchRef
    from czsc_trader.research_tools.evaluation_access import EvaluationAccess
    from czsc_trader.application import RepositoryContext
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
    flows = _install_candidate_dataflows(monkeypatch, inputs, daily, base_dir=root,
        space=DataSpace(Path("research/S900/assets/data")))
    data = _execution_data(flows, root, sessions)
    (root / "src/czsc_trader").mkdir(parents=True)
    (root / "pyproject.toml").write_text("")
    context = ResearchContext(ResearchBatchRef("S900"), RepositoryContext.discover(root), flows,
        StrategyRuntime(dataflows=flows), EvaluationAccess(dataflows=flows, strategy_id="S900"))
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
    flexible = context.evaluation.evaluate(replace(request, costs=(
        EvaluationCost("custom_high", .002, "FORMAL"), EvaluationCost("custom_low", .0005, "SCREENING"),
        EvaluationCost("standard", .001, "STRESS"))))
    assert [(item.scenario_id, item.observation.measurement_tier) for item in flexible.runs] == [
        ("custom_high", "FORMAL"), ("custom_low", "SCREENING"), ("standard", "STRESS")]
    assert flexible.runs[0].observation.cost_drag > flexible.runs[1].observation.cost_drag
    assert flexible.runs[0].observation.total_return < run.observation.total_return
    assert flexible.runs[2].observation.total_return == pytest.approx(run.observation.total_return)
    with pytest.raises(ValueError, match="only FULL execution"):
        context.evaluation.evaluate(replace(request, execution_mode="ACCELERATED"))
    with pytest.raises(ValueError, match="binding belongs to another"):
        context.evaluation.evaluate(replace(request, runtime_binding={**request.runtime_binding, "candidate_id": "S900-C0999"}))
    with pytest.raises(ValueError, match="scenario identities must be unique"):
        context.evaluation.evaluate(replace(request, costs=(EvaluationCost("same", .001), EvaluationCost("same", .002))))
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
def managed_evaluation(candidate_payload, tmp_path, monkeypatch):
    from test_research_contract_upgrade import managed_evaluation as prepare_managed
    return prepare_managed.__wrapped__(candidate_payload, tmp_path, monkeypatch)
