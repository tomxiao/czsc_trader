"""Public TDR replay authenticates and applies stock/ETF session limits."""

from dataclasses import replace
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from dataflows import DataSpace, Dataset
from strategy_runtime import (
    ExecutionPriceBasis, RuntimeContractError, StrategyCandidate, StrategyRuntime,
    implementation_identity,
)
from trading_execution_engine import MarketExecutionRules, SuspensionInformation

from czsc_trader.application import BacktestRequest, RepositoryContext, run_backtest
from czsc_trader.application.errors import ExecutionError
from czsc_trader.backtesting.execution_data import _prepare_backtest_execution_data
from czsc_trader.backtesting.srt_bridge import _validate_execution_binding
from czsc_trader.research_tools import (
    EvaluationBenchmark, EvaluationCost, EvaluationRequest, EvaluationWindow, LimitBuyHold, NextOpenBuyHold,
)
from czsc_trader.research_tools.context import ResearchBatchRef, ResearchContext
from czsc_trader.research_tools.evaluation_access import EvaluationAccess
from test_candidate_runtime_execution import _install_candidate_dataflows
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


_MARKET_CANDIDATE = '''

class MarketReplayFixture(CandidateFixture):
    def __init__(self, parameters):
        from dataclasses import replace
        super().__init__(parameters)
        symbol = parameters.values["symbol"]
        stock = parameters.values["asset_type"] == "stock"
        adjusted = Dataset.STOCK_OHLCV if stock else Dataset.ETF_OHLCV
        raw = Dataset.STOCK_UNADJUSTED_DAILY if stock else Dataset.ETF_UNADJUSTED_DAILY
        requirements = (
            InputRequirement("market", adjusted.value, symbol, "daily", 1, CutoffRule.SIGNAL_SESSION),
            InputRequirement("execution", raw.value, symbol, "daily", 1, CutoffRule.SIGNAL_SESSION),
            InputRequirement("calendar", Dataset.TRADING_CALENDAR.value, "SSE", "daily", 0, CutoffRule.LATEST_AVAILABLE),
        )
        self._definition = replace(
            self._definition, inputs=InputContract(requirements), tradable_symbol=symbol,
            capabilities=RequiredCapabilities((adjusted.value, raw.value, Dataset.TRADING_CALENDAR.value), ("MARKET",)),
        )

    def calculate_history(self, inputs, sessions):
        market = inputs["market"].copy()
        market["Date"] = pd.to_datetime(market["Date"])
        close = market.set_index("Date").reindex(sessions)["Close"]
        target = (close > float(self.definition.parameters.values["threshold"])).astype(float)
        if "exit_date" in self.definition.parameters.values:
            target = (sessions < pd.Timestamp(self.definition.parameters.values["exit_date"])).astype(float)
        return pd.DataFrame({"target_position": target, "fixture_signal": target}, index=sessions)
'''


def _case(candidate_payload, tmp_path, monkeypatch, symbol="588080.SH", *, hfq_factors=None, suspended_dates=()):
    payload, package = candidate_payload
    source = package / "strategies/candidate_fixture.py"
    source.write_text(source.read_text(encoding="utf-8") + _MARKET_CANDIDATE, encoding="utf-8")
    payload["runtime"]["qualname"] = "MarketReplayFixture"
    payload["runtime"]["source_sha256"] = implementation_identity.implementation_sha256(
        ("strategies/candidate_fixture.py",), source_root=package,
    )
    asset = "stock" if symbol == "600722.SH" else "etf"
    payload["parameters"].update(symbol=symbol, asset_type=asset, entry_order_type="MARKET", threshold=0.5)
    dates = pd.bdate_range("2026-08-03", periods=25)
    close = np.r_[np.linspace(0.8, 1.0, 20), 1.1, 1.0, 0.9, 0.95, 1.0]
    daily = pd.DataFrame({"dt": dates, "open": close, "close": close})
    limits = pd.DataFrame({"Date": dates, "DownLimit": 0.1, "UpLimit": 2.0})
    limits.loc[20, "UpLimit"] = 1.1
    flow = pd.DataFrame({"Date": dates, "Flow": 1.0})
    flows = _install_candidate_dataflows(
        monkeypatch, flow, daily, base_dir=tmp_path,
        space=DataSpace(Path("research/S900/assets/data")), price_limits=limits,
        hfq_factors=hfq_factors, asset_type=asset,
        suspended_dates=suspended_dates,
    )
    (tmp_path / "src/czsc_trader").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='market-replay-test'\n", encoding="utf-8")
    repository = RepositoryContext.discover(tmp_path, explicit_root=tmp_path)
    context = ResearchContext(
        ResearchBatchRef("S900"), repository, flows, StrategyRuntime(dataflows=flows),
        EvaluationAccess(dataflows=flows, strategy_id="S900"),
    )
    candidate = StrategyCandidate("S900", "C0001", payload, package)
    return context, candidate, dates, daily, limits


@pytest.mark.parametrize("symbol", ["588080.SH", "600722.SH"])
def test_public_backtest_applies_one_market_contract_to_strategy_and_benchmarks(
    candidate_payload, tmp_path, monkeypatch, symbol,
):
    context, candidate, dates, _, _ = _case(candidate_payload, tmp_path, monkeypatch, symbol)
    if symbol == "588080.SH":
        original_prepare = context.data.prepare

        def prepare_without_status(requests, **kwargs):
            assert all(item.dataset is not Dataset.SECURITY_TRADING_STATUS for item in requests)
            return original_prepare(requests, **kwargs)

        monkeypatch.setattr(context.data, "prepare", prepare_without_status)
    result = run_backtest(context, candidate, BacktestRequest(
        symbol, "stock" if symbol == "600722.SH" else "etf", dates[20].date(), dates[-1].date(), 10000, 100,
    ))
    assert result.manifest["audit"]["status"] == "PASS"
    stock = symbol == "600722.SH"
    assert ("trading_status" in result.execution_data.requests) is stock
    assert result.manifest["execution_data"]["market_security"] == ("CN_STOCK" if stock else "CN_ETF")
    assert result.execution_data.market_rules.suspension_information is (
        SuspensionInformation.PROVIDED if stock else SuspensionInformation.NOT_PROVIDED)
    if not stock:
        assert result.result.account_daily.trading_status.isna().all()
    adjusted = result.execution_data.requests["adjusted_daily"]
    raw = result.execution_data.requests["execution_daily"]
    assert (adjusted.symbol, raw.symbol) == (symbol, symbol)
    assert adjusted.dataset is (Dataset.STOCK_OHLCV if symbol == "600722.SH" else Dataset.ETF_OHLCV)
    assert raw.dataset is (Dataset.STOCK_UNADJUSTED_DAILY if symbol == "600722.SH" else Dataset.ETF_UNADJUSTED_DAILY)
    assert all(item["status"] == "PASS" for item in result.manifest["audit"]["benchmarks"].values())
    ledger = result.result
    assert ledger.orders.iloc[0].status == "UNFILLED"
    assert ledger.orders.iloc[1].status == "FILLED"
    assert ledger.account_daily.iloc[0].cash == 10000
    assert ledger.account_daily.iloc[0].quantity == 0
    assert pd.Timestamp(ledger.fills.iloc[0].fill_time).normalize() == dates[21]
    assert ledger.orders.iloc[1].signal_date == dates[20]
    assert ledger.orders.iloc[0].order_id != ledger.orders.iloc[1].order_id
    assert ledger.fills.fees.sum() > 0
    assert ledger.account_daily.equity.tolist() == pytest.approx(
        (ledger.account_daily.cash + ledger.account_daily.quantity * ledger.account_daily.close).tolist(),
    )
    for prefix in ("buyhold", "ma"):
        benchmark = result.benchmarks
        attempts = getattr(benchmark, f"{prefix}_attempts")
        account = getattr(benchmark, f"{prefix}_account_daily")
        assert attempts.status.tolist() == ["FILLED"]
        assert account.quantity.iloc[0] > 0
        assert getattr(benchmark, f"{prefix}_fills").iloc[0].execution_date == dates[20]
        assert account.equity.tolist() == pytest.approx((account.cash + account.quantity * account.close).tolist())


def test_etf_missing_quotes_are_not_admitted_as_suspended_sessions(candidate_payload, tmp_path, monkeypatch):
    context, candidate, dates, _, _ = _case(candidate_payload, tmp_path, monkeypatch,
                                          suspended_dates=(pd.Timestamp("2026-09-02"),))
    with pytest.raises(ExecutionError, match="execution prices do not cover evaluation sessions.*2026-09-02"):
        run_backtest(context, candidate, BacktestRequest(
            "588080.SH", "etf", dates[20].date(), dates[-1].date(), 10000, 100))


def test_stock_replay_requires_its_status_provider(candidate_payload, tmp_path, monkeypatch):
    from dataflows.errors import DataContractError
    context, candidate, dates, _, _ = _case(candidate_payload, tmp_path, monkeypatch, "600722.SH")

    def unavailable(request):
        raise DataContractError("stock status source unavailable")

    binding = context.data._providers[Dataset.SECURITY_TRADING_STATUS.value]
    monkeypatch.setitem(context.data._providers, Dataset.SECURITY_TRADING_STATUS.value,
                        replace(binding, fetch=unavailable))
    with pytest.raises(ExecutionError, match="trading_status.*stock status source unavailable"):
        run_backtest(context, candidate, BacktestRequest(
            "600722.SH", "stock", dates[20].date(), dates[-1].date(), 10000, 100))


@pytest.mark.parametrize("symbol", ["600722.SH"])
@pytest.mark.parametrize("halt_indices", [(22, 23), (20, 21), (23, 24)], ids=["middle", "start", "end"])
def test_public_daily_replay_retains_suspended_accounts_and_replans_on_resumption(
    candidate_payload, tmp_path, monkeypatch, symbol, halt_indices,
):
    dates = pd.bdate_range("2026-08-03", periods=25)
    context, candidate, _, _, _ = _case(candidate_payload, tmp_path, monkeypatch, symbol,
                                       suspended_dates=tuple(dates[index] for index in halt_indices))
    candidate = StrategyCandidate(candidate.strategy_family_id, candidate.candidate_id,
                                  {**candidate.payload, "parameters": {**candidate.payload["parameters"], "exit_date": dates[21].date().isoformat()}},
                                  candidate.source_root)
    result = run_backtest(context, candidate, BacktestRequest(
        symbol, "stock" if symbol == "600722.SH" else "etf", dates[20].date(), dates[24].date(), 10000, 100,
    ))
    assert result.manifest["audit"]["status"] == "PASS"
    assert all(row["status"] == "PASS" for row in result.manifest["audit"]["benchmarks"].values())
    account = result.result.account_daily.set_index("date")
    assert len(account) == 5
    prior = dates[halt_indices[0] - 1]
    for index in halt_indices:
        day = dates[index]
        if prior in account.index:
            assert account.loc[day, "quantity"] == account.loc[prior, "quantity"]
            assert account.loc[day, "cash"] == account.loc[prior, "cash"]
            assert account.loc[day, "close"] == account.loc[prior, "close"]
        else:
            assert account.loc[day, "quantity"] == 0
            assert account.loc[day, "cash"] == 10000
        assert account.loc[day, "valuation_source_date"] == prior
        assert account.loc[day, "trading_status"] == "SUSPENDED"
    assert not result.result.orders.execution_date.isin(dates[list(halt_indices)]).any()
    if halt_indices == (22, 23):
        assert account.loc[dates[24], "quantity"] == 0
        assert result.result.orders.iloc[-1].execution_date == dates[24]
        assert result.result.orders.iloc[-1].signal_date == dates[21]
        assert result.result.orders.iloc[-1].order_id != result.result.orders.iloc[0].order_id
    from czsc_trader.backtesting.audit_adapter import build_replay_evidence
    from strategy_evaluator import AuditStatus, audit_replay

    evidence = build_replay_evidence(result.signals, result.execution_data, result.result, 10000,
                                     result.metrics["strategy"]["metrics"])
    for field, value in (("valuation_source_date", dates[halt_indices[0]].date().isoformat()),
                         ("close", float(account.loc[dates[halt_indices[0]], "close"]) + 1)):
        rows = [dict(row) for row in evidence.account_daily]
        rows[halt_indices[0] - 20][field] = value
        assert audit_replay(replace(evidence, account_daily=tuple(rows))).status is AuditStatus.FAIL

    request = EvaluationRequest(
        tmp_path, "synthetic", candidate,
        {"candidate_id": candidate.reference_id, "source_files": candidate.payload["runtime"]["source_files"],
         "implementation_sha256": candidate.payload["runtime"]["source_sha256"]},
        symbol, "stock", (EvaluationWindow("full", dates[20].date(), dates[-1].date()),),
        dates[-1].date(), 10000, (EvaluationCost("cost", .001),), result.execution_data,
        benchmark=EvaluationBenchmark(LimitBuyHold(100, .003, .01, .1, 1000000)),
    )
    evaluated = context.evaluation.evaluate(request)
    assert evaluated.runs[0].execution.account_daily.date.tolist() == dates[20:].tolist()
    assert evaluated.runs[0].buyhold.account_daily.date.tolist() == dates[20:].tolist()
    from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence

    validate_evaluation_evidence(serialize_evaluation_evidence(request, evaluated))


@pytest.mark.parametrize("basis", [ExecutionPriceBasis.UNADJUSTED, ExecutionPriceBasis.HFQ_RESEARCH])
def test_prepared_limits_follow_pricing_units_and_binding_rejects_changed_contract(
    candidate_payload, tmp_path, monkeypatch, basis,
):
    factors = np.r_[np.full(21, 2.0), np.full(4, 4.0)]
    context, _, dates, _, _ = _case(candidate_payload, tmp_path, monkeypatch, hfq_factors=factors)
    data = _prepare_backtest_execution_data(
        repository_root=tmp_path, symbol="588080.SH", asset_type="etf",
        start=dates[20].date(), end=dates[-1].date(), dataflows=context.data,
        price_basis=basis,
    )
    _validate_execution_binding(context.data, data, data.prepared)
    first = data.market_rules.for_session(dates[20].date())
    second = data.market_rules.for_session(dates[21].date())
    assert first.up_limit == pytest.approx(1.1)
    assert second.up_limit == pytest.approx(4.0 if basis is ExecutionPriceBasis.HFQ_RESEARCH else 2.0)
    altered = replace(data.market_rules, sessions=tuple(
        replace(item, up_limit=item.up_limit + 0.001) for item in data.market_rules.sessions
    ))
    assert altered.fingerprint != data.market_rules.fingerprint
    with pytest.raises(RuntimeContractError, match="market rules differ"):
        _validate_execution_binding(context.data, replace(data, market_rules=altered), data.prepared)
    changed_identities = {**data.input_identities, "price_limits": "0" * 64}
    with pytest.raises(RuntimeContractError, match="input differs.*price_limits"):
        _validate_execution_binding(context.data, replace(data, input_identities=changed_identities), data.prepared)
    with pytest.raises(RuntimeContractError, match="fingerprint differs"):
        _validate_execution_binding(context.data, replace(data, fingerprint="0" * 64), data.prepared)
    with pytest.raises(ValueError, match="suspension policy"):
        _validate_execution_binding(context.data, replace(data, market_rules=replace(
            data.market_rules, suspension_information=SuspensionInformation.PROVIDED)), data.prepared)
    with pytest.raises(ValueError, match="matching market execution rules"):
        _validate_execution_binding(context.data, replace(data, market_rules=None), data.prepared)
    contract = {**data.market_rules.to_dict(), "contract_version": "UNRECOGNIZED"}
    with pytest.raises(ValueError, match="unsupported market execution contract version"):
        MarketExecutionRules.from_dict(contract)


@pytest.mark.parametrize("basis", [ExecutionPriceBasis.UNADJUSTED, ExecutionPriceBasis.HFQ_RESEARCH])
def test_public_evaluation_records_daily_attempts_and_rejects_tampered_evidence(
    candidate_payload, tmp_path, monkeypatch, basis,
):
    context, candidate, dates, _, _ = _case(
        candidate_payload, tmp_path, monkeypatch,
        hfq_factors=np.r_[np.full(21, 2.0), np.full(4, 4.0)],
    )
    request = EvaluationRequest(
        tmp_path, "synthetic", candidate,
        {"candidate_id": candidate.reference_id,
         "source_files": candidate.payload["runtime"]["source_files"],
         "implementation_sha256": candidate.payload["runtime"]["source_sha256"]},
        "588080.SH", "etf", (EvaluationWindow("full", dates[20].date(), dates[-1].date()),),
        dates[-1].date(), 10000, (EvaluationCost("cost", .001),),
        benchmark=EvaluationBenchmark(NextOpenBuyHold(100)),
        price_basis=basis,
    )
    evaluation = context.evaluation.evaluate(request)
    benchmark = evaluation.runs[0].buyhold
    assert benchmark.attempts.status.tolist() == ["FILLED"]
    assert len(benchmark.orders) == len(benchmark.fills) == 1
    assert benchmark.metrics["closed_trades"] == 0
    from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence

    saved = serialize_evaluation_evidence(request, evaluation)
    validate_evaluation_evidence(saved)
    changed = deepcopy(saved)
    changed["runs"][0]["buyhold"]["attempts"]["data"][0]["status"] = "UNFILLED"
    with pytest.raises(ValueError, match="result hash differs"):
        validate_evaluation_evidence(changed)
    for change in ("none", "missing", "symbol", "price"):
        changed = deepcopy(saved)
        spec = changed["runs"][0]["replay_evidence"]["execution_spec"]
        if change == "none":
            spec["market_rules"] = None
        elif change == "missing":
            del spec["market_rules"]
        elif change == "symbol":
            spec["market_rules"]["symbol"] = "600722.SH"
        else:
            spec["market_rules"]["sessions"][0]["up_limit"] += .001
        with pytest.raises(ValueError, match="market rules differ"):
            validate_evaluation_evidence(changed)


def test_hfq_candidate_inspection_preserves_units_in_prospective_frozen_replay(managed_evaluation, monkeypatch):
    from czsc_trader.application import inspect_candidate
    from czsc_trader.application import inspection_service
    from strategy_manager.freeze_contracts import InspectionCheck, InspectionStatus
    from test_assessment_delivery import fresh_completed
    from test_candidate_freeze import _build_inspection

    research, request = managed_evaluation
    request = replace(request, price_basis=ExecutionPriceBasis.HFQ_RESEARCH,
                      execution_data=None, input_bindings={})
    completed = fresh_completed.__wrapped__((research, request))
    context, inspection_request, _ = _build_inspection(completed)
    pricing = completed[2].execution_data.pricing
    assert pricing.basis is ExecutionPriceBasis.HFQ_RESEARCH
    observed = []
    original = inspection_service.HistoricalExecutor

    def recorded_executor(**kwargs):
        observed.append((kwargs["pricing"], kwargs["market_rules"]))
        return original(**kwargs)

    monkeypatch.setattr(inspection_service, "HistoricalExecutor", recorded_executor)
    report = inspect_candidate(context, inspection_request)
    assert report.status is InspectionStatus.PASS, "\n".join(
        item.detail for item in report.checks if item.status is not InspectionStatus.PASS
    )
    assert observed == [(pricing, completed[2].execution_data.market_rules)]
    checks = {item.check: item.status for item in report.checks}
    assert checks[InspectionCheck.SIGNAL_EQUIVALENCE] is InspectionStatus.PASS
    assert checks[InspectionCheck.LEDGER_EQUIVALENCE] is InspectionStatus.PASS
    assert not context.strategy_root.exists()
