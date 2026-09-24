from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.data import load_execution_prices
from dataflows import DataRequest, DataStatus, Dataset
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
import statsmodels.api as sm


EX73 = "20260924_S008_EX73"
EX73_RECEIPT = "eacee397d9e54726fb0dc17956d6451edf42729239bd3a0a574ecfaf403698d1"
EX16_PANEL_SHA256 = "a757cafd1eb1322f4aebe3d68fc5a6792eab9aae8b13eed8f7b83618be2139b4"
EXECUTION_MANIFEST_SHA256 = "fc5aac30019deed1c04204b7e3a967963782bf0e8bfbe5da3e1b1ce420a832a8"
CPI_SHA256 = "d255b9ed0aeba2f26ddd71d8f8704568864facb4c49d7a3faab190c39946b559"
START = "2013-07-29"
CUTOFF = "2024-12-31"
DISCOVERY_END = "2018-12-31"
CONFIRMATION_START = "2019-01-01"
FEATURES = ("CpiYoY", "CpiAcceleration")
CONTROLS = (
    "rate_us_real_10y_level",
    "rate_us_real_10y_change_20d",
    "currency_usdcnh_return_20d",
    "price_return_20d",
)
HORIZONS = (5, 20, 60)


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _spearman(x: pd.Series, y: pd.Series) -> float | None:
    pair = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
    if len(pair) < 3 or pair["x"].nunique() < 2 or pair["y"].nunique() < 2:
        return None
    return float(pair["x"].corr(pair["y"], method="spearman"))


def _partial_ic(frame: pd.DataFrame) -> float | None:
    complete = frame.loc[:, ["score", "outcome", *CONTROLS]].dropna()
    if len(complete) < 30 or complete["score"].nunique() < 2:
        return None
    controls = sm.add_constant(complete.loc[:, CONTROLS].astype(float), has_constant="add")
    score_residual = sm.OLS(complete["score"].astype(float), controls).fit().resid
    outcome_residual = sm.OLS(complete["outcome"].astype(float), controls).fit().resid
    return _spearman(score_residual, outcome_residual)


def _bootstrap_positive(frame: pd.DataFrame, seed: int) -> float | None:
    pair = frame.loc[:, ["score", "outcome"]].dropna()
    if len(pair) < 50 or pair["score"].nunique() < 2:
        return None
    ranked = pair.rank(method="average", pct=True).to_numpy(dtype=float)
    n = len(ranked)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(500, (n + 2) // 3))
    indices = ((starts[:, :, None] + np.arange(3)) % n).reshape(500, -1)[:, :n]
    samples = ranked[indices]
    x = samples[:, :, 0] - samples[:, :, 0].mean(axis=1, keepdims=True)
    y = samples[:, :, 1] - samples[:, :, 1].mean(axis=1, keepdims=True)
    denominator = np.sqrt((x * x).sum(axis=1) * (y * y).sum(axis=1))
    correlations = (x * y).sum(axis=1) / denominator
    valid = correlations[np.isfinite(correlations)]
    if len(valid) < 475:
        return None
    return float(np.mean(valid > 0))


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260924_S008_EX74",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Does US CPI release information add stable gold ETF upside information after existing state controls?",
            hypothesis="At least one causal CPI event feature retains positive 20-session information after real-rate, currency and price controls.",
            falsification_conditions=(
                "The CPI or execution input identity and causal calendar gate fails",
                "Independent event counts are insufficient in discovery or confirmation",
                "No CPI feature meets the preregistered stability and incremental-information criteria",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026097401,
            allowed_datasets=(Dataset.US_CPI_RELEASE.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "Inflation can raise gold demand through purchasing-power protection",
                    "Inflation can instead raise real-rate or dollar expectations and suppress gold",
                ),
                information_paths=(
                    "released CPI level or acceleration -> gold participation -> later ETF upside",
                    "released CPI -> real rates, currency and price state -> later ETF return",
                ),
                stage_objectives=(
                    "Test event-level CPI information in the development pool",
                    "Distinguish raw association from information beyond existing state controls",
                ),
                observation_metrics=(
                    "5/20/60-session discovery and confirmation rank IC",
                    "confirmation partial IC, annual direction and event-block bootstrap",
                ),
                methodology=(
                    "Verify frozen predecessor and input identities before reading returns",
                    "Use first SSE session after Shanghai release as decision date",
                    "Orient only from discovery 20-session labels and audit both preregistered features",
                ),
                predecessor_experiment_ids=(EX73,),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
                ExperimentDependency("statsmodels", sm.__version__),
                ExperimentDependency("tushare", "1.4.29"),
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[EX73]
        if predecessor.receipt_sha256 != EX73_RECEIPT or predecessor.facts.get("decision") != "PROCEED_US_CPI_INFORMATION_VALUE_AUDIT":
            raise ValueError("EX73 data-gate receipt differs")
        publication = context.data.fetch(
            DataRequest(Dataset.US_CPI_RELEASE, None, START, CUTOFF, "2024-12-11", options={"env_file": ".env"})
        )
        if publication.status is not DataStatus.READY or publication.identity is None:
            raise RuntimeError(f"DFLS CPI is not READY: {publication.error}")
        if publication.identity.content_sha256 != CPI_SHA256:
            raise ValueError("DFLS CPI source identity changed since preregistration")
        cpi = publication.dataframe.copy().sort_values("Date")
        if len(cpi) != 137 or cpi["Date"].duplicated().any():
            raise ValueError("CPI release count or uniqueness differs")
        if not (cpi["AvailableDate"].gt(cpi["Date"])).all():
            raise ValueError("CPI availability leaked into the release day")
        eastern = cpi["ReleaseAt"].dt.tz_convert("America/New_York")
        if not eastern.dt.strftime("%H:%M").eq("08:30").all():
            raise ValueError("CPI release time is not BLS 08:30 Eastern")
        cpi["CpiYoY"] = cpi["YoYPercent"].astype(float)
        cpi["CpiAcceleration"] = cpi["CpiYoY"].diff()
        events = cpi.set_index("AvailableDate").loc[:, list(FEATURES)]
        if events.index.duplicated().any():
            raise ValueError("Multiple releases share a single available session")

        root = _root()
        panel_path = root / "experiments" / "S008" / "20260923_S008_EX16" / "artifacts" / "causal_feature_panel.csv.gz"
        if sha256(panel_path.read_bytes()).hexdigest() != EX16_PANEL_SHA256:
            raise ValueError("EX16 causal feature panel identity differs")
        panel = pd.read_csv(panel_path, compression="gzip", parse_dates=["Date"]).set_index("Date").sort_index()
        controls = panel.loc[:, list(CONTROLS)]
        if not events.index.isin(controls.index).all():
            raise ValueError("CPI event is not on the sealed causal decision calendar")
        if sha256((root / "data" / "raw" / "518880_execution_manifest.json").read_bytes()).hexdigest() != EXECUTION_MANIFEST_SHA256:
            raise ValueError("execution manifest identity differs")
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        prices = load_execution_prices(root / "data" / "raw", symbol="518880.SH", asset_type="etf", cutoff=CUTOFF)
        prices["Date"] = pd.to_datetime(prices["dt"]).dt.normalize()
        prices = prices.set_index("Date").sort_index()
        if not prices.index.equals(panel.index):
            raise ValueError("execution and causal feature calendars differ")
        opens = prices["open"].astype(float)
        sessions = pd.Series(prices.index, index=prices.index)
        outcomes = {h: opens.shift(-(h + 1)).div(opens.shift(-1)).sub(1) for h in HORIZONS}
        exits = {h: sessions.shift(-(h + 1)) for h in HORIZONS}
        controls = controls.loc[events.index]
        discover = events.index <= pd.Timestamp(DISCOVERY_END)
        confirm = events.index >= pd.Timestamp(CONFIRMATION_START)
        orientations: dict[str, float] = {}
        raw_discovery_ic: dict[str, float | None] = {}
        primary_mask = discover & exits[20].loc[events.index].le(pd.Timestamp(DISCOVERY_END)).to_numpy()
        for feature in FEATURES:
            ic = _spearman(events.loc[primary_mask, feature], outcomes[20].loc[events.index[primary_mask]])
            raw_discovery_ic[feature] = ic
            orientations[feature] = -1.0 if ic is not None and ic < 0 else 1.0

        rows: list[dict[str, object]] = []
        for feature_ordinal, feature in enumerate(FEATURES):
            for h in HORIZONS:
                discovery_mask = discover & exits[h].loc[events.index].le(pd.Timestamp(DISCOVERY_END)).to_numpy()
                confirmation_mask = confirm & exits[h].loc[events.index].le(pd.Timestamp(CUTOFF)).to_numpy()
                discovery_dates = events.index[discovery_mask]
                confirmation_dates = events.index[confirmation_mask]
                d = pd.DataFrame({"score": events.loc[discovery_dates, feature] * orientations[feature], "outcome": outcomes[h].loc[discovery_dates]}).dropna()
                c = pd.DataFrame({"score": events.loc[confirmation_dates, feature] * orientations[feature], "outcome": outcomes[h].loc[confirmation_dates]}).join(controls)
                complete = c.dropna()
                annual = {str(year): _spearman(complete.loc[complete.index.year == year, "score"], complete.loc[complete.index.year == year, "outcome"]) for year in range(2019, 2025)}
                identifiable = len(d) >= 50 and len(complete) >= 50 and complete["score"].nunique() >= 10
                rows.append({
                    "feature": feature,
                    "horizon": h,
                    "orientation": "POSITIVE" if orientations[feature] > 0 else "NEGATIVE",
                    "raw_primary_discovery_ic": raw_discovery_ic[feature],
                    "discovery_events": len(d),
                    "confirmation_events": len(complete),
                    "confirmation_unique_values": int(complete["score"].nunique()),
                    "discovery_ic": _spearman(d["score"], d["outcome"]),
                    "confirmation_ic": _spearman(complete["score"], complete["outcome"]),
                    "confirmation_partial_ic": _partial_ic(complete) if identifiable else None,
                    "annual_ic": json.dumps(annual, sort_keys=True, allow_nan=False),
                    "positive_years": sum(value is not None and value > 0 for value in annual.values()),
                    "bootstrap_positive_probability": _bootstrap_positive(complete, 2026097401 + feature_ordinal * 100 + h) if identifiable else None,
                    "identifiable": identifiable,
                })
        ledger = pd.DataFrame(rows)
        ledger["positive_horizon_count"] = ledger.groupby("feature")["confirmation_ic"].transform(lambda values: int(values.gt(0).sum()))
        stable = (
            ledger["identifiable"]
            & ledger["raw_primary_discovery_ic"].abs().ge(0.10)
            & ledger["confirmation_ic"].ge(0.10)
            & ledger["confirmation_partial_ic"].ge(0.10)
            & ledger["positive_years"].ge(4)
            & ledger["positive_horizon_count"].ge(2)
            & ledger["bootstrap_positive_probability"].ge(0.80)
            & ledger["horizon"].eq(20)
        )
        ledger["evidence_label"] = "NO_STABLE_EVIDENCE"
        ledger.loc[~ledger["identifiable"], "evidence_label"] = "UNIDENTIFIABLE"
        ledger.loc[stable, "evidence_label"] = "STABLE_INCREMENTAL_INFORMATION"
        supported = ledger.loc[stable, "feature"].tolist()
        primary_identifiable = ledger.loc[ledger["horizon"].eq(20), "identifiable"].all()
        decision = (
            "INCONCLUSIVE_CPI_INFORMATION_AUDIT" if not primary_identifiable
            else "PROCEED_CPI_ROLE_REVIEW" if supported
            else "STOP_CPI_AS_UPSIDE_SOURCE"
        )
        ledger_path = context.workspace.path("information_path_ledger.csv")
        ledger.to_csv(ledger_path, index=False, float_format="%.12f", lineterminator="\n")
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if supported else ExperimentOutcome.INCONCLUSIVE,
            facts={
                "decision": decision,
                "event_count": len(cpi),
                "path_count": len(ledger),
                "supported_primary_features": supported,
                "cpi_content_sha256": publication.identity.content_sha256,
                "execution_manifest_sha256": EXECUTION_MANIFEST_SHA256,
            },
            diagnostics={
                "reads_development_returns": True,
                "reads_sealed_validation": False,
                "selects_prototype": False,
                "searches_parameters": False,
                "creates_candidate": False,
            },
            artifacts=(context.workspace.register_artifact("information_path_ledger.csv", "cpi-event-information-ledger"),),
        )
