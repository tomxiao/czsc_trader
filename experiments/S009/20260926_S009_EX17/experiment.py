"""S009 EX17: auditable post-hoc gap attribution from immutable accounts."""

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


EXPERIMENT_ID = "20260926_S009_EX17"
RECEIPTS = {
    "20260926_S009_EX14": "710827833597666848097a654f3eb05dfb9cb1249e06bc36881377fa719f453f",
    "20260926_S009_EX15": "4d961be51f966963448227ebb281ddfe918f0731944940ca53d06b7a8dac6f4f",
    "20260926_S009_EX16": "4809e0fae5957d0e3e9dc3cba1d3dbfdd475b6a59f250798762cb9d26289c8ac",
}
INITIAL_CASH = 1_000_000.0
END = date(2024, 12, 31)


def _attribution(strategy: pd.DataFrame, baseline: pd.DataFrame) -> pd.DataFrame:
    left = strategy.sort_values("date").reset_index(drop=True)
    right = baseline.sort_values("date").reset_index(drop=True)
    if len(left) != 1456 or len(right) != len(left) or not left["date"].equals(right["date"]):
        raise ValueError("accounts do not have the identical 1456 evaluation dates")
    if left["date"].max().date() > END or left["date"].duplicated().any():
        raise ValueError("invalid development dates")
    for account in (left, right):
        if account["equity"].le(0).any() or account[["quantity_before", "quantity"]].lt(0).any().any():
            raise ValueError("invalid account state")
    previous = left["equity"].shift(fill_value=INITIAL_CASH)
    baseline_previous = right["equity"].shift(fill_value=INITIAL_CASH)
    s_log = np.log(left["equity"] / previous)
    b_log = np.log(right["equity"] / baseline_previous)
    before = left["quantity_before"].to_numpy()
    after = left["quantity"].to_numpy()
    categories = np.select(
        [(before == 0) & (after == 0), (before > 0) & (after > 0),
         (before == 0) & (after > 0), (before > 0) & (after == 0)],
        ["PURE_FLAT", "CONTINUOUS_HOLD", "ENTRY", "EXIT"], default="INVALID",
    )
    if (categories == "INVALID").any():
        raise ValueError("unclassified quantity transition")
    output = pd.DataFrame({
        "date": left["date"], "category": categories,
        "strategy_log_return": s_log, "buyhold_log_return": b_log,
        "log_excess": s_log - b_log,
        "strategy_equity": left["equity"], "buyhold_equity": right["equity"],
        "exposure": left["quantity"] * left["close"] / left["equity"],
    })
    expected = np.log(left["equity"].iloc[-1] / right["equity"].iloc[-1])
    if not np.isclose(output["log_excess"].sum(), expected, rtol=0, atol=1e-10):
        raise ValueError("daily attribution does not reconcile to terminal accounts")
    return output


def _precheck() -> None:
    dates = pd.bdate_range("2020-01-01", periods=1456)
    baseline = pd.DataFrame({"date": dates, "equity": INITIAL_CASH * 1.001 ** np.arange(1, 1457),
                             "quantity_before": np.zeros(1456), "quantity": np.zeros(1456)})
    before = np.zeros(1456, dtype=int)
    after = np.zeros(1456, dtype=int)
    before[2:5] = 100
    after[1:4] = 100
    strategy = pd.DataFrame({"date": dates, "equity": INITIAL_CASH * 1.002 ** np.arange(1, 1457),
                             "quantity_before": before, "quantity": after,
                             "close": np.ones(1456)})
    # Synthetic dates are intentionally mapped inside the declared development interval.
    dates = pd.bdate_range("2019-01-02", "2024-12-31")[:1456]
    baseline["date"] = dates
    strategy["date"] = dates
    result = _attribution(strategy, baseline)
    if set(result["category"]) != {"PURE_FLAT", "CONTINUOUS_HOLD", "ENTRY", "EXIT"}:
        raise ValueError("synthetic transition coverage failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S009",
            mode=ExperimentMode.DISCOVERY,
            research_question="Where did S009 prototypes lose executable return relative to same-execution BuyHold?",
            hypothesis="Missed upside, avoided downside and trading drag separate the opportunity problem from risk protection.",
            falsification_conditions=(
                "Daily components fail to reconcile to terminal account advantage",
                "Archived accounts disagree in dates, fee scenario or predecessor identity",
                "The apparent return gap cannot be traced beyond post-hoc market segmentation",
            ),
            development_cutoff=END, random_seed=2026091701,
            allowed_datasets=(Dataset.ETF_UNADJUSTED_DAILY.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.ROBUSTNESS,
                first_principles=("A return-seeking strategy must retain tradable gold upside after its risk controls and costs",),
                information_paths=("Historical account and market returns describe, but do not predict, missed opportunity",),
                stage_objectives=("Reconcile the full-account return gap", "Route the next question to information, timing or execution"),
                observation_metrics=("missed upside", "avoided downside", "exposure", "annual concentration", "fees", "closed trades"),
                methodology=("Zero-threshold four-way comparison", "Highest-annualized already-seen point per prototype, explicitly post-hoc", "Exact daily log-return attribution", "Existing 30bp stress where archived"),
                predecessor_experiment_ids=tuple(RECEIPTS),
            ),
            dependencies=(ExperimentDependency("numpy", np.__version__), ExperimentDependency("pandas", pd.__version__)),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            subjects=("518880.SH",),
        )

    def synthetic_precheck(self) -> None:
        _precheck()

    def execute(self, context) -> ExperimentResult:
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        root = Path(__file__).resolve().parent
        archives = {}
        for experiment_id, receipt in RECEIPTS.items():
            if context.predecessors[experiment_id].receipt_sha256 != receipt:
                raise ValueError(f"{experiment_id} predecessor receipt differs")
            archive = root.parent / experiment_id
            validate_experiment_archive(archive)
            archives[experiment_id] = archive / "artifacts"
        ex14, ex15, ex16 = (archives[key] for key in RECEIPTS)
        daily14 = pd.read_csv(ex14 / "account_daily.csv.gz", parse_dates=["date"])
        daily15 = pd.read_csv(ex15 / "account_daily.csv.gz", parse_dates=["date"])
        daily16 = pd.read_csv(ex16 / "account_daily.csv.gz", parse_dates=["date"])
        fills14 = pd.read_csv(ex14 / "fills.csv.gz")
        fills15 = pd.read_csv(ex15 / "fills.csv.gz")
        fills16 = pd.read_csv(ex16 / "fills.csv.gz")
        metrics14 = pd.read_csv(ex14 / "trial_metrics.csv")
        ledgers = {"P03": pd.read_csv(ex15 / "search_trial_ledger.csv")}
        alternatives = pd.read_csv(ex16 / "search_trial_ledger.csv")
        for prototype in ("P01", "P02", "P04"):
            ledgers[prototype] = alternatives.loc[alternatives["prototype"].eq(prototype)].copy()
        selected = []
        for prototype, ledger in ledgers.items():
            distinct = ledger.loc[ledger["reused_from_trial"].isna()]
            best = distinct.sort_values(["annualized_return", "trial"], ascending=[False, True]).iloc[0]
            selected.append({"prototype": prototype, "trial": int(best["trial"]),
                             "annualized_return": float(best["annualized_return"]),
                             "liquidity_threshold": float(best["liquidity_threshold"]),
                             "policy_threshold": float(best["policy_threshold"]),
                             "selection": "POST_HOC_DEVELOPMENT_MAX_ANNUAL"})
        attribution = []
        aggregate = []
        annual = []
        for prototype in ("P01", "P02", "P03", "P04"):
            for variant in ("ZERO", "BEST_SEEN"):
                selection = next(row for row in selected if row["prototype"] == prototype)
                if variant == "BEST_SEEN" and selection["liquidity_threshold"] == 0 and selection["policy_threshold"] == 0:
                    continue
                archive_daily, archive_fills, trial = ((daily14, fills14, prototype) if variant == "ZERO" else
                                                       (daily15, fills15, selection["trial"]) if prototype == "P03" else
                                                       (daily16, fills16, selection["trial"]))
                for scenario in ("primary", "stress"):
                    left = archive_daily.loc[archive_daily["trial"].eq(trial) & archive_daily["scenario"].eq(scenario)]
                    if left.empty:
                        if scenario == "primary":
                            raise ValueError(f"missing primary account: {prototype} {variant}")
                        continue
                    right = daily14.loc[daily14["trial"].eq("BH") & daily14["scenario"].eq(scenario)]
                    day = _attribution(left, right)
                    day.insert(0, "scenario", scenario)
                    day.insert(0, "variant", variant)
                    day.insert(0, "prototype", prototype)
                    attribution.append(day)
                    flat = day.loc[day["category"].eq("PURE_FLAT")]
                    missed = flat.loc[flat["buyhold_log_return"].gt(0), "buyhold_log_return"].sum()
                    avoided = -flat.loc[flat["buyhold_log_return"].lt(0), "buyhold_log_return"].sum()
                    grouped = day.groupby("category")["log_excess"].sum()
                    fill = archive_fills.loc[archive_fills["trial"].eq(trial) & archive_fills["scenario"].eq(scenario)]
                    fee = float(fill["fees"].sum())
                    equity = float(day["strategy_equity"].iloc[-1])
                    bh_equity = float(day["buyhold_equity"].iloc[-1])
                    years = len(day) / 252
                    aggregate.append({"prototype": prototype, "variant": variant, "source_trial": trial,
                                      "scenario": scenario, "sessions": len(day),
                                      "strategy_annualized": (equity / INITIAL_CASH) ** (1 / years) - 1,
                                      "buyhold_annualized": (bh_equity / INITIAL_CASH) ** (1 / years) - 1,
                                      "annualized_gap": (equity / INITIAL_CASH) ** (1 / years) - (bh_equity / INITIAL_CASH) ** (1 / years),
                                      "total_log_excess": float(day["log_excess"].sum()),
                                      "pure_flat_log_excess": float(grouped.get("PURE_FLAT", 0)),
                                      "continuous_hold_log_excess": float(grouped.get("CONTINUOUS_HOLD", 0)),
                                      "entry_log_excess": float(grouped.get("ENTRY", 0)),
                                      "exit_log_excess": float(grouped.get("EXIT", 0)),
                                      "missed_upside_log": float(missed), "avoided_downside_log": float(avoided),
                                      "pure_flat_days": len(flat), "entry_days": int(day["category"].eq("ENTRY").sum()),
                                      "exit_days": int(day["category"].eq("EXIT").sum()),
                                      "mean_exposure": float(day["exposure"].mean()), "fill_fees_total": fee})
                    for year, segment in day.groupby(day["date"].dt.year):
                        annual.append({"prototype": prototype, "variant": variant, "scenario": scenario,
                                       "year": int(year), "log_excess": float(segment["log_excess"].sum()),
                                       "flat_log_excess": float(segment.loc[segment["category"].eq("PURE_FLAT"), "log_excess"].sum()),
                                       "strategy_log_return": float(segment["strategy_log_return"].sum()),
                                       "buyhold_log_return": float(segment["buyhold_log_return"].sum())})
        aggregate_frame = pd.DataFrame(aggregate)
        if len(aggregate_frame.loc[aggregate_frame["scenario"].eq("primary")]) < 4:
            raise ValueError("incomplete prototype attribution")
        baseline = metrics14.loc[metrics14["trial"].eq("BH") & metrics14["scenario"].eq("primary")].iloc[0]
        target = 1.5 * float(baseline["annualized_return"])
        if not np.isclose(target, 1.5 * aggregate_frame.loc[aggregate_frame["scenario"].eq("primary"), "buyhold_annualized"].iloc[0], atol=1e-9):
            raise ValueError("BuyHold baseline differs from account")
        output = {
            "attribution_daily.csv.gz": pd.concat(attribution, ignore_index=True),
            "attribution_summary.csv": aggregate_frame,
            "annual_attribution.csv": pd.DataFrame(annual),
            "selected_development_points.csv": pd.DataFrame(selected),
        }
        artifacts = []
        for name, frame in output.items():
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n",
                         compression="gzip" if name.endswith(".gz") else None)
            artifacts.append(context.workspace.register_artifact(name, f"S009-{name.split('.')[0].replace('_', '-')}"))
        summary = {"decision": "POST_HOC_GAP_ATTRIBUTION_ONLY", "buyhold_target_annualized": target,
                   "account_variants": len(aggregate_frame), "sealed_validation_read": False,
                   "predecessor_receipts": RECEIPTS}
        context.workspace.path("summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S009-gap-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "account_variants": len(aggregate_frame),
                   "sealed_validation_read": False},
            diagnostics={"buyhold_target_annualized": target}, artifacts=tuple(artifacts),
        )
