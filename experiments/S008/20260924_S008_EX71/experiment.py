from __future__ import annotations

from datetime import date
from hashlib import sha256
import gzip
import json
from math import ceil
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


EX70_ID = "20260924_S008_EX70"
EX70_RECEIPT = "f56689b29a6602e4ac6df171a40d6b91bbd6bb46a5c343e1952aa74d97f434d9"
EXECUTION_MANIFEST_SHA256 = "fc5aac30019deed1c04204b7e3a967963782bf0e8bfbe5da3e1b1ce420a832a8"
START = "2013-07-29"
CUTOFF = "2024-12-31"
DISCOVERY_END = "2018-12-31"
CONFIRMATION_START = "2019-01-01"
HORIZONS = (5, 20, 60)
INTRADAY_FEATURES = (
    "CloseLocation",
    "MorningReturn",
    "AfternoonReturn",
    "LastHourReturn",
    "LastHourVolumeShare",
    "LastHourAmountShare",
    "OvernightGap",
    "IntradayReturn",
)
FUTURES_FEATURES = ("CurveSlope", "OpenInterestGrowth5", "HoldingImbalance")
FEATURES = INTRADAY_FEATURES + FUTURES_FEATURES


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _spearman(left: pd.Series, right: pd.Series) -> float | None:
    pair = pd.concat([left.rename("x"), right.rename("y")], axis=1).dropna()
    if len(pair) < 3 or pair["x"].nunique() < 2 or pair["y"].nunique() < 2:
        return None
    return float(pair["x"].corr(pair["y"], method="spearman"))


def _score(discovery: pd.Series, confirmation: pd.Series) -> tuple[pd.Series, pd.Series]:
    training = discovery.dropna().astype(float)
    if len(training) < 3:
        return pd.Series(np.nan, index=discovery.index), pd.Series(np.nan, index=confirmation.index)
    low, high = training.quantile([0.01, 0.99]).tolist()
    reference = np.sort(training.clip(low, high).to_numpy(dtype=float))
    if np.unique(reference).size < 2:
        return pd.Series(np.nan, index=discovery.index), pd.Series(np.nan, index=confirmation.index)

    def transform(values: pd.Series) -> pd.Series:
        numeric = values.astype(float).clip(low, high)
        positions = np.searchsorted(reference, numeric.to_numpy(dtype=float), side="right")
        output = pd.Series(positions / len(reference) - 0.5, index=values.index, dtype=float)
        output.loc[values.isna()] = np.nan
        return output

    return transform(discovery), transform(confirmation)


def _partial_ic(score: pd.Series, outcome: pd.Series, prices: pd.DataFrame) -> float | None:
    close = prices["close"].astype(float)
    past_return = close.pct_change(20, fill_method=None)
    volatility = close.pct_change(fill_method=None).rolling(20).std(ddof=0)
    years = pd.get_dummies(score.index.year, prefix="year", drop_first=True, dtype=float)
    years.index = score.index
    frame = pd.concat(
        [
            score.rename("score"),
            outcome.rename("outcome"),
            past_return.rename("past_return_20"),
            volatility.rename("volatility_20"),
            years,
        ],
        axis=1,
    ).dropna()
    if len(frame) < 100 or frame["score"].nunique() < 2:
        return None
    controls = sm.add_constant(frame.drop(columns=["score", "outcome"]).astype(float))
    score_residual = sm.OLS(frame["score"].astype(float), controls).fit().resid
    outcome_residual = sm.OLS(frame["outcome"].astype(float), controls).fit().resid
    return _spearman(score_residual, outcome_residual)


def _hac_pvalue(score: pd.Series, outcome: pd.Series, horizon: int) -> float | None:
    pair = pd.concat([score.rename("score"), outcome.rename("outcome")], axis=1).dropna()
    if len(pair) < 100 or pair["score"].nunique() < 2:
        return None
    normalized = (pair["score"] - pair["score"].mean()) / pair["score"].std(ddof=0)
    fit = sm.OLS(
        pair["outcome"].to_numpy(dtype=float),
        sm.add_constant(normalized.to_numpy(dtype=float)),
    ).fit(cov_type="HAC", cov_kwds={"maxlags": horizon})
    two_sided = float(fit.pvalues[1])
    return two_sided / 2 if float(fit.params[1]) >= 0 else 1 - two_sided / 2


def _bootstrap_probability(score: pd.Series, outcome: pd.Series, seed: int) -> float | None:
    pair = pd.concat([score.rename("score"), outcome.rename("outcome")], axis=1).dropna()
    if len(pair) < 100 or pair["score"].nunique() < 2:
        return None
    ranked = pair.rank(method="average", pct=True).to_numpy(dtype=float)
    count = len(ranked)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, count, size=(200, ceil(count / 60)))
    indices = ((starts[:, :, None] + np.arange(60)) % count).reshape(200, -1)[:, :count]
    sampled = ranked[indices]
    x = sampled[:, :, 0] - sampled[:, :, 0].mean(axis=1, keepdims=True)
    y = sampled[:, :, 1] - sampled[:, :, 1].mean(axis=1, keepdims=True)
    denominator = np.sqrt((x * x).sum(axis=1) * (y * y).sum(axis=1))
    correlations = (x * y).sum(axis=1) / denominator
    finite = correlations[np.isfinite(correlations)]
    if len(finite) < 190:
        raise ValueError("too many invalid block-bootstrap repetitions")
    return float(np.mean(finite > 0))


def _bh(pvalues: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=pvalues.index, dtype=float)
    ordered = pvalues.dropna().sort_values()
    if ordered.empty:
        return result
    adjusted = ordered.to_numpy(dtype=float) * len(ordered) / np.arange(1, len(ordered) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    result.loc[ordered.index] = np.minimum(adjusted, 1.0)
    return result


def _futures_panel(
    daily: pd.DataFrame, mapping: pd.DataFrame, holding: pd.DataFrame
) -> pd.DataFrame:
    mapped = mapping.merge(daily, on=["Date", "Contract"], how="left", validate="one_to_one")
    if mapped["Settle"].isna().any():
        raise ValueError("main mapping is missing contract settlement bars")
    candidates = daily.merge(
        mapped[["Date", "MaturityDate"]].rename(columns={"MaturityDate": "MainMaturityDate"}),
        on="Date",
    )
    candidates = candidates.loc[
        candidates["MaturityDate"].ge(candidates["MainMaturityDate"] + pd.Timedelta(days=60))
        & candidates["Volume"].gt(0)
    ]
    far = (
        candidates.sort_values(["Date", "MaturityDate", "Contract"])
        .drop_duplicates("Date")
        .set_index("Date")
    )
    main = mapped.set_index("Date").sort_index()
    days_apart = (far["MaturityDate"] - main["MaturityDate"]).dt.days
    curve_slope = (far["Settle"] / main["Settle"] - 1.0) * 365.0 / days_apart
    total_interest = daily.groupby("Date")["OpenInterest"].sum(min_count=1).sort_index()
    interest_growth = total_interest.pct_change(5, fill_method=None)
    by_day = holding.groupby("Date")
    long_total = by_day["LongHolding"].sum(min_count=1)
    short_total = by_day["ShortHolding"].sum(min_count=1)
    holding_imbalance = (long_total - short_total) / (long_total + short_total)
    panel = pd.DataFrame(index=main.index)
    panel["CurveSlope"] = curve_slope
    panel["OpenInterestGrowth5"] = interest_growth
    panel["HoldingImbalance"] = holding_imbalance
    panel.index.name = "SourceDate"
    return panel.reset_index()


def _align_futures_to_etf(
    futures: pd.DataFrame, etf_dates: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.Series]:
    decisions = pd.DataFrame({"Date": etf_dates}).sort_values("Date")
    aligned = pd.merge_asof(
        decisions,
        futures.sort_values("SourceDate"),
        left_on="Date",
        right_on="SourceDate",
        direction="backward",
        allow_exact_matches=False,
    ).set_index("Date")
    age = (pd.Series(aligned.index, index=aligned.index) - aligned["SourceDate"]).dt.days
    too_old = age.gt(10)
    aligned.loc[too_old, list(FUTURES_FEATURES)] = np.nan
    if aligned["SourceDate"].ge(pd.Series(aligned.index, index=aligned.index)).fillna(False).any():
        raise ValueError("futures observations are not strictly earlier than ETF decisions")
    return aligned.loc[:, list(FUTURES_FEATURES)], age


def _information_ledger(panel: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    opens = prices["open"].astype(float)
    sessions = pd.Series(prices.index, index=prices.index)
    labels = {h: opens.shift(-(h + 1)).div(opens.shift(-1)).sub(1) for h in HORIZONS}
    exits = {h: sessions.shift(-(h + 1)) for h in HORIZONS}
    discover = panel.index.to_series().le(pd.Timestamp(DISCOVERY_END))
    confirm = panel.index.to_series().ge(pd.Timestamp(CONFIRMATION_START))
    primary_mask = discover & exits[20].le(pd.Timestamp(DISCOVERY_END))
    orientations = {}
    raw_primary_ic = {}
    for feature in FEATURES:
        ic = _spearman(panel.loc[primary_mask, feature], labels[20].loc[primary_mask])
        raw_primary_ic[feature] = ic
        orientations[feature] = -1.0 if ic is not None and ic < 0 else 1.0

    rows = []
    for horizon in HORIZONS:
        discover_mask = discover & exits[horizon].le(pd.Timestamp(DISCOVERY_END))
        confirm_mask = confirm & exits[horizon].le(pd.Timestamp(CUTOFF))
        yd = labels[horizon].loc[discover_mask]
        yc = labels[horizon].loc[confirm_mask]
        for ordinal, feature in enumerate(FEATURES):
            sd, sc = _score(panel.loc[discover_mask, feature], panel.loc[confirm_mask, feature])
            sd *= orientations[feature]
            sc *= orientations[feature]
            d_count = int(pd.concat([sd, yd], axis=1).dropna().shape[0])
            c_pair = pd.concat([sc.rename("score"), yc.rename("outcome")], axis=1).dropna()
            c_count = len(c_pair)
            identifiable = d_count >= 1000 and c_count >= 1000 and c_pair["score"].nunique() >= 10
            annual = {}
            for year in range(2019, 2025):
                year_pair = c_pair.loc[c_pair.index.year == year]
                annual[str(year)] = (
                    _spearman(year_pair["score"], year_pair["outcome"])
                    if len(year_pair) >= 100
                    else None
                )
            if identifiable:
                low = c_pair["score"].quantile(0.2)
                high = c_pair["score"].quantile(0.8)
                spread = float(
                    c_pair.loc[c_pair["score"].ge(high), "outcome"].mean()
                    - c_pair.loc[c_pair["score"].le(low), "outcome"].mean()
                )
            else:
                spread = None
            rows.append(
                {
                    "feature": feature,
                    "family": "INTRADAY" if feature in INTRADAY_FEATURES else "FUTURES",
                    "horizon": horizon,
                    "orientation": "POSITIVE" if orientations[feature] > 0 else "NEGATIVE",
                    "raw_primary_discovery_ic": raw_primary_ic[feature],
                    "discovery_observations": d_count,
                    "confirmation_observations": c_count,
                    "discovery_ic": _spearman(sd, yd),
                    "confirmation_ic": _spearman(sc, yc),
                    "confirmation_partial_ic": _partial_ic(sc, yc, prices)
                    if identifiable
                    else None,
                    "hac_one_sided_pvalue": _hac_pvalue(sc, yc, horizon) if identifiable else None,
                    "annual_ic": json.dumps(annual, sort_keys=True, allow_nan=False),
                    "positive_confirmation_years": sum(
                        v is not None and v > 0 for v in annual.values()
                    ),
                    "top_minus_bottom_return": spread,
                    "bootstrap_positive_probability": (
                        _bootstrap_probability(sc, yc, 2026097101 + horizon * 1000 + ordinal)
                        if identifiable
                        else None
                    ),
                    "identifiable": identifiable,
                }
            )
    ledger = pd.DataFrame(rows)
    if len(ledger) != 33:
        raise ValueError("frozen information path count differs")
    ledger["bh_qvalue"] = _bh(ledger["hac_one_sided_pvalue"])
    ledger["positive_horizon_count"] = ledger.groupby("feature")["confirmation_ic"].transform(
        lambda values: int(values.gt(0).sum())
    )
    stable = (
        ledger["identifiable"]
        & ledger["raw_primary_discovery_ic"].abs().ge(0.02)
        & ledger["confirmation_ic"].gt(0)
        & ledger["confirmation_partial_ic"].ge(0.01)
        & ledger["positive_confirmation_years"].ge(4)
        & ledger["positive_horizon_count"].ge(2)
        & ledger["top_minus_bottom_return"].gt(0)
        & ledger["bootstrap_positive_probability"].ge(0.70)
    )
    ledger["evidence_label"] = "NO_STABLE_EVIDENCE"
    ledger.loc[~ledger["identifiable"], "evidence_label"] = "UNIDENTIFIABLE"
    ledger.loc[stable, "evidence_label"] = "DIRECTIONALLY_STABLE"
    ledger.loc[stable & ledger["hac_one_sided_pvalue"].le(0.05), "evidence_label"] = (
        "NOMINAL_SUPPORT"
    )
    ledger.loc[
        stable & ledger["bh_qvalue"].le(0.10) & ledger["bootstrap_positive_probability"].ge(0.80),
        "evidence_label",
    ] = "FDR_SUPPORTED"
    return ledger.sort_values(["family", "feature", "horizon"]).reset_index(drop=True)


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260924_S008_EX71",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Do ETF intraday participation and SHFE gold futures facts add stable upside information?",
            hypothesis="At least one causal feature family improves the 20-session upside information audit after price and volatility controls.",
            falsification_conditions=(
                "Any governed input or causal-alignment gate fails",
                "No primary-horizon path retains stable confirmation and partial information",
                "Apparent association is concentrated in fewer than four confirmation years",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026097101,
            allowed_datasets=(
                Dataset.FUTURES_SHFE_GOLD_DAILY.value,
                Dataset.FUTURES_SHFE_GOLD_MAPPING.value,
                Dataset.FUTURES_SHFE_GOLD_HOLDING.value,
            ),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "Persistent gold ETF buying may be visible in completed intraday bars before daily state filters",
                    "Futures curve and leveraged positioning can encode expectations before ETF medium-term trend confirmation",
                ),
                information_paths=(
                    "completed ETF intraday bars -> participation descriptors -> later ETF upside",
                    "prior-session SHFE futures curve and positioning -> expectations -> later ETF upside",
                ),
                stage_objectives=(
                    "Test stable incremental information in the development pool only",
                    "Select no prototype, strategy parameter, or candidate",
                ),
                observation_metrics=(
                    "5/20/60-session rank IC and partial IC",
                    "annual direction, HAC, block bootstrap, top-bottom spread, global FDR",
                ),
                methodology=(
                    "Gate all governed inputs and causal alignment before reading return labels",
                    "Orient each feature on discovery-period 20-session labels only",
                    "Audit all 33 preregistered paths without choosing a trading rule",
                ),
                predecessor_experiment_ids=(EX70_ID,),
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
        predecessor = context.predecessors[EX70_ID]
        if predecessor.receipt_sha256 != EX70_RECEIPT or not predecessor.facts.get("intraday_pass"):
            raise ValueError("EX70 causal input receipt does not match the frozen predecessor")
        artifact = next(
            (item for item in predecessor.artifacts if item.path == "intraday_causal_panel.csv.gz"),
            None,
        )
        if artifact is None:
            raise ValueError("EX70 intraday panel is missing")
        root = _root()
        panel_path = root / "experiments" / "S008" / EX70_ID / "artifacts" / artifact.path
        if sha256(panel_path.read_bytes()).hexdigest() != artifact.sha256:
            raise ValueError("EX70 intraday panel differs from its receipt")
        intraday = pd.read_csv(panel_path, compression="gzip", parse_dates=["Date"]).set_index(
            "Date"
        )
        if (
            len(intraday) != 2781
            or intraday.index.min() != pd.Timestamp(START)
            or intraday.index.max() != pd.Timestamp(CUTOFF)
        ):
            raise ValueError("EX70 intraday panel calendar is incomplete")

        datasets = {}
        identities = {}
        for dataset in (
            Dataset.FUTURES_SHFE_GOLD_DAILY,
            Dataset.FUTURES_SHFE_GOLD_MAPPING,
            Dataset.FUTURES_SHFE_GOLD_HOLDING,
        ):
            result = context.data.fetch(
                DataRequest(dataset, "AU.SHFE", START, CUTOFF, CUTOFF, options={"env_file": ".env"})
            )
            if result.status is not DataStatus.READY or result.identity is None:
                raise RuntimeError(
                    f"governed futures dataset is not READY: {dataset}: {result.error}"
                )
            if "next China trading session" not in result.identity.metadata["available_at"]:
                raise ValueError("futures availability contract differs")
            datasets[dataset] = result.dataframe.copy()
            identities[dataset.value] = {
                "rows": len(result.dataframe),
                "sha256": result.identity.content_sha256,
                "start": result.identity.data_start,
                "cutoff": result.identity.data_cutoff,
                "available_at": result.identity.metadata["available_at"],
            }
        futures = _futures_panel(
            datasets[Dataset.FUTURES_SHFE_GOLD_DAILY],
            datasets[Dataset.FUTURES_SHFE_GOLD_MAPPING],
            datasets[Dataset.FUTURES_SHFE_GOLD_HOLDING],
        )
        aligned, source_age = _align_futures_to_etf(futures, intraday.index)
        panel = intraday.loc[:, list(INTRADAY_FEATURES)].join(aligned, validate="one_to_one")
        coverage = {feature: float(panel[feature].notna().mean()) for feature in FEATURES}
        values = panel.loc[:, list(FEATURES)].to_numpy(dtype=float)
        all_finite = bool((np.isfinite(values) | np.isnan(values)).all())
        if min(coverage.values()) < 0.95 or not all_finite or source_age.dropna().lt(1).any():
            return ExperimentResult(
                outcome=ExperimentOutcome.FAIL,
                facts={"decision": "STOP_NEW_INPUT_DATA_GATE", "coverage": coverage},
                diagnostics={"reads_real_returns": False, "reads_sealed_validation": False},
            )

        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        manifest_path = root / "data" / "raw" / "518880_execution_manifest.json"
        if sha256(manifest_path.read_bytes()).hexdigest() != EXECUTION_MANIFEST_SHA256:
            raise ValueError("execution manifest identity differs from preregistration")
        prices = load_execution_prices(
            root / "data" / "raw", symbol="518880.SH", asset_type="etf", cutoff=CUTOFF
        )
        prices["Date"] = pd.to_datetime(prices["dt"]).dt.normalize()
        prices = prices.set_index("Date").sort_index()
        if not prices.index.equals(panel.index):
            raise ValueError("execution prices and feature decision dates differ")
        ledger = _information_ledger(panel, prices)
        ledger_path = context.workspace.path("information_path_ledger.csv.gz")
        ledger.to_csv(
            ledger_path,
            index=False,
            compression={"method": "gzip", "compresslevel": 9, "mtime": 0},
            lineterminator="\n",
        )
        supported = {"DIRECTIONALLY_STABLE", "NOMINAL_SUPPORT", "FDR_SUPPORTED"}
        primary = ledger.loc[ledger["horizon"].eq(20)].copy()
        primary_supported = primary.loc[primary["evidence_label"].isin(supported)].copy()
        families = sorted(primary_supported["family"].unique().tolist())
        decision = {
            (): "STOP_NEW_INFORMATION_PATHS",
            ("FUTURES",): "PROCEED_FUTURES_ROLE_REVIEW",
            ("INTRADAY",): "PROCEED_INTRADAY_ROLE_REVIEW",
            ("FUTURES", "INTRADAY"): "PROCEED_DUAL_ROLE_REVIEW",
        }[tuple(families)]
        audit = {
            "schema_version": 1,
            "decision": decision,
            "development_window": [START, CUTOFF],
            "discovery_end": DISCOVERY_END,
            "confirmation_start": CONFIRMATION_START,
            "ex70_receipt": predecessor.receipt_sha256,
            "execution_manifest_sha256": EXECUTION_MANIFEST_SHA256,
            "futures_identities": identities,
            "feature_coverage": coverage,
            "maximum_futures_source_age_days": int(source_age.dropna().max()),
            "strictly_prior_futures_source": True,
            "path_count": len(ledger),
            "primary_supported": primary_supported[
                [
                    "feature",
                    "family",
                    "evidence_label",
                    "confirmation_ic",
                    "confirmation_partial_ic",
                ]
            ].to_dict(orient="records"),
            "reads_sealed_validation": False,
            "selects_prototype": False,
            "searches_parameters": False,
            "creates_candidate": False,
        }
        audit_path = context.workspace.path("information_audit.json.gz")
        audit_path.write_bytes(
            gzip.compress(
                (
                    json.dumps(audit, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
                ).encode("utf-8"),
                mtime=0,
            )
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if families else ExperimentOutcome.INCONCLUSIVE,
            facts={
                "decision": decision,
                "path_count": len(ledger),
                "primary_supported_count": len(primary_supported),
                "primary_supported_by_family": {
                    family: int(primary_supported["family"].eq(family).sum())
                    for family in ("INTRADAY", "FUTURES")
                },
                "minimum_feature_coverage": min(coverage.values()),
                "futures_data_rows": {key: value["rows"] for key, value in identities.items()},
            },
            diagnostics={
                "reads_development_returns": True,
                "reads_sealed_validation": False,
                "selects_prototype": False,
                "searches_parameters": False,
                "creates_candidate": False,
            },
            artifacts=(
                context.workspace.register_artifact(
                    "information_path_ledger.csv.gz", "complete-information-path-ledger"
                ),
                context.workspace.register_artifact(
                    "information_audit.json.gz", "causal-information-audit"
                ),
            ),
        )
