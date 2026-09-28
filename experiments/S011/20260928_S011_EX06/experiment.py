"""S011 EX06: return-first H02 participation search on full executable accounts."""

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


EXPERIMENT_ID = "20260928_S011_EX06"
PREDECESSOR = "20260928_S011_EX05"
PREDECESSOR_RECEIPT = "20e40d021a57a89b9d550796523381103117d7817a5c43b9ebddd08b47a83f22"
EXPECTED_DATA_FINGERPRINT = "5ff112832469691ee998941c75ff0e74704e901941e5f11b1ca8ef30946e2803"
SYMBOL = "159326.SZ"
START = date(2024, 9, 10)
END = date(2026, 9, 24)
SEED = 2026092806
SHARE_WINDOWS = (5, 10, 20)
ENTRY_MODES = ("ANY", "MOM3_POS", "MOM10_POS", "MOM20_POS")
MAX_HOLDS = (10, 20, 40, 0)
SEARCH_BUDGET = len(SHARE_WINDOWS) * len(ENTRY_MODES) * len(MAX_HOLDS)
SOURCE_FILES = ("strategies/s011_ex06.py",)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"research source unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidate(source_root: Path, number: int, parameters: dict) -> StrategyCandidate:
    return StrategyCandidate(
        "S011", f"EX06T{number:02d}",
        {"runtime": {
            "module": "strategy_runtime.strategies.s011_ex06",
            "qualname": "S011H02ReturnFirst", "contract_version": 1,
            "source_files": list(SOURCE_FILES),
            "source_sha256": implementation_sha256(SOURCE_FILES, source_root=source_root),
        }, "parameters": parameters}, source_root,
    )


def _synthetic_precheck() -> None:
    root = Path(__file__).resolve().parent
    repository = root.parents[2]
    validate_experiment_archive(root.parent / PREDECESSOR)
    previous = _load("s011_ex05_evaluator_for_ex06_preflight", root.parent / PREDECESSOR / "experiment.py")
    strategy = _load("s011_ex06_synthetic_strategy", root / "runtime" / "strategy_runtime" / "strategies" / "s011_ex06.py")
    sessions = pd.bdate_range("2024-09-09", "2024-12-31")
    prices = 10.0 + 0.05 * np.arange(len(sessions))
    market = pd.DataFrame({
        "Date": sessions, "Open": prices, "High": prices + 0.1,
        "Low": prices - 0.1, "Close": prices, "Volume": 100000.0,
        "Amount": prices * 100000.0,
    })
    shares = pd.DataFrame({"Date": sessions[1:],
                           "TotalShare": 1e9 * np.exp(0.005 * np.arange(len(sessions) - 1))})
    test_inputs = {"adjusted_daily": market, "shares": shares}
    for window in SHARE_WINDOWS:
        history = strategy.target_history(test_inputs, sessions, window, "ANY", 10)
        if not history["target_position"].eq(1).any() or not history["target_position"].eq(0).any():
            raise ValueError("EX06 synthetic flow expression has no entry/exit")
    altered = shares.copy()
    changed_day = sessions[24]
    altered.loc[altered["Date"].eq(changed_day), "TotalShare"] *= 1.1
    original = strategy.target_history(test_inputs, sessions, 10, "ANY", 10)
    revised = strategy.target_history({**test_inputs, "shares": altered}, sessions, 10, "ANY", 10)
    if not np.isclose(original.loc[changed_day, "share_growth"], revised.loc[changed_day, "share_growth"]):
        raise ValueError("EX06 same-day shares leaked into T decision")
    if np.isclose(original.loc[sessions[25], "share_growth"], revised.loc[sessions[25], "share_growth"]):
        raise ValueError("EX06 next-day published shares were not applied")
    momentum = strategy.target_history(test_inputs, sessions, 10, "MOM20_POS", 10)
    if momentum["prior_price_momentum"].dropna().le(0).any():
        raise ValueError("EX06 synthetic rising-price momentum is invalid")

    calendar = pd.DataFrame({"Date": pd.date_range("2024-08-01", "2025-01-31")})
    calendar["IsOpen"] = (calendar["Date"].dt.weekday < 5).astype(int)

    def provider(request):
        value = {Dataset.TRADING_CALENDAR.value: calendar,
                 Dataset.ETF_OHLCV.value: market,
                 Dataset.ETF_UNADJUSTED_DAILY.value: market,
                 Dataset.ETF_SHARE_SIZE.value: shares}[str(request.dataset)]
        frame = value.loc[value["Date"].between(request.start, request.end)].copy()
        return frame, {"vendor": "S011_EX06_SYNTHETIC", "synthetic": True,
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
    candidate = _candidate(source_root, 0, {"share_window": 10, "entry_mode": "ANY", "max_hold": 10})
    temporary = repository / ".tmp" / "s011-ex06-preflight" / candidate.runtime_identity_sha256[:16]
    result, _ = previous._run(candidate, SyntheticData(), flows, temporary,
                              start=START, end=date(2024, 12, 31))
    if result.orders.empty or result.fills.empty or result.trades.empty:
        raise ValueError("EX06 synthetic SRT/TXE produced no complete trading cycle")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question="Can wider H02 participation reach the full-account return target before risk/frequency refinement?",
            hypothesis="Lagged ETF share expansion marks persistent demand; fuller participation may capture the upside missed by EX05 short holds.",
            falsification_conditions=(
                "No point reaches the return target after costs on the full development account",
                "Data, same-execution BuyHold, source closure or causal share publication differs",
                "Any apparent return relies on invalid LIMIT/MARKET orders or incomplete account coverage",
            ),
            development_cutoff=END, random_seed=SEED,
            allowed_datasets=(Dataset.ETF_OHLCV.value, Dataset.ETF_UNADJUSTED_DAILY.value,
                              Dataset.ETF_SHARE_SIZE.value, Dataset.TRADING_CALENDAR.value),
            subjects=(SYMBOL,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PARAMETER_SEARCH,
                first_principles=("Sustained creations may leave residual executable demand",
                                  "Search ranking must first test the user return goal"),
                information_paths=("T-1 published ETF shares -> 5/10/20-session expansion -> next-session ETF position",),
                stage_objectives=("Test return-first participation variants of H02",
                                  "Record drawdown and trade frequency without penalizing them in return ranking"),
                observation_metrics=("CAGR", "maximum drawdown", "closed trades per 60 sessions",
                                     "exposure", "unfilled limits", "fees"),
                methodology=(
                    "48 fixed joint points: share windows 5/10/20, entry ANY or positive 3/10/20-day price momentum, max hold 10/20/40/unlimited",
                    "Primary ranking and selection use only full-account CAGR; no drawdown/frequency score penalties",
                    "Return target: CAGR >= 1.5x same-order BuyHold CAGR; if BuyHold CAGR <=0, strategy CAGR >0 and ending equity > BuyHold",
                    "Report but do not optimize risk/frequency until a return-qualifying point exists; final hard goals remain lower drawdown and 4-6 closed trades/60",
                    "All 48 trials and same-execution BuyHold use SRT/TXE, 10bp each side, 0.5% prior-close buy LIMIT, market sell",
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
            raise ValueError("EX05 predecessor receipt differs")
        root = Path(__file__).resolve().parent
        repository = root.parents[2]
        validate_experiment_archive(root.parent / PREDECESSOR)
        previous = _load("s011_ex05_evaluator_for_ex06_run", root.parent / PREDECESSOR / "experiment.py")
        env_file = repository / ".env"
        if not env_file.is_file():
            raise ValueError("research data credential file is missing")
        flows = previous.MemoizedGovernedFlows(context.data, env_file)
        data = prepare_backtest_execution_data(
            srt_data_root=context.workspace.root, symbol=SYMBOL, asset_type="etf",
            start=START, end=END, env_file=env_file, dataflows=flows,
        )
        if data.evaluation_start != pd.Timestamp(START) or data.evaluation_end != pd.Timestamp(END):
            raise ValueError("EX06 evaluation endpoints differ from frozen window")
        if data.fingerprint != EXPECTED_DATA_FINGERPRINT:
            raise ValueError("EX06 development execution data differ from EX05")
        buyhold = previous._candidate(root.parent / PREDECESSOR / "runtime" / "strategy_runtime", "BH")
        bh_result, bh_prepared = previous._run(
            buyhold, data, flows, context.workspace.path("scratch/bh/anchor").parent,
        )
        baseline = previous._metrics(bh_result)
        prior_summary = json.loads((root.parent / PREDECESSOR / "artifacts" / "summary.json").read_text(encoding="utf-8"))
        if any(not np.isclose(baseline[key], prior_summary["baseline"][key], rtol=0, atol=1e-8)
               for key in ("ending_equity", "cagr", "max_drawdown")):
            raise ValueError("EX06 same-execution BuyHold differs from EX05")
        baseline["prepared_identity"] = bh_prepared.data_identity
        tables = {name: [] for name in ("decisions", "orders", "fills", "trades", "account_daily")}
        for name, frames in tables.items():
            frame = getattr(bh_result, name).copy()
            frame.insert(0, "trial", "BH")
            frames.append(frame)
        records = []
        source_root = root / "runtime" / "strategy_runtime"
        number = -1
        for share_window in SHARE_WINDOWS:
            for entry_mode in ENTRY_MODES:
                for max_hold in MAX_HOLDS:
                    number += 1
                    parameters = {"share_window": share_window, "entry_mode": entry_mode,
                                  "max_hold": max_hold}
                    candidate = _candidate(source_root, number, parameters)
                    result, prepared = previous._run(
                        candidate, data, flows,
                        context.workspace.path(f"scratch/t{number:02d}/anchor").parent,
                    )
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
            raise ValueError("EX06 trial count differs from frozen budget")
        trial_frame = pd.DataFrame(records)
        best = trial_frame.sort_values("cagr", ascending=False).iloc[0]
        return_qualifiers = trial_frame.loc[trial_frame["return_goal_met"]]
        full_qualifiers = trial_frame.loc[trial_frame["all_goals_met"]]
        if len(full_qualifiers):
            decision = "ALL_STAGE3_GOALS_MET"
        elif len(return_qualifiers):
            decision = "RETURN_GOAL_MET_ONLY"
        else:
            decision = "RETURN_GOAL_NOT_MET"
        paths = []
        trial_frame.to_csv(context.workspace.path("search_trial_ledger.csv"), index=False, lineterminator="\n")
        paths.append(("search_trial_ledger.csv", "s011-h02-return-first-trials"))
        for name, frames in tables.items():
            filename = f"{name}.csv.gz"
            pd.concat(frames, ignore_index=True).to_csv(
                context.workspace.path(filename), index=False, compression="gzip", lineterminator="\n")
            paths.append((filename, f"s011-h02-return-first-{name}"))
        identities = [{"dataset": key[0], "symbol": key[1], "start": key[2], "end": key[3],
                       "frequency": key[5], "content_sha256": value.identity.content_sha256}
                      for key, value in flows.results.items() if value.identity is not None]
        pd.DataFrame(identities).to_csv(context.workspace.path("input_identities.csv"), index=False, lineterminator="\n")
        paths.append(("input_identities.csv", "s011-h02-return-first-input-identities"))
        summary = {
            "decision": decision, "search_budget": SEARCH_BUDGET,
            "return_qualifying_points": len(return_qualifiers),
            "all_goals_qualifying_points": len(full_qualifiers),
            "baseline": baseline, "return_target_cagr": 1.5 * baseline["cagr"] if baseline["cagr"] > 0 else 0,
            "highest_return_trial": int(best["trial"]),
            "highest_return_parameters": {"share_window": int(best["share_window"]),
                                          "entry_mode": str(best["entry_mode"]),
                                          "max_hold": int(best["max_hold"])},
            "highest_return_metrics": {name: float(best[name]) for name in ("cagr", "max_drawdown", "closed_per_60")},
            "evaluation_sessions": len(data.evaluation_sessions),
            "data_fingerprint": data.fingerprint, "actual_workers": 1,
            "sealed_validation_read": False,
        }
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8",
        )
        paths.append(("summary.json", "s011-h02-return-first-summary"))
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
