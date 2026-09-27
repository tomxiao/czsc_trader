"""S009 EX19: S008 FX opportunity as a potential P03 short exit signal."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
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


EXPERIMENT_ID = "20260926_S009_EX19"
RECEIPTS = {
    "20260925_S009_EX04": "f920ee1275018fbd5672f29fe4dabff31371636215b85570c50bcfcc6a4c0f38",
    "20260926_S009_EX10": "5e283dd9cddfb894103507f9b991762df7b7f63eecb75642eb4fdb339896abeb",
    "20260926_S009_EX14": "710827833597666848097a654f3eb05dfb9cb1249e06bc36881377fa719f453f",
}
S008_MANIFESTS = {
    "20260923_S008_EX16": "416340591eb7d24c169496293a27d4445785ac26e88142229139ab320ec5e0ae",
    "20260923_S008_EX18": "eab14f3ad0f694d996717d998577dfd5abdd4939736ccf2b43a7fb55a70f4933",
}
FEE_ROUNDTRIP = 0.002
BOOTSTRAP_BLOCK = 5
BOOTSTRAP_SAMPLES = 2000
SEED = 2026091901


def _group_stats(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, sample in (("ALL", frame), *((str(year), part) for year, part in frame.groupby(frame["Date"].dt.year))):
        for positive in (False, True):
            group = sample.loc[sample["fx_positive"].eq(positive)]
            rows.append({
                "year": year, "fx_positive": positive, "days": len(group),
                "mean_5d_open_return": float(group["Outcome"].mean()),
                "mean_price_residual": float(group["residual"].mean()),
            })
    return pd.DataFrame(rows)


def _moving_block_intervals(frame: pd.DataFrame) -> tuple[tuple[float, float], tuple[float, float]]:
    rng = np.random.default_rng(SEED)
    n = len(frame)
    if n < BOOTSTRAP_BLOCK * 5:
        raise ValueError("insufficient evaluation dates for block bootstrap")
    weak_means = []
    residual_differences = []
    starts = np.arange(n - BOOTSTRAP_BLOCK + 1)
    for _ in range(BOOTSTRAP_SAMPLES):
        draw = rng.choice(starts, size=int(np.ceil(n / BOOTSTRAP_BLOCK)), replace=True)
        indexes = (draw[:, None] + np.arange(BOOTSTRAP_BLOCK)).reshape(-1)[:n]
        sample = frame.iloc[indexes]
        held = sample.loc[sample["target_position"].eq(1)]
        weak = held.loc[~held["fx_positive"]]
        strong = held.loc[held["fx_positive"]]
        if weak.empty or strong.empty:
            raise ValueError("bootstrap draw lacks one FX group")
        weak_means.append(float(weak["Outcome"].mean()))
        residual_differences.append(float(strong["residual"].mean() - weak["residual"].mean()))
    return (tuple(np.quantile(weak_means, [0.025, 0.975])),
            tuple(np.quantile(residual_differences, [0.025, 0.975])))


def _precheck() -> None:
    dates = pd.bdate_range("2020-01-01", periods=30)
    synthetic = pd.DataFrame({"Date": dates, "Outcome": np.linspace(-0.01, 0.01, 30),
                              "BaselinePrediction": np.zeros(30),
                              "target_position": np.tile([1.0, 1.0, 0.0], 10),
                              "fx_positive": np.tile([False, True, False], 10)})
    synthetic["residual"] = synthetic["Outcome"] - synthetic["BaselinePrediction"]
    stats = _group_stats(synthetic.loc[synthetic["target_position"].eq(1)])
    if stats.loc[stats["year"].eq("ALL"), "days"].sum() != 20:
        raise ValueError("synthetic held-state grouping differs")
    intervals = _moving_block_intervals(synthetic)
    if not all(np.isfinite(value) for pair in intervals for value in pair):
        raise ValueError("synthetic bootstrap produced invalid interval")
    if not (FEE_ROUNDTRIP == 2 * 0.001 and BOOTSTRAP_BLOCK == 5):
        raise ValueError("fee or temporal probe changed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S009", mode=ExperimentMode.DISCOVERY,
            research_question="Does the S008 causal FX component identify P03 held days where a 5-session exit beats remaining invested after a round trip?",
            hypothesis="CNY strength removes RMB-gold translation support soon enough that exiting for five sessions avoids a net loss.",
            falsification_conditions=(
                "FX-nonpositive held days still have positive 5-session tradable returns",
                "Their prospective loss is smaller than the 20bp round-trip fee",
                "Residual separation does not survive calendar-block uncertainty or annual audit",
                "Cross-strategy archive identities, dates or causal coverage fail",
            ),
            development_cutoff=date(2024, 12, 31), random_seed=SEED,
            allowed_datasets=(Dataset.USDCNH_DAILY.value, Dataset.ETF_UNADJUSTED_DAILY.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.MECHANISM_DISCOVERY,
                first_principles=("CNY translation can contribute to RMB gold returns independently of global gold sentiment",),
                information_paths=("Prior USDCNH depreciation/strength -> RMB gold translation -> next-five-session executable return",),
                stage_objectives=("Check whether the weak-FX held state justifies paying for a temporary exit",),
                observation_metrics=("five-session open return", "price-baseline residual", "year consistency", "block interval", "flat-state and 20-session diagnostics"),
                methodology=("One natural zero split", "P03 held decisions only for primary comparison", "5-day calendar moving-block bootstrap, 2000 draws", "20bp round-trip proxy; no strategy backtest"),
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
        repo = root.parents[2]
        for experiment_id, receipt in RECEIPTS.items():
            if context.predecessors[experiment_id].receipt_sha256 != receipt:
                raise ValueError(f"predecessor receipt differs: {experiment_id}")
            validate_experiment_archive(root.parent / experiment_id)
        for experiment_id, expected_hash in S008_MANIFESTS.items():
            archive = repo / "experiments" / "S008" / experiment_id
            validate_experiment_archive(archive)
            actual_hash = sha256((archive / "experiment_manifest.json").read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                raise ValueError(f"S008 cross-strategy archive identity differs: {experiment_id}")
        s008 = pd.read_csv(
            repo / "experiments/S008/20260923_S008_EX16/artifacts/causal_feature_panel.csv.gz",
            usecols=["Date", "currency_usdcnh_return_20d"], parse_dates=["Date"],
        )
        component = pd.read_csv(repo / "experiments/S008/20260923_S008_EX18/artifacts/component_panel.csv")
        role = component.loc[component["feature"].eq("currency_usdcnh_return_20d"), "financial_role"]
        if role.tolist() != ["OPPORTUNITY"]:
            raise ValueError("S008 FX component no longer carries opportunity responsibility")
        decisions = pd.read_csv(root.parent / "20260926_S009_EX14/artifacts/decisions.csv.gz",
                                parse_dates=["signal_date"])
        decisions = decisions.loc[decisions["trial"].eq("P03") & decisions["scenario"].eq("primary")]
        decisions = decisions[["signal_date", "target_position"]].rename(columns={"signal_date": "Date"})
        five = pd.read_csv(root.parent / "20260925_S009_EX04/artifacts/annual_forward_predictions.csv.gz",
                           parse_dates=["Date"])
        five = five.loc[five["Horizon"].eq(5)]
        if five.groupby("Date")[["Outcome", "BaselinePrediction"]].nunique(dropna=False).max().max() != 1:
            raise ValueError("EX04 outcomes or price baselines differ across features")
        five = five.drop_duplicates("Date")[["Date", "Outcome", "BaselinePrediction"]].sort_values("Date")
        for name, frame in (("FX", s008), ("P03", decisions), ("EX04", five)):
            if frame["Date"].duplicated().any():
                raise ValueError(f"{name} has duplicate dates")
        aligned = five.merge(decisions, on="Date", how="left", validate="one_to_one")
        aligned = aligned.merge(s008, on="Date", how="left", validate="one_to_one")
        if aligned[["target_position", "currency_usdcnh_return_20d"]].isna().any().any():
            raise ValueError("missing causal component or P03 decision on evaluation date")
        if len(aligned) != 1450 or aligned["Date"].max().date() > date(2024, 12, 31):
            raise ValueError("evaluation date coverage or sealed boundary differs")
        aligned["fx_positive"] = aligned["currency_usdcnh_return_20d"].gt(0)
        aligned["residual"] = aligned["Outcome"] - aligned["BaselinePrediction"]
        held = aligned.loc[aligned["target_position"].eq(1)].copy()
        flat = aligned.loc[aligned["target_position"].eq(0)].copy()
        stats = _group_stats(held)
        weak = held.loc[~held["fx_positive"]]
        strong = held.loc[held["fx_positive"]]
        weak_mean = float(weak["Outcome"].mean())
        residual_difference = float(strong["residual"].mean() - weak["residual"].mean())
        weak_interval, residual_interval = _moving_block_intervals(aligned)
        annual_weak = stats.loc[stats["year"].ne("ALL") & ~stats["fx_positive"]]
        negative_years = int(annual_weak["mean_5d_open_return"].lt(-FEE_ROUNDTRIP).sum())
        qualifies = (weak_mean < -FEE_ROUNDTRIP and weak_interval[1] < -FEE_ROUNDTRIP
                     and residual_difference > 0 and residual_interval[0] > 0
                     and negative_years >= 4)
        twenty = pd.read_csv(root.parent / "20260926_S009_EX10/artifacts/annual_forward_predictions.csv.gz",
                             parse_dates=["Date"])
        twenty = twenty.loc[twenty["Baseline"].eq("PRICE_VIX_LIQUIDITY"), ["Date", "Outcome"]]
        twenty = twenty.merge(aligned[["Date", "target_position", "fx_positive"]], on="Date",
                              how="inner", validate="one_to_one")
        diagnostic = []
        for scope, sample in (("P03_HELD", held), ("P03_FLAT", flat)):
            for positive in (False, True):
                group = sample.loc[sample["fx_positive"].eq(positive)]
                diagnostic.append({"scope": scope, "fx_positive": positive, "days": len(group),
                                   "mean_5d_open_return": float(group["Outcome"].mean())})
        for positive in (False, True):
            group = twenty.loc[twenty["target_position"].eq(1) & twenty["fx_positive"].eq(positive)]
            diagnostic.append({"scope": "P03_HELD_20D", "fx_positive": positive, "days": len(group),
                               "mean_5d_open_return": float(group["Outcome"].mean())})
        artifacts = []
        for name, frame in (("aligned_5d.csv.gz", aligned), ("held_annual_groups.csv", stats),
                            ("diagnostic_groups.csv", pd.DataFrame(diagnostic))):
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n",
                         compression="gzip" if name.endswith(".gz") else None)
            artifacts.append(context.workspace.register_artifact(name, f"S009-{name.split('.')[0].replace('_', '-')}"))
        summary = {
            "decision": "REVIEW_EXIT_PROTOTYPE" if qualifies else "STOP_FX_EXIT_PATH",
            "held_days": len(held), "flat_days": len(flat), "weak_fx_held_days": len(weak),
            "weak_fx_mean_5d_return": weak_mean, "strong_fx_mean_5d_return": float(strong["Outcome"].mean()),
            "weak_fx_mean_ci95": list(weak_interval), "price_residual_difference": residual_difference,
            "price_residual_difference_ci95": list(residual_interval),
            "negative_weak_fx_years": negative_years, "required_negative_years": 4,
            "roundtrip_fee": FEE_ROUNDTRIP, "bootstrap_draws": BOOTSTRAP_SAMPLES,
            "cross_strategy_s008_manifest_sha256": S008_MANIFESTS,
            "sealed_validation_read": False, "account_replay_performed": False,
        }
        context.workspace.path("summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S009-FX-exit-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if qualifies else ExperimentOutcome.FAIL,
            facts={"decision": summary["decision"], "held_days": len(held),
                   "negative_weak_fx_years": negative_years, "sealed_validation_read": False},
            diagnostics={"weak_fx_mean_5d_return": weak_mean,
                         "price_residual_difference": residual_difference},
            artifacts=tuple(artifacts),
        )
