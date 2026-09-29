"""S010 EX14: seal lagged historical basket snapshots and stock-price readiness."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd
from czsc_trader.experiment_archive import validate_experiment_archive
from dataflows import DataRequest, Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)


EXPERIMENT_ID = "20260929_S010_EX14"
RECEIPTS = {
    "20260929_S010_EX01": "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77",
    "20260929_S010_EX02": "37487d63f23277b86ab092f0dcc9e2e9f7f61db17fd03bf5ccb627e6af2ff981",
    "20260929_S010_EX03": "11650e695bffb0776dd700eb763fb644836878998ae46006acabdac86c1fb815",
    "20260929_S010_EX04": "aa501bc4e97f57378f79cbe57e689ff11f3641c57a665b254c1e6e8f75e8d0ee",
    "20260929_S010_EX05": "a5f4f9d56696fe894da94ef4a37591887f141664f8819cc064d7f6290747626d",
    "20260929_S010_EX06": "a5ae3eb4633f97d0b4c1aa815fc5fc6992eff7d4adc0e0a2afb009c331b02276",
    "20260929_S010_EX07": "f39fc5db88c7ed9c7996a96fd4d7fee4ec1c73e275c6e553aee343f0e30cb8ba",
    "20260929_S010_EX08": "d48bba43ce2e25e1fd6c3f4a7613f57776331ff79190546986e9ffe4658bf6c9",
    "20260929_S010_EX09": "6c9dc8791d54a205f0356ce587ccb349ceb983757409edd0218b0561fac682d9",
    "20260929_S010_EX10": "f31c3df4cec34265cbe59902cbbb5987c1e2ec99e460f6f7aa7d5261886a86ca",
    "20260929_S010_EX11": "577edf88220d5cba3f16c857267ed608fe27d312e3da5f95bc57727a0131cf51",
    "20260929_S010_EX12": "6b0ab17d03232dc2d79afea75a306b11b2efef0d5aaf3775b00f4dd7c83a87c9",
    "20260929_S010_EX13": "ae3ff0deff311b496e5b22bd84b1b54a2aea83567e3f086f3a265709c8500619",
}
WEIGHT_SHA256 = "053aae2ea24653ce42e914c11c12f6620e94337f1566015e174fe436082865fb"
START, CUTOFF = "2024-09-09", "2026-09-28"
STOCK_START = "2024-08-01"
SNAPSHOT_DELAY_DAYS = 35
MAX_STALE_SESSIONS = 10
SEED = 2026092914


def _available_snapshot(weights: pd.DataFrame, session: pd.Timestamp) -> pd.Timestamp | None:
    eligible = weights.index[weights.index + pd.Timedelta(days=SNAPSHOT_DELAY_DAYS) <= session]
    return None if eligible.empty else eligible.max()


def _coverage(weights: pd.DataFrame, closes: pd.DataFrame,
              sessions: pd.DatetimeIndex) -> pd.DataFrame:
    weight_dates = pd.DatetimeIndex(sorted(weights["Date"].unique()))
    snapshots = weights.set_index("Date", drop=False)
    wide = closes.pivot(index="Date", columns="Symbol", values="Close").sort_index()
    if wide.index.duplicated().any() or wide.columns.duplicated().any():
        raise ValueError("duplicate stock close key")
    daily = wide.reindex(wide.index.union(sessions)).sort_index().ffill(limit=MAX_STALE_SESSIONS)
    daily = daily.reindex(sessions)
    rows = []
    for position, session in enumerate(sessions):
        snapshot = _available_snapshot(pd.DataFrame(index=weight_dates), session)
        if snapshot is None or position == 0:
            continue
        basket = snapshots.loc[[snapshot]]
        symbols = basket["ConstituentSymbol"].tolist()
        current = daily.loc[session].reindex(symbols)
        previous = daily.loc[sessions[position - 1]].reindex(symbols)
        valid = current.notna().to_numpy() & previous.notna().to_numpy()
        w = basket["Weight"].to_numpy(dtype=float)
        rows.append({
            "Date": session, "SnapshotDate": snapshot,
            "SnapshotAgeDays": (session - snapshot).days,
            "MemberCount": len(symbols), "AvailableCount": int(valid.sum()),
            "WeightCoveragePct": float(w[valid].sum()),
        })
    return pd.DataFrame(rows)


def _precheck() -> None:
    synthetic = pd.DataFrame(index=pd.DatetimeIndex(["2024-09-30", "2024-10-31"]))
    if _available_snapshot(synthetic, pd.Timestamp("2024-11-03")) is not None:
        raise ValueError("snapshot became available before 35 calendar days")
    if _available_snapshot(synthetic, pd.Timestamp("2024-11-04")) != pd.Timestamp("2024-09-30"):
        raise ValueError("snapshot lag boundary differs")
    if _available_snapshot(synthetic, pd.Timestamp("2024-12-05")) != pd.Timestamp("2024-10-31"):
        raise ValueError("latest eligible snapshot not selected")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Can lagged index weights and component stock closes support a causal basket-breadth survey?",
            hypothesis="Monthly constituent snapshots and stock bars cover enough of the ETF calendar after a conservative lag.",
            falsification_conditions=("Weight snapshots or stock sources unavailable",
                                    "Lagged basket coverage insufficient",
                                    "Predecessor or source identity differs"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED,
            allowed_datasets=(Dataset.INDEX_CONSTITUENT_WEIGHT.value, Dataset.STOCK_OHLCV.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.DATA_GATE,
                first_principles=("Internal participation needs historically defined members and observable prices",),
                information_paths=("Lagged monthly member snapshot plus T stock closes -> T basket state",),
                stage_objectives=("Seal index membership and stock data identities",
                                  "Quantify daily price coverage after a 35-day weight lag"),
                observation_metrics=("Snapshot count and weight sums", "stock READY/FAILED counts",
                                     "daily member and weighted coverage"),
                methodology=("Single-thread DFLS fetches", "Thirty-five calendar-day snapshot lag",
                             "At most ten-session price carry for coverage audit"),
                predecessor_experiment_ids=tuple(RECEIPTS),
            ),
            subjects=("159326.SZ",),
            dependencies=(ExperimentDependency("numpy", np.__version__),
                          ExperimentDependency("pandas", pd.__version__)),
            capabilities=ExperimentCapabilities(reads_real_returns=True, reads_sealed_validation=True),
        )

    def synthetic_precheck(self) -> None:
        _precheck()

    def execute(self, context) -> ExperimentResult:
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        root = Path(__file__).resolve().parent
        for name, receipt in RECEIPTS.items():
            if context.predecessors[name].receipt_sha256 != receipt:
                raise ValueError(f"predecessor receipt differs: {name}")
            validate_experiment_archive(root.parent / name)
        env_file = str(root.parents[2] / ".env")
        weight_result = context.data.fetch(DataRequest(
            Dataset.INDEX_CONSTITUENT_WEIGHT, "931994.CSI", START, CUTOFF, None,
            "snapshot", {"env_file": env_file},
        ))
        if not weight_result.ready or weight_result.identity is None:
            error = weight_result.error
            raise ValueError("index weight DFLS unavailable: " + weight_result.status.value
                             + ("" if error is None else f" {error.code}: {error.message}"))
        if weight_result.identity.content_sha256 != WEIGHT_SHA256:
            raise ValueError("index weight identity changed after pre-registration")
        weights = weight_result.dataframe.copy()
        weights["Date"] = pd.to_datetime(weights["Date"], errors="raise")
        weights = weights.sort_values(["Date", "ConstituentSymbol"]).reset_index(drop=True)
        if weights.duplicated(["Date", "ConstituentSymbol"]).any():
            raise ValueError("duplicate index membership key")
        if (weights["Weight"] <= 0).any() or not np.isfinite(weights["Weight"]).all():
            raise ValueError("invalid index weights")
        weight_sums = weights.groupby("Date")["Weight"].sum()
        symbols = sorted(weights["ConstituentSymbol"].unique())
        quality, parts = [], []
        for position, symbol in enumerate(symbols, start=1):
            result = context.data.fetch(DataRequest(
                Dataset.STOCK_OHLCV, symbol, STOCK_START, CUTOFF, None,
                "daily", {"env_file": env_file},
            ))
            if not result.ready or result.identity is None:
                error = result.error
                quality.append({"Symbol": symbol, "Status": result.status.value,
                                "Rows": 0, "FirstDate": "", "LastDate": "",
                                "ContentSha256": "", "Adjustment": "",
                                "ErrorCode": "" if error is None else error.code})
                continue
            frame = result.dataframe[["Date", "Close"]].copy()
            frame["Date"] = pd.to_datetime(frame["Date"], errors="raise")
            if frame["Date"].duplicated().any() or frame["Close"].le(0).any():
                raise ValueError(f"invalid stock close data: {symbol}")
            frame["Symbol"] = symbol
            parts.append(frame[["Date", "Symbol", "Close"]])
            quality.append({"Symbol": symbol, "Status": result.status.value,
                            "Rows": len(frame), "FirstDate": result.identity.data_start,
                            "LastDate": result.identity.data_cutoff,
                            "ContentSha256": result.identity.content_sha256,
                            "Adjustment": result.identity.metadata.get("adjustment", ""),
                            "ErrorCode": ""})
            if position % 20 == 0:
                print(f"S010 EX14 stock sources inspected: {position}/{len(symbols)}", flush=True)
        closes = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
            columns=["Date", "Symbol", "Close"])
        if closes.empty:
            coverage = pd.DataFrame(columns=["Date", "SnapshotDate", "SnapshotAgeDays",
                                             "MemberCount", "AvailableCount", "WeightCoveragePct"])
        else:
            first = root.parent / "20260929_S010_EX01" / "artifacts"
            calendar = pd.DatetimeIndex(pd.read_csv(
                first / "factor_matrix.csv.gz", usecols=["Date"], parse_dates=["Date"]
            )["Date"])
            coverage = _coverage(weights, closes, calendar)
        quality_frame = pd.DataFrame(quality)
        failed = int(quality_frame["Status"].ne("READY").sum())
        decision = "BREADTH_SOURCE_AUDIT_COMPLETE" if not failed and not coverage.empty else "BREADTH_SOURCE_INCOMPLETE"
        artifacts = []
        for name, frame in (("weight_snapshots.csv.gz", weights),
                            ("stock_closes.csv.gz", closes),
                            ("stock_quality.csv", quality_frame),
                            ("daily_coverage.csv", coverage)):
            frame.to_csv(context.workspace.path(name), index=False,
                         compression="gzip" if name.endswith(".gz") else None,
                         lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX14-{name.split('.')[0]}"))
        summary = {
            "decision": decision, "weight_sha256": weight_result.identity.content_sha256,
            "weight_snapshot_count": len(weight_sums), "weight_rows": len(weights),
            "weight_sum_min": float(weight_sums.min()), "weight_sum_max": float(weight_sums.max()),
            "union_symbol_count": len(symbols), "stock_ready_count": len(parts),
            "stock_failed_count": failed, "coverage_rows": len(coverage),
            "coverage_weight_min": None if coverage.empty else float(coverage["WeightCoveragePct"].min()),
            "coverage_weight_median": None if coverage.empty else float(coverage["WeightCoveragePct"].median()),
            "snapshot_delay_calendar_days": SNAPSHOT_DELAY_DAYS,
            "source_publication_timestamp_verified": False,
            "future_labels_read": False, "account_replay_performed": False,
        }
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX14-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": decision, "stock_ready_count": len(parts),
                   "stock_failed_count": failed, "future_labels_read": False},
            diagnostics={"coverage_rows": len(coverage)}, artifacts=tuple(artifacts),
        )
