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


EX74 = "20260924_S008_EX74"
EX74_RECEIPT = "0d6fd2579ef0caec6af0e1bd3228c81e94695440b02bd8ffa4984872057fd081"
DATASETS = (
    (Dataset.US_REAL_YIELD_DAILY, None, 2998),
    (Dataset.US_CPI_RELEASE, None, 144),
    (Dataset.US_NOMINAL_YIELD_DAILY, None, 2999),
    (Dataset.US_ISM_PMI_RELEASE, None, 144),
    (Dataset.US_FEDERAL_BUDGET_RELEASE, None, 144),
    (Dataset.GLOBAL_INDEX_DAILY, "SPX", 3020),
)


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260924_S008_EX75",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Can Tushare publish five gold-timing factor families with bounded causal availability?",
            hypothesis="The six required raw series cover the S008 development pool with auditable identities.",
            falsification_conditions=(
                "Any DFLS request lacks READY status or content identity",
                "Observed history differs from the preregistered coverage",
                "A monthly release is usable on or before its Tushare source date",
                "The nominal-yield and SPX calendars have too little overlap",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026097501,
            allowed_datasets=tuple(item[0].value for item in DATASETS),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.DATA_GATE,
                first_principles=(
                    "Real rates represent gold holding opportunity cost",
                    "Inflation, growth, fiscal credit and cross-asset stress can change gold demand",
                ),
                information_paths=(
                    "Tushare source event -> conservative China availability -> causal monthly factor",
                    "US yield and equity closes -> lagged cross-asset state -> later gold participation",
                ),
                stage_objectives=("Validate Tushare data identities and causal source-time boundaries only",),
                observation_metrics=("row counts, annual event counts, input hashes and calendar overlap",),
                methodology=(
                    "Fetch all inputs through DFLS and freeze their content identities",
                    "Do not read ETF returns or source data dated after 2024",
                ),
                predecessor_experiment_ids=(EX74,),
            ),
            dependencies=(
                ExperimentDependency("pandas", pd.__version__),
                ExperimentDependency("tushare", "1.4.29"),
            ),
            capabilities=ExperimentCapabilities(),
        )

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[EX74]
        if predecessor.receipt_sha256 != EX74_RECEIPT:
            raise ValueError("EX74 receipt identity differs")
        if predecessor.facts.get("decision") != "STOP_CPI_AS_UPSIDE_SOURCE":
            raise ValueError("EX74 conclusion differs")
        frames = {}
        inventory = []
        issues = []
        for dataset, symbol, expected_rows in DATASETS:
            publication = context.data.fetch(DataRequest(
                dataset, symbol, "2013-01-01", "2024-12-31", "2024-12-01",
                options={"env_file": ".env"},
            ))
            if publication.status is not DataStatus.READY or publication.identity is None:
                issues.append(f"{dataset.value}: {publication.status.value}")
                continue
            frame = publication.dataframe
            frames[dataset] = frame
            if len(frame) != expected_rows:
                issues.append(f"{dataset.value}: row count {len(frame)} != {expected_rows}")
            if "AvailableDate" in frame and not frame["AvailableDate"].gt(frame["Date"]).all():
                issues.append(f"{dataset.value}: non-causal availability")
            if dataset in {Dataset.US_CPI_RELEASE, Dataset.US_ISM_PMI_RELEASE, Dataset.US_FEDERAL_BUDGET_RELEASE}:
                annual = frame["Date"].dt.year.value_counts()
                if any(int(annual.get(year, 0)) != 12 for year in range(2013, 2025)):
                    issues.append(f"{dataset.value}: monthly event sequence incomplete")
            inventory.append({
                "Dataset": dataset.value,
                "Rows": len(frame),
                "FirstDate": frame["Date"].min().date().isoformat(),
                "LastDate": frame["Date"].max().date().isoformat(),
                "ContentSha256": publication.identity.content_sha256,
                "AvailableAt": publication.identity.metadata["available_at"],
                "UnverifiedClockRows": publication.identity.metadata.get("unverified_source_clock_rows", 0),
            })
        if Dataset.US_ISM_PMI_RELEASE in frames:
            pmi = frames[Dataset.US_ISM_PMI_RELEASE]["PmiIndex"]
            if not pmi.between(0, 100).all():
                issues.append("PMI value outside 0-100")
        overlap = 0
        if Dataset.US_NOMINAL_YIELD_DAILY in frames and Dataset.GLOBAL_INDEX_DAILY in frames:
            overlap = len(set(frames[Dataset.US_NOMINAL_YIELD_DAILY]["Date"]) & set(frames[Dataset.GLOBAL_INDEX_DAILY]["Date"]))
            if overlap < 2900:
                issues.append(f"nominal yield/SPX overlap {overlap} < 2900")
        inventory_path = context.workspace.path("input_inventory.csv")
        pd.DataFrame(inventory).to_csv(inventory_path, index=False, lineterminator="\n")
        artifact = context.workspace.register_artifact("input_inventory.csv", "tushare-factor-input-inventory")
        passed = not issues and len(inventory) == len(DATASETS)
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if passed else ExperimentOutcome.FAIL,
            facts={
                "decision": "PROCEED_TUSHARE_FACTOR_INFORMATION_AUDIT" if passed else "STOP_TUSHARE_FACTOR_DATA_GATE",
                "dataset_count": len(inventory),
                "nominal_spx_overlap": overlap,
                "issues": issues,
                "content_sha256_by_dataset": {row["Dataset"]: row["ContentSha256"] for row in inventory},
            },
            diagnostics={"reads_real_returns": False, "reads_sealed_validation": False},
            artifacts=(artifact,),
        )
