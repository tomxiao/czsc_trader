"""S009 development-pool full-account comparison after the EX13 execution gate."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from czsc_trader.backtesting.execution_data import prepare_backtest_execution_data
from czsc_trader.experiment_archive import validate_experiment_archive
from dataflows import DataRequest, Dataflows, Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentDefinition, ExperimentDependency, ExperimentMode,
    ExperimentOutcome, ExperimentProtocol, ExperimentResult, ExperimentStage,
    ResearchExperiment,
)
from strategy_runtime import (
    ExecutionPolicy, StrategyCandidate, StrategyInit, StrategyRuntime, TradableWindow,
    implementation_sha256,
)
from trading_execution_engine import HistoricalExecutor


EXPERIMENT_ID = "20260926_S009_EX14"
PREDECESSOR = "20260926_S009_EX13"
PREDECESSOR_RECEIPT = "8a93908cef3c59d2b764abccf787fb8acf95fd8b81c89f0a4dce8c1509949071"
START = date(2019, 1, 2)
END = date(2024, 12, 31)
INITIAL_CASH = 1_000_000.0
PROTOTYPES = ("P01", "P02", "P03", "P04")
FEES = (("primary", 0.001), ("stress", 0.003))


class CredentialFlows:
    """Add explicit local credentials to DFLS requests, memoizing identical publications."""

    def __init__(self, env_file: Path) -> None:
        self._inner = Dataflows()
        self._env_file = str(env_file.resolve())
        self._cache = {}

    def fetch(self, request: DataRequest):
        key = (str(request.dataset), request.symbol, request.start, request.end,
               request.required_cutoff, request.frequency, repr(request.coverage),
               repr(sorted((key, repr(value)) for key, value in request.options.items())))
        if key not in self._cache:
            enriched = replace(request, options={**request.options, "env_file": self._env_file})
            self._cache[key] = self._inner.fetch(enriched)
        return self._cache[key]


def _candidate(root: Path, trial: str) -> StrategyCandidate:
    if trial == "BH":
        module, qualname, files, parameters = (
            "strategy_runtime.strategies.s009_ex14_buyhold", "S009BuyHold",
            ("strategies/s009_ex14_buyhold.py",), {},
        )
    else:
        module, qualname, files, parameters = (
            "strategy_runtime.strategies.s009_ex14", "S009PrototypeEx14",
            ("strategies/s009_ex14.py",), {"prototype_id": trial},
        )
    return StrategyCandidate(
        "S009", f"EX14{trial}",
        {"runtime": {"module": module, "qualname": qualname,
                     "contract_version": 1, "source_files": list(files),
                     "source_sha256": implementation_sha256(files, source_root=root)},
         "parameters": parameters},
        root,
    )


def _policy(definition, fee: float) -> ExecutionPolicy:
    settings = dict(definition.execution.settings)
    settings["capital"] = {**settings["capital"], "fee_rate": fee}
    return ExecutionPolicy(definition.execution.policy_type, settings)


def _run(candidate: StrategyCandidate, fee: float, data, flows,
         directory: Path, *, start: date = START, end: date = END):
    runtime = StrategyRuntime()
    definition = runtime.describe(candidate)
    policy = _policy(definition, fee)
    instance = runtime.create(StrategyInit(
        candidate, TradableWindow(start, end), directory, execution_policy=policy,
    ))
    with patch("strategy_runtime.preparation.Dataflows", return_value=flows):
        prepared = instance.prepare_data()
    executor = HistoricalExecutor(
        strategy_reference=instance.identity.reference_id,
        symbol="518880.SH", execution_daily=data.execution_daily,
        execution_intraday=data.execution_intraday,
        evaluation_start=pd.Timestamp(start), evaluation_end=pd.Timestamp(end),
        initial_cash=INITIAL_CASH, execution_policy=policy,
        order_types=instance.definition.capabilities.order_types,
    )
    result = instance.run_window(executor=executor)
    sessions = data.evaluation_sessions
    if len(result.decisions) != len(sessions) or len(result.account_daily) != len(sessions):
        raise ValueError("S009 decisions/account ledger do not cover all evaluation sessions")
    if result.account_daily["cash"].lt(-1e-7).any():
        raise ValueError("S009 account spent more than available cash")
    if not result.orders.loc[result.orders["side"].eq("BUY"), "order_type"].eq("LIMIT").all():
        raise ValueError("S009 buy order is not a limit order")
    if not result.orders.loc[result.orders["side"].eq("SELL"), "order_type"].eq("MARKET").all():
        raise ValueError("S009 sell order is not a market order")
    expected_fees = result.fills["quantity"] * result.fills["price"] * fee
    if not np.allclose(result.fills["fees"], expected_fees, rtol=0, atol=1e-6):
        raise ValueError("S009 actual transaction fees differ from declared policy")
    if result.account_daily["date"].max() > pd.Timestamp(END):
        raise ValueError("sealed validation date was read")
    return result, prepared


def _metric(result, fee: float) -> dict[str, float | int | None]:
    ledger = result.account_daily
    equity = ledger["equity"].astype(float)
    n = len(equity)
    annualized = float((equity.iloc[-1] / INITIAL_CASH) ** (252 / n) - 1)
    peak = equity.cummax().clip(lower=INITIAL_CASH)
    drawdown = float((1 - equity / peak).max())
    closed = result.trades.loc[result.trades["status"].eq("CLOSED")]
    returns = closed["net_return"].astype(float)
    wins, losses = returns[returns.gt(0)], returns[returns.lt(0)]
    pnl = returns * closed["quantity"].astype(float) * closed["entry_price"].astype(float) * (1 + fee)
    positive_pnl, negative_pnl = pnl[pnl.gt(0)].sum(), -pnl[pnl.lt(0)].sum()
    buy_orders = result.orders.loc[result.orders["side"].eq("BUY")]
    unfilled = buy_orders["status"].eq("UNFILLED")
    exposure = ledger["quantity"].astype(float) * ledger["close"].astype(float) / equity
    return {
        "sessions": n,
        "ending_equity": float(equity.iloc[-1]),
        "total_return": float(equity.iloc[-1] / INITIAL_CASH - 1),
        "annualized_return": annualized,
        "max_drawdown": drawdown,
        "calmar": annualized / drawdown if drawdown else None,
        "closed_trades": int(len(closed)),
        "closed_trades_per_year": float(len(closed) * 252 / n),
        "win_loss_ratio": float(wins.mean() / -losses.mean()) if not wins.empty and not losses.empty else None,
        "profit_factor": float(positive_pnl / negative_pnl) if negative_pnl > 0 else None,
        "mean_exposure": float(exposure.mean()),
        "buy_orders": int(len(buy_orders)),
        "unfilled_buy_orders": int(unfilled.sum()),
        "unfilled_buy_rate": float(unfilled.mean()) if len(buy_orders) else None,
        "fill_fees_total": float(result.fills["fees"].sum()),
    }


def _synthetic_precheck() -> None:
    root = Path(__file__).resolve().parent
    repository = root.parents[2]
    validate_experiment_archive(repository / "experiments" / "S009" / PREDECESSOR)
    sessions = pd.bdate_range("2018-01-01", "2019-02-28")
    market = pd.DataFrame({
        "Date": sessions, "Open": 10.0, "High": 10.1, "Low": 9.9,
        "Close": 10.0, "Volume": 100000.0, "Amount": 1_000_000.0,
    })
    calendar = pd.DataFrame({"Date": pd.date_range("2017-01-01", "2019-12-31")})
    calendar["IsOpen"] = (calendar["Date"].dt.weekday < 5).astype(int)

    def provider(request):
        frame = calendar if str(request.dataset) == Dataset.TRADING_CALENDAR.value else market
        frame = frame.loc[frame["Date"].between(request.start, request.end)].copy()
        return frame, {"vendor": "S009_EX14_SYNTHETIC", "synthetic": True,
                       "adjustment": "hfq" if str(request.dataset) == Dataset.ETF_OHLCV.value else "none"}

    flows = Dataflows({Dataset.TRADING_CALENDAR.value: provider,
                       Dataset.ETF_OHLCV.value: provider,
                       Dataset.ETF_UNADJUSTED_DAILY.value: provider})
    candidate = _candidate(root / "runtime" / "strategy_runtime", "BH")
    class SyntheticData:
        execution_daily = market.rename(columns={
            "Date": "dt", "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "vol", "Amount": "amount",
        })
        execution_intraday = pd.DataFrame(columns=["dt", "high", "low"])
        evaluation_sessions = pd.bdate_range("2019-01-02", "2019-02-28")
    temp = repository / ".tmp" / "s009-ex14-preflight" / candidate.runtime_identity_sha256[:16]
    result, _ = _run(candidate, 0.003, SyntheticData(), flows, temp,
                     start=date(2019, 1, 2), end=date(2019, 2, 28))
    buys = result.orders.loc[result.orders["side"].eq("BUY")]
    if len(buys) != 1 or not buys["status"].eq("FILLED").all():
        raise ValueError("same-execution BuyHold synthetic entry failed")
    path = root / "runtime" / "strategy_runtime" / "strategies" / "s009_ex14.py"
    spec = importlib.util.spec_from_file_location("s009_ex14_precheck", path)
    if spec is None or spec.loader is None:
        raise ValueError("S009 successor source is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    policy = pd.DataFrame({
        "Date": sessions,
        "AvailableDate": sessions + pd.offsets.BDay(1),
        "PolicyUncertaintyIndex": 100.0 + np.arange(len(sessions)) * 0.01,
    })
    duplicate = policy["Date"].eq(pd.Timestamp("2018-06-04"))
    policy.loc[duplicate, "AvailableDate"] = pd.Timestamp("2018-06-06")
    inputs = {"adjusted_daily": market, "policy_uncertainty": policy}
    for symbol in module.SHARE_SYMBOLS:
        inputs[f"shares_{symbol}"] = pd.DataFrame({
            "Date": sessions, "TotalShare": 1e9 + np.arange(len(sessions)) * 1000.0,
        })
    history = module.opportunity_history(inputs, SyntheticData.evaluation_sessions, "P02")
    if len(history) != len(SyntheticData.evaluation_sessions):
        raise ValueError("same-day FRED publication consolidation failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S009",
            mode=ExperimentMode.DISCOVERY,
            research_question="Do fixed EX13 opportunity prototypes beat same-execution BuyHold on 2019-2024 full accounts?",
            hypothesis="Causally available domestic liquidity or global policy uncertainty leaves executable subsequent gold gains.",
            falsification_conditions=(
                "No fixed prototype reaches both user hard goals in the development account",
                "Claimed advantage disappears under aligned costs or comes only from isolated years",
                "Execution, data identity, or sealed-data boundary is invalid",
            ),
            development_cutoff=END, random_seed=2026091401,
            allowed_datasets=(
                Dataset.ETF_OHLCV.value, Dataset.ETF_UNADJUSTED_DAILY.value,
                Dataset.ETF_SHARE_SIZE.value, Dataset.US_POLICY_UNCERTAINTY_DAILY.value,
                Dataset.TRADING_CALENDAR.value,
            ),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PROTOTYPE,
                first_principles=(
                    "A return-seeking signal must capture more executable gains than BuyHold after costs",
                    "Risk avoidance is useful only after its lost upside is measured",
                ),
                information_paths=(
                    "Prior ETF share changes -> domestic participation -> gold ETF opportunity",
                    "Strictly prior FRED release -> safe-haven allocation -> gold ETF opportunity",
                ),
                stage_objectives=(
                    "Evaluate four fixed EX13 behaviors and same-execution BuyHold",
                    "Determine annualized-return and maximum-drawdown hard goals on full accounts",
                ),
                observation_metrics=(
                    "closed trade frequency", "Calmar", "win/loss ratio", "profit factor",
                    "mean exposure", "unfilled buy rate", "annual return", "fee sensitivity",
                ),
                methodology=(
                    "Use 2019-01-02 to 2024-12-31 only; no threshold or structure tuning",
                    "Each trial has 1m cash, SRT plans and TXE ledger under 10bp and 30bp fees",
                    "LIMIT buys at previous-close 10% upper band minus one tick; MARKET sells",
                    "BuyHold uses identical order and cost rules with constant full target",
                    "Save complete decisions, orders, fills, trades, account ledgers and identities",
                ),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            dependencies=(ExperimentDependency("numpy", np.__version__),
                          ExperimentDependency("pandas", pd.__version__)),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            subjects=("518880.SH",),
        )

    def synthetic_precheck(self) -> None:
        _synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        if context.predecessors[PREDECESSOR].receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX13 predecessor receipt differs")
        experiment = Path(__file__).resolve().parent
        repository = experiment.parents[2]
        env_file = repository / ".env"
        if not env_file.is_file():
            raise ValueError("research credential file is unavailable")
        flows = CredentialFlows(env_file)
        data = prepare_backtest_execution_data(
            srt_data_root=context.workspace.root, symbol="518880.SH", asset_type="etf",
            start=START, end=END, env_file=env_file, dataflows=flows,
        )
        if data.evaluation_start != pd.Timestamp(START) or data.evaluation_end != pd.Timestamp(END):
            raise ValueError("declared evaluation endpoints are unavailable")
        baseline_root = experiment / "runtime" / "strategy_runtime"
        trial_rows = []
        input_rows = []
        tables = {name: [] for name in ("decisions", "orders", "fills", "trades", "account_daily")}
        annual_rows = []
        decision_sequences = {}
        for trial in ("BH", *PROTOTYPES):
            candidate = _candidate(baseline_root, trial)
            for scenario, fee in FEES:
                result, prepared = _run(
                    candidate, fee, data, flows,
                    context.workspace.path(f"scratch/{trial}_{scenario}/anchor").parent,
                )
                key = f"{trial}_{scenario}"
                decision_sequences[key] = tuple(result.decisions["target_position"].tolist())
                trial_rows.append({"trial": trial, "scenario": scenario, "fee_rate": fee,
                                   **_metric(result, fee)})
                input_rows.append({"trial": trial, "scenario": scenario,
                                   "input": "SRT_PREPARED_INPUTS", "content_sha256": "",
                                   "prepared_identity": prepared.data_identity})
                for table in tables:
                    frame = getattr(result, table).copy()
                    frame.insert(0, "scenario", scenario)
                    frame.insert(0, "trial", trial)
                    tables[table].append(frame)
                ledger = result.account_daily.copy()
                ledger["year"] = pd.to_datetime(ledger["date"]).dt.year
                last_equity = INITIAL_CASH
                for year, group in ledger.groupby("year", sort=True):
                    final_equity = float(group["equity"].iloc[-1])
                    annual_rows.append({"trial": trial, "scenario": scenario,
                                        "year": int(year),
                                        "year_return": final_equity / last_equity - 1.0,
                                        "ending_equity": final_equity})
                    last_equity = final_equity
            if decision_sequences[f"{trial}_primary"] != decision_sequences[f"{trial}_stress"]:
                raise ValueError("fee scenario unexpectedly changed target decisions")
        metrics = pd.DataFrame(trial_rows)
        input_rows.extend({"trial": "DFLS", "scenario": "published",
                           "input": f"{key[0]}|{key[1]}|{key[2]}|{key[3]}|{key[5]}",
                           "content_sha256": result.identity.content_sha256,
                           "prepared_identity": ""}
                          for key, result in flows._cache.items() if result.identity is not None)
        for scenario, _ in FEES:
            baseline = metrics.loc[metrics["trial"].eq("BH") & metrics["scenario"].eq(scenario)].iloc[0]
            mask = metrics["scenario"].eq(scenario)
            metrics.loc[mask, "annualized_vs_buyhold"] = metrics.loc[mask, "annualized_return"] - baseline["annualized_return"]
            metrics.loc[mask, "drawdown_vs_buyhold"] = metrics.loc[mask, "max_drawdown"] - baseline["max_drawdown"]
            metrics.loc[mask, "hard_gate"] = (
                metrics.loc[mask, "annualized_return"].ge(1.5 * baseline["annualized_return"])
                & metrics.loc[mask, "max_drawdown"].lt(baseline["max_drawdown"])
            )
        paths = []
        for name, frame in [("trial_metrics", metrics), ("annual_metrics", pd.DataFrame(annual_rows)),
                            ("input_identities", pd.DataFrame(input_rows))]:
            filename = f"{name}.csv"
            frame.to_csv(context.workspace.path(filename), index=False, lineterminator="\n")
            paths.append((filename, f"S009-{name.replace('_', '-')}") )
        for name, frames in tables.items():
            filename = f"{name}.csv.gz"
            pd.concat(frames, ignore_index=True).to_csv(
                context.workspace.path(filename), index=False, compression="gzip", lineterminator="\n")
            paths.append((filename, f"S009-full-{name.replace('_', '-')}") )
        primary = metrics.loc[metrics["scenario"].eq("primary") & metrics["trial"].ne("BH")]
        qualifiers = primary.loc[primary["hard_gate"], "trial"].tolist()
        summary = {"development_cutoff": END.isoformat(), "data_fingerprint": data.fingerprint,
                   "evaluation_sessions": len(data.evaluation_sessions),
                   "primary_qualifiers": qualifiers,
                   "same_execution_buyhold": True, "sealed_validation_read": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paths.append(("summary.json", "S009-development-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if qualifiers else ExperimentOutcome.FAIL,
            facts={"decision": "DEVELOPMENT_HARD_GATE_PASS" if qualifiers else "NO_DEVELOPMENT_QUALIFIER",
                   "primary_qualifiers": qualifiers, "prototype_count": len(PROTOTYPES),
                   "evaluation_sessions": len(data.evaluation_sessions),
                   "sealed_validation_read": False},
            diagnostics={"cost_scenarios": [fee for _, fee in FEES],
                         "buyhold_annualized_primary": float(metrics.loc[
                             metrics["trial"].eq("BH") & metrics["scenario"].eq("primary"),
                             "annualized_return"].iloc[0]),
                         "data_fingerprint": data.fingerprint},
            artifacts=tuple(context.workspace.register_artifact(path, kind) for path, kind in paths),
        )
