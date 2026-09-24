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


EX83 = "20260924_S008_EX83"
EX83_RECEIPT = "71dc30ae352cfdd7d096d3ca5eb359e6f7792604afac66f7197ce36295807e54"
START, END = "2018-03-26", "2024-12-31"


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260925_S008_EX84",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Can Tushare publish a causally bounded domestic crude-futures index through 2024?",
            hypothesis="SC.NH has complete, identified 2018-2024 history usable only after source-session close.",
            falsification_conditions=(
                "DFLS publication is not READY or lacks a content identity",
                "Coverage, price validity or uniqueness differs from the preregistered gate",
                "Source availability is not bounded after the source-session close",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026098401,
            allowed_datasets=(Dataset.DOMESTIC_INDEX_DAILY.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.DATA_GATE,
                first_principles=(
                    "Oil supply and demand shocks can affect inflation, growth and risk preference differently",
                    "A domestic oil-futures index is an incomplete proxy for global crude spot prices",
                ),
                information_paths=(
                    "Tushare SC.NH source session -> DFLS identity -> later China decision session",
                ),
                stage_objectives=("Validate domestic oil index coverage and causal source contract only",),
                observation_metrics=("source rows, annual coverage, dates, price positivity and content identity",),
                methodology=(
                    "Fetch SC.NH only through existing DFLS DOMESTIC_INDEX_DAILY",
                    "Do not read ETF returns or post-2024 source observations",
                ),
                predecessor_experiment_ids=(EX83,),
            ),
            dependencies=(
                ExperimentDependency("pandas", pd.__version__),
                ExperimentDependency("tushare", "1.4.29"),
            ),
            capabilities=ExperimentCapabilities(),
        )

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[EX83]
        if predecessor.receipt_sha256 != EX83_RECEIPT:
            raise ValueError("EX83 receipt identity differs")
        if predecessor.facts.get("decision") != "NO_REPRODUCIBLE_CROWDING_MECHANISM":
            raise ValueError("EX83 conclusion differs")
        publication = context.data.fetch(DataRequest(
            Dataset.DOMESTIC_INDEX_DAILY,
            "SC.NH",
            START,
            END,
            "2024-12-01",
            options={"env_file": ".env"},
        ))
        issues = []
        inventory = []
        annual = {}
        identity_hash = None
        if publication.status is not DataStatus.READY or publication.identity is None:
            issues.append(f"SC.NH publication {publication.status.value}")
        else:
            frame = publication.dataframe.sort_values("Date")
            identity_hash = publication.identity.content_sha256
            annual = {str(year): int(count) for year, count in frame["Date"].dt.year.value_counts().sort_index().items()}
            availability = publication.identity.metadata.get("availability_rule")
            if len(frame) < 1600:
                issues.append(f"SC.NH has only {len(frame)} rows")
            if frame["Date"].duplicated().any():
                issues.append("SC.NH has duplicate dates")
            if frame["Date"].min() != pd.Timestamp(START) or frame["Date"].max() != pd.Timestamp(END):
                issues.append("SC.NH endpoints differ")
            if not frame["Close"].gt(0).all():
                issues.append("SC.NH has nonpositive or missing close")
            if annual.get("2018", 0) < 180 or any(annual.get(str(year), 0) < 220 for year in range(2019, 2025)):
                issues.append("SC.NH annual coverage below the preregistered minimum")
            if availability != "current session after market close":
                issues.append(f"SC.NH availability rule differs: {availability!r}")
            inventory.append({
                "Dataset": Dataset.DOMESTIC_INDEX_DAILY.value,
                "Symbol": "SC.NH",
                "Rows": len(frame),
                "FirstDate": frame["Date"].min().date().isoformat(),
                "LastDate": frame["Date"].max().date().isoformat(),
                "ContentSha256": identity_hash,
                "AvailabilityRule": availability,
                "MinClose": float(frame["Close"].min()),
            })
        pd.DataFrame(inventory).to_csv(context.workspace.path("oil_input_inventory.csv"), index=False, lineterminator="\n")
        passed = not issues and len(inventory) == 1
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if passed else ExperimentOutcome.FAIL,
            facts={
                "decision": "PROCEED_DOMESTIC_OIL_DRIVER_SATELLITE" if passed else "STOP_DOMESTIC_OIL_DATA_GATE",
                "issues": issues,
                "content_sha256": identity_hash,
                "annual_rows": annual,
                "oil_window_start": START,
                "oil_window_end": END,
            },
            diagnostics={"reads_real_returns": False, "reads_sealed_validation": False},
            artifacts=(context.workspace.register_artifact("oil_input_inventory.csv", "tushare-sc-oil-input-inventory"),),
        )
