"""S010 EX21: sealed PCF and constituent intraday source gate."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pandas as pd
from czsc_trader.experiment_archive import validate_experiment_archive
from dataflows import DataRequest, Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)


EXPERIMENT_ID = "20260929_S010_EX21"
RECEIPTS = {"20260929_S010_EX20": "00fd820c9782bbba0a0eaf76abe5b39eefecef6b9cdb5a41ebb0c0b8ab623df1"}
START, CUTOFF = "2024-12-26", "2026-09-28"
SAMPLE_DATES = ("2025-03-03", "2026-09-28")
SEED = 2026092921


def _latest_available(pcf: pd.DataFrame, session: str) -> tuple[str, pd.DataFrame]:
    decision = pd.Timestamp(session + " 10:35:00")
    candidates = pcf.loc[pd.to_datetime(pcf["AvailableDate"]) <= decision]
    if candidates.empty:
        raise ValueError(f"no PCF available by decision time: {session}")
    selected = str(candidates["Date"].max())
    if selected >= session:
        raise ValueError(f"same-day PCF leaked into decision: {session}")
    return selected, candidates.loc[candidates["Date"].eq(selected)].copy()


def _sample_symbols(basket: pd.DataFrame) -> tuple[str, str]:
    eligible = basket.loc[basket["Quantity"].gt(0) & basket["ConstituentSymbol"].ne("159900.SZ")]
    names = sorted(eligible["ConstituentSymbol"].astype(str).unique())
    sh = next((name for name in names if name.startswith("6") and name.endswith(".SH")), None)
    sz = next((name for name in names if name.startswith(("0", "3")) and name.endswith(".SZ")), None)
    if sh is None or sz is None:
        raise ValueError("sample PCF lacks a positive-quantity SH/SZ stock pair")
    return sh, sz


def _precheck() -> None:
    sample = pd.DataFrame({
        "Date": ["2025-02-28", "2025-02-28", "2025-03-03"],
        "AvailableDate": ["2025-03-03 09:30:00", "2025-03-03 09:30:00", "2025-03-04 09:30:00"],
        "ConstituentSymbol": ["600001.SH", "000001.SZ", "159900.SZ"],
        "Quantity": [100, 100, 100],
    })
    selected, basket = _latest_available(sample, "2025-03-03")
    if selected != "2025-02-28" or _sample_symbols(basket) != ("600001.SH", "000001.SZ"):
        raise ValueError("synthetic PCF lag or sample selection failed")
    try:
        _latest_available(sample, "2025-02-28")
    except ValueError:
        pass
    else:
        raise ValueError("PCF exposed before its available time")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Does DFLS supply complete lagged PCF and aligned constituent intraday samples?",
            hypothesis="The new PCF and stock-minute interfaces permit a bounded causal intraday basket test.",
            falsification_conditions=("PCF incomplete or temporally unsafe", "Minute sample unavailable or misaligned"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED,
            allowed_datasets=(Dataset.ETF_CREATION_REDEMPTION_BASKET.value,
                              Dataset.STOCK_OHLCV.value, Dataset.ETF_OHLCV.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.DATA_GATE,
                first_principles=("A basket lead-lag test needs historically available membership and aligned prices",),
                information_paths=("T-1 available PCF and completed T 5-minute bars -> T 10:35 information",),
                stage_objectives=("Seal PCF coverage and availability", "Audit two dated stock/ETF minute samples"),
                observation_metrics=("PCF days and virtual-cash rows", "5-minute READY and aligned 10:30 bars"),
                methodology=("Single-thread DFLS requests", "Fixed dates and deterministic two-symbol selection"),
                predecessor_experiment_ids=tuple(RECEIPTS),
            ),
            subjects=("159326.SZ",),
            dependencies=(ExperimentDependency("pandas", pd.__version__),),
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
        pcf_result = context.data.fetch(DataRequest(
            Dataset.ETF_CREATION_REDEMPTION_BASKET, "159326.SZ", START, CUTOFF,
            CUTOFF, "daily", {"env_file": env_file},
        ))
        if not pcf_result.ready or pcf_result.identity is None:
            error = pcf_result.error
            raise ValueError("PCF DFLS unavailable: " + pcf_result.status.value
                             + ("" if error is None else f" {error.code}: {error.message}"))
        pcf = pcf_result.dataframe.copy()
        dates = pd.to_datetime(pcf["Date"])
        available = pd.to_datetime(pcf["AvailableDate"])
        if pcf.duplicated(["Date", "ConstituentSymbol"]).any():
            raise ValueError("duplicate PCF primary key")
        if (available.dt.normalize() <= dates).any():
            raise ValueError("PCF available on or before source day")
        day_counts = pcf.groupby("Date").size()
        cash_counts = pcf["ConstituentSymbol"].eq("159900.SZ").groupby(pcf["Date"]).sum()
        if not cash_counts.eq(1).all():
            raise ValueError("PCF virtual-cash count differs from one per day")
        pcf.to_csv(context.workspace.path("pcf_snapshot.csv.gz"), index=False,
                   compression="gzip", lineterminator="\n")
        artifacts = [context.workspace.register_artifact("pcf_snapshot.csv.gz", "S010-EX21-pcf-snapshot")]
        samples, quality = [], []
        for session in SAMPLE_DATES:
            pcf_date, basket = _latest_available(pcf, session)
            sh, sz = _sample_symbols(basket)
            samples.append({"DecisionDate": session, "PcfDate": pcf_date,
                            "PcfAvailableDate": str(basket["AvailableDate"].iloc[0]),
                            "PcfRows": len(basket), "SH": sh, "SZ": sz})
            stamps: dict[str, set[pd.Timestamp]] = {}
            for dataset, symbol in ((Dataset.ETF_OHLCV, "159326.SZ"),
                                    (Dataset.STOCK_OHLCV, sh), (Dataset.STOCK_OHLCV, sz)):
                result = context.data.fetch(DataRequest(
                    dataset, symbol, session, session, session, "5m", {"env_file": env_file},
                ))
                row = {"Date": session, "Dataset": dataset.value, "Symbol": symbol,
                       "Status": result.status.value, "Rows": 0, "FirstBar": "", "LastBar": "",
                       "ContentSha256": "", "Adjustment": "", "ErrorCode": ""}
                if result.ready and result.identity is not None:
                    frame = result.dataframe
                    bar_times = pd.to_datetime(frame["Date"], errors="raise")
                    if bar_times.duplicated().any() or not bar_times.dt.normalize().eq(pd.Timestamp(session)).all():
                        raise ValueError(f"invalid intraday bar keys: {symbol} {session}")
                    if frame[["Open", "High", "Low", "Close"]].le(0).any().any():
                        raise ValueError(f"nonpositive intraday prices: {symbol} {session}")
                    stamps[symbol] = set(bar_times)
                    row.update(Rows=len(frame), FirstBar=str(bar_times.min()),
                               LastBar=str(bar_times.max()),
                               ContentSha256=result.identity.content_sha256,
                               Adjustment=str(result.identity.metadata.get("adjustment", "")))
                else:
                    row["ErrorCode"] = "" if result.error is None else result.error.code
                quality.append(row)
            common = set.intersection(*(stamps.get(symbol, set()) for symbol in ("159326.SZ", sh, sz)))
            samples[-1]["CommonBars"] = len(common)
            samples[-1]["Common1030"] = pd.Timestamp(session + " 10:30:00") in common
        sample_frame, quality_frame = pd.DataFrame(samples), pd.DataFrame(quality)
        complete = (quality_frame["Status"].eq("READY").all()
                    and quality_frame["Rows"].ge(40).all()
                    and sample_frame["Common1030"].all())
        decision = "PCF_INTRADAY_SAMPLE_READY" if complete else "PCF_INTRADAY_SAMPLE_INCOMPLETE"
        for name, frame in (("sample_selection.csv", sample_frame), ("minute_quality.csv", quality_frame)):
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX21-{name.split('.')[0]}"))
        summary = {
            "decision": decision, "pcf_rows": len(pcf), "pcf_days": len(day_counts),
            "pcf_rows_per_day_min": int(day_counts.min()), "pcf_rows_per_day_max": int(day_counts.max()),
            "pcf_virtual_cash_days": int(cash_counts.eq(1).sum()),
            "pcf_identity_sha256": pcf_result.identity.content_sha256,
            "pcf_source_publication_timestamp_verified": False,
            "pcf_historical_revision_history_verified": False,
            "minute_ready_requests": int(quality_frame["Status"].eq("READY").sum()),
            "minute_total_requests": len(quality_frame),
            "aligned_sample_days": int(sample_frame["Common1030"].sum()),
            "full_top10_coverage_verified": False, "future_labels_read": False,
            "account_replay_performed": False,
        }
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX21-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if complete else ExperimentOutcome.INCONCLUSIVE,
            facts={"decision": decision, "pcf_days": len(day_counts),
                   "minute_ready_requests": summary["minute_ready_requests"], "future_labels_read": False},
            diagnostics={"aligned_sample_days": summary["aligned_sample_days"]},
            artifacts=tuple(artifacts),
        )
