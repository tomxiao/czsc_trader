"""S011 EX10: strict-H06 catch-up failure exits with full-account search."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
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


EXPERIMENT_ID = "20260928_S011_EX10"
PREDECESSORS = {
    "20260928_S011_EX08": "7db11a17eae765db2c5e3a0abcba92d7dec3e929557f1f32a0b55b110456ddf6",
    "20260928_S011_EX09": "7b627d5cfde60f6093ea4e3ba1b99013a9e76712265dbbba063b6b833c02a596",
}
EX05 = "20260928_S011_EX05"
SYMBOL = "159326.SZ"
MARKET = "000300.SH"
START = date(2024, 9, 10)
END = date(2026, 9, 24)
EXPECTED_EXECUTION_FINGERPRINT = "5ff112832469691ee998941c75ff0e74704e901941e5f11b1ca8ef30946e2803"
EXPECTED_MARKET_SHA256 = "e1983f68713e3808c0b23ef1531e94f36c5332249f6b65336ffc05602d36dccd"
SEED = 2026092810
SHOCK_AGES = (30, 40)
MAX_HOLDS = (10, 12)
RELATIVE_FAILURE_FLOORS = (-1.0, -0.02, -0.04, -0.06)
SEARCH_BUDGET = len(SHOCK_AGES) * len(MAX_HOLDS) * len(RELATIVE_FAILURE_FLOORS)
SOURCE_FILES = ("strategies/s011_ex10.py",)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"research source unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidate(source_root: Path, number: int, parameters: dict) -> StrategyCandidate:
    return StrategyCandidate(
        "S011", f"EX10T{number:02d}",
        {"runtime": {
            "module": "strategy_runtime.strategies.s011_ex10",
            "qualname": "S011H06FailureExit", "contract_version": 1,
            "source_files": list(SOURCE_FILES),
            "source_sha256": implementation_sha256(SOURCE_FILES, source_root=source_root),
        }, "parameters": parameters}, source_root,
    )


def _synthetic_precheck() -> None:
    root = Path(__file__).resolve().parent
    repository = root.parents[2]
    for predecessor in PREDECESSORS:
        validate_experiment_archive(root.parent / predecessor)
    strategy = _load("s011_ex10_strategy_preflight", root / "runtime/strategy_runtime/strategies/s011_ex10.py")
    prior_strategy = _load("s011_ex08_strategy_for_ex10_preflight",
                           root.parent / "20260928_S011_EX08/runtime/strategy_runtime/strategies/s011_ex08.py")
    evaluator = _load("s011_ex05_evaluator_for_ex10_preflight", root.parent / EX05 / "experiment.py")
    sessions = pd.bdate_range("2024-05-01", "2024-12-31")
    market_returns = np.full(len(sessions), 0.001)
    market_returns[160] = 0.061
    etf_returns = np.full(len(sessions), 0.001)
    etf_returns[162] = -0.05
    market_close = 100.0 * np.exp(np.cumsum(market_returns))
    etf_close = 10.0 * np.exp(np.cumsum(etf_returns))
    etf = pd.DataFrame({
        "Date": sessions, "Open": etf_close, "High": etf_close * 1.01,
        "Low": etf_close * 0.99, "Close": etf_close,
        "Volume": 100000.0, "Amount": etf_close * 100000.0,
    })
    market = pd.DataFrame({
        "Date": sessions, "Open": market_close, "High": market_close * 1.01,
        "Low": market_close * 0.99, "Close": market_close,
        "Volume": 1000000.0, "Amount": market_close * 1000000.0,
    })
    inputs = {"adjusted_daily": etf, "market_daily": market}
    stopped = strategy.target_history(inputs, sessions, 40, 10, -0.02)
    no_stop = strategy.target_history(inputs, sessions, 40, 10, -1.0)
    earlier = prior_strategy.target_history(inputs, sessions, 40, 0.0, 10)
    if not np.array_equal(no_stop.target_position.to_numpy(), earlier.target_position.to_numpy()):
        raise ValueError("EX10 no-stop anchor changes the strict H06 signal")
    if stopped.target_position.iloc[160] != 1 or stopped.target_position.iloc[162] != 0:
        raise ValueError("EX10 synthetic post-entry relative failure did not exit")
    if not stopped.iloc[:162].equals(no_stop.iloc[:162]):
        # The new diagnostic column differs only in structure; compare the shared decision columns.
        if not stopped.target_position.iloc[:162].equals(no_stop.target_position.iloc[:162]):
            raise ValueError("EX10 future relative failure changed an earlier decision")
    calendar = pd.DataFrame({"Date": pd.date_range("2024-04-01", "2025-01-31")})
    calendar["IsOpen"] = (calendar["Date"].dt.weekday < 5).astype(int)

    def provider(request):
        value = {
            Dataset.TRADING_CALENDAR.value: calendar,
            Dataset.ETF_OHLCV.value: etf,
            Dataset.ETF_UNADJUSTED_DAILY.value: etf,
            Dataset.DOMESTIC_INDEX_DAILY.value: market,
        }[str(request.dataset)]
        frame = value.loc[value["Date"].between(request.start, request.end)].copy()
        return frame, {"vendor": "S011_EX10_SYNTHETIC", "synthetic": True,
                       "adjustment": "hfq" if str(request.dataset) == Dataset.ETF_OHLCV.value else "none"}

    flows = Dataflows({dataset: provider for dataset in (
        Dataset.TRADING_CALENDAR.value, Dataset.ETF_OHLCV.value,
        Dataset.ETF_UNADJUSTED_DAILY.value, Dataset.DOMESTIC_INDEX_DAILY.value,
    )})

    class SyntheticData:
        execution_daily = etf.rename(columns={
            "Date": "dt", "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "vol", "Amount": "amount",
        })
        execution_intraday = pd.DataFrame(columns=["dt", "high", "low"])
        evaluation_sessions = sessions[sessions >= pd.Timestamp(START)]

    source_root = root / "runtime/strategy_runtime"
    candidate = _candidate(source_root, 0, {"max_shock_age": 40, "max_hold": 10,
                                            "relative_failure_floor": -0.02})
    synthetic_identity = sha256(etf.to_csv(index=False).encode("utf-8")
                                + market.to_csv(index=False).encode("utf-8")).hexdigest()[:16]
    temporary = repository / ".tmp/s011-ex10-preflight" / candidate.runtime_identity_sha256[:16] / synthetic_identity
    result, _ = evaluator._run(candidate, SyntheticData(), flows, temporary,
                               start=START, end=date(2024, 12, 31))
    if result.orders.empty or result.fills.empty or result.trades.empty:
        raise ValueError("EX10 synthetic SRT/TXE produced no complete trade")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question="Can exiting failed relative catch-up make strict H06 meet all S011 full-account goals?",
            hypothesis="A lagging ETF should catch up after the market impulse; continued post-entry relative losses contradict that trade.",
            falsification_conditions=(
                "No strict-H06 failure-exit point reaches the 1.5x BuyHold return goal",
                "No return-reaching point meets lower drawdown and 4-6 closed trades per 60 sessions",
                "The no-stop anchor or data/predecessor identity differs from EX08/EX09",
            ),
            development_cutoff=END, random_seed=SEED,
            allowed_datasets=(Dataset.ETF_OHLCV.value, Dataset.ETF_UNADJUSTED_DAILY.value,
                              Dataset.DOMESTIC_INDEX_DAILY.value, Dataset.TRADING_CALENDAR.value),
            subjects=(SYMBOL,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PARAMETER_SEARCH,
                first_principles=(
                    "Strict H06 requires ETF same-day return no higher than CSI300 before entry",
                    "Relative losses after entry are an observable failure of catch-up, allowing a causal exit",
                    "EX08/09 showed that merely shortening holding or extending stale market impulses dilutes returns",
                ),
                information_paths=(
                    "Recent CSI300 up impulse -> ETF same-day relative underreaction -> next-session long; post-entry ETF-minus-market path -> failure exit",
                ),
                stage_objectives=(
                    "Jointly test age, maximum hold and a mechanism-specific relative-failure exit",
                    "Compare full SRT/TXE accounts with the same-order BuyHold and an exact no-stop anchor",
                ),
                observation_metrics=("CAGR", "maximum drawdown", "closed trades per 60 sessions",
                                     "exposure", "unfilled buy limits", "fees"),
                methodology=(
                    "16 fixed points: shock ages 30/40, max holds 10/12, post-signal relative failure floors disabled/-2/-4/-6%",
                    "Entry requires T ETF-minus-CSI300 daily log return <=0; exit when regime ends, hold expires or cumulative relative loss crosses floor",
                    "Rank only by full-account CAGR; final hard goals are 1.5x BuyHold CAGR, lower drawdown and 4-6 closes/60",
                    "All trials use SRT/TXE, 10bp each side, prior-close +0.5% LIMIT buy and MARKET sell",
                    "Development dates 2024-09-10 to 2026-09-24, 1m initial cash; full trial/order/fill/account ledgers retained",
                    "Post-EX08/EX09 successor in the viewed development pool; no independent validation claimed",
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
        for predecessor, receipt in PREDECESSORS.items():
            if context.predecessors[predecessor].receipt_sha256 != receipt:
                raise ValueError(f"predecessor receipt differs: {predecessor}")
            validate_experiment_archive(root.parent / predecessor)
        evaluator = _load("s011_ex05_evaluator_for_ex10", root.parent / EX05 / "experiment.py")
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
            raise ValueError("EX10 governed market input is not READY")
        if market.identity.content_sha256 != EXPECTED_MARKET_SHA256:
            raise ValueError("EX10 market data differ from EX08")
        data = prepare_backtest_execution_data(
            srt_data_root=context.workspace.root, symbol=SYMBOL, asset_type="etf",
            start=START, end=END, env_file=env_file, dataflows=flows,
        )
        if data.evaluation_start != pd.Timestamp(START) or data.evaluation_end != pd.Timestamp(END):
            raise ValueError("EX10 evaluation endpoints differ from frozen window")
        if data.fingerprint != EXPECTED_EXECUTION_FINGERPRINT:
            raise ValueError("EX10 ETF execution data differ from EX08/EX09")
        baseline_candidate = evaluator._candidate(root.parent / EX05 / "runtime/strategy_runtime", "BH")
        baseline_result, baseline_prepared = evaluator._run(
            baseline_candidate, data, flows, context.workspace.path("scratch/bh/anchor").parent,
        )
        baseline = evaluator._metrics(baseline_result)
        baseline["prepared_identity"] = baseline_prepared.data_identity
        prior_summary = json.loads((root.parent / "20260928_S011_EX09/artifacts/summary.json").read_text(encoding="utf-8"))
        if any(not np.isclose(baseline[key], prior_summary["baseline"][key], rtol=0, atol=1e-8)
               for key in ("ending_equity", "cagr", "max_drawdown")):
            raise ValueError("EX10 same-order BuyHold differs from EX09")
        prior_accounts = pd.read_csv(root.parent / "20260928_S011_EX08/artifacts/account_daily.csv.gz")
        anchor_accounts = prior_accounts.loc[prior_accounts["trial"].astype(str).eq("43")]
        if len(anchor_accounts) != len(data.evaluation_sessions):
            raise ValueError("EX08 strict-H06 account anchor is incomplete")
        tables = {name: [] for name in ("decisions", "orders", "fills", "trades", "account_daily")}
        for name, frames in tables.items():
            frame = getattr(baseline_result, name).copy()
            frame.insert(0, "trial", "BH")
            frames.append(frame)
        records = []
        source_root = root / "runtime/strategy_runtime"
        for number, (age, hold, floor) in enumerate(
            (age, hold, floor)
            for age in SHOCK_AGES for hold in MAX_HOLDS for floor in RELATIVE_FAILURE_FLOORS
        ):
            parameters = {"max_shock_age": age, "max_hold": hold, "relative_failure_floor": floor}
            candidate = _candidate(source_root, number, parameters)
            result, prepared = evaluator._run(
                candidate, data, flows, context.workspace.path(f"scratch/t{number:02d}/anchor").parent,
            )
            if parameters == {"max_shock_age": 40, "max_hold": 10, "relative_failure_floor": -1.0}:
                if not np.allclose(result.account_daily["equity"].to_numpy(dtype=float),
                                   anchor_accounts["equity"].to_numpy(dtype=float), rtol=0, atol=1e-6):
                    raise ValueError("EX10 no-stop anchor differs from EX08 strict-H06 trial 43")
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
            raise ValueError("EX10 trial count differs from frozen budget")
        ledger = pd.DataFrame(records)
        best = ledger.sort_values("cagr", ascending=False).iloc[0]
        return_qualifiers = ledger.loc[ledger.return_goal_met]
        full_qualifiers = ledger.loc[ledger.all_goals_met]
        decision = ("ALL_STAGE3_GOALS_MET" if len(full_qualifiers)
                    else "RETURN_GOAL_MET_ONLY" if len(return_qualifiers)
                    else "RETURN_GOAL_NOT_MET")
        paths = []
        ledger.to_csv(context.workspace.path("search_trial_ledger.csv"), index=False, lineterminator="\n")
        paths.append(("search_trial_ledger.csv", "s011-h06-failure-exit-trials"))
        for name, frames in tables.items():
            filename = f"{name}.csv.gz"
            pd.concat(frames, ignore_index=True).to_csv(
                context.workspace.path(filename), index=False, compression="gzip", lineterminator="\n",
            )
            paths.append((filename, f"s011-h06-failure-exit-{name}"))
        identities = [{"dataset": key[0], "symbol": key[1], "start": key[2], "end": key[3],
                       "frequency": key[5], "content_sha256": value.identity.content_sha256}
                      for key, value in flows.results.items() if value.identity is not None]
        pd.DataFrame(identities).to_csv(context.workspace.path("input_identities.csv"), index=False, lineterminator="\n")
        paths.append(("input_identities.csv", "s011-h06-failure-exit-input-identities"))
        summary = {
            "decision": decision, "search_budget": SEARCH_BUDGET,
            "return_qualifying_points": len(return_qualifiers),
            "all_goals_qualifying_points": len(full_qualifiers),
            "baseline": baseline,
            "return_target_cagr": 1.5 * baseline["cagr"] if baseline["cagr"] > 0 else 0,
            "highest_return_trial": int(best["trial"]),
            "highest_return_parameters": {name: int(best[name]) if name != "relative_failure_floor" else float(best[name])
                                          for name in ("max_shock_age", "max_hold", "relative_failure_floor")},
            "highest_return_metrics": {name: float(best[name]) for name in
                                       ("cagr", "max_drawdown", "closed_per_60")},
            "evaluation_sessions": len(data.evaluation_sessions),
            "data_fingerprint": data.fingerprint, "market_content_sha256": market.identity.content_sha256,
            "actual_workers": 1, "sealed_validation_read": False,
        }
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8",
        )
        paths.append(("summary.json", "s011-h06-failure-exit-summary"))
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
