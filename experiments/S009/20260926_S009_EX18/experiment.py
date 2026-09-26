"""S009 EX18: duration structure of causally observed P03 negative states."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd

from czsc_trader.experiment_archive import validate_experiment_archive
from dataflows import Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)


EXPERIMENT_ID = "20260926_S009_EX18"
RECEIPTS = {
    "20260926_S009_EX14": "710827833597666848097a654f3eb05dfb9cb1249e06bc36881377fa719f453f",
    "20260926_S009_EX17": "db25093229cc1931ba601009a1bc8f8cbaea74d1ee10732d9d50643c12b01637",
}


def _duration(decisions: pd.DataFrame, baseline: pd.DataFrame) -> pd.DataFrame:
    rows = decisions.sort_values("valid_session").reset_index(drop=True)
    market = baseline.sort_values("date").reset_index(drop=True)
    if len(rows) != 1456 or len(market) != len(rows):
        raise ValueError("incomplete EX14 accounts")
    if not rows["valid_session"].equals(market["date"]) or rows["valid_session"].duplicated().any():
        raise ValueError("decision/account dates differ")
    if rows["valid_session"].max().date() > date(2024, 12, 31):
        raise ValueError("sealed evaluation date encountered")
    target = rows["target_position"].to_numpy(dtype=float)
    if not np.isin(target, [0, 1]).all():
        raise ValueError("unexpected P03 target")
    negative = target == 0
    for column in ("BroadLiquidity20", "BroadLiquidity60", "PolicyUncertainty20"):
        if rows.loc[negative, column].isna().any():
            raise ValueError(f"negative-state feature unavailable: {column}")
    if (rows.loc[negative, "BroadLiquidity20"].gt(0) |
        rows.loc[negative, "BroadLiquidity60"].gt(0) |
        rows.loc[negative, "PolicyUncertainty20"].gt(0)).any():
        raise ValueError("P03 negative state conflicts with causal signals")
    age = np.zeros(len(rows), dtype=int)
    spell = np.zeros(len(rows), dtype=int)
    current = 0
    for index, is_negative in enumerate(negative):
        if is_negative:
            if index == 0 or not negative[index - 1]:
                current += 1
            age[index] = 1 if index == 0 else age[index - 1] + 1
            spell[index] = current
    if market["equity"].le(0).any():
        raise ValueError("invalid baseline equity")
    previous = market["equity"].shift(fill_value=1_000_000.0)
    log_return = np.log(market["equity"] / previous)
    result = pd.DataFrame({"date": rows["valid_session"], "target_position": target,
                           "negative_state_age": age, "negative_spell": spell,
                           "group": np.where(age == 0, "INVESTED", np.where(age <= 2, "EARLY", "PERSISTENT")),
                           "buyhold_log_return": log_return})
    if not np.isclose(result["buyhold_log_return"].sum(),
                      np.log(market["equity"].iloc[-1] / 1_000_000.0), atol=1e-10):
        raise ValueError("baseline daily log returns do not close")
    return result


def _precheck() -> None:
    dates = pd.bdate_range("2019-01-02", periods=1456)
    target = np.ones(1456)
    target[1:3] = 0
    target[5:9] = 0
    decisions = pd.DataFrame({"valid_session": dates, "target_position": target,
                              "BroadLiquidity20": np.where(target == 0, -1., 1.),
                              "BroadLiquidity60": np.where(target == 0, -1., 1.),
                              "PolicyUncertainty20": np.where(target == 0, -1., 1.)})
    baseline = pd.DataFrame({"date": dates, "equity": 1_000_000 * 1.001 ** np.arange(1, 1457)})
    result = _duration(decisions, baseline)
    if result.loc[1:2, "negative_state_age"].tolist() != [1, 2] or result.loc[5:8, "negative_state_age"].tolist() != [1, 2, 3, 4]:
        raise ValueError("synthetic duration boundary failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S009", mode=ExperimentMode.DISCOVERY,
            research_question="Does the duration of P03's causal negative state distinguish missed gold upside from avoided downside?",
            hypothesis="A one- or two-session negative interruption is noisy; sustained negatives may carry more downside information.",
            falsification_conditions=(
                "Early and persistent negative states have no stable contrasting opportunity cost",
                "Decision dates or negative-state signals fail to align with the archived market account",
                "Any finding depends on sealed validation or ex-post state selection",
            ),
            development_cutoff=date(2024, 12, 31), random_seed=2026091801,
            allowed_datasets=(Dataset.ETF_UNADJUSTED_DAILY.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.MECHANISM_DISCOVERY,
                first_principles=("Short interruptions in allocation preference may be noise while persistent withdrawal may reflect a real regime",),
                information_paths=("Causally observed negative-state duration -> next-session gold exposure opportunity cost",),
                stage_objectives=("Distinguish early from sustained negative-state return exposure", "Decide whether patient exit merits a new execution prototype"),
                observation_metrics=("upside missed", "downside avoided", "year stability", "negative spells"),
                methodology=("Fixed age 1-2 versus age 3+ groups", "Same-execution BuyHold daily returns", "No parameter search or candidate promotion"),
                predecessor_experiment_ids=tuple(RECEIPTS),
            ),
            dependencies=(ExperimentDependency("numpy", np.__version__), ExperimentDependency("pandas", pd.__version__)),
            capabilities=ExperimentCapabilities(reads_real_returns=True), subjects=("518880.SH",),
        )

    def synthetic_precheck(self) -> None:
        _precheck()

    def execute(self, context) -> ExperimentResult:
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        root = Path(__file__).resolve().parent
        for experiment_id, receipt in RECEIPTS.items():
            if context.predecessors[experiment_id].receipt_sha256 != receipt:
                raise ValueError(f"predecessor identity differs: {experiment_id}")
            validate_experiment_archive(root.parent / experiment_id)
        source = root.parent / "20260926_S009_EX14" / "artifacts"
        decisions = pd.read_csv(source / "decisions.csv.gz", parse_dates=["valid_session"])
        baseline = pd.read_csv(source / "account_daily.csv.gz", parse_dates=["date"])
        decisions = decisions.loc[decisions["trial"].eq("P03") & decisions["scenario"].eq("primary")]
        baseline = baseline.loc[baseline["trial"].eq("BH") & baseline["scenario"].eq("primary")]
        daily = _duration(decisions, baseline)
        negative = daily.loc[daily["negative_state_age"].gt(0)].copy()
        summary = []
        for group, sample in negative.groupby("group"):
            positive = sample.loc[sample["buyhold_log_return"].gt(0), "buyhold_log_return"]
            negative_returns = sample.loc[sample["buyhold_log_return"].lt(0), "buyhold_log_return"]
            summary.append({"group": group, "days": len(sample), "spells": sample["negative_spell"].nunique(),
                            "missed_upside_log": float(positive.sum()),
                            "avoided_downside_log": float(-negative_returns.sum()),
                            "net_buyhold_log_return": float(sample["buyhold_log_return"].sum()),
                            "mean_daily_log_return": float(sample["buyhold_log_return"].mean())})
        summary_frame = pd.DataFrame(summary).sort_values("group")
        annual = negative.groupby([negative["date"].dt.year.rename("year"), "group"], as_index=False).agg(
            days=("buyhold_log_return", "size"), net_buyhold_log_return=("buyhold_log_return", "sum"))
        spells = negative.groupby("negative_spell", as_index=False).agg(
            start=("date", "min"), end=("date", "max"), duration=("negative_state_age", "max"),
            net_buyhold_log_return=("buyhold_log_return", "sum"))
        outputs = {"negative_state_daily.csv.gz": daily, "duration_summary.csv": summary_frame,
                   "annual_duration.csv": annual, "negative_spells.csv": spells}
        artifacts = []
        for name, frame in outputs.items():
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n",
                         compression="gzip" if name.endswith(".gz") else None)
            artifacts.append(context.workspace.register_artifact(name, f"S009-{name.split('.')[0].replace('_', '-')}"))
        context.workspace.path("summary.json").write_text(
            json.dumps({"decision": "DURATION_DIAGNOSTIC_ONLY", "sealed_validation_read": False,
                        "predecessor_receipts": RECEIPTS}, indent=2) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S009-duration-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": "DURATION_DIAGNOSTIC_ONLY", "negative_spells": len(spells),
                   "sealed_validation_read": False},
            diagnostics={"early_days": int(summary_frame.loc[summary_frame["group"].eq("EARLY"), "days"].iloc[0]),
                         "persistent_days": int(summary_frame.loc[summary_frame["group"].eq("PERSISTENT"), "days"].iloc[0])},
            artifacts=tuple(artifacts),
        )
