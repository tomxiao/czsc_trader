from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path

from czsc_trader.data import load_execution_prices
from dataflows import Dataset
import numpy as np
import pandas as pd
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)


EX79 = "20260924_S008_EX79"
EX79_RECEIPT = "9b523167ec93271e2d2dbf13473cd925db30c0b50a3293d1e79e331679f20547"
EX85 = "20260925_S008_EX85"
EX85_RECEIPT = "f9563be746df8c62d517a87469b348386117a72f8673088f80dfa9ce14c667c2"
POSITION_SHA256 = "bc3547d53effbcac45433a7c73fd0a9411fbc7184189e56857df721b54f48466"
METRICS_SHA256 = "c602a0aee1a186fcc16b4ab9086dc178218af94006c741f4b29e0de5f955bbb6"
PANEL_SHA256 = "a757cafd1eb1322f4aebe3d68fc5a6792eab9aae8b13eed8f7b83618be2139b4"
EXECUTION_MANIFEST_SHA256 = "fc5aac30019deed1c04204b7e3a967963782bf0e8bfbe5da3e1b1ce420a832a8"
REPRESENTATIVES = ("P02_REGIME_RECOVERY", "P06_CORE_CARRY_REGIME_VETO")
FEATURES = (
    "price_return_20d", "gold_sge_return_20d", "currency_usdcnh_return_20d",
    "rate_us_real_10y_change_20d", "risk_sse_return_20d",
)


def quarter_attribution(frame: pd.DataFrame, representative: str) -> pd.DataFrame:
    """Pure, fixed-calendar attribution used by the synthetic precheck and experiment."""
    if not {"OpenLogReturn", representative}.issubset(frame):
        raise ValueError("attribution inputs are incomplete")
    result = []
    for quarter, group in frame.groupby(frame.index.to_period("Q"), sort=True):
        returns = group["OpenLogReturn"].astype(float)
        held = group[representative].astype(int)
        if not held.isin((0, 1)).all() or returns.isna().any():
            raise ValueError("invalid position or return")
        cash = held.eq(0)
        missed_positive = float(returns.loc[cash & returns.gt(0)].sum())
        avoided_negative = float(-returns.loc[cash & returns.lt(0)].sum())
        buyhold = float(returns.sum())
        strategy = float((returns * held).sum())
        if not np.isclose(buyhold - strategy, missed_positive - avoided_negative, atol=1e-12):
            raise ValueError("quarter attribution does not reconcile")
        stretches = cash.ne(cash.shift()).cumsum()
        longest_cash = int(cash.groupby(stretches).sum().max())
        first_held = np.flatnonzero(held.to_numpy() == 1)
        result.append({
            "Quarter": str(quarter), "Representative": representative,
            "FirstDate": group.index.min().date().isoformat(),
            "LastDate": group.index.max().date().isoformat(),
            "Sessions": len(group), "BuyHoldLogReturn": buyhold,
            "HeldLogReturn": strategy, "Exposure": float(held.mean()),
            "CashSessions": int(cash.sum()),
            "MissedPositiveLogReturn": missed_positive,
            "AvoidedNegativeLogReturn": avoided_negative,
            "NetCashOpportunityGap": buyhold - strategy,
            "Early20CashSessions": int(cash.iloc[:20].sum()),
            "LongestCashRun": longest_cash,
            "FirstHeldDelay": int(first_held[0]) if len(first_held) else None,
        })
    return pd.DataFrame(result)


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260925_S008_EX86",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Which fixed-calendar upside quarters were missed by frozen S008 representatives, and what was already observable?",
            hypothesis="Upside participation gaps may cluster in episodes where the representative remains cash despite prior observable gold and price recovery.",
            falsification_conditions=(
                "Missed upside is not concentrated in the fixed top-ten upside quarters",
                "Attribution fails to reconcile or prior-session inputs are unavailable",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026098601,
            allowed_datasets=(Dataset.ETF_UNADJUSTED_DAILY.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.MECHANISM_DISCOVERY,
                first_principles=(
                    "A long-or-cash strategy can exceed BuyHold only by participating sufficiently in rises and avoiding sufficient falls",
                    "High exposure can solve missed upside while sacrificing downside protection",
                ),
                information_paths=(
                    "Prior-session gold, ETF and macro observations -> fixed representative position -> next open-to-open return",
                ),
                stage_objectives=("Locate upside participation gaps without creating a new trading rule",),
                observation_metrics=("Quarter return decomposition, exposure, cash delay and prior-session feature availability",),
                methodology=(
                    "Pin EX48 positions, EX16 panel and execution-price manifest",
                    "Select top-ten positive calendar quarters by fixed BuyHold ranking",
                    "Reconcile each quarter and compare prior-session observations without p-value claims",
                ),
                predecessor_experiment_ids=(EX79, EX85),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def execute(self, context) -> ExperimentResult:
        for name, receipt, decision in (
            (EX79, EX79_RECEIPT, "DISCOVERY_ONLY_OPPORTUNITY_MAP_REVIEW_REQUIRED"),
            (EX85, EX85_RECEIPT, "NO_PREREGISTERED_ASSOCIATION_SHIFT"),
        ):
            predecessor = context.predecessors[name]
            if predecessor.receipt_sha256 != receipt or predecessor.facts.get("decision") != decision:
                raise ValueError(f"{name} predecessor differs")
        root = Path(__file__).resolve().parents[3]
        position_path = root / "experiments/S008/20260923_S008_EX48/artifacts/representative_positions.csv.gz"
        metrics_path = root / "experiments/S008/20260923_S008_EX48/artifacts/position_gap_metrics.csv"
        panel_path = root / "experiments/S008/20260923_S008_EX16/artifacts/causal_feature_panel.csv.gz"
        manifest_path = root / "data/raw/518880_execution_manifest.json"
        for path, expected in ((position_path, POSITION_SHA256), (metrics_path, METRICS_SHA256), (panel_path, PANEL_SHA256), (manifest_path, EXECUTION_MANIFEST_SHA256)):
            if sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"pinned input differs: {path.name}")
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        positions = pd.read_csv(position_path, parse_dates=["Date"]).set_index("Date").sort_index()
        panel = pd.read_csv(panel_path, parse_dates=["Date"]).set_index("Date").sort_index()
        if positions.index[0] != pd.Timestamp("2014-07-31") or positions.index[-1] != pd.Timestamp("2024-12-31"):
            raise ValueError("EX48 position window differs")
        if not positions.index.is_unique or not positions.index.isin(panel.index).all():
            raise ValueError("position dates differ from causal panel")
        prices = load_execution_prices(root / "data/raw", symbol="518880.SH", asset_type="etf", cutoff="2024-12-31")
        opens = prices["open"].reindex(positions.index).astype(float)
        if opens.isna().any() or not opens.gt(0).all():
            raise ValueError("execution open prices unavailable")
        returns = np.log(opens.shift(-1) / opens).dropna()
        frame = positions.loc[returns.index, ["oracle", *REPRESENTATIVES]].copy()
        frame["OpenLogReturn"] = returns
        if not frame["oracle"].isin((0, 1)).all():
            raise ValueError("oracle position invalid")
        ledger = pd.concat((quarter_attribution(frame, name) for name in REPRESENTATIVES), ignore_index=True)
        rankings = ledger.loc[ledger.Representative == REPRESENTATIVES[0]]
        rankings = rankings.loc[(rankings.Sessions >= 30) & (rankings.BuyHoldLogReturn > 0)]
        selected = rankings.sort_values(["BuyHoldLogReturn", "Quarter"], ascending=[False, True]).head(10)
        if len(selected) != 10:
            raise ValueError("fewer than ten positive complete quarters")
        top_quarters = selected["Quarter"].tolist()
        ledger["Top10Upside"] = ledger["Quarter"].isin(top_quarters)
        observations = []
        prior_panel = panel[list(FEATURES)].shift(1).reindex(frame.index)
        for quarter in top_quarters:
            dates = frame.index[frame.index.to_period("Q").astype(str) == quarter]
            first = dates[0]
            first_values = prior_panel.loc[first]
            for name in REPRESENTATIVES:
                segment = frame.loc[dates]
                missed_positive = segment.index[(segment[name].eq(0)) & (segment["OpenLogReturn"].gt(0))]
                leading = prior_panel.loc[missed_positive]
                known = leading[["price_return_20d", "gold_sge_return_20d"]].notna().all(axis=1)
                aligned = leading.loc[known]
                both_positive = (aligned["price_return_20d"] > 0) & (aligned["gold_sge_return_20d"] > 0)
                observations.append({
                    "Quarter": quarter, "Representative": name,
                    "LeadDate": first.date().isoformat(),
                    **{f"Lead_{field}": float(first_values[field]) if pd.notna(first_values[field]) else None for field in FEATURES},
                    "MissedPositiveSessions": len(missed_positive),
                    "KnownPriorPriceGoldSessions": int(known.sum()),
                    "PriorPriceGoldBothPositiveSessions": int(both_positive.sum()),
                    "PriorPriceGoldBothPositiveShare": float(both_positive.mean()) if len(aligned) else None,
                    "MissingPriorPriceGoldSessions": int((~known).sum()),
                })
        observation_frame = pd.DataFrame(observations)
        ex48 = pd.read_csv(metrics_path)
        for name in REPRESENTATIVES:
            subgroup = frame.loc[:, [name, "OpenLogReturn"]]
            held = subgroup[name].astype(bool)
            positive = returns.gt(0)
            negative = returns.lt(0)
            expected_exposure = float(held.mean())
            expected_capture = float(returns.loc[positive & held].sum() / returns.loc[positive].sum())
            expected_avoidance = float(1 - abs(returns.loc[negative & held].sum()) / abs(returns.loc[negative].sum()))
            original = ex48.loc[ex48.representative == name].iloc[0]
            for computed, field in (
                (expected_exposure, "exposure_ratio"),
                (expected_capture, "positive_log_return_capture_ratio"),
                (expected_avoidance, "negative_log_return_avoidance_ratio"),
            ):
                if not np.isclose(computed, float(original[field]), atol=1e-11):
                    raise ValueError(f"EX48 total does not reconcile: {name} {field}")
        ledger.sort_values(["Quarter", "Representative"]).to_csv(context.workspace.path("quarter_attribution.csv"), index=False, float_format="%.12f", lineterminator="\n")
        observation_frame.to_csv(context.workspace.path("prior_observability.csv"), index=False, float_format="%.12f", lineterminator="\n")
        p02 = ledger.loc[(ledger.Representative == REPRESENTATIVES[0]) & ledger.Top10Upside]
        other = ledger.loc[(ledger.Representative == REPRESENTATIVES[1]) & ledger.Top10Upside]
        facts = {
            "decision": "REVIEW_UPSIDE_PARTICIPATION_GAPS",
            "top10_quarters": top_quarters,
            "p02_top10_missed_positive_log_return": float(p02.MissedPositiveLogReturn.sum()),
            "p02_top10_avoided_negative_log_return": float(p02.AvoidedNegativeLogReturn.sum()),
            "p06_top10_missed_positive_log_return": float(other.MissedPositiveLogReturn.sum()),
            "p06_top10_avoided_negative_log_return": float(other.AvoidedNegativeLogReturn.sum()),
            "p02_top10_net_cash_gap": float(p02.NetCashOpportunityGap.sum()),
            "all_quarters": int(ledger.Quarter.nunique()),
        }
        return ExperimentResult(
            outcome=ExperimentOutcome.INCONCLUSIVE,
            facts=facts,
            diagnostics={"descriptive_only": True, "new_strategy_rule": False, "reads_sealed_validation": False},
            artifacts=(
                context.workspace.register_artifact("quarter_attribution.csv", "frozen-representative-quarter-attribution"),
                context.workspace.register_artifact("prior_observability.csv", "prior-session-observability-in-upside-quarters"),
            ),
        )
