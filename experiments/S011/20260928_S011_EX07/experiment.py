"""S011 EX07: focused return-first successor of the EX06 boundary result."""

from __future__ import annotations

from datetime import date
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from czsc_trader.backtesting.execution_data import prepare_backtest_execution_data
from czsc_trader.experiment_archive import validate_experiment_archive
from dataflows import Dataflows, Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)
from strategy_runtime import StrategyCandidate, implementation_sha256


EXPERIMENT_ID = "20260928_S011_EX07"
PREDECESSOR = "20260928_S011_EX06"
PREDECESSOR_RECEIPT = "91e356e5647a96224bfd670ba9c5fe5f1acd40d4beac5d500b6bb81456d90483"
EX05 = "20260928_S011_EX05"
EXPECTED_DATA_FINGERPRINT = "5ff112832469691ee998941c75ff0e74704e901941e5f11b1ca8ef30946e2803"
SYMBOL = "159326.SZ"
START = date(2024, 9, 10)
END = date(2026, 9, 24)
SEED = 2026092807
SHARE_WINDOWS = (15, 20, 25, 30)
MOMENTUM_WINDOWS = (1, 2, 3, 5)
MAX_HOLDS = (5, 7, 10, 14)
SEARCH_BUDGET = len(SHARE_WINDOWS) * len(MOMENTUM_WINDOWS) * len(MAX_HOLDS)
SOURCE_FILES = ("strategies/s011_ex07.py",)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"research source unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidate(source_root: Path, number: int, parameters: dict) -> StrategyCandidate:
    return StrategyCandidate(
        "S011", f"EX07T{number:02d}",
        {"runtime": {
            "module": "strategy_runtime.strategies.s011_ex07",
            "qualname": "S011H02Focused", "contract_version": 1,
            "source_files": list(SOURCE_FILES),
            "source_sha256": implementation_sha256(SOURCE_FILES, source_root=source_root),
        }, "parameters": parameters}, source_root,
    )


def _synthetic_precheck() -> None:
    root = Path(__file__).resolve().parent
    repository = root.parents[2]
    validate_experiment_archive(root.parent / PREDECESSOR)
    prior = _load("s011_ex06_strategy_for_ex07_preflight",
                  root.parent / PREDECESSOR / "runtime" / "strategy_runtime" / "strategies" / "s011_ex06.py")
    current = _load("s011_ex07_strategy_preflight",
                    root / "runtime" / "strategy_runtime" / "strategies" / "s011_ex07.py")
    previous = _load("s011_ex05_evaluator_for_ex07_preflight", root.parent / EX05 / "experiment.py")
    sessions = pd.bdate_range("2024-09-09", "2024-12-31")
    prices = 10.0 + 0.05 * np.arange(len(sessions))
    market = pd.DataFrame({
        "Date": sessions, "Open": prices, "High": prices + 0.1,
        "Low": prices - 0.1, "Close": prices, "Volume": 100000.0,
        "Amount": prices * 100000.0,
    })
    shares = pd.DataFrame({"Date": sessions[1:],
                           "TotalShare": 1e9 * np.exp(0.005 * np.arange(len(sessions) - 1))})
    inputs = {"adjusted_daily": market, "shares": shares}
    earlier = prior.target_history(inputs, sessions, 20, "MOM3_POS", 10)
    anchor = current.target_history(inputs, sessions, 20, 3, 10)
    if not earlier.equals(anchor):
        raise ValueError("EX07 anchor changes the EX06 signal expression")
    altered = shares.copy()
    changed_day = sessions[24]
    altered.loc[altered["Date"].eq(changed_day), "TotalShare"] *= 1.1
    revised = current.target_history({**inputs, "shares": altered}, sessions, 20, 3, 10)
    if not np.isclose(anchor.loc[changed_day, "share_growth"], revised.loc[changed_day, "share_growth"]):
        raise ValueError("EX07 same-day shares leaked into T decision")
    if np.isclose(anchor.loc[sessions[25], "share_growth"], revised.loc[sessions[25], "share_growth"]):
        raise ValueError("EX07 next-day share publication was not applied")
    calendar = pd.DataFrame({"Date": pd.date_range("2024-08-01", "2025-01-31")})
    calendar["IsOpen"] = (calendar["Date"].dt.weekday < 5).astype(int)

    def provider(request):
        value = {Dataset.TRADING_CALENDAR.value: calendar,
                 Dataset.ETF_OHLCV.value: market,
                 Dataset.ETF_UNADJUSTED_DAILY.value: market,
                 Dataset.ETF_SHARE_SIZE.value: shares}[str(request.dataset)]
        frame = value.loc[value["Date"].between(request.start, request.end)].copy()
        return frame, {"vendor": "S011_EX07_SYNTHETIC", "synthetic": True,
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
    candidate = _candidate(source_root, 0, {"share_window": 20, "momentum_window": 3, "max_hold": 10})
    temporary = repository / ".tmp" / "s011-ex07-preflight" / candidate.runtime_identity_sha256[:16]
    result, _ = previous._run(candidate, SyntheticData(), flows, temporary,
                              start=START, end=date(2024, 12, 31))
    if result.orders.empty or result.fills.empty or result.trades.empty:
        raise ValueError("EX07 synthetic SRT/TXE produced no complete trading cycle")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question="Does a preregistered neighborhood beyond EX06's flow/hold boundaries reach H02's full-account return target?",
            hypothesis="Later-stage ETF creations plus short-term price confirmation may preserve more executable upside than EX06's bounded grid.",
            falsification_conditions=(
                "No point reaches the 1.5x BuyHold return target after costs",
                "EX06 anchor signal/account, data identity or causal share publication changes",
                "Any account or order violates the execution policy",
            ),
            development_cutoff=END, random_seed=SEED,
            allowed_datasets=(Dataset.ETF_OHLCV.value, Dataset.ETF_UNADJUSTED_DAILY.value,
                              Dataset.ETF_SHARE_SIZE.value, Dataset.TRADING_CALENDAR.value),
            subjects=(SYMBOL,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PARAMETER_SEARCH,
                first_principles=("An observed search boundary calls for a bounded successor, not retroactive EX06 editing",
                                  "Executable return is the first-stage ranking target"),
                information_paths=("T-1 published ETF shares -> 15/20/25/30-session growth -> short price confirmation -> next-session ETF position",),
                stage_objectives=("Search the joint neighborhood of EX06's highest-return point",
                                  "Keep risk and frequency diagnostic until return passes"),
                observation_metrics=("CAGR", "maximum drawdown", "closed trades per 60 sessions",
                                     "exposure", "unfilled limits", "fees"),
                methodology=(
                    "64 fixed joint points: share windows 15/20/25/30, positive price momentum 1/2/3/5 days, max hold 5/7/10/14",
                    "Rank and select solely by full-account CAGR; no drawdown/frequency penalty",
                    "EX06 20/3/10 anchor must reproduce its full account equity path",
                    "Same-order BuyHold return target remains 1.5x CAGR; lower drawdown and 4-6 closes/60 remain final hard goals",
                    "All 64 trials use SRT/TXE, 10bp each side, 0.5% prior-close LIMIT buy and MARKET sell",
                    "Development dates 2024-09-10 to 2026-09-24, 1m initial cash, complete orders and accounts retained",
                ),
                predecessor_experiment_ids=(PREDECESSOR,),
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
        if context.predecessors[PREDECESSOR].receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX06 predecessor receipt differs")
        root = Path(__file__).resolve().parent
        repository = root.parents[2]
        validate_experiment_archive(root.parent / PREDECESSOR)
        previous = _load("s011_ex05_evaluator_for_ex07_run", root.parent / EX05 / "experiment.py")
        env_file = repository / ".env"
        if not env_file.is_file():
            raise ValueError("research data credential file is missing")
        flows = previous.MemoizedGovernedFlows(context.data, env_file)
        data = prepare_backtest_execution_data(
            srt_data_root=context.workspace.root, symbol=SYMBOL, asset_type="etf",
            start=START, end=END, env_file=env_file, dataflows=flows,
        )
        if data.evaluation_start != pd.Timestamp(START) or data.evaluation_end != pd.Timestamp(END):
            raise ValueError("EX07 evaluation endpoints differ from frozen window")
        if data.fingerprint != EXPECTED_DATA_FINGERPRINT:
            raise ValueError("EX07 development execution data differ from EX06")
        buyhold = previous._candidate(root.parent / EX05 / "runtime" / "strategy_runtime", "BH")
        bh_result, bh_prepared = previous._run(buyhold, data, flows,
                                               context.workspace.path("scratch/bh/anchor").parent)
        baseline = previous._metrics(bh_result)
        prior_summary = json.loads((root.parent / PREDECESSOR / "artifacts" / "summary.json").read_text(encoding="utf-8"))
        if any(not np.isclose(baseline[key], prior_summary["baseline"][key], rtol=0, atol=1e-8)
               for key in ("ending_equity", "cagr", "max_drawdown")):
            raise ValueError("EX07 same-execution BuyHold differs from EX06")
        baseline["prepared_identity"] = bh_prepared.data_identity
        prior_accounts = pd.read_csv(root.parent / PREDECESSOR / "artifacts" / "account_daily.csv.gz")
        anchor_accounts = prior_accounts.loc[prior_accounts["trial"].eq("36")]
        if len(anchor_accounts) != len(data.evaluation_sessions):
            raise ValueError("EX06 anchor account is incomplete")
        tables = {name: [] for name in ("decisions", "orders", "fills", "trades", "account_daily")}
        for name, frames in tables.items():
            frame = getattr(bh_result, name).copy()
            frame.insert(0, "trial", "BH")
            frames.append(frame)
        records = []
        source_root = root / "runtime" / "strategy_runtime"
        number = -1
        for share_window in SHARE_WINDOWS:
            for momentum_window in MOMENTUM_WINDOWS:
                for max_hold in MAX_HOLDS:
                    number += 1
                    parameters = {"share_window": share_window,
                                  "momentum_window": momentum_window, "max_hold": max_hold}
                    candidate = _candidate(source_root, number, parameters)
                    result, prepared = previous._run(
                        candidate, data, flows,
                        context.workspace.path(f"scratch/t{number:02d}/anchor").parent,
                    )
                    if parameters == {"share_window": 20, "momentum_window": 3, "max_hold": 10}:
                        if not np.allclose(result.account_daily["equity"].to_numpy(dtype=float),
                                           anchor_accounts["equity"].to_numpy(dtype=float), rtol=0, atol=1e-6):
                            raise ValueError("EX07 anchor account differs from EX06 trial 36")
                    metrics = previous._metrics(result)
                    return_gate, risk_gate, frequency_gate = previous._gate(metrics, baseline)
                    records.append({"trial": number, **parameters, **metrics,
                                    "return_goal_met": return_gate,
                                    "risk_goal_met": risk_gate,
                                    "frequency_goal_met": frequency_gate,
                                    "all_goals_met": return_gate and risk_gate and frequency_gate,
                                    "prepared_identity": prepared.data_identity})
                    for name, frames in tables.items():
                        frame = getattr(result, name).copy()
                        frame.insert(0, "trial", number)
                        frames.append(frame)
        if number + 1 != SEARCH_BUDGET:
            raise ValueError("EX07 trial count differs from frozen budget")
        trial_frame = pd.DataFrame(records)
        best = trial_frame.sort_values("cagr", ascending=False).iloc[0]
        return_qualifiers = trial_frame.loc[trial_frame["return_goal_met"]]
        full_qualifiers = trial_frame.loc[trial_frame["all_goals_met"]]
        decision = ("ALL_STAGE3_GOALS_MET" if len(full_qualifiers)
                    else "RETURN_GOAL_MET_ONLY" if len(return_qualifiers)
                    else "RETURN_GOAL_NOT_MET")
        paths = []
        trial_frame.to_csv(context.workspace.path("search_trial_ledger.csv"), index=False, lineterminator="\n")
        paths.append(("search_trial_ledger.csv", "s011-h02-focused-trials"))
        for name, frames in tables.items():
            filename = f"{name}.csv.gz"
            pd.concat(frames, ignore_index=True).to_csv(
                context.workspace.path(filename), index=False, compression="gzip", lineterminator="\n")
            paths.append((filename, f"s011-h02-focused-{name}"))
        identities = [{"dataset": key[0], "symbol": key[1], "start": key[2], "end": key[3],
                       "frequency": key[5], "content_sha256": value.identity.content_sha256}
                      for key, value in flows.results.items() if value.identity is not None]
        pd.DataFrame(identities).to_csv(context.workspace.path("input_identities.csv"), index=False, lineterminator="\n")
        paths.append(("input_identities.csv", "s011-h02-focused-input-identities"))
        summary = {
            "decision": decision, "search_budget": SEARCH_BUDGET,
            "return_qualifying_points": len(return_qualifiers),
            "all_goals_qualifying_points": len(full_qualifiers),
            "baseline": baseline, "return_target_cagr": 1.5 * baseline["cagr"] if baseline["cagr"] > 0 else 0,
            "highest_return_trial": int(best["trial"]),
            "highest_return_parameters": {name: int(best[name]) for name in
                                          ("share_window", "momentum_window", "max_hold")},
            "highest_return_metrics": {name: float(best[name]) for name in
                                       ("cagr", "max_drawdown", "closed_per_60")},
            "evaluation_sessions": len(data.evaluation_sessions),
            "data_fingerprint": data.fingerprint, "actual_workers": 1,
            "sealed_validation_read": False,
        }
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8",
        )
        paths.append(("summary.json", "s011-h02-focused-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if len(full_qualifiers) else ExperimentOutcome.FAIL,
            facts={"decision": decision, "search_trials": SEARCH_BUDGET,
                   "return_qualifying_points": len(return_qualifiers),
                   "all_goals_qualifying_points": len(full_qualifiers),
                   "highest_return_trial": int(best["trial"]),
                   "sealed_validation_read": False},
            diagnostics={"baseline_cagr": baseline["cagr"],
                         "baseline_max_drawdown": baseline["max_drawdown"],
                         "data_fingerprint": data.fingerprint},
            artifacts=tuple(context.workspace.register_artifact(path, role) for path, role in paths),
        )
