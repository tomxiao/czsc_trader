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


EXPERIMENT_ID = "20260925_S009_EX05"
PREDECESSOR = "20260925_S009_EX04"
PREDECESSOR_RECEIPT = "f920ee1275018fbd5672f29fe4dabff31371636215b85570c50bcfcc6a4c0f38"
SYMBOLS = ("510050.SH", "510300.SH")
START, END = "2013-07-29", "2024-12-31"
EXPECTED_ROWS = 2781


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S009",
            mode=ExperimentMode.DISCOVERY,
            research_question="Can broad-equity ETF share histories support an auditable liquidity-allocation hypothesis?",
            hypothesis="Two long-lived broad-equity ETFs have complete, causally usable share histories through DFLS.",
            falsification_conditions=(
                "Either publication is not READY or lacks a content identity",
                "Coverage, common calendar, positivity, or availability metadata differs from the frozen contract",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026090501,
            allowed_datasets=(Dataset.ETF_SHARE_SIZE.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.DATA_GATE,
                first_principles=(
                    "ETF creations expose participant allocation demand",
                    "Two broad products reduce reliance on one fund's idiosyncratic share changes",
                ),
                information_paths=(
                    "Broad-equity ETF share observation -> T+1 morning publication -> later gold ETF decision",
                ),
                stage_objectives=("Validate source identity, coverage, and causal availability without reading returns",),
                observation_metrics=("row count, endpoints, calendar equality, positivity, content hashes",),
                methodology=(
                    "Fetch both products through DFLS and stop on any contract mismatch",
                    "Do not load target prices, returns, or sealed validation",
                ),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            dependencies=(ExperimentDependency("pandas", pd.__version__),),
            capabilities=ExperimentCapabilities(),
            subjects=("518880.SH",),
        )

    def synthetic_precheck(self) -> None:
        dates = pd.bdate_range("2024-01-01", periods=6)
        shares = pd.Series([100.0, 100.0, 102.0, 102.0, 105.0, 104.0], index=dates)
        lagged = shares.shift(1)
        if lagged.first_valid_index() != dates[1] or lagged.loc[dates[1]] != shares.loc[dates[0]]:
            raise ValueError("strict prior-source alignment differs")
        if not shares.gt(0).all() or len(shares.pct_change().dropna()) != 5:
            raise ValueError("synthetic share transform differs")

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[PREDECESSOR]
        if predecessor.receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX04 predecessor receipt differs")
        inventory: list[dict[str, object]] = []
        calendars: list[tuple[pd.Timestamp, ...]] = []
        issues: list[str] = []
        for symbol in SYMBOLS:
            publication = context.data.fetch(DataRequest(
                Dataset.ETF_SHARE_SIZE,
                symbol,
                START,
                END,
                END,
                options={"env_file": ".env"},
            ))
            if publication.status is not DataStatus.READY or publication.identity is None:
                issues.append(f"{symbol}: publication {publication.status.value}")
                continue
            frame = publication.dataframe.sort_values("Date")
            calendar = tuple(pd.to_datetime(frame["Date"]))
            calendars.append(calendar)
            if len(frame) != EXPECTED_ROWS:
                issues.append(f"{symbol}: rows {len(frame)} != {EXPECTED_ROWS}")
            if frame["Date"].duplicated().any() or not frame["TotalShare"].gt(0).all():
                issues.append(f"{symbol}: duplicate date or nonpositive share")
            if frame["Date"].min() != pd.Timestamp(START) or frame["Date"].max() != pd.Timestamp(END):
                issues.append(f"{symbol}: endpoints differ")
            availability = publication.identity.metadata.get("availability_rule")
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
        if len(calendars) == len(SYMBOLS) and calendars[0] != calendars[1]:
            issues.append("broad-equity ETF calendars differ")
        pd.DataFrame(inventory).to_csv(context.workspace.path("share_input_inventory.csv"), index=False, lineterminator="\n")
        passed = not issues and len(inventory) == len(SYMBOLS)
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if passed else ExperimentOutcome.FAIL,
            facts={
                "decision": "PROCEED_TO_LIQUIDITY_REPLICATION_AUDIT" if passed else "STOP_LIQUIDITY_DATA_GATE",
                "issues": issues,
                "rows_by_symbol": {item["Symbol"]: item["Rows"] for item in inventory},
                "input_hashes": {item["Symbol"]: item["ContentSha256"] for item in inventory},
                "common_calendar": len(calendars) == len(SYMBOLS) and calendars[0] == calendars[1],
            },
            diagnostics={"reads_real_returns": False, "reads_sealed_validation": False, "post_hoc_hypothesis": True},
            artifacts=(context.workspace.register_artifact("share_input_inventory.csv", "broad-equity-share-input-inventory"),),
        )
