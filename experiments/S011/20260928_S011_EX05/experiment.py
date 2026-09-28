"""S011 EX05: bounded joint H02 search with full SRT/TXE accounts."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import importlib.util
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from czsc_trader.backtesting.execution_data import prepare_backtest_execution_data
from czsc_trader.experiment_archive import validate_experiment_archive
from dataflows import DataRequest, Dataflows, Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)
from strategy_runtime import (
    StrategyCandidate, StrategyInit, StrategyRuntime, TradableWindow,
    implementation_sha256,
)
from trading_execution_engine import HistoricalExecutor


EXPERIMENT_ID = "20260928_S011_EX05"
PREDECESSORS = {
    "20260928_S011_EX02": "5c820f80a763596a80b8faa8340f986372fb252c2684a7c6aed600e0e124c931",
    "20260928_S011_EX03": "fe13686d0a5a4167438ca496716d7a7554b37de875270412d793c8ab39a57e3b",
}
SYMBOL = "159326.SZ"
START = date(2024, 9, 10)
END = date(2026, 9, 24)
INITIAL_CASH = 1_000_000.0
SEED = 2026092805
SHARE_THRESHOLDS = (0.0, 0.02, 0.05)
PULLBACK_CEILINGS = (-0.02, 0.0, 0.02)
MAX_HOLDS = (4, 6, 8, 10)
SEARCH_BUDGET = len(SHARE_THRESHOLDS) * len(PULLBACK_CEILINGS) * len(MAX_HOLDS)


class MemoizedGovernedFlows:
    def __init__(self, port, env_file: Path) -> None:
        self._port = port
        self._env_file = str(env_file.resolve())
        self.results = {}

    def fetch(self, request: DataRequest):
        key = (str(request.dataset), request.symbol, request.start, request.end,
               request.required_cutoff, request.frequency, repr(request.coverage),
               repr(sorted((name, repr(value)) for name, value in request.options.items())))
        if key not in self.results:
            enriched = replace(request, options={**request.options, "env_file": self._env_file})
            self.results[key] = self._port.fetch(enriched)
        return self.results[key]


def _candidate(source_root: Path, trial: int | str, parameters: dict | None = None) -> StrategyCandidate:
    baseline = trial == "BH"
    source = "strategies/s011_ex05_buyhold.py" if baseline else "strategies/s011_ex05.py"
    return StrategyCandidate(
        "S011", f"EX05{trial if baseline else f'T{trial:02d}'}",
        {"runtime": {
            "module": "strategy_runtime.strategies.s011_ex05_buyhold" if baseline else "strategy_runtime.strategies.s011_ex05",
            "qualname": "S011BuyHold" if baseline else "S011H02",
            "contract_version": 1, "source_files": [source],
            "source_sha256": implementation_sha256((source,), source_root=source_root),
        }, "parameters": {} if baseline else parameters}, source_root,
    )


def _run(candidate: StrategyCandidate, data, flows, directory: Path,
         *, start: date = START, end: date = END):
    runtime = StrategyRuntime()
    definition = runtime.describe(candidate)
    policy = definition.execution
    instance = runtime.create(StrategyInit(
        candidate, TradableWindow(start, end), directory, execution_policy=policy,
    ))
    with patch("strategy_runtime.preparation.Dataflows", return_value=flows):
        prepared = instance.prepare_data()
    executor = HistoricalExecutor(
        strategy_reference=instance.identity.reference_id, symbol=SYMBOL,
        execution_daily=data.execution_daily, execution_intraday=data.execution_intraday,
        evaluation_start=pd.Timestamp(start), evaluation_end=pd.Timestamp(end),
        initial_cash=INITIAL_CASH, execution_policy=policy,
        order_types=instance.definition.capabilities.order_types,
    )
    result = instance.run_window(executor=executor)
    sessions = data.evaluation_sessions
    if len(result.decisions) != len(sessions) or len(result.account_daily) != len(sessions):
        raise ValueError("EX05 decision or account ledger misses evaluation sessions")
    if result.account_daily["cash"].lt(-1e-7).any():
        raise ValueError("EX05 account borrowed cash")
    if not result.orders.loc[result.orders["side"].eq("BUY"), "order_type"].eq("LIMIT").all():
        raise ValueError("EX05 buy order is not LIMIT")
    if not result.orders.loc[result.orders["side"].eq("SELL"), "order_type"].eq("MARKET").all():
        raise ValueError("EX05 sell order is not MARKET")
    fees = result.fills["quantity"] * result.fills["price"] * 0.001
    if not np.allclose(result.fills["fees"], fees, rtol=0, atol=1e-6):
        raise ValueError("EX05 fill fees differ from 10bp one-way")
    return result, prepared


def _metrics(result) -> dict[str, float | int]:
    ledger = result.account_daily
    equity = ledger["equity"].astype(float)
    n = len(equity)
    cagr = float((equity.iloc[-1] / INITIAL_CASH) ** (252 / n) - 1)
    drawdown = float((1 - equity / equity.cummax().clip(lower=INITIAL_CASH)).max())
    closed = result.trades.loc[result.trades["status"].eq("CLOSED")]
    buys = result.orders.loc[result.orders["side"].eq("BUY")]
    return {
        "sessions": n, "ending_equity": float(equity.iloc[-1]), "cagr": cagr,
        "max_drawdown": drawdown, "closed_trades": len(closed),
        "closed_per_60": float(60 * len(closed) / n),
        "buy_orders": len(buys), "unfilled_buys": int(buys["status"].eq("UNFILLED").sum()),
        "fees": float(result.fills["fees"].sum()),
        "mean_exposure": float((ledger["quantity"] * ledger["close"] / equity).mean()),
    }


def _gate(metrics: dict, baseline: dict) -> tuple[bool, bool, bool]:
    if baseline["cagr"] > 0:
        return_gate = metrics["cagr"] >= 1.5 * baseline["cagr"]
    else:
        return_gate = metrics["cagr"] > 0 and metrics["ending_equity"] > baseline["ending_equity"]
    risk_gate = metrics["max_drawdown"] < baseline["max_drawdown"]
    frequency_gate = 4 <= metrics["closed_per_60"] <= 6
    return return_gate, risk_gate, frequency_gate


def _synthetic_precheck() -> None:
    root = Path(__file__).resolve().parent
    repository = root.parents[2]
    source = root / "runtime" / "strategy_runtime" / "strategies" / "s011_ex05.py"
    spec = importlib.util.spec_from_file_location("s011_ex05_synthetic", source)
    if spec is None or spec.loader is None:
        raise ValueError("EX05 strategy source is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target_history = module.target_history
    sessions = pd.bdate_range("2024-09-09", "2024-12-31")
    prices = 10.0 + 0.06 * np.arange(len(sessions)) + 0.15 * np.sin(np.arange(len(sessions)))
    market = pd.DataFrame({
        "Date": sessions, "Open": prices, "High": prices + 0.1,
        "Low": prices - 0.1, "Close": prices, "Volume": 100000.0,
        "Amount": prices * 100000.0,
    })
    shares = pd.DataFrame({"Date": sessions[1:],
                           "TotalShare": 1e9 * np.exp(0.005 * np.arange(len(sessions) - 1))})
    calendar = pd.DataFrame({"Date": pd.date_range("2024-08-01", "2025-01-31")})
    calendar["IsOpen"] = (calendar["Date"].dt.weekday < 5).astype(int)
    example = {"adjusted_daily": market, "shares": shares}
    history = target_history(example, sessions, 0.0, 0.02, 4)
    altered = shares.copy()
    changed_day = sessions[20]
    altered.loc[altered["Date"].eq(changed_day), "TotalShare"] *= 1.1
    revised = target_history({**example, "shares": altered}, sessions, 0.0, 0.02, 4)
    if not np.isclose(history.loc[changed_day, "share_growth_10"], revised.loc[changed_day, "share_growth_10"]):
        raise ValueError("H02 same-day share count leaked into T decision")
    if np.isclose(history.loc[sessions[21], "share_growth_10"], revised.loc[sessions[21], "share_growth_10"]):
        raise ValueError("H02 T+1 share publication was not applied")

    def provider(request):
        value = {Dataset.TRADING_CALENDAR.value: calendar,
                 Dataset.ETF_OHLCV.value: market,
                 Dataset.ETF_UNADJUSTED_DAILY.value: market,
                 Dataset.ETF_SHARE_SIZE.value: shares}[str(request.dataset)]
        frame = value.loc[value["Date"].between(request.start, request.end)].copy()
        return frame, {"vendor": "S011_EX05_SYNTHETIC", "synthetic": True,
                       "adjustment": "hfq" if str(request.dataset) == Dataset.ETF_OHLCV.value else "none"}

    flows = Dataflows({dataset: provider for dataset in (
        Dataset.TRADING_CALENDAR.value, Dataset.ETF_OHLCV.value,
        Dataset.ETF_UNADJUSTED_DAILY.value, Dataset.ETF_SHARE_SIZE.value,
    )})
    class SyntheticData:
        execution_daily = market.rename(columns={"Date": "dt", "Open": "open", "High": "high",
                                                  "Low": "low", "Close": "close", "Volume": "vol", "Amount": "amount"})
        execution_intraday = pd.DataFrame(columns=["dt", "high", "low"])
        evaluation_sessions = sessions[sessions >= pd.Timestamp(START)]
    source_root = root / "runtime" / "strategy_runtime"
    for trial, parameters in (("BH", None), (0, {"share_threshold": 0.0,
                                                "pullback_ceiling": 0.02, "max_hold": 4})):
        candidate = _candidate(source_root, trial, parameters)
        temporary = repository / ".tmp" / "s011-ex05-preflight" / candidate.runtime_identity_sha256[:16]
        result, _ = _run(candidate, SyntheticData(), flows, temporary,
                         start=START, end=date(2024, 12, 31))
        if result.orders.empty or result.fills.empty:
            raise ValueError("EX05 synthetic SRT/TXE produced no orders or fills")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question="Can H02 lagged share expansion yield a qualifying executable ETF timing account?",
            hypothesis="Persistent primary-market creations leave subsequent ETF upside, with short price pauses offering entries.",
            falsification_conditions=(
                "No joint parameter point meets return, drawdown and full-sample frequency gates",
                "Execution/data identities or causal share lag fails",
                "Reported advantage depends on unfilled limits or incomplete accounts",
            ),
            development_cutoff=END, random_seed=SEED,
            allowed_datasets=(Dataset.ETF_OHLCV.value, Dataset.ETF_UNADJUSTED_DAILY.value,
                              Dataset.ETF_SHARE_SIZE.value, Dataset.TRADING_CALENDAR.value),
            subjects=(SYMBOL,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PARAMETER_SEARCH,
                first_principles=("Only published ETF shares can inform T-close decisions",
                                  "A return-seeking signal must capture executable upside after costs"),
                information_paths=("T-1 shares -> trailing 10-session expansion -> persistent creations -> next-open ETF demand",),
                stage_objectives=("Jointly search H02 opportunity, entry and exit parameters",
                                  "Measure same-order BuyHold and all complete strategy accounts"),
                observation_metrics=("CAGR", "maximum drawdown", "closed trades per 60 sessions",
                                     "exposure", "unfilled limits", "fees"),
                methodology=(
                    "36 fixed joint grid points: share 0/2/5%, prior-3d return ceiling -2/0/2%, max hold 4/6/8/10",
                    "Primary score: CAGR minus 2x return shortfall, 2x drawdown excess, 0.05x frequency distance",
                    "Hard goals assessed separately: CAGR target, lower drawdown, 4-6 closed trades/60",
                    "All 36 trials and same-cost BuyHold use SRT/TXE, 10bp each side, 0.5% prior-close buy limit, market sell",
                    "Development dates 2024-09-10 to 2026-09-24, 1m starting cash, all orders and account ledgers retained",
                ),
                predecessor_experiment_ids=tuple(PREDECESSORS),
            ),
            dependencies=(ExperimentDependency("numpy", np.__version__),
                          ExperimentDependency("pandas", pd.__version__)),
            capabilities=ExperimentCapabilities(reads_real_returns=True,
                                                searches_parameters=True,
                                                selects_parameters=True),
        )

    def synthetic_precheck(self) -> None:
        _synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        context.require_capability(ExperimentCapability.SEARCH_PARAMETERS)
        context.require_capability(ExperimentCapability.SELECT_PARAMETERS)
        root = Path(__file__).resolve().parent
        repository = root.parents[2]
        for experiment_id, receipt in PREDECESSORS.items():
            if context.predecessors[experiment_id].receipt_sha256 != receipt:
                raise ValueError(f"predecessor receipt differs: {experiment_id}")
            validate_experiment_archive(root.parent / experiment_id)
        env_file = repository / ".env"
        if not env_file.is_file():
            raise ValueError("research data credential file is missing")
        flows = MemoizedGovernedFlows(context.data, env_file)
        data = prepare_backtest_execution_data(
            srt_data_root=context.workspace.root, symbol=SYMBOL, asset_type="etf",
            start=START, end=END, env_file=env_file, dataflows=flows,
        )
        if data.evaluation_start != pd.Timestamp(START) or data.evaluation_end != pd.Timestamp(END):
            raise ValueError("EX05 evaluation endpoints differ from frozen window")
        source_root = root / "runtime" / "strategy_runtime"
        tables = {name: [] for name in ("decisions", "orders", "fills", "trades", "account_daily")}
        records = []
        baseline = None
        number = -1
        for share_threshold, pullback_ceiling, max_hold in (
            (share, pullback, hold)
            for share in SHARE_THRESHOLDS for pullback in PULLBACK_CEILINGS for hold in MAX_HOLDS
        ):
            number += 1
            if baseline is None:
                buyhold = _candidate(source_root, "BH")
                bh_result, bh_prepared = _run(buyhold, data, flows, context.workspace.path("scratch/bh/anchor").parent)
                baseline = _metrics(bh_result)
                baseline["prepared_identity"] = bh_prepared.data_identity
                for name, frames in tables.items():
                    frame = getattr(bh_result, name).copy()
                    frame.insert(0, "trial", "BH")
                    frames.append(frame)
            parameters = {"share_threshold": share_threshold,
                          "pullback_ceiling": pullback_ceiling, "max_hold": max_hold}
            candidate = _candidate(source_root, number, parameters)
            result, prepared = _run(candidate, data, flows,
                                    context.workspace.path(f"scratch/t{number:02d}/anchor").parent)
            metrics = _metrics(result)
            return_gate, risk_gate, frequency_gate = _gate(metrics, baseline)
            frequency_distance = max(0.0, 4 - metrics["closed_per_60"], metrics["closed_per_60"] - 6)
            target_cagr = max(0.0, 1.5 * baseline["cagr"])
            score = (metrics["cagr"] - 2 * max(0.0, target_cagr - metrics["cagr"])
                     - 2 * max(0.0, metrics["max_drawdown"] - baseline["max_drawdown"])
                     - 0.05 * frequency_distance)
            records.append({"trial": number, **parameters, **metrics,
                            "return_gate": return_gate, "risk_gate": risk_gate,
                            "frequency_gate": frequency_gate,
                            "hard_gate": return_gate and risk_gate and frequency_gate,
                            "score": score, "prepared_identity": prepared.data_identity})
            for name, frames in tables.items():
                frame = getattr(result, name).copy()
                frame.insert(0, "trial", number)
                frames.append(frame)
        if number + 1 != SEARCH_BUDGET:
            raise ValueError("EX05 trial count differs from frozen budget")
        trial_frame = pd.DataFrame(records)
        qualifiers = trial_frame.loc[trial_frame["hard_gate"]]
        ranked = qualifiers if not qualifiers.empty else trial_frame
        best = ranked.sort_values("score", ascending=False).iloc[0]
        paths = []
        trial_frame.to_csv(context.workspace.path("search_trial_ledger.csv"), index=False, lineterminator="\n")
        paths.append(("search_trial_ledger.csv", "s011-h02-search-trials"))
        for name, frames in tables.items():
            filename = f"{name}.csv.gz"
            pd.concat(frames, ignore_index=True).to_csv(
                context.workspace.path(filename), index=False, compression="gzip", lineterminator="\n")
            paths.append((filename, f"s011-h02-{name}"))
        identities = [{"dataset": key[0], "symbol": key[1], "start": key[2], "end": key[3],
                       "frequency": key[5], "content_sha256": value.identity.content_sha256}
                      for key, value in flows.results.items() if value.identity is not None]
        pd.DataFrame(identities).to_csv(context.workspace.path("input_identities.csv"), index=False, lineterminator="\n")
        paths.append(("input_identities.csv", "s011-h02-input-identities"))
        import json
        summary = {"decision": "STAGE3_GOALS_MET" if len(qualifiers) else "STAGE3_GOALS_NOT_MET",
                   "search_budget": SEARCH_BUDGET, "qualifying_points": len(qualifiers),
                   "baseline": baseline, "best_trial": int(best["trial"]),
                   "best_metrics": {name: float(best[name]) for name in ("cagr", "max_drawdown", "closed_per_60")},
                   "evaluation_sessions": len(data.evaluation_sessions),
                   "data_fingerprint": data.fingerprint, "actual_workers": 1,
                   "sealed_validation_read": False}
        context.workspace.path("summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        paths.append(("summary.json", "s011-h02-search-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if len(qualifiers) else ExperimentOutcome.FAIL,
            facts={"decision": summary["decision"], "search_trials": SEARCH_BUDGET,
                   "qualifying_points": len(qualifiers), "best_trial": int(best["trial"]),
                   "sealed_validation_read": False},
            diagnostics={"baseline_cagr": baseline["cagr"],
                         "baseline_max_drawdown": baseline["max_drawdown"],
                         "data_fingerprint": data.fingerprint},
            artifacts=tuple(context.workspace.register_artifact(path, role) for path, role in paths),
        )
