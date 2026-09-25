from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd
from research_experiment import (
    ExperimentCapabilities,
    ExperimentCapability,
    ExperimentDefinition,
    ExperimentDependency,
    ExperimentMode,
    ExperimentOutcome,
    ExperimentProtocol,
    ExperimentResult,
    ExperimentStage,
    ResearchExperiment,
)


EX68 = "20260924_S008_EX68"
EX68_RECEIPT = "a9c683cb0d64e94fa8930c753e2bfd9626949d1e864b00b8152b9953b0aceb01"
EX16_PANEL_SHA256 = "a757cafd1eb1322f4aebe3d68fc5a6792eab9aae8b13eed8f7b83618be2139b4"
EX42_LEDGER_SHA256 = "55a3c508f15f95c642f00c7bf6dc795dd68c966055bf85c828ea559aeefad95b"
EX48_HASHES = {
    "position_gap_metrics.csv": "c602a0aee1a186fcc16b4ab9086dc178218af94006c741f4b29e0de5f955bbb6",
    "oracle_segment_ledger.csv": "a6c518116253f2f06789d53a0a511b02776aeebccff09f825a96c12410b5c6b6",
    "transition_gap_ledger.csv": "bfb2ec702bb523a81cd25e48800aef313abef7d6cd835293383872de6a8af5c3",
    "representative_positions.csv.gz": "bc3547d53effbcac45433a7c73fd0a9411fbc7184189e56857df721b54f48466",
}
FEATURES = (
    "price_return_20d",
    "gold_sge_return_20d",
    "currency_usdcnh_return_20d",
    "rate_us_real_10y_change_20d",
)
REPRESENTATIVES = ("P02_REGIME_RECOVERY", "P06_CORE_CARRY_REGIME_VETO")


def _asof_value_and_rank(panel: pd.DataFrame, signal_date: pd.Timestamp, feature: str) -> tuple[float | None, float | None]:
    if signal_date not in panel.index:
        raise ValueError("signal date is absent from the causal panel")
    value = panel.at[signal_date, feature]
    if pd.isna(value):
        return None, None
    window = panel.loc[:signal_date, feature].tail(252).dropna()
    if len(window) < 100:
        return float(value), None
    percentile = float((window.lt(value).sum() + 0.5 * window.eq(value).sum()) / len(window))
    return float(value), percentile


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260924_S008_EX78",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="What exposure structure makes the S008 target possible, and what was visible before the hindsight regime transitions?",
            hypothesis="The target requires a small number of long exposure regimes and timely avoidance of adverse regimes, but only four hindsight transitions may be too few to learn a reliable gate.",
            falsification_conditions=(
                "EX68 or the frozen EX42/EX48/EX16 evidence identity differs",
                "Oracle has a different window, entry count or number of state transitions",
                "An alleged pre-transition feature is unavailable on its signal date",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026097801,
            allowed_datasets=("archived.tushare_etf_execution", "archived.tushare_causal_panel"),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.MECHANISM_DISCOVERY,
                first_principles=(
                    "With only cash or long exposure, return enhancement must combine sufficient upside participation and selective downside avoidance",
                    "An ex-post optimum is a feasibility bound, not information available to traders",
                ),
                information_paths=("long-exposure regimes", "adverse-regime avoidance", *FEATURES),
                stage_objectives=("Map the opportunity topology without choosing an indicator", "Count independent transitions and inspect strictly prior observables"),
                observation_metrics=("segment duration and log-return contribution", "exposure, positive capture, negative avoidance, annual return and drawdown", "T-1 and T-21 causal feature values and expanding percentiles"),
                methodology=("Hash-verify fixed EX42/EX48/EX16 inputs", "Use existing P02 and P06 without replacement", "Treat all Oracle transitions as hindsight-labelled development observations"),
                predecessor_experiment_ids=(EX68,),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[EX68]
        if predecessor.receipt_sha256 != EX68_RECEIPT or predecessor.facts.get("decision") != "PROCEED_TO_UPSIDE_PARTICIPATION_INFORMATION_AUDIT":
            raise ValueError("EX68 predecessor differs")
        root = Path(__file__).resolve().parents[3]
        ex42 = root / "experiments" / "S008" / "20260923_S008_EX42" / "artifacts"
        ex48 = root / "experiments" / "S008" / "20260923_S008_EX48" / "artifacts"
        ex16 = root / "experiments" / "S008" / "20260923_S008_EX16" / "artifacts" / "causal_feature_panel.csv.gz"
        if sha256((ex42 / "oracle_budget_ledger.csv").read_bytes()).hexdigest() != EX42_LEDGER_SHA256:
            raise ValueError("EX42 Oracle budget identity differs")
        if sha256(ex16.read_bytes()).hexdigest() != EX16_PANEL_SHA256:
            raise ValueError("EX16 causal panel identity differs")
        for name, expected in EX48_HASHES.items():
            if sha256((ex48 / name).read_bytes()).hexdigest() != expected:
                raise ValueError(f"EX48 evidence identity differs: {name}")
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        budget = pd.read_csv(ex42 / "oracle_budget_ledger.csv")
        oracle = budget.loc[budget["cadence"].eq("DAILY") & budget["maximum_entry_budget"].eq(2)]
        if len(oracle) != 1 or int(oracle.iloc[0]["entry_count"]) != 2 or int(oracle.iloc[0]["exit_count"]) != 2:
            raise ValueError("Oracle budget differs")
        metrics = pd.read_csv(ex48 / "position_gap_metrics.csv").set_index("representative")
        segments = pd.read_csv(ex48 / "oracle_segment_ledger.csv", parse_dates=["start", "end"])
        positions = pd.read_csv(ex48 / "representative_positions.csv.gz", compression="gzip", parse_dates=["Date"]).set_index("Date").sort_index()
        if positions.index[0] != pd.Timestamp("2014-07-31") or positions.index[-1] != pd.Timestamp("2024-12-31") or positions.index.has_duplicates:
            raise ValueError("Oracle common window differs")
        if not positions["oracle"].isin([0, 1]).all() or positions["oracle"].sum() / len(positions) != float(oracle.iloc[0]["exposure_ratio"]):
            raise ValueError("Oracle states or exposure differ")
        transitions = positions.loc[positions["oracle"].ne(positions["oracle"].shift())].iloc[1:]
        if len(transitions) != 4 or len(segments["segment_id"].unique()) != 5:
            raise ValueError("Oracle segment topology differs")
        selection = segments.loc[segments["representative"].isin(REPRESENTATIVES)].copy()
        if len(selection) != 10 or selection.groupby("representative")["segment_id"].nunique().ne(5).any():
            raise ValueError("representative segment coverage differs")
        selection["start"] = selection["start"].dt.strftime("%Y-%m-%d")
        selection["end"] = selection["end"].dt.strftime("%Y-%m-%d")
        selection.to_csv(context.workspace.path("opportunity_segments.csv"), index=False, float_format="%.12f", lineterminator="\n")
        main = metrics.loc[list(REPRESENTATIVES), [
            "annualized_return", "maximum_drawdown_magnitude", "exposure_ratio",
            "positive_log_return_capture_ratio", "negative_avoidance_ratio",
            "false_cash_sessions", "false_long_sessions",
        ]].copy()
        main.loc["ORACLE", [
            "annualized_return", "maximum_drawdown_magnitude", "exposure_ratio",
            "positive_log_return_capture_ratio", "negative_avoidance_ratio",
        ]] = [
            float(oracle.iloc[0]["annualized_return"]),
            float(oracle.iloc[0]["maximum_drawdown_magnitude"]),
            float(oracle.iloc[0]["exposure_ratio"]),
            float(oracle.iloc[0]["positive_log_return_capture_ratio"]),
            float(oracle.iloc[0]["negative_log_return_avoidance_ratio"]),
        ]
        main.index.name = "reference"
        main.to_csv(context.workspace.path("exposure_budget.csv"), float_format="%.12f", lineterminator="\n")
        causal = pd.read_csv(ex16, compression="gzip", parse_dates=["Date"]).set_index("Date").sort_index()
        if causal.index.has_duplicates or causal.index.max() > pd.Timestamp("2024-12-31"):
            raise ValueError("causal feature panel crosses the development boundary")
        observations = []
        for execution_date, record in transitions.iterrows():
            execution_index = positions.index.get_loc(execution_date)
            if execution_index < 21:
                raise ValueError("transition lacks 21 prior trading sessions")
            for lead in (1, 21):
                signal_date = positions.index[execution_index - lead]
                row = {"ExecutionDate": execution_date.date().isoformat(), "OracleNewState": int(record["oracle"]), "LeadSessions": lead, "SignalDate": signal_date.date().isoformat()}
                for feature in FEATURES:
                    value, percentile = _asof_value_and_rank(causal, signal_date, feature)
                    row[feature] = value
                    row[f"{feature}_Trailing252Percentile"] = percentile
                observations.append(row)
        observed = pd.DataFrame(observations)
        observed.to_csv(context.workspace.path("transition_observability.csv"), index=False, float_format="%.12f", lineterminator="\n")
        return ExperimentResult(
            outcome=ExperimentOutcome.INCONCLUSIVE,
            facts={"decision": "DISCOVERY_ONLY_OPPORTUNITY_MAP_REVIEW_REQUIRED", "oracle_segments": 5, "oracle_transitions": 4, "oracle_long_sessions": int(positions["oracle"].sum()), "common_sessions": len(positions)},
            diagnostics={"reads_real_returns": True, "reads_sealed_validation": False, "searches_parameters": False, "creates_candidate": False, "oracle_is_hindsight_only": True},
            artifacts=(
                context.workspace.register_artifact("opportunity_segments.csv", "hindsight-opportunity-segments"),
                context.workspace.register_artifact("exposure_budget.csv", "frozen-exposure-comparison"),
                context.workspace.register_artifact("transition_observability.csv", "pre-transition-causal-observations"),
            ),
        )
