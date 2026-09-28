"""S011 EX04: targeted post-selection diagnostic of the FX-strength hypothesis."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from czsc_trader.experiment_archive import validate_experiment_archive
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


EXPERIMENT_ID = "20260928_S011_EX04"
PREDECESSORS = {
    "20260928_S011_EX02": "5c820f80a763596a80b8faa8340f986372fb252c2684a7c6aed600e0e124c931",
    "20260928_S011_EX03": "fe13686d0a5a4167438ca496716d7a7554b37de875270412d793c8ab39a57e3b",
}
SEED = 20260904
SPLIT_DAY = 248
HORIZONS = (5, 10, 20)
BLOCK = 20
BOOTSTRAPS = 2000
ROUND_TRIP_COST_PROXY = 0.002
FACTOR = "x_fx_momentum_w20"
CONTROLS = (
    "p_momentum_w5", "p_momentum_w20", "p_momentum_w60",
    "x_market_momentum_w20", "x_market_volatility_w20",
)


def _state_difference(frame: pd.DataFrame, outcome: str) -> tuple[float, int, int]:
    strong = frame.loc[frame["FXStrength"], outcome]
    other = frame.loc[~frame["FXStrength"], outcome]
    if strong.empty or other.empty:
        return np.nan, len(strong), len(other)
    return float(strong.mean() - other.mean()), len(strong), len(other)


def _block_interval(frame: pd.DataFrame, outcome: str) -> tuple[float, float, int]:
    n = len(frame)
    if n < BLOCK * 5:
        raise ValueError("insufficient observations for fixed block bootstrap")
    rng = np.random.default_rng(SEED)
    starts = np.arange(n - BLOCK + 1)
    values: list[float] = []
    for _ in range(BOOTSTRAPS):
        chosen = rng.choice(starts, size=int(np.ceil(n / BLOCK)), replace=True)
        indexes = (chosen[:, None] + np.arange(BLOCK)).reshape(-1)[:n]
        difference, positive, negative = _state_difference(frame.iloc[indexes], outcome)
        if positive and negative:
            values.append(difference)
    if len(values) < int(0.95 * BOOTSTRAPS):
        raise ValueError("too many bootstrap draws lack a comparison state")
    low, high = np.quantile(values, [0.025, 0.975])
    return float(low), float(high), len(values)


def _conditional_coefficient(frame: pd.DataFrame, outcome: str) -> tuple[float, float]:
    controls = frame[list(CONTROLS)].to_numpy(dtype=float)
    scale = controls.std(axis=0)
    if np.any(scale <= 0):
        raise ValueError("a frozen price/market control is constant")
    controls = (controls - controls.mean(axis=0)) / scale
    design = np.column_stack((np.ones(len(frame)), frame["FXStrength"].to_numpy(dtype=float), controls))
    coefficients, _, rank, singular = np.linalg.lstsq(design, frame[outcome].to_numpy(dtype=float), rcond=None)
    if rank != design.shape[1] or singular[-1] <= 0:
        raise ValueError("conditional regression is rank deficient")
    return float(coefficients[1]), float(singular[0] / singular[-1])


def _transition_frequency(manual: pd.DataFrame) -> tuple[int, int, float]:
    known = manual[FACTOR].notna()
    values = manual.loc[known, FACTOR].lt(0).to_numpy(dtype=bool)
    if len(values) < 2:
        raise ValueError("no causal FX state history")
    opens = int((~values[:-1] & values[1:]).sum())
    closes = int((values[:-1] & ~values[1:]).sum())
    return opens, closes, float(60 * closes / len(values))


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question="Does the selected causal FX-strength state retain ETF return advantage after price and market checks?",
            hypothesis="CNY strength precedes incremental power-grid ETF demand that remains tradable from next open.",
            falsification_conditions=(
                "Predecessor receipt, artifact identity or factor-target alignment differs",
                "FX strength does not separate subsequent return after market and price controls",
                "The relation is concentrated in one period or cannot survive cost/frequency checks",
            ),
            development_cutoff=date(2026, 9, 24),
            random_seed=SEED,
            allowed_datasets=("etf.ohlcv", "index.domestic_daily", "fx.usdcnh_daily"),
            subjects=("159326.SZ",),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.MECHANISM_DISCOVERY,
                first_principles=("A macro state must add to known price and market state before strategy design",),
                information_paths=("Lagged USD/CNH trend -> ETF demand -> next-open tradable-price proxy",),
                stage_objectives=("Targeted post-selection falsification of H01 within the development pool",),
                observation_metrics=("State return spread, market difference, split periods, controls, block interval and transitions",),
                methodology=("Natural zero split; fixed 5/10/20-day outcomes; 20-day block resampling; no order simulation",),
                predecessor_experiment_ids=tuple(PREDECESSORS),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def synthetic_precheck(self) -> None:
        toy = pd.DataFrame({"FXStrength": [True, False, True, False], "Y": [2.0, 0.0, 4.0, 2.0]})
        difference, strong, other = _state_difference(toy, "Y")
        if not np.isclose(difference, 2.0) or (strong, other) != (2, 2):
            raise ValueError("state comparison differs on synthetic inputs")
        if ROUND_TRIP_COST_PROXY != 2 * 0.001 or HORIZONS != (5, 10, 20):
            raise ValueError("cost or horizon contract changed")

    def execute(self, context) -> ExperimentResult:
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        root = Path(__file__).resolve().parent
        for predecessor_id, receipt in PREDECESSORS.items():
            if context.predecessors[predecessor_id].receipt_sha256 != receipt:
                raise ValueError(f"predecessor receipt differs: {predecessor_id}")
            validate_experiment_archive(root.parent / predecessor_id)
        manual = pd.read_parquet(root.parent / "20260928_S011_EX02" / "artifacts" / "manual_factor_panel.parquet")
        target = pd.read_parquet(root.parent / "20260928_S011_EX03" / "artifacts" / "forward_targets.parquet")
        if len(manual) != 496 or len(target) != 496:
            raise ValueError("fixed decision calendar changed")
        target_dates = pd.DatetimeIndex(pd.to_datetime(target["Date"]).dt.normalize())
        if not pd.DatetimeIndex(manual.index).equals(target_dates):
            raise ValueError("factor and future target decision dates differ")
        needed = (FACTOR, *CONTROLS)
        if not set(needed).issubset(manual.columns):
            raise ValueError("frozen EX02 panel misses H01 or price controls")
        sample = manual[list(needed)].reset_index(drop=True).copy()
        sample["Date"] = target_dates
        sample["DecisionDay"] = np.arange(len(sample))
        sample["FXStrength"] = sample[FACTOR].lt(0)
        for horizon in HORIZONS:
            sample[f"ETF_h{horizon}"] = target[f"ETF_h{horizon}"].to_numpy(dtype=float)
            sample[f"Difference_h{horizon}"] = target[f"ETF_minus_market_h{horizon}"].to_numpy(dtype=float)
        required = list(needed) + [f"ETF_h{h}" for h in HORIZONS] + [f"Difference_h{h}" for h in HORIZONS]
        sample = sample.dropna(subset=required).reset_index(drop=True)
        if len(sample) < 400:
            raise ValueError("complete-case sample is shorter than frozen minimum 400 sessions")

        groups: list[dict[str, object]] = []
        for horizon in HORIZONS:
            for period, part in (
                ("ALL", sample),
                ("FIRST", sample.loc[sample["DecisionDay"].lt(SPLIT_DAY)]),
                ("SECOND", sample.loc[sample["DecisionDay"].ge(SPLIT_DAY)]),
            ):
                for outcome in (f"ETF_h{horizon}", f"Difference_h{horizon}"):
                    spread, strong, other = _state_difference(part, outcome)
                    groups.append({
                        "Horizon": horizon, "Period": period, "Outcome": outcome,
                        "Samples": len(part), "StrongN": strong, "OtherN": other,
                        "StrongMean": float(part.loc[part["FXStrength"], outcome].mean()),
                        "OtherMean": float(part.loc[~part["FXStrength"], outcome].mean()),
                        "StrongMinusOther": spread,
                    })
        group_frame = pd.DataFrame(groups)
        strata: list[dict[str, object]] = []
        sample["PriorETFPositive"] = sample["p_momentum_w20"].ge(0)
        sample["PriorMarketPositive"] = sample["x_market_momentum_w20"].ge(0)
        for (etf_positive, market_positive), part in sample.groupby(
            ["PriorETFPositive", "PriorMarketPositive"], sort=True
        ):
            spread, strong, other = _state_difference(part, "Difference_h10")
            strata.append({
                "PriorETFPositive": bool(etf_positive), "PriorMarketPositive": bool(market_positive),
                "Samples": len(part), "StrongN": strong, "OtherN": other,
                "MarketDifferenceSpread_h10": spread,
            })
        bootstrap = {}
        for outcome in ("ETF_h10", "Difference_h10"):
            low, high, valid_draws = _block_interval(sample, outcome)
            bootstrap[outcome] = {"lower_95": low, "upper_95": high, "valid_draws": valid_draws}
        coefficient, condition_number = _conditional_coefficient(sample, "Difference_h10")
        opens, closes, closes_per_60 = _transition_frequency(manual)
        strong_mean_h10 = float(sample.loc[sample["FXStrength"], "ETF_h10"].mean())
        summary = {
            "decision": "TARGETED_FX_DIAGNOSTIC_COMPLETE",
            "complete_case_days": len(sample),
            "first_day": str(sample["Date"].iloc[0].date()),
            "last_day": str(sample["Date"].iloc[-1].date()),
            "primary_etf_spread_h10": float(group_frame.loc[
                group_frame["Horizon"].eq(10) & group_frame["Period"].eq("ALL")
                & group_frame["Outcome"].eq("ETF_h10"), "StrongMinusOther"
            ].iloc[0]),
            "primary_market_difference_spread_h10": float(group_frame.loc[
                group_frame["Horizon"].eq(10) & group_frame["Period"].eq("ALL")
                & group_frame["Outcome"].eq("Difference_h10"), "StrongMinusOther"
            ].iloc[0]),
            "block_intervals": bootstrap,
            "conditional_market_difference_coefficient_h10": coefficient,
            "conditional_design_condition_number": condition_number,
            "state_open_transitions": opens,
            "state_close_transitions": closes,
            "state_closes_per_60_days": closes_per_60,
            "strong_state_etf_mean_h10_after_20bp_proxy": strong_mean_h10 - ROUND_TRIP_COST_PROXY,
            "strategy_or_orders_simulated": False,
            "post_selection_development_evidence": True,
        }
        group_frame.to_csv(context.workspace.path("state_groups.csv"), index=False, lineterminator="\n")
        pd.DataFrame(strata).to_csv(context.workspace.path("price_market_strata.csv"), index=False, lineterminator="\n")
        sample.to_parquet(context.workspace.path("complete_case_panel.parquet"), compression="zstd", index=False)
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        artifacts = tuple(context.workspace.register_artifact(name, role) for name, role in (
            ("state_groups.csv", "h01-state-outcome-groups"),
            ("price_market_strata.csv", "h01-price-market-strata"),
            ("complete_case_panel.parquet", "h01-complete-case-panel"),
            ("summary.json", "h01-diagnostic-summary"),
        ))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={
                "decision": summary["decision"], "complete_case_days": summary["complete_case_days"],
                "primary_etf_spread_h10": summary["primary_etf_spread_h10"],
                "primary_market_difference_spread_h10": summary["primary_market_difference_spread_h10"],
                "conditional_market_difference_coefficient_h10": coefficient,
                "state_closes_per_60_days": closes_per_60,
            },
            diagnostics={"strategy_or_orders_simulated": False, "post_selection_development_evidence": True},
            artifacts=artifacts,
        )
