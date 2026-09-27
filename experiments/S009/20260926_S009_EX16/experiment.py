"""S009 EX16: bounded checks of the three EX14 prototypes omitted from EX15."""

from __future__ import annotations

from datetime import date
import importlib.util
import json
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
from czsc_trader.backtesting.execution_data import prepare_backtest_execution_data
from czsc_trader.experiment_archive import validate_experiment_archive
from dataflows import Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)
from strategy_runtime import StrategyCandidate, implementation_sha256


EXPERIMENT_ID = "20260926_S009_EX16"
EX14 = "20260926_S009_EX14"
EX15 = "20260926_S009_EX15"
RECEIPTS = {
    EX14: "710827833597666848097a654f3eb05dfb9cb1249e06bc36881377fa719f453f",
    EX15: "4d961be51f966963448227ebb281ddfe918f0731944940ca53d06b7a8dac6f4f",
}
START = date(2019, 1, 2)
END = date(2024, 12, 31)
SEED = 2026091601
SEARCH_BUDGET = 118
PROTOTYPES = ("P01", "P02", "P04")
SOURCE_FILES = ("strategies/s009_ex16.py",)
ANCHORS = ((0.0, 0.0), (-0.05, -0.25), (0.05, 0.25),
           (-0.05, 0.25), (0.05, -0.25))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"research source unavailable: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidate(root: Path, number: int, prototype: str,
               liquidity: float, policy: float) -> StrategyCandidate:
    return StrategyCandidate(
        "S009", f"EX16T{number:03d}",
        {"runtime": {
            "module": "strategy_runtime.strategies.s009_ex16",
            "qualname": "S009PrototypeAlternatives", "contract_version": 1,
            "source_files": list(SOURCE_FILES),
            "source_sha256": implementation_sha256(SOURCE_FILES, source_root=root),
        }, "parameters": {
            "prototype_id": prototype,
            "liquidity_threshold": liquidity,
            "policy_threshold": policy,
        }}, root,
    )


def _synthetic_precheck() -> None:
    root = Path(__file__).resolve().parent
    repository = root.parents[2]
    for experiment_id in (EX14, EX15):
        validate_experiment_archive(root.parent / experiment_id)
    old = _load("s009_ex14_alternatives", root.parent / EX14 / "runtime"
                / "strategy_runtime" / "strategies" / "s009_ex14.py")
    new = _load("s009_ex16_alternatives", root / "runtime"
                / "strategy_runtime" / "strategies" / "s009_ex16.py")
    ex13 = _load("s009_ex13_synthetic_for_ex16", root.parent
                 / "20260926_S009_EX13" / "experiment.py")
    previous = _load("s009_ex14_evaluator_for_ex16", root.parent / EX14 / "experiment.py")
    frames = ex13._frames()
    sessions = pd.bdate_range("2019-02-01", "2019-04-30")
    inputs = {
        "adjusted_daily": frames[(Dataset.ETF_OHLCV.value, "518880.SH")],
        "policy_uncertainty": frames[(Dataset.US_POLICY_UNCERTAINTY_DAILY.value, None)],
    }
    for symbol in old.SHARE_SYMBOLS:
        inputs[f"shares_{symbol}"] = frames[(Dataset.ETF_SHARE_SIZE.value, symbol)]
    market = frames[(Dataset.ETF_UNADJUSTED_DAILY.value, "518880.SH")]

    class SyntheticData:
        execution_daily = market.rename(columns={
            "Date": "dt", "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "vol", "Amount": "amount",
        })
        execution_intraday = pd.DataFrame(columns=["dt", "high", "low"])
        evaluation_sessions = sessions

    source_root = root / "runtime" / "strategy_runtime"
    for number, prototype in enumerate(PROTOTYPES):
        expected = old.opportunity_history(inputs, sessions, prototype)
        actual = new.opportunity_history(inputs, sessions, prototype, 0.0, 0.0)
        if not expected.equals(actual):
            raise ValueError(f"EX16 zero threshold changed EX14 {prototype} signals")
        candidate = _candidate(source_root, number, prototype, 0.0, 0.0)
        temp = repository / ".tmp" / "s009-ex16-preflight" / candidate.runtime_identity_sha256[:16]
        result, _ = previous._run(
            candidate, 0.001, SyntheticData(), ex13._flows(frames), temp,
            start=date(2019, 2, 1), end=date(2019, 4, 30),
        )
        if result.orders.empty or result.fills.empty or result.trades.empty:
            raise ValueError(f"EX16 synthetic SRT/TXE did not close a {prototype} trade")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID,
            strategy_id="S009", mode=ExperimentMode.DISCOVERY,
            research_question="Do the three EX14 alternatives omitted from EX15 have feasible threshold regions against same-execution BuyHold?",
            hypothesis="Signal magnitude may make liquidity-only, policy-only or their conjunction participate in enough gold upside after costs.",
            falsification_conditions=(
                "No evaluated point passes both annualized-return and maximum-drawdown hard goals",
                "A zero-threshold account differs from its EX14 predecessor",
                "Any account or data request breaches the development cutoff or fee contract",
            ),
            development_cutoff=END, random_seed=SEED,
            allowed_datasets=(Dataset.ETF_OHLCV.value, Dataset.ETF_UNADJUSTED_DAILY.value,
                              Dataset.ETF_SHARE_SIZE.value,
                              Dataset.US_POLICY_UNCERTAINTY_DAILY.value,
                              Dataset.TRADING_CALENDAR.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PARAMETER_SEARCH,
                first_principles=(
                    "Threshold magnitude may separate causal allocation changes from noise",
                    "A return-seeking signal must retain enough executable upside after fees",
                ),
                information_paths=(
                    "Lagged broad ETF share changes -> domestic gold participation",
                    "Prior FRED policy release -> global safe-haven gold participation",
                ),
                stage_objectives=(
                    "Check P01 and P02 bounded one-dimensional spaces exhaustively",
                    "Jointly search P04 thresholds under one immutable budget",
                    "Do not infer all-mechanism failure from P03-only evidence",
                ),
                observation_metrics=(
                    "Calmar", "closed-trade frequency", "win/loss ratio", "profit factor",
                    "exposure", "unfilled buys", "per-year returns", "30bp sensitivity",
                ),
                methodology=(
                    "P01: 29 L grid points from -.10 to .18; P02: 25 U grid points from -.55 to .65",
                    "P04: 64 joint TPE suggestions, seed 2026091601, InMemoryStorage",
                    "Primary 10bp score = annualized - 2*max(0, drawdown - BuyHold drawdown)",
                    "Hard gate separately requires annualized >= 1.5x BuyHold and drawdown < BuyHold",
                    "Top five distinct points per prototype receive 30bp stress evaluation",
                    "All 118 suggestions and complete distinct-point TXE account ledgers are retained",
                ),
                predecessor_experiment_ids=(EX14, EX15),
            ),
            dependencies=(ExperimentDependency("numpy", np.__version__),
                          ExperimentDependency("pandas", pd.__version__),
                          ExperimentDependency("optuna", optuna.__version__)),
            capabilities=ExperimentCapabilities(reads_real_returns=True,
                                                searches_parameters=True,
                                                selects_parameters=True),
            subjects=("518880.SH",),
        )

    def synthetic_precheck(self) -> None:
        _synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        for experiment_id, receipt in RECEIPTS.items():
            if context.predecessors[experiment_id].receipt_sha256 != receipt:
                raise ValueError(f"{experiment_id} predecessor receipt differs")
        context.require_capability(ExperimentCapability.SEARCH_PARAMETERS)
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        root = Path(__file__).resolve().parent
        repository = root.parents[2]
        for experiment_id in (EX14, EX15):
            validate_experiment_archive(root.parent / experiment_id)
        previous = _load("s009_ex14_evaluator_ex16", root.parent / EX14 / "experiment.py")
        ex15 = _load("s009_ex15_governed_port_ex16", root.parent / EX15 / "experiment.py")
        baseline_metrics = pd.read_csv(root.parent / EX14 / "artifacts" / "trial_metrics.csv")
        baseline = baseline_metrics.loc[
            baseline_metrics["trial"].eq("BH") & baseline_metrics["scenario"].eq("primary")
        ].iloc[0]
        prior_accounts = pd.read_csv(root.parent / EX14 / "artifacts"
                                     / "account_daily.csv.gz", parse_dates=["date"])
        env_file = repository / ".env"
        if not env_file.is_file():
            raise ValueError("research credential file is unavailable")
        flows = ex15.MemoizedGovernedFlows(context.data, env_file)
        data = prepare_backtest_execution_data(
            srt_data_root=context.workspace.root, symbol="518880.SH", asset_type="etf",
            start=START, end=END, env_file=env_file, dataflows=flows,
        )
        if data.evaluation_start != pd.Timestamp(START) or data.evaluation_end != pd.Timestamp(END):
            raise ValueError("declared evaluation endpoints are unavailable")
        source_root = root / "runtime" / "strategy_runtime"
        tables = {name: [] for name in
                  ("decisions", "orders", "fills", "trades", "account_daily")}
        records = []
        annual_rows = []
        cache = {}

        def evaluate(number: int, prototype: str, liquidity: float, policy: float,
                     optuna_trial=None) -> None:
            key = (prototype, liquidity, policy)
            reused_from = None
            if key in cache:
                metrics, source_trial, _, _ = cache[key]
                reused_from = source_trial
            else:
                candidate = _candidate(source_root, number, prototype, liquidity, policy)
                result, prepared = previous._run(
                    candidate, 0.001, data, flows,
                    context.workspace.path(f"scratch/t{number:03d}/anchor").parent,
                )
                metrics = previous._metric(result, 0.001)
                if (liquidity, policy) == (0.0, 0.0):
                    earlier = prior_accounts.loc[
                        prior_accounts["trial"].eq(prototype)
                        & prior_accounts["scenario"].eq("primary")]
                    if not np.allclose(
                        result.account_daily["equity"].to_numpy(dtype=float),
                        earlier["equity"].to_numpy(dtype=float), rtol=0, atol=1e-6,
                    ):
                        raise ValueError(f"EX16 zero threshold account differs from EX14 {prototype}")
                cache[key] = (metrics, number, result, prepared.data_identity)
                annual_rows.extend(ex15._annual_rows(result, number, "primary"))
                for table, frames in tables.items():
                    frame = getattr(result, table).copy()
                    frame.insert(0, "scenario", "primary")
                    frame.insert(0, "trial", number)
                    frame.insert(0, "prototype", prototype)
                    frames.append(frame)
            score = float(metrics["annualized_return"] - 2 * max(
                0.0, metrics["max_drawdown"] - baseline["max_drawdown"]))
            if optuna_trial is not None:
                study.tell(optuna_trial, score)
            hard_gate = bool(metrics["annualized_return"] >= 1.5 * baseline["annualized_return"]
                             and metrics["max_drawdown"] < baseline["max_drawdown"])
            records.append({"trial": number, "prototype": prototype,
                            "liquidity_threshold": liquidity,
                            "policy_threshold": policy,
                            "reused_from_trial": reused_from,
                            "score": score, "hard_gate": hard_gate, **metrics})

        number = 0
        for index in range(-10, 19):
            evaluate(number, "P01", round(index / 100, 2), 0.0)
            number += 1
        for index in range(-11, 14):
            evaluate(number, "P02", 0.0, round(index / 20, 2))
            number += 1
        sampler = optuna.samplers.TPESampler(seed=SEED, multivariate=True)
        study = optuna.create_study(direction="maximize", sampler=sampler,
                                   storage=optuna.storages.InMemoryStorage())
        for liquidity, policy in ANCHORS:
            study.enqueue_trial({"liquidity_threshold": liquidity,
                                 "policy_threshold": policy})
        for _ in range(64):
            trial = study.ask()
            liquidity = round(trial.suggest_float("liquidity_threshold", -0.10, 0.18,
                                                  step=0.01), 2)
            policy = round(trial.suggest_float("policy_threshold", -0.55, 0.65,
                                               step=0.05), 2)
            evaluate(number, "P04", liquidity, policy, trial)
            number += 1
        if number != SEARCH_BUDGET or len(records) != SEARCH_BUDGET or len(study.trials) != 64:
            raise ValueError("EX16 trial ledger differs from the frozen budget")
        context.require_capability(ExperimentCapability.SELECT_PARAMETERS)
        stress_rows = []
        for prototype in PROTOTYPES:
            ranked = sorted(
                ((key, value) for key, value in cache.items() if key[0] == prototype),
                key=lambda item: item[1][0]["annualized_return"] - 2 * max(
                    0.0, item[1][0]["max_drawdown"] - baseline["max_drawdown"]),
                reverse=True,
            )[:5]
            for key, (_, source_trial, _, _) in ranked:
                candidate = _candidate(source_root, source_trial, *key)
                result, prepared = previous._run(
                    candidate, 0.003, data, flows,
                    context.workspace.path(f"scratch/stress_t{source_trial:03d}/anchor").parent,
                )
                stress_rows.append({"prototype": prototype, "trial": source_trial,
                                    "liquidity_threshold": key[1],
                                    "policy_threshold": key[2],
                                    "prepared_identity": prepared.data_identity,
                                    **previous._metric(result, 0.003)})
                annual_rows.extend(ex15._annual_rows(result, source_trial, "stress"))
                for table, frames in tables.items():
                    frame = getattr(result, table).copy()
                    frame.insert(0, "scenario", "stress")
                    frame.insert(0, "trial", source_trial)
                    frame.insert(0, "prototype", prototype)
                    frames.append(frame)
        trial_frame = pd.DataFrame(records)
        distinct = trial_frame.loc[trial_frame["reused_from_trial"].isna()]
        qualifiers = distinct.loc[distinct["hard_gate"]]
        paths = []
        for name, frame in (("search_trial_ledger.csv", trial_frame),
                            ("stress_metrics.csv", pd.DataFrame(stress_rows)),
                            ("annual_metrics.csv", pd.DataFrame(annual_rows))):
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n")
            paths.append((name, f"S009-{name.removesuffix('.csv').replace('_', '-')}"))
        for table, frames in tables.items():
            name = f"{table}.csv.gz"
            pd.concat(frames, ignore_index=True).to_csv(
                context.workspace.path(name), index=False,
                compression="gzip", lineterminator="\n",
            )
            paths.append((name, f"S009-search-{table.replace('_', '-')}"))
        input_rows = [
            {"dataset": key[0], "symbol": key[1], "start": key[2], "end": key[3],
             "frequency": key[5], "content_sha256": result.identity.content_sha256}
            for key, result in flows.results.items() if result.identity is not None
        ]
        pd.DataFrame(input_rows).to_csv(context.workspace.path("input_identities.csv"),
                                        index=False, lineterminator="\n")
        paths.append(("input_identities.csv", "S009-search-input-identities"))
        qualified_by_prototype = {
            prototype: int(qualifiers["prototype"].eq(prototype).sum())
            for prototype in PROTOTYPES
        }
        summary = {"search_budget": SEARCH_BUDGET,
                   "distinct_points": len(distinct),
                   "qualifying_points": len(qualifiers),
                   "qualified_by_prototype": qualified_by_prototype,
                   "evaluation_sessions": len(data.evaluation_sessions),
                   "data_fingerprint": data.fingerprint,
                   "sealed_validation_read": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paths.append(("summary.json", "S009-alternatives-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if len(qualifiers) else ExperimentOutcome.FAIL,
            facts={"decision": "DEVELOPMENT_FEASIBLE_POINTS" if len(qualifiers)
                   else "NO_FEASIBLE_POINT_IN_FROZEN_ALTERNATIVES",
                   "search_trials": SEARCH_BUDGET,
                   "distinct_points": len(distinct),
                   "qualifying_points": len(qualifiers),
                   "qualified_by_prototype": qualified_by_prototype,
                   "sealed_validation_read": False},
            diagnostics={"baseline_annualized": float(baseline["annualized_return"]),
                         "baseline_max_drawdown": float(baseline["max_drawdown"]),
                         "data_fingerprint": data.fingerprint,
                         "search_method": "P01_P02_EXHAUSTIVE_GRID_P04_TPE"},
            artifacts=tuple(context.workspace.register_artifact(path, kind)
                            for path, kind in paths),
        )
