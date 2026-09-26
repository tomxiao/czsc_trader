"""S009 EX15: bounded joint threshold search on the EX14 P03 mechanism."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import importlib.util
import json
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
from czsc_trader.backtesting.execution_data import prepare_backtest_execution_data
from czsc_trader.experiment_archive import validate_experiment_archive
from dataflows import DataRequest, Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)
from strategy_runtime import StrategyCandidate, implementation_sha256


EXPERIMENT_ID = "20260926_S009_EX15"
PREDECESSOR = "20260926_S009_EX14"
PREDECESSOR_RECEIPT = "710827833597666848097a654f3eb05dfb9cb1249e06bc36881377fa719f453f"
START = date(2019, 1, 2)
END = date(2024, 12, 31)
SEED = 2026091501
SEARCH_BUDGET = 64
INITIAL_ANCHORS = ((0.0, 0.0), (-0.05, -0.25), (0.05, 0.25),
                   (-0.05, 0.25), (0.05, -0.25))
SOURCE_FILES = ("strategies/s009_ex15.py",)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"research source unavailable: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _predecessor_module(root: Path):
    return _load_module("s009_ex14_frozen_evaluation", root / PREDECESSOR / "experiment.py")


def _candidate(source_root: Path, number: int, liquidity: float,
               policy: float) -> StrategyCandidate:
    source_hash = implementation_sha256(SOURCE_FILES, source_root=source_root)
    return StrategyCandidate(
        "S009", f"EX15T{number:03d}",
        {"runtime": {
            "module": "strategy_runtime.strategies.s009_ex15",
            "qualname": "S009PrototypeSearch",
            "contract_version": 1,
            "source_files": list(SOURCE_FILES),
            "source_sha256": source_hash,
        }, "parameters": {
            "prototype_id": "P03",
            "liquidity_threshold": liquidity,
            "policy_threshold": policy,
        }}, source_root,
    )


class MemoizedGovernedFlows:
    """Use the REX-governed DFLS port with explicit credentials and exact-result reuse."""

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


def _synthetic_precheck() -> None:
    root = Path(__file__).resolve().parent
    repository = root.parents[2]
    predecessor = repository / "experiments" / "S009" / PREDECESSOR
    validate_experiment_archive(predecessor)
    previous = _predecessor_module(root.parent)
    original = _load_module(
        "s009_ex14_frozen_runtime",
        predecessor / "runtime" / "strategy_runtime" / "strategies" / "s009_ex14.py",
    )
    successor = _load_module(
        "s009_ex15_search_runtime",
        root / "runtime" / "strategy_runtime" / "strategies" / "s009_ex15.py",
    )
    ex13 = _load_module(
        "s009_ex13_synthetic_source",
        root.parent / "20260926_S009_EX13" / "experiment.py",
    )
    frames = ex13._frames()
    sessions = pd.bdate_range("2019-02-01", "2019-04-30")
    inputs = {
        "adjusted_daily": frames[(Dataset.ETF_OHLCV.value, "518880.SH")],
        "policy_uncertainty": frames[(Dataset.US_POLICY_UNCERTAINTY_DAILY.value, None)],
    }
    for symbol in original.SHARE_SYMBOLS:
        inputs[f"shares_{symbol}"] = frames[(Dataset.ETF_SHARE_SIZE.value, symbol)]
    old = original.opportunity_history(inputs, sessions, "P03")
    new = successor.opportunity_history(inputs, sessions, "P03", 0.0, 0.0)
    if not old.equals(new):
        raise ValueError("EX15 zero thresholds changed EX14 prototype signals")

    market = frames[(Dataset.ETF_UNADJUSTED_DAILY.value, "518880.SH")]
    class SyntheticData:
        execution_daily = market.rename(columns={
            "Date": "dt", "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "vol", "Amount": "amount",
        })
        execution_intraday = pd.DataFrame(columns=["dt", "high", "low"])
        evaluation_sessions = sessions
    source_root = root / "runtime" / "strategy_runtime"
    candidate = _candidate(source_root, 0, 0.0, 0.0)
    temp = repository / ".tmp" / "s009-ex15-preflight" / candidate.runtime_identity_sha256[:16]
    result, _ = previous._run(
        candidate, 0.001, SyntheticData(), ex13._flows(frames), temp,
        start=date(2019, 2, 1), end=date(2019, 4, 30),
    )
    if result.orders.empty or result.fills.empty or result.trades.empty:
        raise ValueError("EX15 synthetic SRT/TXE account did not close trades")


def _annual_rows(result, trial: int, scenario: str):
    ledger = result.account_daily.copy()
    ledger["year"] = pd.to_datetime(ledger["date"]).dt.year
    last_equity = 1_000_000.0
    rows = []
    for year, group in ledger.groupby("year", sort=True):
        ending = float(group["equity"].iloc[-1])
        rows.append({"trial": trial, "scenario": scenario, "year": int(year),
                     "year_return": ending / last_equity - 1.0,
                     "ending_equity": ending})
        last_equity = ending
    return rows


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID,
            strategy_id="S009", mode=ExperimentMode.DISCOVERY,
            research_question="Can joint causal thresholds make P03 exceed 1.5x same-execution BuyHold annualized return with strictly smaller drawdown?",
            hypothesis="Requiring suitable domestic creation and US policy-surprise magnitudes improves residual gold upside capture or reduces unproductive turnover.",
            falsification_conditions=(
                "No evaluated threshold region satisfies both hard goals",
                "Any apparent success depends on a lone unstable point or invalid causal execution",
                "The 0/0 anchor fails to reproduce EX14 P03 account equity",
            ),
            development_cutoff=END, random_seed=SEED,
            allowed_datasets=(Dataset.ETF_OHLCV.value, Dataset.ETF_UNADJUSTED_DAILY.value,
                              Dataset.ETF_SHARE_SIZE.value,
                              Dataset.US_POLICY_UNCERTAINTY_DAILY.value,
                              Dataset.TRADING_CALENDAR.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PARAMETER_SEARCH,
                first_principles=(
                    "Signal magnitude can distinguish incidental changes from tradable allocation shifts",
                    "Exposure and turnover are coupled, so thresholds must be searched jointly",
                ),
                information_paths=(
                    "Lagged broad ETF share growth -> domestic gold participation",
                    "Prior FRED policy uncertainty -> global safe-haven demand",
                ),
                stage_objectives=(
                    "Test whether the EX14 P03 mechanism has a feasible development region",
                    "Preserve all 64 Optuna suggestions and complete full-account ledgers",
                ),
                observation_metrics=(
                    "Calmar", "closed-trade frequency", "win/loss ratio", "profit factor",
                    "exposure", "unfilled buys", "per-year returns", "30bp sensitivity",
                ),
                methodology=(
                    "Joint TPE search over L [-0.10,0.18] step .01 and U [-0.55,0.65] step .05",
                    "64 trials including five fixed anchors, seed 2026091501, InMemoryStorage",
                    "Primary 10bp score = annualized - 2*max(0, drawdown - BuyHold drawdown)",
                    "Hard gate separately requires annualized >= 1.5x BuyHold and drawdown < BuyHold",
                    "Stress-evaluate only the top five distinct primary-score settings at 30bp",
                    "No 2025+ reads or candidate creation; preserve complete trial and account evidence",
                ),
                predecessor_experiment_ids=(PREDECESSOR,),
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
        if context.predecessors[PREDECESSOR].receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX14 predecessor receipt differs")
        context.require_capability(ExperimentCapability.SEARCH_PARAMETERS)
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        experiment = Path(__file__).resolve().parent
        repository = experiment.parents[2]
        predecessor = experiment.parent / PREDECESSOR
        validate_experiment_archive(predecessor)
        previous = _predecessor_module(experiment.parent)
        baseline_metrics = pd.read_csv(predecessor / "artifacts" / "trial_metrics.csv")
        baseline = baseline_metrics.loc[
            baseline_metrics["trial"].eq("BH") & baseline_metrics["scenario"].eq("primary")
        ].iloc[0]
        previous_p03 = pd.read_csv(
            predecessor / "artifacts" / "account_daily.csv.gz", parse_dates=["date"])
        previous_p03 = previous_p03.loc[
            previous_p03["trial"].eq("P03") & previous_p03["scenario"].eq("primary")
        ]
        env_file = repository / ".env"
        if not env_file.is_file():
            raise ValueError("research credential file is unavailable")
        flows = MemoizedGovernedFlows(context.data, env_file)
        data = prepare_backtest_execution_data(
            srt_data_root=context.workspace.root,
            symbol="518880.SH", asset_type="etf", start=START, end=END,
            env_file=env_file, dataflows=flows,
        )
        if data.evaluation_start != pd.Timestamp(START) or data.evaluation_end != pd.Timestamp(END):
            raise ValueError("declared evaluation endpoints are unavailable")
        source_root = experiment / "runtime" / "strategy_runtime"
        sampler = optuna.samplers.TPESampler(seed=SEED, multivariate=True)
        study = optuna.create_study(direction="maximize", sampler=sampler,
                                   storage=optuna.storages.InMemoryStorage())
        for liquidity, policy in INITIAL_ANCHORS:
            study.enqueue_trial({"liquidity_threshold": liquidity,
                                 "policy_threshold": policy})
        records = []
        cache = {}
        account_tables = {name: [] for name in
                          ("decisions", "orders", "fills", "trades", "account_daily")}
        annual_rows = []
        for _ in range(SEARCH_BUDGET):
            trial = study.ask()
            liquidity = round(trial.suggest_float("liquidity_threshold", -0.10, 0.18,
                                                  step=0.01), 2)
            policy = round(trial.suggest_float("policy_threshold", -0.55, 0.65,
                                               step=0.05), 2)
            key = (liquidity, policy)
            reused_from = None
            if key in cache:
                metrics, source_trial, _, _ = cache[key]
                reused_from = source_trial
            else:
                candidate = _candidate(source_root, trial.number, liquidity, policy)
                result, prepared = previous._run(
                    candidate, 0.001, data, flows,
                    context.workspace.path(f"scratch/t{trial.number:03d}/anchor").parent,
                )
                metrics = previous._metric(result, 0.001)
                if trial.number == 0:
                    if key != (0.0, 0.0) or not np.allclose(
                        result.account_daily["equity"].to_numpy(dtype=float),
                        previous_p03["equity"].to_numpy(dtype=float), rtol=0, atol=1e-6,
                    ):
                        raise ValueError("EX15 zero threshold account differs from EX14 P03")
                cache[key] = (metrics, trial.number, result, prepared.data_identity)
                annual_rows.extend(_annual_rows(result, trial.number, "primary"))
                for table, frames in account_tables.items():
                    frame = getattr(result, table).copy()
                    frame.insert(0, "scenario", "primary")
                    frame.insert(0, "trial", trial.number)
                    frames.append(frame)
            score = float(metrics["annualized_return"] - 2 * max(
                0.0, metrics["max_drawdown"] - baseline["max_drawdown"]))
            study.tell(trial, score)
            qualified = bool(metrics["annualized_return"] >= 1.5 * baseline["annualized_return"]
                             and metrics["max_drawdown"] < baseline["max_drawdown"])
            records.append({
                "trial": trial.number, "liquidity_threshold": liquidity,
                "policy_threshold": policy, "reused_from_trial": reused_from,
                "score": score, "hard_gate": qualified, **metrics,
            })
        if len(records) != SEARCH_BUDGET or len(study.trials) != SEARCH_BUDGET:
            raise ValueError("Optuna trial ledger does not match the frozen budget")
        context.require_capability(ExperimentCapability.SELECT_PARAMETERS)
        ranked = sorted(cache.items(), key=lambda item: (
            item[1][0]["annualized_return"] - 2 * max(
                0.0, item[1][0]["max_drawdown"] - baseline["max_drawdown"])),
            reverse=True,
        )[:5]
        stress_rows = []
        for key, (_, source_trial, _, _) in ranked:
            candidate = _candidate(source_root, source_trial, *key)
            result, prepared = previous._run(
                candidate, 0.003, data, flows,
                context.workspace.path(f"scratch/stress_t{source_trial:03d}/anchor").parent,
            )
            stress_rows.append({"trial": source_trial,
                                "liquidity_threshold": key[0],
                                "policy_threshold": key[1],
                                "prepared_identity": prepared.data_identity,
                                **previous._metric(result, 0.003)})
            annual_rows.extend(_annual_rows(result, source_trial, "stress"))
            for table, frames in account_tables.items():
                frame = getattr(result, table).copy()
                frame.insert(0, "scenario", "stress")
                frame.insert(0, "trial", source_trial)
                frames.append(frame)

        trial_frame = pd.DataFrame(records)
        distinct = trial_frame.loc[trial_frame["reused_from_trial"].isna()]
        qualified = distinct.loc[distinct["hard_gate"]]
        paths = []
        for name, frame in (("search_trial_ledger.csv", trial_frame),
                            ("stress_metrics.csv", pd.DataFrame(stress_rows)),
                            ("annual_metrics.csv", pd.DataFrame(annual_rows))):
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n")
            paths.append((name, f"S009-{name.removesuffix('.csv').replace('_', '-')}"))
        for table, frames in account_tables.items():
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
        summary = {
            "search_budget": SEARCH_BUDGET, "distinct_points": len(distinct),
            "qualifying_points": len(qualified),
            "best_score_trial": int(trial_frame.loc[trial_frame["score"].idxmax(), "trial"]),
            "evaluation_sessions": len(data.evaluation_sessions),
            "data_fingerprint": data.fingerprint,
            "sealed_validation_read": False,
        }
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paths.append(("summary.json", "S009-search-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if len(qualified) else ExperimentOutcome.FAIL,
            facts={"decision": "DEVELOPMENT_FEASIBLE_POINTS" if len(qualified)
                   else "NO_FEASIBLE_POINT_IN_FROZEN_SEARCH",
                   "search_trials": SEARCH_BUDGET, "distinct_points": len(distinct),
                   "qualifying_points": len(qualified),
                   "sealed_validation_read": False},
            diagnostics={"best_score_trial": summary["best_score_trial"],
                         "baseline_annualized": float(baseline["annualized_return"]),
                         "baseline_max_drawdown": float(baseline["max_drawdown"]),
                         "data_fingerprint": data.fingerprint,
                         "search_method": "optuna_tpe_inmemory_joint_thresholds"},
            artifacts=tuple(context.workspace.register_artifact(path, kind)
                            for path, kind in paths),
        )
