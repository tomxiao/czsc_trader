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


EX81 = "20260924_S008_EX81"
EX81_RECEIPT = "36344a16b37ed289c5963f82b4559555b0acbe4c1d1969a06794628a7af0ae95"
EX16_PANEL_SHA256 = "a757cafd1eb1322f4aebe3d68fc5a6792eab9aae8b13eed8f7b83618be2139b4"
EXECUTION_MANIFEST_SHA256 = "fc5aac30019deed1c04204b7e3a967963782bf0e8bfbe5da3e1b1ce420a832a8"
START, END = "2013-07-29", "2024-12-31"
HORIZONS = (5, 20, 60)
CONTROLS = (
    "rate_us_real_10y_level",
    "rate_us_real_10y_change_20d",
    "currency_usdcnh_return_20d",
    "price_return_20d",
)


def _ic(x: pd.Series, y: pd.Series) -> float | None:
    pair = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
    if len(pair) < 20 or pair["x"].nunique() < 2 or pair["y"].nunique() < 2:
        return None
    return float(pair["x"].corr(pair["y"], method="spearman"))


def _partial_ic(frame: pd.DataFrame) -> float | None:
    complete = frame.loc[:, ["score", "outcome", "own_flow", *CONTROLS]].dropna()
    if len(complete) < 30 or complete["score"].nunique() < 2:
        return None
    design = sm.add_constant(complete.loc[:, ["own_flow", *CONTROLS]].astype(float), has_constant="add")
    score_residual = sm.OLS(complete["score"].astype(float), design).fit().resid
    outcome_residual = sm.OLS(complete["outcome"].astype(float), design).fit().resid
    return _ic(score_residual, outcome_residual)


def _bootstrap_positive(frame: pd.DataFrame, horizon: int, seed: int) -> float | None:
    pair = frame.loc[:, ["score", "outcome"]].dropna()
    if len(pair) < 100 or pair["score"].nunique() < 2:
        return None
    ranked = pair.rank(method="average", pct=True).to_numpy(dtype=float)
    n = len(ranked)
    block = horizon + 1
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(500, (n + block - 1) // block))
    indices = ((starts[:, :, None] + np.arange(block)) % n).reshape(500, -1)[:, :n]
    samples = ranked[indices]
    x = samples[:, :, 0] - samples[:, :, 0].mean(axis=1, keepdims=True)
    y = samples[:, :, 1] - samples[:, :, 1].mean(axis=1, keepdims=True)
    denominator = np.sqrt((x * x).sum(axis=1) * (y * y).sum(axis=1))
    correlations = np.divide((x * y).sum(axis=1), denominator, out=np.full(500, np.nan), where=denominator > 0)
    valid = correlations[np.isfinite(correlations)]
    return float(np.mean(valid > 0)) if len(valid) >= 475 else None


def _check_lag() -> None:
    shares = pd.Series([100.0, 200.0, 200.0, 300.0], index=pd.date_range("2024-01-01", periods=4))
    visible = shares.pct_change(1).shift(1)
    if not pd.isna(visible.iloc[1]) or visible.iloc[2] != 1.0 or visible.iloc[3] != 0.0:
        raise AssertionError("ETF share publication lag leaks source-day information")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260924_S008_EX82",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Does lagged peer gold-ETF creation demand add stable upside information?",
            hypothesis="Rising peer shares lead later target ETF returns beyond own flow and known market state.",
            falsification_conditions=(
                "Any frozen input identity or synthetic causal lag check fails",
                "Positive relation is confined to one development era or disappears after controls",
                "The apparent relation depends on overlapping labels or a minority of years",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026098201,
            allowed_datasets=(Dataset.ETF_SHARE_SIZE.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "Primary-market ETF share creations may reveal changing gold allocation demand",
                    "Target returns may already price common demand or own-fund flow",
                ),
                information_paths=tuple(f"peer ETF share change {h} source days" for h in HORIZONS),
                stage_objectives=(
                    "Audit independent peer-flow information without selecting a strategy",
                    "Separate raw association, own-flow overlap, market-state controls and temporal instability",
                ),
                observation_metrics=(
                    "5/20/60-day raw and partial IC by era, annual direction, non-overlap IC and block bootstrap",
                ),
                methodology=(
                    "Verify EX81/EX16/execution identities and synthetic share-publication lag before reading returns",
                    "Use only next-day-published source shares for later T close decisions and T+1 open entry",
                    "Keep both 2014-2018 and 2019-2024 as viewed development evidence",
                ),
                predecessor_experiment_ids=(EX81,),
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
        predecessor = context.predecessors[EX81]
        if predecessor.receipt_sha256 != EX81_RECEIPT:
            raise ValueError("EX81 receipt identity differs")
        if predecessor.facts.get("decision") != "PROCEED_PEER_FLOW_INFORMATION_AUDIT":
            raise ValueError("EX81 did not pass the peer-flow data gate")
        _check_lag()
        shares = {}
        for symbol in ("518880.SH", "518800.SH"):
            publication = context.data.fetch(DataRequest(
                Dataset.ETF_SHARE_SIZE, symbol, START, END, "2024-12-01",
                options={"env_file": ".env"},
            ))
            if publication.status is not DataStatus.READY or publication.identity is None:
                raise RuntimeError(f"DFLS ETF shares {symbol} are not READY")
            if publication.identity.content_sha256 != predecessor.facts["input_hashes"][symbol]:
                raise ValueError(f"DFLS ETF shares {symbol} source identity changed")
            shares[symbol] = publication.dataframe.set_index("Date")["TotalShare"].astype(float).sort_index()
        own = shares["518880.SH"]
        peer = shares["518800.SH"]
        if not own.index.equals(peer.index) or len(own) != 2781:
            raise ValueError("ETF share calendars differ from EX81")
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
        opens = prices["open"].astype(float)
        decision_dates = pd.Series(prices.index, index=prices.index)
        panel = pd.DataFrame(index=own.index)
        for h in HORIZONS:
            panel[f"PeerFlow{h}"] = peer.pct_change(h).shift(1)
            panel[f"OwnFlow{h}"] = own.pct_change(h).shift(1)
            panel[f"Forward{h}"] = opens.shift(-(h + 1)).div(opens.shift(-1)).sub(1)
            panel[f"ExitDate{h}"] = decision_dates.shift(-(h + 1))
        panel = panel.join(controls)
        panel.index.name = "Date"
        panel_path = context.workspace.path("causal_peer_flow_panel.csv")
        panel.to_csv(panel_path, float_format="%.12f", lineterminator="\n")

        ledger = []
        for h in HORIZONS:
            era = {}
            for name, start, end in (
                ("early", pd.Timestamp("2014-01-01"), pd.Timestamp("2018-12-31")),
                ("late", pd.Timestamp("2019-01-01"), pd.Timestamp(END)),
            ):
                mask = panel.index.to_series().ge(start) & panel.index.to_series().le(end) & panel[f"ExitDate{h}"].le(end)
                dates = panel.index[mask]
                era[name] = pd.DataFrame({
                    "score": panel.loc[dates, f"PeerFlow{h}"],
                    "own_flow": panel.loc[dates, f"OwnFlow{h}"],
                    "outcome": panel.loc[dates, f"Forward{h}"],
                }).join(controls).dropna(subset=["score", "own_flow", "outcome"])
            early, late = era["early"], era["late"]
            early_partial, late_partial = _partial_ic(early), _partial_ic(late)
            early_nonoverlap, late_nonoverlap = early.iloc[::h], late.iloc[::h]
            early_nonoverlap_ic = _ic(early_nonoverlap["score"], early_nonoverlap["outcome"])
            late_nonoverlap_ic = _ic(late_nonoverlap["score"], late_nonoverlap["outcome"])
            annual = {
                str(year): _ic(late.loc[late.index.year == year, "score"], late.loc[late.index.year == year, "outcome"])
                for year in range(2019, 2025)
            }
            bootstrap = _bootstrap_positive(late, h, 2026098201 + h)
            positive = late.loc[late["score"].gt(0), "outcome"]
            nonpositive = late.loc[late["score"].le(0), "outcome"]
            screen = (
                early_partial is not None and early_partial > 0
                and late_partial is not None and late_partial >= 0.05
                and sum(value is not None and value > 0 for value in annual.values()) >= 4
                and bootstrap is not None and bootstrap >= 0.90
                and len(early_nonoverlap) >= 20 and len(late_nonoverlap) >= 20
                and early_nonoverlap_ic is not None and early_nonoverlap_ic > 0
                and late_nonoverlap_ic is not None and late_nonoverlap_ic > 0
            )
            ledger.append({
                "Horizon": h,
                "EarlyN": len(early),
                "LateN": len(late),
                "EarlyIC": _ic(early["score"], early["outcome"]),
                "LateIC": _ic(late["score"], late["outcome"]),
                "EarlyPartialIC": early_partial,
                "LatePartialIC": late_partial,
                "EarlyNonoverlapN": len(early_nonoverlap),
                "LateNonoverlapN": len(late_nonoverlap),
                "EarlyNonoverlapIC": early_nonoverlap_ic,
                "LateNonoverlapIC": late_nonoverlap_ic,
                "LatePositiveYears": sum(value is not None and value > 0 for value in annual.values()),
                "LateAnnualIC": json.dumps(annual, sort_keys=True, allow_nan=False),
                "LateBootstrapPositive": bootstrap,
                "LatePositiveFlowN": len(positive),
                "LateNonpositiveFlowN": len(nonpositive),
                "LateMeanSpread": float(positive.mean() - nonpositive.mean()) if len(positive) and len(nonpositive) else None,
                "PassesPrototypeReviewScreen": screen,
            })
        ledger_frame = pd.DataFrame(ledger)
        ledger_path = context.workspace.path("peer_flow_information_ledger.csv")
        ledger_frame.to_csv(ledger_path, index=False, float_format="%.12f", lineterminator="\n")
        promising = bool(ledger_frame["PassesPrototypeReviewScreen"].any())
        return ExperimentResult(
            outcome=ExperimentOutcome.INCONCLUSIVE,
            facts={
                "decision": "PROMISING_PEER_FLOW_REVIEW_REQUIRED" if promising else "NO_STABLE_PEER_FLOW_EVIDENCE",
                "audited_paths": len(ledger_frame),
                "promising_horizons": [int(row["Horizon"]) for row in ledger if row["PassesPrototypeReviewScreen"]],
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
                context.workspace.register_artifact("causal_peer_flow_panel.csv", "development-peer-flow-panel"),
                context.workspace.register_artifact("peer_flow_information_ledger.csv", "peer-flow-information-ledger"),
            ),
        )
