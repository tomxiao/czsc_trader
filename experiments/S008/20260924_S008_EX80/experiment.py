from __future__ import annotations

from datetime import date

import pandas as pd

from dataflows import DataRequest, DataStatus, Dataset
from research_experiment import (
    ExperimentCapabilities,
    ExperimentDefinition,
    ExperimentDependency,
    ExperimentMode,
    ExperimentOutcome,
    ExperimentProtocol,
    ExperimentResult,
    ExperimentStage,
    ResearchExperiment,
)


EX79 = "20260924_S008_EX79"
EX79_RECEIPT = "9b523167ec93271e2d2dbf13473cd925db30c0b50a3293d1e79e331f20547"
SYMBOLS = ("518880.SH", "518800.SH")
EXPECTED_ROWS = 2781
START, END = "2013-07-29", "2024-12-31"


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260924_S008_EX80",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Can a peer gold ETF's primary-market shares be a causally usable independent input?",
            hypothesis="Tushare exposes complete, auditable peer and target ETF share histories.",
            falsification_conditions=(
                "Either DFLS input is not READY or lacks a content identity",
                "Either history differs from the preregistered 2781-day full calendar",
                "Share values or T+1 availability metadata fail the data contract",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026098001,
            allowed_datasets=(Dataset.ETF_SHARE_SIZE.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.DATA_GATE,
                first_principles=(
                    "Gold ETF creations and redemptions expose investor allocation demand",
                    "A peer fund can reveal demand distinct from the target fund's own flow",
                ),
                information_paths=(
                    "Tushare peer ETF share observation -> T+1 morning publication -> later SSE decision close",
                ),
                stage_objectives=("Validate historical coverage, source identity and causal availability only",),
                observation_metrics=("row counts, calendar equality, share positivity and content hashes",),
                methodology=(
                    "Fetch both funds through DFLS, without reading ETF prices or returns",
                    "Stop on any coverage or data-contract mismatch",
                ),
                predecessor_experiment_ids=(EX79,),
            ),
            dependencies=(
                ExperimentDependency("pandas", pd.__version__),
                ExperimentDependency("tushare", "1.4.29"),
            ),
            capabilities=ExperimentCapabilities(),
        )

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[EX79]
        if predecessor.receipt_sha256 != EX79_RECEIPT:
            raise ValueError("EX79 receipt identity differs")
        if predecessor.facts.get("decision") != "DISCOVERY_ONLY_OPPORTUNITY_MAP_REVIEW_REQUIRED":
            raise ValueError("EX79 conclusion differs")
        inventory = []
        calendars = []
        issues = []
        for symbol in SYMBOLS:
            publication = context.data.fetch(DataRequest(
                Dataset.ETF_SHARE_SIZE, symbol, START, END, "2024-12-01",
                options={"env_file": ".env"},
            ))
            if publication.status is not DataStatus.READY or publication.identity is None:
                issues.append(f"{symbol}: publication {publication.status.value}")
                continue
            frame = publication.dataframe.sort_values("Date")
            calendars.append((symbol, tuple(frame["Date"])))
            if len(frame) != EXPECTED_ROWS:
                issues.append(f"{symbol}: rows {len(frame)} != {EXPECTED_ROWS}")
            if frame["Date"].duplicated().any() or not frame["TotalShare"].gt(0).all():
                issues.append(f"{symbol}: duplicate date or nonpositive share")
            if frame["Date"].min() != pd.Timestamp(START) or frame["Date"].max() != pd.Timestamp(END):
                issues.append(f"{symbol}: endpoint differs")
            metadata = publication.identity.metadata
            availability = metadata.get("availability_rule")
            if availability != "T+1 08:30 Asia/Shanghai":
                issues.append(f"{symbol}: availability {availability!r} differs")
            inventory.append({
                "Symbol": symbol,
                "Rows": len(frame),
                "FirstDate": frame["Date"].min().date().isoformat(),
                "LastDate": frame["Date"].max().date().isoformat(),
                "ContentSha256": publication.identity.content_sha256,
                "AvailabilityRule": availability,
                "MinShare": float(frame["TotalShare"].min()),
            })
        if len(calendars) == len(SYMBOLS) and calendars[0][1] != calendars[1][1]:
            issues.append("peer and target calendars differ")
        path = context.workspace.path("share_input_inventory.csv")
        pd.DataFrame(inventory).to_csv(path, index=False, lineterminator="\n")
        passed = not issues and len(inventory) == len(SYMBOLS)
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if passed else ExperimentOutcome.FAIL,
            facts={
                "decision": "PROCEED_PEER_FLOW_INFORMATION_AUDIT" if passed else "STOP_PEER_FLOW_DATA_GATE",
                "issues": issues,
                "input_hashes": {row["Symbol"]: row["ContentSha256"] for row in inventory},
                "rows_by_symbol": {row["Symbol"]: row["Rows"] for row in inventory},
                "common_calendar": len(calendars) == len(SYMBOLS) and calendars[0][1] == calendars[1][1],
            },
            diagnostics={"reads_real_returns": False, "reads_sealed_validation": False},
            artifacts=(context.workspace.register_artifact("share_input_inventory.csv", "gold-etf-share-input-inventory"),),
        )
