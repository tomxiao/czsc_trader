"""S011 EX08: H06 market-impulse/ETF-catch-up joint search."""

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


EXPERIMENT_ID = "20260928_S011_EX08"
PREDECESSORS = {
    "20260928_S011_EX03": "fe13686d0a5a4167438ca496716d7a7554b37de875270412d793c8ab39a57e3b",
    "20260928_S011_EX07": "2a4b10c0844c6ed6a7330e3e93138e33b7bbdd621e6a016775225b3a3a2a534b",
}
EX05 = "20260928_S011_EX05"
SYMBOL = "159326.SZ"
MARKET = "000300.SH"
START = date(2024, 9, 10)
END = date(2026, 9, 24)
EXPECTED_EXECUTION_FINGERPRINT = "5ff112832469691ee998941c75ff0e74704e901941e5f11b1ca8ef30946e2803"
EXPECTED_MARKET_SHA256 = "e1983f68713e3808c0b23ef1531e94f36c5332249f6b65336ffc05602d36dccd"
SEED = 2026092808
SHOCK_AGES = (10, 20, 30, 40)
RELATIVE_CEILINGS = (-0.01, 0.0, 0.01)
MAX_HOLDS = (3, 5, 7, 10)
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
        "S011", f"EX08T{number:02d}",
        {"runtime": {
            "module": "strategy_runtime.strategies.s011_ex08",
            "qualname": "S011H06", "contract_version": 1,
            "source_files": list(SOURCE_FILES),
            "source_sha256": implementation_sha256(SOURCE_FILES, source_root=source_root),
        }, "parameters": parameters}, source_root,
    )


def _synthetic_precheck() -> None:
    root = Path(__file__).resolve().parent
    repository = root.parents[2]
    strategy = _load("s011_ex08_preflight", root / "runtime/strategy_runtime/strategies/s011_ex08.py")
    evaluator = _load("s011_ex05_evaluator_for_ex08_preflight", root.parent / EX05 / "experiment.py")
    sessions = pd.bdate_range("2024-05-01", "2024-12-31")
    market_returns = np.full(len(sessions), 0.001)
    market_returns[160] = 0.061
    market_close = 100.0 * np.exp(np.cumsum(market_returns))
    etf_close = 10.0 * np.exp(0.001 * np.arange(len(sessions)))
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
    history = strategy.target_history({"adjusted_daily": etf, "market_daily": market}, sessions, 30, 0.0, 5)
    if history["opportunity"].iloc[:60].any() or not history["opportunity"].iloc[160]:
        raise ValueError("H06 60-session shock window is misaligned")
    if not history["underreaction"].iloc[160] or history["target_position"].iloc[160] != 1:
        raise ValueError("H06 synthetic impulse/underreaction did not enter")
    shifted = market.copy()
    shifted.loc[161, "Close"] *= 1.08
    changed = strategy.target_history({"adjusted_daily": etf, "market_daily": shifted}, sessions, 30, 0.0, 5)
    if not history.iloc[:161].equals(changed.iloc[:161]):
        raise ValueError("H06 future market close changed an earlier decision")
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
        return frame, {"vendor": "S011_EX08_SYNTHETIC", "synthetic": True,
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
    candidate = _candidate(source_root, 0, {"max_shock_age": 30, "relative_ceiling": 0.0, "max_hold": 5})
    synthetic_identity = sha256(market.to_csv(index=False).encode("utf-8")).hexdigest()[:16]
    temporary = repository / ".tmp/s011-ex08-preflight" / candidate.runtime_identity_sha256[:16] / synthetic_identity
    result, _ = evaluator._run(candidate, SyntheticData(), flows, temporary,
                               start=START, end=date(2024, 12, 31))
    if result.orders.empty or result.fills.empty or result.trades.empty:
        raise ValueError("H06 synthetic SRT/TXE produced no complete trade")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question="Can the H06 market-impulse/ETF-catch-up mechanism reach the full-account S011 goals?",
            hypothesis="A recent CSI300 up impulse followed by ETF relative underreaction leaves executable ETF upside.",
            falsification_conditions=(
                "No search point reaches the 1.5x BuyHold return goal after costs",
                "Market/ETF data identity or T-close causal alignment fails",
                "Any account or order violates the confirmed execution policy",
            ),
            development_cutoff=END, random_seed=SEED,
            allowed_datasets=(Dataset.ETF_OHLCV.value, Dataset.ETF_UNADJUSTED_DAILY.value,
                              Dataset.DOMESTIC_INDEX_DAILY.value, Dataset.TRADING_CALENDAR.value),
            subjects=(SYMBOL,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PARAMETER_SEARCH,
                first_principles=(
                    "A broad-market impulse may diffuse to the thematic ETF with delay",
                    "ETF relative underreaction is observable at T close; trades start no earlier than T+1",
                    "Return is ranked first; risk and frequency remain separately reported hard goals",
                ),
                information_paths=(
                    "CSI300 trailing-60 strongest daily return age -> recent risk-on regime -> ETF same-day relative lag -> next-session long entry",
                ),
                stage_objectives=(
                    "Search only H06 regime/relative-entry/holding expressions",
                    "Compare all complete SRT/TXE accounts with same-order BuyHold",
                ),
                observation_metrics=("CAGR", "maximum drawdown", "closed trades per 60 sessions",
                                     "exposure", "unfilled buy limits", "fees"),
                methodology=(
                    "48 fixed joint points: shock ages 10/20/30/40, ETF-minus-market daily ceilings -1/0/+1%, holds 3/5/7/10",
                    "Exit when shock regime ends or maximum hold expires; do not re-enter on the exit decision day",
                    "Rank all points solely by full-account CAGR; no risk/frequency penalty in selection",
                    "Final hard goals: CAGR >= 1.5x same-order BuyHold, lower drawdown, 4-6 closed trades/60",
                    "All trials use SRT/TXE, 10bp each side, prior-close +0.5% LIMIT buy and MARKET sell",
                    "Development dates 2024-09-10 to 2026-09-24, 1m initial cash; full trial/order/fill/account ledgers retained",
                    "Post-EX03 selected development pool, including H02 EX05-07 and H06 event inspection; no independent validation claimed",
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
        evaluator = _load("s011_ex05_evaluator_for_ex08", root.parent / EX05 / "experiment.py")
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
            raise ValueError("H06 governed market input is not READY")
        if market.identity.content_sha256 != EXPECTED_MARKET_SHA256:
            raise ValueError("H06 market data differ from EX02")
        data = prepare_backtest_execution_data(
            srt_data_root=context.workspace.root, symbol=SYMBOL, asset_type="etf",
            start=START, end=END, env_file=env_file, dataflows=flows,
        )
        if data.evaluation_start != pd.Timestamp(START) or data.evaluation_end != pd.Timestamp(END):
            raise ValueError("EX08 evaluation endpoints differ from frozen window")
        if data.fingerprint != EXPECTED_EXECUTION_FINGERPRINT:
            raise ValueError("EX08 ETF execution data differ from EX07")
        baseline_candidate = evaluator._candidate(root.parent / EX05 / "runtime/strategy_runtime", "BH")
        baseline_result, baseline_prepared = evaluator._run(
            baseline_candidate, data, flows, context.workspace.path("scratch/bh/anchor").parent,
        )
        baseline = evaluator._metrics(baseline_result)
        baseline["prepared_identity"] = baseline_prepared.data_identity
        prior_summary = json.loads((root.parent / "20260928_S011_EX07/artifacts/summary.json").read_text(encoding="utf-8"))
        if any(not np.isclose(baseline[key], prior_summary["baseline"][key], rtol=0, atol=1e-8)
               for key in ("ending_equity", "cagr", "max_drawdown")):
            raise ValueError("EX08 same-order BuyHold differs from EX07")
        tables = {name: [] for name in ("decisions", "orders", "fills", "trades", "account_daily")}
        for name, frames in tables.items():
            frame = getattr(baseline_result, name).copy()
            frame.insert(0, "trial", "BH")
            frames.append(frame)
        records = []
        source_root = root / "runtime/strategy_runtime"
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
            raise ValueError("EX08 trial count differs from frozen budget")
        ledger = pd.DataFrame(records)
        best = ledger.sort_values("cagr", ascending=False).iloc[0]
        return_qualifiers = ledger.loc[ledger.return_goal_met]
        full_qualifiers = ledger.loc[ledger.all_goals_met]
        decision = ("ALL_STAGE3_GOALS_MET" if len(full_qualifiers)
                    else "RETURN_GOAL_MET_ONLY" if len(return_qualifiers)
                    else "RETURN_GOAL_NOT_MET")
        paths = []
        ledger.to_csv(context.workspace.path("search_trial_ledger.csv"), index=False, lineterminator="\n")
        paths.append(("search_trial_ledger.csv", "s011-h06-search-trials"))
        for name, frames in tables.items():
            filename = f"{name}.csv.gz"
            pd.concat(frames, ignore_index=True).to_csv(
                context.workspace.path(filename), index=False, compression="gzip", lineterminator="\n",
            )
            paths.append((filename, f"s011-h06-{name}"))
        identities = [{"dataset": key[0], "symbol": key[1], "start": key[2], "end": key[3],
                       "frequency": key[5], "content_sha256": value.identity.content_sha256}
                      for key, value in flows.results.items() if value.identity is not None]
        pd.DataFrame(identities).to_csv(context.workspace.path("input_identities.csv"), index=False, lineterminator="\n")
        paths.append(("input_identities.csv", "s011-h06-input-identities"))
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
        paths.append(("summary.json", "s011-h06-search-summary"))
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
