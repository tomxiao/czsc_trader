from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.data import load_execution_prices
from dataflows import DataRequest, DataStatus, Dataset
import numpy as np
import pandas as pd
import statsmodels.api as sm
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


EX82 = "20260924_S008_EX82"
EX82_RECEIPT = "9c6483465fea3ac2fdcd8d7315de7acf91f1cce78f836be608c7c338ed007689"
SHARE_HASHES = {
    "518880.SH": "a749a38023fb01189ad24ad949dc90998293f2fd285fe08a7f21a453213b62d4",
    "518800.SH": "41b9215f9a6d77ca5c35705985c500b5c084816f32ebb99010fbaa6c8c03254c",
}
EX16_PANEL_SHA256 = "a757cafd1eb1322f4aebe3d68fc5a6792eab9aae8b13eed8f7b83618be2139b4"
EXECUTION_MANIFEST_SHA256 = "fc5aac30019deed1c04204b7e3a967963782bf0e8bfbe5da3e1b1ce420a832a8"
START, END = "2013-07-29", "2024-12-31"
HORIZONS = (20, 60)
CONTROLS = (
    "rate_us_real_10y_level",
    "rate_us_real_10y_change_20d",
    "currency_usdcnh_return_20d",
    "price_return_20d",
)
ERAS = (
    ("early", pd.Timestamp("2014-01-01"), pd.Timestamp("2018-12-31")),
    ("late", pd.Timestamp("2019-01-01"), pd.Timestamp(END)),
)


def _spearman(x: pd.Series, y: pd.Series) -> float | None:
    pair = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
    if len(pair) < 20 or pair["x"].nunique() < 2 or pair["y"].nunique() < 2:
        return None
    return float(pair["x"].corr(pair["y"], method="spearman"))


def _comparison(frame: pd.DataFrame) -> dict[str, float | int | None]:
    event = frame.loc[frame["Event"], "Outcome"]
    control = frame.loc[~frame["Event"], "Outcome"]
    return {
        "EventN": len(event),
        "ControlN": len(control),
        "EventMean": float(event.mean()) if len(event) else None,
        "ControlMean": float(control.mean()) if len(control) else None,
        "MeanSpread": float(event.mean() - control.mean()) if len(event) and len(control) else None,
        "EventLossRate": float(event.lt(0).mean()) if len(event) else None,
        "ControlLossRate": float(control.lt(0).mean()) if len(control) else None,
        "LossRateLift": float(event.lt(0).mean() - control.lt(0).mean()) if len(event) and len(control) else None,
    }


def _year_bootstrap(frame: pd.DataFrame, seed: int) -> tuple[float | None, float | None, float | None]:
    years = sorted(frame.index.year.unique())
    if len(years) < 4:
        return None, None, None
    annual = [frame.loc[frame.index.year == year] for year in years]
    rng = np.random.default_rng(seed)
    spreads = []
    for draw in rng.integers(0, len(years), size=(500, len(years))):
        sample = pd.concat([annual[i] for i in draw], ignore_index=True)
        spread = _comparison(sample)["MeanSpread"]
        if spread is not None:
            spreads.append(spread)
    if len(spreads) < 475:
        return None, None, None
    return float(np.mean(np.array(spreads) < 0)), float(np.quantile(spreads, .025)), float(np.quantile(spreads, .975))


def _decluster_event_mean(frame: pd.DataFrame, horizon: int, calendar: pd.DatetimeIndex) -> tuple[int, float | None]:
    positions = calendar.get_indexer(frame.index[frame["Event"]])
    if (positions < 0).any():
        raise ValueError("event date is absent from the target trading calendar")
    kept = []
    last = -horizon
    for position in positions:
        if position - last >= horizon:
            kept.append(position)
            last = position
    outcomes = frame.loc[calendar[kept], "Outcome"] if kept else pd.Series(dtype=float)
    return len(outcomes), float(outcomes.mean()) if len(outcomes) else None


def _adjusted_event_effect(frame: pd.DataFrame, horizon: int) -> tuple[float | None, float | None, int]:
    fields = ["Outcome", "Event", "OwnFlow60", "PriorPrice60", *CONTROLS]
    complete = frame.loc[:, fields].dropna()
    if len(complete) < 100 or complete["Event"].nunique() != 2:
        return None, None, len(complete)
    design = complete.loc[:, ["OwnFlow60", "PriorPrice60", *CONTROLS]].astype(float).copy()
    design.insert(0, "Event", complete["Event"].astype(float))
    years = pd.Series(complete.index.year, index=complete.index)
    dummies = pd.get_dummies(years, prefix="Year", drop_first=True, dtype=float)
    design = sm.add_constant(pd.concat([design, dummies], axis=1), has_constant="add")
    fitted = sm.OLS(complete["Outcome"].astype(float), design).fit(
        cov_type="HAC", cov_kwds={"maxlags": horizon + 1},
    )
    return float(fitted.params["Event"]), float(fitted.pvalues["Event"]), len(complete)


def _synthetic_precheck() -> None:
    dates = pd.date_range("2024-01-01", periods=12, freq="D")
    shares = pd.Series([100] * 5 + [200] * 7, index=dates, dtype=float)
    closes = pd.Series([10] * 5 + list(range(11, 18)), index=dates, dtype=float)
    opens = pd.Series(range(10, 22), index=dates, dtype=float)
    flow = shares.pct_change(1).shift(1)
    threshold = flow.shift(1).rolling(3, min_periods=3).quantile(.75)
    event = flow.gt(threshold) & closes.pct_change(1).gt(0)
    forward = opens.shift(-3).div(opens.shift(-1)).sub(1)
    if flow.iloc[5] != 0 or flow.iloc[6] != 1 or threshold.iloc[6] != 0:
        raise AssertionError("peer-flow publication or trailing threshold leaks source day")
    if bool(event.iloc[5]) or not bool(event.iloc[6]):
        raise AssertionError("crowding event does not respect source lag and price condition")
    if forward.iloc[6] != opens.iloc[9] / opens.iloc[7] - 1 or not pd.isna(forward.iloc[-3]):
        raise AssertionError("T+1 open forward label is misaligned")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260924_S008_EX83",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Does peer gold-ETF creation demand after a rally mark subsequent crowding risk?",
            hypothesis="Large lagged peer share creation after a target rally precedes weaker returns and higher downside risk.",
            falsification_conditions=(
                "The flow does not follow prior target rallies in both development eras",
                "Conditional forward weakness or loss risk is absent in either era",
                "The relation disappears when both peer and target ETF shares grow",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026098301,
            allowed_datasets=(Dataset.ETF_SHARE_SIZE.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "ETF share creations can reflect investor demand after observed gold price appreciation",
                    "Crowded late participation may precede weaker subsequent returns or higher downside",
                ),
                information_paths=(
                    "prior gold ETF rally -> peer share creation surge -> subsequent 20/60-day loss risk",
                ),
                stage_objectives=(
                    "Falsify or preserve a new, explicitly post-EX82 crowding-risk hypothesis",
                    "Separate fund substitution, overlapping labels and temporal instability",
                ),
                observation_metrics=(
                    "prior-price/flow correlation; conditional return and loss-rate spreads by era and horizon",
                    "co-creation subset, annual direction, year-block bootstrap and de-clustered events",
                ),
                methodology=(
                    "Run synthetic lag, rolling-threshold and T+1 label precheck before real returns",
                    "Use only frozen DFLS shares, EX16 controls and target execution prices through 2024",
                    "Keep both eras as viewed development evidence and do not tune the 75th-percentile threshold",
                ),
                predecessor_experiment_ids=(EX82,),
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
        predecessor = context.predecessors[EX82]
        if predecessor.receipt_sha256 != EX82_RECEIPT:
            raise ValueError("EX82 receipt identity differs")
        if predecessor.facts.get("decision") != "NO_STABLE_PEER_FLOW_EVIDENCE":
            raise ValueError("EX82 conclusion differs")
        _synthetic_precheck()
        shares = {}
        for symbol in ("518880.SH", "518800.SH"):
            publication = context.data.fetch(DataRequest(
                Dataset.ETF_SHARE_SIZE, symbol, START, END, "2024-12-01",
                options={"env_file": ".env"},
            ))
            if publication.status is not DataStatus.READY or publication.identity is None:
                raise RuntimeError(f"DFLS ETF shares {symbol} are not READY")
            if publication.identity.content_sha256 != SHARE_HASHES[symbol]:
                raise ValueError(f"DFLS ETF shares {symbol} identity differs from EX81")
            shares[symbol] = publication.dataframe.set_index("Date")["TotalShare"].astype(float).sort_index()
        own, peer = shares["518880.SH"], shares["518800.SH"]
        if not own.index.equals(peer.index) or len(own) != 2781:
            raise ValueError("ETF share calendar differs from EX81")
        root = Path(__file__).resolve().parents[3]
        control_path = root / "experiments" / "S008" / "20260923_S008_EX16" / "artifacts" / "causal_feature_panel.csv.gz"
        if sha256(control_path.read_bytes()).hexdigest() != EX16_PANEL_SHA256:
            raise ValueError("EX16 causal feature panel identity changed")
        controls = pd.read_csv(control_path, compression="gzip", parse_dates=["Date"]).set_index("Date").sort_index()[list(CONTROLS)]
        if sha256((root / "data" / "raw" / "518880_execution_manifest.json").read_bytes()).hexdigest() != EXECUTION_MANIFEST_SHA256:
            raise ValueError("execution-price manifest identity changed")
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        prices = load_execution_prices(root / "data" / "raw", symbol="518880.SH", asset_type="etf", cutoff=END)
        prices["Date"] = pd.to_datetime(prices["dt"]).dt.normalize()
        prices = prices.set_index("Date").sort_index()
        if not prices.index.equals(own.index) or not controls.index.equals(own.index):
            raise ValueError("ETF price, share and control calendars differ")
        close = prices["close"].astype(float)
        open_price = prices["open"].astype(float)
        panel = pd.DataFrame(index=own.index)
        panel["PeerFlow60"] = peer.pct_change(60).shift(1)
        panel["OwnFlow60"] = own.pct_change(60).shift(1)
        panel["PriorPrice60"] = close.pct_change(60)
        panel["FlowWindowPrice60"] = close.pct_change(60).shift(1)
        panel["PreFlowPrice60"] = close.pct_change(60).shift(61)
        panel["SurgeThreshold"] = panel["PeerFlow60"].shift(1).rolling(252, min_periods=252).quantile(.75)
        panel["Rally"] = panel["PriorPrice60"].gt(0)
        panel["Event"] = panel["Rally"] & panel["PeerFlow60"].gt(0) & panel["PeerFlow60"].gt(panel["SurgeThreshold"])
        decision_dates = pd.Series(prices.index, index=prices.index)
        for h in HORIZONS:
            panel[f"Forward{h}"] = open_price.shift(-(h + 1)).div(open_price.shift(-1)).sub(1)
            panel[f"ExitDate{h}"] = decision_dates.shift(-(h + 1))
        panel = panel.join(controls)
        panel.index.name = "Date"
        panel.to_csv(context.workspace.path("causal_crowding_panel.csv"), float_format="%.12f", lineterminator="\n")

        price_flow = {}
        concurrent_price_flow = {}
        rows = []
        for era, start, end in ERAS:
            base = panel.loc[(panel.index >= start) & (panel.index <= end)].dropna(subset=["PeerFlow60", "OwnFlow60", "PriorPrice60", "PreFlowPrice60", "SurgeThreshold"])
            price_flow[era] = _spearman(base["PeerFlow60"], base["PreFlowPrice60"])
            concurrent_price_flow[era] = _spearman(base["PeerFlow60"], base["FlowWindowPrice60"])
            for h in HORIZONS:
                eligible = base.loc[base["Rally"] & base[f"ExitDate{h}"].le(end)].dropna(subset=[f"Forward{h}"])
                view = eligible.rename(columns={f"Forward{h}": "Outcome"})
                comparison = _comparison(view)
                annual = {}
                for year in sorted(view.index.year.unique()):
                    year_view = view.loc[view.index.year == year]
                    annual[str(year)] = _comparison(year_view)["MeanSpread"]
                co_creation = _comparison(view.loc[view["OwnFlow60"].gt(0)])
                bootstrap_negative, ci_low, ci_high = _year_bootstrap(view, 2026098301 + h + (0 if era == "early" else 100))
                decluster_n, decluster_mean = _decluster_event_mean(view, h, panel.index)
                adjusted_coef, adjusted_p, adjusted_n = _adjusted_event_effect(view, h)
                rows.append({
                    "Era": era,
                    "Horizon": h,
                    "PriceFlowIC": price_flow[era],
                    "ConcurrentPriceFlowIC": concurrent_price_flow[era],
                    **comparison,
                    "AnnualMeanSpread": json.dumps(annual, sort_keys=True, allow_nan=False),
                    "NegativeYears": sum(value is not None and value < 0 for value in annual.values()),
                    "BootstrapNegative": bootstrap_negative,
                    "BootstrapCI025": ci_low,
                    "BootstrapCI975": ci_high,
                    "CoCreationEventN": co_creation["EventN"],
                    "CoCreationControlN": co_creation["ControlN"],
                    "CoCreationMeanSpread": co_creation["MeanSpread"],
                    "DeclusterEventN": decluster_n,
                    "DeclusterEventMean": decluster_mean,
                    "AdjustedEventCoef": adjusted_coef,
                    "AdjustedEventP": adjusted_p,
                    "AdjustedN": adjusted_n,
                })
        ledger = pd.DataFrame(rows)
        ledger.to_csv(context.workspace.path("crowding_mechanism_ledger.csv"), index=False, float_format="%.12f", lineterminator="\n")
        promising = []
        for h in HORIZONS:
            early = ledger.loc[ledger["Era"].eq("early") & ledger["Horizon"].eq(h)].iloc[0]
            late = ledger.loc[ledger["Era"].eq("late") & ledger["Horizon"].eq(h)].iloc[0]
            checks = []
            for item in (early, late):
                checks.extend((
                    pd.notna(item["PriceFlowIC"]) and item["PriceFlowIC"] > 0,
                    item["EventN"] >= 20 and item["ControlN"] >= 20,
                    pd.notna(item["MeanSpread"]) and item["MeanSpread"] < 0,
                    pd.notna(item["AdjustedEventCoef"]) and item["AdjustedEventCoef"] < 0,
                    pd.notna(item["LossRateLift"]) and item["LossRateLift"] > 0,
                    item["CoCreationEventN"] >= 10 and item["CoCreationControlN"] >= 10,
                    pd.notna(item["CoCreationMeanSpread"]) and item["CoCreationMeanSpread"] < 0,
                ))
            checks.extend((late["NegativeYears"] >= 4, pd.notna(late["BootstrapNegative"]) and late["BootstrapNegative"] >= .90))
            if all(checks):
                promising.append(h)
        decision = "DISCOVERY_ONLY_CROWDING_REVIEW_REQUIRED" if promising else "NO_REPRODUCIBLE_CROWDING_MECHANISM"
        return ExperimentResult(
            outcome=ExperimentOutcome.INCONCLUSIVE,
            facts={
                "decision": decision,
                "promising_horizons": promising,
                "price_flow_ic_by_era": price_flow,
                "concurrent_price_flow_ic_by_era": concurrent_price_flow,
                "audited_comparisons": len(ledger),
                "reads_previously_viewed_development_eras": True,
            },
            diagnostics={
                "reads_real_returns": True,
                "reads_sealed_validation": False,
                "selects_prototype": False,
                "searches_parameters": False,
                "creates_candidate": False,
            },
            artifacts=(
                context.workspace.register_artifact("causal_crowding_panel.csv", "development-crowding-panel"),
                context.workspace.register_artifact("crowding_mechanism_ledger.csv", "crowding-mechanism-ledger"),
            ),
        )
