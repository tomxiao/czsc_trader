from __future__ import annotations

from datetime import date

import pandas as pd

from dataflows import DataRequest, DataStatus, Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentDefinition, ExperimentDependency, ExperimentMode,
    ExperimentOutcome, ExperimentProtocol, ExperimentResult, ExperimentStage, ResearchExperiment,
)


EXPERIMENT_ID = "20260925_S009_EX07"
PREDECESSOR = "20260925_S009_EX06"
PREDECESSOR_RECEIPT = "3db5a251dcf76af9a6affa5cf017de681f21fe4b56425eca1de0164b16fe1a57"
REFERENCE = "510050.SH"
SYMBOL = "159915.SZ"
START, END = "2013-07-29", "2024-12-31"
EXPECTED_MISSING = (
    "2013-10-17", "2013-11-14", "2013-12-10", "2014-03-21", "2014-04-11",
    "2014-04-22", "2014-05-08", "2014-11-07", "2014-12-31", "2015-01-05", "2015-02-02",
)


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S009",
            mode=ExperimentMode.DISCOVERY,
            research_question="Can 159915 provide a third auditable broad-equity share proxy despite early isolated gaps?",
            hypothesis="Its complete evaluation-era history and causal forward-fill policy support a final cross-product replication.",
            falsification_conditions=(
                "The input or reference publication is not READY or lacks identity",
                "Coverage, positivity, availability, or the frozen early-gap contract differs",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026090701,
            allowed_datasets=(Dataset.ETF_SHARE_SIZE.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.DATA_GATE,
                first_principles=(
                    "A third product can adjudicate a split two-product replication",
                    "Missing historical observations may only carry prior-known values forward",
                ),
                information_paths=("159915 share observation -> T+1 publication -> later gold ETF decision",),
                stage_objectives=("Validate the third proxy and its missing-date contract without reading returns",),
                observation_metrics=("row count, endpoints, missing dates, positivity, content hashes",),
                methodology=("Compare source dates with the pinned full reference calendar and stop on any mismatch",),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            dependencies=(ExperimentDependency("pandas", pd.__version__),),
            capabilities=ExperimentCapabilities(),
            subjects=("518880.SH",),
        )

    def synthetic_precheck(self) -> None:
        dates = pd.bdate_range("2024-01-01", periods=6)
        sparse = pd.Series([100.0, 102.0, 104.0], index=dates[[0, 2, 5]])
        filled = sparse.reindex(dates).ffill()
        if filled.isna().any() or filled.loc[dates[1]] != 100.0 or filled.loc[dates[4]] != 102.0:
            raise ValueError("causal forward-fill differs")

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[PREDECESSOR]
        if predecessor.receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX06 predecessor receipt differs")
        publications = {}
        for symbol in (REFERENCE, SYMBOL):
            item = context.data.fetch(DataRequest(
                Dataset.ETF_SHARE_SIZE, symbol, START, END, END, options={"env_file": ".env"},
            ))
            if item.status is not DataStatus.READY or item.identity is None:
                raise RuntimeError(f"{symbol} share input is not READY")
            publications[symbol] = item
        reference = publications[REFERENCE].dataframe.sort_values("Date")
        target = publications[SYMBOL].dataframe.sort_values("Date")
        missing = pd.DatetimeIndex(reference["Date"]).difference(pd.DatetimeIndex(target["Date"]))
        missing_text = tuple(item.date().isoformat() for item in missing)
        issues = []
        if len(reference) != 2781 or len(target) != 2770:
            issues.append(f"row counts differ: reference={len(reference)}, target={len(target)}")
        if target["Date"].min() != pd.Timestamp(START) or target["Date"].max() != pd.Timestamp(END):
            issues.append("target endpoints differ")
        if target["Date"].duplicated().any() or not target["TotalShare"].gt(0).all():
            issues.append("target dates or shares are invalid")
        if missing_text != EXPECTED_MISSING:
            issues.append(f"missing dates differ: {missing_text}")
        for symbol, item in publications.items():
            if item.identity.metadata.get("availability_rule") != "T+1 08:30 Asia/Shanghai":
                issues.append(f"{symbol} availability differs")
        inventory = pd.DataFrame([
            {
                "Symbol": symbol, "Rows": len(item.dataframe),
                "FirstDate": item.dataframe["Date"].min().date().isoformat(),
                "LastDate": item.dataframe["Date"].max().date().isoformat(),
                "ContentSha256": item.identity.content_sha256,
                "AvailabilityRule": item.identity.metadata.get("availability_rule"),
            }
            for symbol, item in publications.items()
        ])
        inventory.to_csv(context.workspace.path("share_input_inventory.csv"), index=False, lineterminator="\n")
        pd.DataFrame({"MissingDate": list(EXPECTED_MISSING)}).to_csv(
            context.workspace.path("missing_date_ledger.csv"), index=False, lineterminator="\n"
        )
        passed = not issues
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if passed else ExperimentOutcome.FAIL,
            facts={
                "decision": "PROCEED_TO_THIRD_PROXY_AUDIT" if passed else "STOP_THIRD_PROXY_DATA_GATE",
                "issues": issues, "missing_count": len(missing),
                "input_hashes": {symbol: item.identity.content_sha256 for symbol, item in publications.items()},
            },
            diagnostics={"reads_real_returns": False, "reads_sealed_validation": False},
            artifacts=(
                context.workspace.register_artifact("share_input_inventory.csv", "third-proxy-share-input-inventory"),
                context.workspace.register_artifact("missing_date_ledger.csv", "third-proxy-missing-date-ledger"),
            ),
        )
