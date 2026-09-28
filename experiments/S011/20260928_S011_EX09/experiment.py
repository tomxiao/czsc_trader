"""S011 EX09: strict-H06 successor across impulse-age and holding boundaries."""

from __future__ import annotations

from datetime import date
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from czsc_trader.backtesting.execution_data import prepare_backtest_execution_data
from czsc_trader.experiment_archive import validate_experiment_archive
from dataflows import DataRequest, DataStatus, Dataflows, Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)
from strategy_runtime import StrategyCandidate, implementation_sha256


EXPERIMENT_ID = "20260928_S011_EX09"
PREDECESSOR = "20260928_S011_EX08"
PREDECESSOR_RECEIPT = "7db11a17eae765db2c5e3a0abcba92d7dec3e929557f1f32a0b55b110456ddf6"
EX05 = "20260928_S011_EX05"
SYMBOL = "159326.SZ"
MARKET = "000300.SH"
START = date(2024, 9, 10)
END = date(2026, 9, 24)
EXPECTED_EXECUTION_FINGERPRINT = "5ff112832469691ee998941c75ff0e74704e901941e5f11b1ca8ef30946e2803"
EXPECTED_MARKET_SHA256 = "e1983f68713e3808c0b23ef1531e94f36c5332249f6b65336ffc05602d36dccd"
SEED = 2026092809
SHOCK_AGES = (40, 45, 50, 55)
RELATIVE_CEILINGS = (-0.01, 0.0)
MAX_HOLDS = (8, 9, 10)
SEARCH_BUDGET = len(SHOCK_AGES) * len(RELATIVE_CEILINGS) * len(MAX_HOLDS)
SOURCE_FILES = ("strategies/s011_ex08.py",)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"research source unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidate(source_root: Path, number: int, parameters: dict) -> StrategyCandidate:
    return StrategyCandidate(
        "S011", f"EX09T{number:02d}",
        {"runtime": {
            "module": "strategy_runtime.strategies.s011_ex08",
            "qualname": "S011H06", "contract_version": 1,
            "source_files": list(SOURCE_FILES),
            "source_sha256": implementation_sha256(SOURCE_FILES, source_root=source_root),
        }, "parameters": parameters}, source_root,
    )


def _synthetic_precheck() -> None:
    root = Path(__file__).resolve().parent
    validate_experiment_archive(root.parent / PREDECESSOR)
    preceding = _load("s011_ex08_preflight_for_ex09", root.parent / PREDECESSOR / "experiment.py")
    preceding._synthetic_precheck()
    strategy = _load("s011_ex08_strategy_for_ex09_preflight",
                     root.parent / PREDECESSOR / "runtime/strategy_runtime/strategies/s011_ex08.py")
    sessions = pd.bdate_range("2024-09-09", periods=125)
    market_returns = np.full(len(sessions), 0.001)
    market_returns[60] = 0.061
    market_close = 100.0 * np.exp(np.cumsum(market_returns))
    etf_close = 10.0 * np.exp(0.001 * np.arange(len(sessions)))
    market = pd.DataFrame({"Date": sessions, "Close": market_close})
    etf = pd.DataFrame({"Date": sessions, "Close": etf_close})
    narrow = strategy.target_history({"adjusted_daily": etf, "market_daily": market}, sessions, 40, 0.0, 10)
    wide = strategy.target_history({"adjusted_daily": etf, "market_daily": market}, sessions, 50, 0.0, 10)
    if narrow["opportunity"].iloc[105] or not wide["opportunity"].iloc[105]:
        raise ValueError("EX09 expanded H06 shock age is not causally distinguished")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question="Can strict ETF underreaction, with a wider market-impulse age, jointly meet S011 goals?",
            hypothesis="Recent broad-market risk-on may diffuse to a lagging ETF across a wider 40-55-session age range.",
            falsification_conditions=(
                "No strict-underreaction point reaches the 1.5x BuyHold return goal after costs",
                "A return-reaching point misses the required 4-6 closed trades per 60 sessions",
                "Data, SRT/TXE or predecessor identity differs from EX08",
            ),
            development_cutoff=END, random_seed=SEED,
            allowed_datasets=(Dataset.ETF_OHLCV.value, Dataset.ETF_UNADJUSTED_DAILY.value,
                              Dataset.DOMESTIC_INDEX_DAILY.value, Dataset.TRADING_CALENDAR.value),
            subjects=(SYMBOL,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PARAMETER_SEARCH,
                first_principles=(
                    "EX08 strict-underreaction 40/0/10 was near the return target but below the frequency goal",
                    "EX08's only return-reaching +1% entry admitted ETF same-day outperformers, so strict H06 requires <=0",
                    "An older impulse can raise exposure and trade density but weakens a delayed-diffusion explanation",
                ),
                information_paths=(
                    "CSI300 trailing-60 strongest daily return age -> ETF same-day nonpositive excess -> next-session long entry",
                ),
                stage_objectives=(
                    "Search the age/hold neighborhood while retaining strict ETF relative underreaction",
                    "Separate return, drawdown and full-sample closed-trade gates on complete accounts",
                ),
                observation_metrics=("CAGR", "maximum drawdown", "closed trades per 60 sessions",
                                     "exposure", "unfilled buy limits", "fees"),
                methodology=(
                    "24 fixed joint points: shock ages 40/45/50/55, ETF-minus-market ceilings -1/0%, holds 8/9/10",
                    "Same archived EX08 SRT implementation and EX05 evaluator; no new signal family or exit condition",
                    "Rank by full-account CAGR only; lower drawdown and 4-6 closed trades/60 remain separate hard goals",
                    "All trials use SRT/TXE, 10bp each side, prior-close +0.5% LIMIT buy and MARKET sell",
                    "Development dates 2024-09-10 to 2026-09-24, 1m initial cash; full trial/order/fill/account ledgers retained",
                    "Post-EX08 successor in same viewed development pool; no independent validation claimed",
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
            raise ValueError("EX08 predecessor receipt differs")
        root = Path(__file__).resolve().parent
        repository = root.parents[2]
        validate_experiment_archive(root.parent / PREDECESSOR)
        evaluator = _load("s011_ex05_evaluator_for_ex09", root.parent / EX05 / "experiment.py")
        env_file = repository / ".env"
        if not env_file.is_file():
            raise ValueError("research data credential file is missing")
        flows = evaluator.MemoizedGovernedFlows(context.data, env_file)
        market = flows.fetch(DataRequest(
            dataset=Dataset.DOMESTIC_INDEX_DAILY, symbol=MARKET,
            start="2024-09-09", end=END.isoformat(), required_cutoff=END.isoformat(),
            frequency="daily",
        ))
        if market.status is not DataStatus.READY or market.identity is None:
            raise ValueError("EX09 governed market input is not READY")
        if market.identity.content_sha256 != EXPECTED_MARKET_SHA256:
            raise ValueError("EX09 market data differ from EX08")
        data = prepare_backtest_execution_data(
            srt_data_root=context.workspace.root, symbol=SYMBOL, asset_type="etf",
            start=START, end=END, env_file=env_file, dataflows=flows,
        )
        if data.evaluation_start != pd.Timestamp(START) or data.evaluation_end != pd.Timestamp(END):
            raise ValueError("EX09 evaluation endpoints differ from frozen window")
        if data.fingerprint != EXPECTED_EXECUTION_FINGERPRINT:
            raise ValueError("EX09 ETF execution data differ from EX08")
        baseline_candidate = evaluator._candidate(root.parent / EX05 / "runtime/strategy_runtime", "BH")
        baseline_result, baseline_prepared = evaluator._run(
            baseline_candidate, data, flows, context.workspace.path("scratch/bh/anchor").parent,
        )
        baseline = evaluator._metrics(baseline_result)
        baseline["prepared_identity"] = baseline_prepared.data_identity
        prior_summary = json.loads((root.parent / PREDECESSOR / "artifacts/summary.json").read_text(encoding="utf-8"))
        if any(not np.isclose(baseline[key], prior_summary["baseline"][key], rtol=0, atol=1e-8)
               for key in ("ending_equity", "cagr", "max_drawdown")):
            raise ValueError("EX09 same-order BuyHold differs from EX08")
        tables = {name: [] for name in ("decisions", "orders", "fills", "trades", "account_daily")}
        for name, frames in tables.items():
            frame = getattr(baseline_result, name).copy()
            frame.insert(0, "trial", "BH")
            frames.append(frame)
        records = []
        source_root = root.parent / PREDECESSOR / "runtime/strategy_runtime"
        for number, (age, ceiling, hold) in enumerate(
            (age, ceiling, hold)
            for age in SHOCK_AGES for ceiling in RELATIVE_CEILINGS for hold in MAX_HOLDS
        ):
            parameters = {"max_shock_age": age, "relative_ceiling": ceiling, "max_hold": hold}
            candidate = _candidate(source_root, number, parameters)
            result, prepared = evaluator._run(
                candidate, data, flows, context.workspace.path(f"scratch/t{number:02d}/anchor").parent,
            )
            metrics = evaluator._metrics(result)
            return_gate, risk_gate, frequency_gate = evaluator._gate(metrics, baseline)
            records.append({"trial": number, **parameters, **metrics,
                            "return_goal_met": return_gate, "risk_goal_met": risk_gate,
                            "frequency_goal_met": frequency_gate,
                            "all_goals_met": return_gate and risk_gate and frequency_gate,
                            "prepared_identity": prepared.data_identity})
            for name, frames in tables.items():
                frame = getattr(result, name).copy()
                frame.insert(0, "trial", number)
                frames.append(frame)
        if len(records) != SEARCH_BUDGET:
            raise ValueError("EX09 trial count differs from frozen budget")
        ledger = pd.DataFrame(records)
        best = ledger.sort_values("cagr", ascending=False).iloc[0]
        return_qualifiers = ledger.loc[ledger.return_goal_met]
        full_qualifiers = ledger.loc[ledger.all_goals_met]
        decision = ("ALL_STAGE3_GOALS_MET" if len(full_qualifiers)
                    else "RETURN_GOAL_MET_ONLY" if len(return_qualifiers)
                    else "RETURN_GOAL_NOT_MET")
        paths = []
        ledger.to_csv(context.workspace.path("search_trial_ledger.csv"), index=False, lineterminator="\n")
        paths.append(("search_trial_ledger.csv", "s011-h06-strict-successor-trials"))
        for name, frames in tables.items():
            filename = f"{name}.csv.gz"
            pd.concat(frames, ignore_index=True).to_csv(
                context.workspace.path(filename), index=False, compression="gzip", lineterminator="\n",
            )
            paths.append((filename, f"s011-h06-strict-successor-{name}"))
        identities = [{"dataset": key[0], "symbol": key[1], "start": key[2], "end": key[3],
                       "frequency": key[5], "content_sha256": value.identity.content_sha256}
                      for key, value in flows.results.items() if value.identity is not None]
        pd.DataFrame(identities).to_csv(context.workspace.path("input_identities.csv"), index=False, lineterminator="\n")
        paths.append(("input_identities.csv", "s011-h06-strict-successor-input-identities"))
        summary = {
            "decision": decision, "search_budget": SEARCH_BUDGET,
            "return_qualifying_points": len(return_qualifiers),
            "all_goals_qualifying_points": len(full_qualifiers),
            "baseline": baseline,
            "return_target_cagr": 1.5 * baseline["cagr"] if baseline["cagr"] > 0 else 0,
            "highest_return_trial": int(best["trial"]),
            "highest_return_parameters": {name: int(best[name]) if name != "relative_ceiling" else float(best[name])
                                          for name in ("max_shock_age", "relative_ceiling", "max_hold")},
            "highest_return_metrics": {name: float(best[name]) for name in
                                       ("cagr", "max_drawdown", "closed_per_60")},
            "evaluation_sessions": len(data.evaluation_sessions),
            "data_fingerprint": data.fingerprint, "market_content_sha256": market.identity.content_sha256,
            "actual_workers": 1, "sealed_validation_read": False,
        }
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8",
        )
        paths.append(("summary.json", "s011-h06-strict-successor-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if len(full_qualifiers) else ExperimentOutcome.FAIL,
            facts={"decision": decision, "search_trials": SEARCH_BUDGET,
                   "return_qualifying_points": len(return_qualifiers),
                   "all_goals_qualifying_points": len(full_qualifiers),
                   "highest_return_trial": int(best["trial"]), "sealed_validation_read": False},
            diagnostics={"baseline_cagr": baseline["cagr"],
                         "baseline_max_drawdown": baseline["max_drawdown"],
                         "data_fingerprint": data.fingerprint},
            artifacts=tuple(context.workspace.register_artifact(path, role) for path, role in paths),
        )
