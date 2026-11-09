# Risk ownership: TDR-05
"""Public TDR replay authenticates and applies stock/ETF session limits."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from dataflows import DataSpace
from strategy_runtime import (
    ExecutionPriceBasis, RuntimeContractError, StrategyCandidate, StrategyRuntime,
    implementation_identity,
)

from czsc_trader.application import RepositoryContext
from czsc_trader.backtesting.execution_data import _prepare_backtest_execution_data
from czsc_trader.backtesting.srt_bridge import _validate_execution_binding
from czsc_trader.research_tools.context import ResearchBatchRef, ResearchContext
from czsc_trader.research_tools.evaluation_access import EvaluationAccess
from test_candidate_runtime_execution import _install_candidate_dataflows
from managed_evaluation_support import managed_evaluation as managed_evaluation


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

    def calculate_context_history(self, inputs, context):
        sessions = context.sessions
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


def test_TDR_05_C05_prepared_limits_follow_pricing_units_and_binding_rejects_changed_contract(
    candidate_payload, tmp_path, monkeypatch,
):
    basis = ExecutionPriceBasis.HFQ_RESEARCH
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
