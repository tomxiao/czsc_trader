from __future__ import annotations

from datetime import date
from hashlib import sha256
from math import atanh, erfc, sqrt
from pathlib import Path

from dataflows import DataRequest, DataStatus, Dataset
import numpy as np
import pandas as pd
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome,
    ExperimentProtocol, ExperimentResult, ExperimentStage, ResearchExperiment,
)


EX84 = "20260925_S008_EX84"
EX84_RECEIPT = "e30c7d917bca87278ee995d61f84dfb624567697cdf34c58a11a370602fcae79"
PANEL_HASH = "a757cafd1eb1322f4aebe3d68fc5a6792eab9aae8b13eed8f7b83618be2139b4"
OIL_HASH = "5f678d2a435bf3d1cc5025c6049c43da5c272c9725d878a0db0daf9971791ec3"
DRIVERS = {
    "real_yield": "rate_us_real_10y_change_20d",
    "usdcnh": "currency_usdcnh_return_20d",
    "equity_risk": "risk_sse_return_20d",
    "etf_flow": "flow_etf_share_change_20d",
    "gold_anchor": "gold_sge_return_20d",
    "domestic_oil": "oil_return_20d",
}
ERAS = {
    "early": ("2014-01-01", "2018-12-31"),
    "middle": ("2019-01-01", "2021-12-31"),
    "late": ("2022-01-01", "2024-12-31"),
    "oil_before": ("2018-01-01", "2021-12-31"),
    "oil_after": ("2022-01-01", "2024-12-31"),
}


def sample_anchors(sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Select disjoint 20-session windows without looking at returns."""
    if not sessions.is_monotonic_increasing or not sessions.is_unique:
        raise ValueError("ETF sessions must be ordered and unique")
    start = int(sessions.searchsorted(pd.Timestamp("2014-01-01")))
    positions = np.arange(start, len(sessions), 20)
    rows = []
    for pos in positions:
        current = sessions[pos]
        future = sessions[pos + 20] if pos + 20 < len(sessions) else pd.NaT
        for era, (begin, end) in ERAS.items():
            if not pd.Timestamp(begin) <= current <= pd.Timestamp(end):
                continue
            if pd.notna(future) and future > pd.Timestamp(end):
                continue
            rows.append({"Date": current, "Era": era, "Position": int(pos), "FutureDate": future})
    return pd.DataFrame(rows)


def _rho(x: pd.Series, y: pd.Series) -> tuple[int, float | None]:
    pair = pd.concat((x, y), axis=1).dropna()
    n = len(pair)
    if n < 4 or pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2:
        return n, None
    return n, float(pair.iloc[:, 0].corr(pair.iloc[:, 1], method="spearman"))


def _shift_p(r1: float, n1: int, r2: float, n2: int) -> float:
    a, b = np.clip((r1, r2), -0.999999, 0.999999)
    z = abs(atanh(a) - atanh(b)) / sqrt(1 / (n1 - 3) + 1 / (n2 - 3))
    return erfc(z / sqrt(2))


def _bh(pvalues: list[float]) -> list[float]:
    if not pvalues:
        return []
    order = np.argsort(pvalues)
    result = [1.0] * len(pvalues)
    running = 1.0
    for rank in range(len(order) - 1, -1, -1):
        index = int(order[rank])
        running = min(running, float(pvalues[index]) * len(pvalues) / (rank + 1))
        result[index] = running
    return result


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260925_S008_EX85",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Did gold ETF driver associations change across fixed historical periods, including domestic oil?",
            hypothesis="At least one driver association may differ across fixed periods; a change is not proof of causation.",
            falsification_conditions=(
                "No comparison meets the preregistered multiplicity-adjusted sign-switch rule",
                "A key source is unavailable or has an unexpected identity",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026098501,
            allowed_datasets=(Dataset.DOMESTIC_INDEX_DAILY.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.MECHANISM_DISCOVERY,
                first_principles=(
                    "Gold opportunity cost, currency translation, risk demand and ETF ownership have competing price paths",
                    "Oil supply and demand shocks may imply opposite gold responses",
                ),
                information_paths=(
                    "Causal macro and market variables at T -> ETF return in disjoint future 20-session window",
                    "Same-window variables and ETF return -> descriptive co-movement only",
                ),
                stage_objectives=("Audit stable historical association and possible fixed-era switches",),
                observation_metrics=("Era Spearman rho, sample count, Fisher shift p and BH q",),
                methodology=(
                    "Read pinned EX16 causal panel only through 2024 and pinned EX84 oil via DFLS",
                    "Select every twentieth ETF session before inspecting return values",
                    "No parameter search, strategy backtest or sealed validation",
                ),
                predecessor_experiment_ids=(EX84,),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
                ExperimentDependency("tushare", "1.4.29"),
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[EX84]
        if predecessor.receipt_sha256 != EX84_RECEIPT:
            raise ValueError("EX84 receipt identity differs")
        if predecessor.facts.get("decision") != "PROCEED_DOMESTIC_OIL_DRIVER_SATELLITE":
            raise ValueError("EX84 oil data gate differs")
        repo = Path(__file__).resolve().parents[3]
        panel_path = repo / "experiments/S008/20260923_S008_EX16/artifacts/causal_feature_panel.csv.gz"
        if sha256(panel_path.read_bytes()).hexdigest() != PANEL_HASH:
            raise ValueError("EX16 causal panel identity differs")
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        panel = pd.read_csv(panel_path, parse_dates=["Date"]).set_index("Date").sort_index()
        if not panel.index.is_unique or panel.index.max() != pd.Timestamp("2024-12-31"):
            raise ValueError("EX16 calendar or cutoff differs")
        oil = context.data.fetch(DataRequest(
            Dataset.DOMESTIC_INDEX_DAILY, "SC.NH", "2018-03-26", "2024-12-31",
            "2024-12-01", options={"env_file": ".env"},
        ))
        if oil.status is not DataStatus.READY or oil.identity is None:
            raise ValueError("SC.NH DFLS publication not READY")
        if oil.identity.content_sha256 != OIL_HASH:
            raise ValueError("SC.NH identity differs from EX84")
        oil_frame = oil.dataframe.sort_values("Date").set_index("Date")
        oil_close = pd.to_numeric(oil_frame["Close"])
        oil_at_prior_session = oil_close.reindex(panel.index).ffill().shift(1)
        panel["oil_return_20d"] = oil_at_prior_session.pct_change(20, fill_method=None)
        anchors = sample_anchors(panel.index)
        if anchors.empty:
            raise ValueError("no anchors")
        for name in DRIVERS.values():
            if name not in panel:
                raise ValueError(f"missing driver {name}")
        correlations = []
        for relation in ("contemporaneous", "predictive"):
            for era in ERAS:
                sample = anchors.loc[anchors["Era"] == era]
                pos = sample["Position"].to_numpy(dtype=int)
                if relation == "predictive":
                    pos = pos[pos + 20 < len(panel)]
                    outcome = panel["price_return_20d"].iloc[pos + 20].reset_index(drop=True)
                else:
                    outcome = panel["price_return_20d"].iloc[pos].reset_index(drop=True)
                for driver, col in DRIVERS.items():
                    if (driver == "domestic_oil") != era.startswith("oil_"):
                        continue
                    values = panel[col].iloc[pos].reset_index(drop=True)
                    n, rho = _rho(values, outcome)
                    correlations.append({
                        "Relation": relation, "Era": era, "Driver": driver,
                        "N": n, "SpearmanRho": rho,
                    })
        corr = pd.DataFrame(correlations)
        tests = []
        comparisons = (("early", "late"), ("middle", "late"), ("oil_before", "oil_after"))
        for relation in ("contemporaneous", "predictive"):
            for left, right in comparisons:
                drivers = ("domestic_oil",) if left.startswith("oil_") else tuple(d for d in DRIVERS if d != "domestic_oil")
                for driver in drivers:
                    a = corr.loc[(corr.Relation == relation) & (corr.Era == left) & (corr.Driver == driver)].iloc[0]
                    b = corr.loc[(corr.Relation == relation) & (corr.Era == right) & (corr.Driver == driver)].iloc[0]
                    p = _shift_p(float(a.SpearmanRho), int(a.N), float(b.SpearmanRho), int(b.N)) if int(a.N) >= 20 and int(b.N) >= 20 and pd.notna(a.SpearmanRho) and pd.notna(b.SpearmanRho) else None
                    tests.append({
                        "Relation": relation, "LeftEra": left, "RightEra": right,
                        "Driver": driver, "LeftN": int(a.N), "RightN": int(b.N),
                        "LeftRho": a.SpearmanRho, "RightRho": b.SpearmanRho,
                        "DeltaRho": float(b.SpearmanRho - a.SpearmanRho) if pd.notna(a.SpearmanRho) and pd.notna(b.SpearmanRho) else None,
                        "PApprox": p,
                    })
        shifts = pd.DataFrame(tests)
        valid = shifts["PApprox"].notna()
        shifts["QBH"] = np.nan
        shifts.loc[valid, "QBH"] = _bh(shifts.loc[valid, "PApprox"].tolist())
        shifts["SwitchClue"] = (
            (shifts["LeftRho"] * shifts["RightRho"] < 0)
            & (shifts["DeltaRho"].abs() >= 0.35)
            & (shifts["QBH"] <= 0.10)
            & (shifts["LeftN"] >= 20) & (shifts["RightN"] >= 20)
        )
        corr.to_csv(context.workspace.path("era_correlations.csv"), index=False, lineterminator="\n")
        shifts.to_csv(context.workspace.path("shift_tests.csv"), index=False, lineterminator="\n")
        pd.DataFrame([
            {"Input": "EX16 causal feature panel", "Sha256": PANEL_HASH, "Cutoff": "2024-12-31"},
            {"Input": "DFLS SC.NH", "Sha256": oil.identity.content_sha256, "Cutoff": oil.identity.data_cutoff},
        ]).to_csv(context.workspace.path("input_identities.csv"), index=False, lineterminator="\n")
        clues = shifts.loc[shifts["SwitchClue"], ["Relation", "LeftEra", "RightEra", "Driver"]].to_dict("records")
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if clues else ExperimentOutcome.INCONCLUSIVE,
            facts={
                "decision": "ASSOCIATION_SHIFT_CLUE" if clues else "NO_PREREGISTERED_ASSOCIATION_SHIFT",
                "clues": clues,
                "anchor_count": int(anchors.loc[anchors.Era.isin(("early", "middle", "late")), "Date"].nunique()),
                "tested_comparisons": len(shifts),
                "valid_comparisons": int(valid.sum()),
                "oil_identity": oil.identity.content_sha256,
            },
            diagnostics={"causal_claim": False, "alpha_claim": False, "reads_sealed_validation": False},
            artifacts=(
                context.workspace.register_artifact("era_correlations.csv", "driver-era-correlations"),
                context.workspace.register_artifact("shift_tests.csv", "multiplicity-adjusted-shift-tests"),
                context.workspace.register_artifact("input_identities.csv", "pinned-input-identities"),
            ),
        )
