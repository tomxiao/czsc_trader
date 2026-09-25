from __future__ import annotations

from datetime import date

import pandas as pd

from dataflows import DataCoverageRequirement, DataRequest, DataStatus, Dataset
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


EXPERIMENT_ID = "20260926_S009_EX09"
PREDECESSOR = "20260925_S009_EX08"
PREDECESSOR_RECEIPT = "472088fa4cc6992a1aaa00b0294e288e4b2ae7c7b019a124c5ce8a880fd173ba"
START, END = "2014-03-28", "2024-12-31"
EVALUATION_START = "2019-01-01"
EXPECTED_ROWS = 3931
EXPECTED_OPEN_DAYS = 1456
EXPECTED_SHA256 = "e4cbd292506fd5ec1e85ccbca0ab37b8bbfdc2cea8e0f186fef27f18a22fe525"


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S009",
            mode=ExperimentMode.DISCOVERY,
            research_question=(
                "Can FRED initial-release U.S. policy uncertainty become a complete, causal S009 input?"
            ),
            hypothesis=(
                "A fixed initial-release series with strict prior China-session alignment can support a formal "
                "test of global policy uncertainty as a gold opportunity mechanism."
            ),
            falsification_conditions=(
                "The FRED or SSE calendar publication is not READY with a stable identity",
                "Coverage, fixed-series lineage, positive values, or strict-prior alignment differs",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026090901,
            allowed_datasets=(
                Dataset.US_POLICY_UNCERTAINTY_DAILY.value,
                Dataset.TRADING_CALENDAR.value,
            ),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.DATA_GATE,
                first_principles=(
                    "Global policy uncertainty can change safe-haven allocation independently of domestic liquidity",
                    "Revised macro history cannot be used as if it were known at the original decision date",
                ),
                information_paths=(
                    "U.S. policy-news uncertainty -> safe-haven allocation -> later RMB gold ETF appreciation",
                ),
                stage_objectives=(
                    "Validate FRED initial-release identity and strict-prior SSE decision coverage without returns",
                ),
                observation_metrics=(
                    "row count, endpoints, content hash, lineage, positivity, mapped decision count",
                ),
                methodology=(
                    "Require the frozen DFLS identity and map only AvailableDate strictly before each SSE session",
                ),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            dependencies=(ExperimentDependency("pandas", pd.__version__),),
            capabilities=ExperimentCapabilities(),
            subjects=("518880.SH",),
        )

    def synthetic_precheck(self) -> None:
        source = pd.DataFrame({
            "AvailableDate": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "PolicyUncertaintyIndex": [100.0, 120.0],
        })
        decisions = pd.DataFrame({"Date": pd.to_datetime(["2024-01-03", "2024-01-04"])})
        aligned = pd.merge_asof(
            decisions,
            source,
            left_on="Date",
            right_on="AvailableDate",
            direction="backward",
            allow_exact_matches=False,
        )
        if aligned["PolicyUncertaintyIndex"].tolist() != [100.0, 120.0]:
            raise ValueError("strict-prior FRED alignment differs")

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[PREDECESSOR]
        if predecessor.receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX08 predecessor receipt differs")
        if predecessor.facts.get("decision") != "COMPONENT_PANEL_PRODUCED":
            raise ValueError("EX08 component-panel decision differs")

        policy = context.data.fetch(DataRequest(
            Dataset.US_POLICY_UNCERTAINTY_DAILY,
            None,
            START,
            END,
            None,
            options={"env_file": ".env"},
            coverage=DataCoverageRequirement(maximum_start_lag_days=0, minimum_rows=3900),
        ))
        calendar = context.data.fetch(DataRequest(
            Dataset.TRADING_CALENDAR,
            "SSE",
            EVALUATION_START,
            END,
            END,
            options={"env_file": ".env"},
        ))
        issues: list[str] = []
        if policy.status is not DataStatus.READY or policy.identity is None:
            issues.append(f"policy publication is {policy.status.value}")
        if calendar.status is not DataStatus.READY or calendar.identity is None:
            issues.append(f"calendar publication is {calendar.status.value}")
        if issues:
            return ExperimentResult(
                outcome=ExperimentOutcome.FAIL,
                facts={"decision": "STOP_POLICY_UNCERTAINTY_DATA_GATE", "issues": issues},
                diagnostics={"reads_real_returns": False, "reads_sealed_validation": False},
            )

        frame = policy.dataframe.sort_values("Date").reset_index(drop=True)
        metadata = policy.identity.metadata
        if len(frame) != EXPECTED_ROWS:
            issues.append(f"row count differs: {len(frame)}")
        if frame["Date"].min() != pd.Timestamp(START):
            issues.append("first observation date differs")
        if frame["Date"].max() < pd.Timestamp("2024-12-30"):
            issues.append("last observation date is too early")
        if frame["AvailableDate"].max() != pd.Timestamp(END):
            issues.append("last available date differs")
        if policy.identity.content_sha256 != EXPECTED_SHA256:
            issues.append("policy input content identity differs")
        if frame["Date"].duplicated().any() or not frame["PolicyUncertaintyIndex"].gt(0).all():
            issues.append("policy dates or values are invalid")
        if frame["AvailableDate"].lt(frame["Date"]).any():
            issues.append("policy availability precedes its observation date")
        expected_metadata = {
            "series_id": "USEPUINDXD",
            "vintage_mode": "INITIAL_RELEASE_ONLY",
            "fred_output_type": 4,
            "availability_time_field": "AvailableDate",
            "source_calendar": "FRED_CALENDAR_DAY",
            "available_at": "initial release date reported by ALFRED",
        }
        for key, value in expected_metadata.items():
            if metadata.get(key) != value:
                issues.append(f"metadata differs: {key}")

        decisions = calendar.dataframe.loc[
            calendar.dataframe["IsOpen"].eq(1), ["Date"]
        ].sort_values("Date")
        source = frame.loc[:, ["Date", "AvailableDate", "PolicyUncertaintyIndex"]].sort_values(
            ["AvailableDate", "Date"]
        )
        aligned = pd.merge_asof(
            decisions,
            source,
            left_on="Date",
            right_on="AvailableDate",
            direction="backward",
            allow_exact_matches=False,
        )
        mapped = int(aligned["PolicyUncertaintyIndex"].notna().sum())
        strict = bool(
            aligned.loc[aligned["AvailableDate"].notna(), "AvailableDate"].lt(
                aligned.loc[aligned["AvailableDate"].notna(), "Date_x"]
            ).all()
        )
        if len(decisions) != EXPECTED_OPEN_DAYS or mapped != EXPECTED_OPEN_DAYS:
            issues.append(f"SSE decision coverage differs: sessions={len(decisions)}, mapped={mapped}")
        if not strict:
            issues.append("SSE alignment is not strict prior")

        inventory = pd.DataFrame([{
            "Dataset": Dataset.US_POLICY_UNCERTAINTY_DAILY.value,
            "Rows": len(frame),
            "FirstDate": frame["Date"].min().date().isoformat(),
            "LastDate": frame["Date"].max().date().isoformat(),
            "LastAvailableDate": frame["AvailableDate"].max().date().isoformat(),
            "ContentSha256": policy.identity.content_sha256,
            "SeriesId": metadata.get("series_id"),
            "VintageMode": metadata.get("vintage_mode"),
        }])
        inventory.to_csv(context.workspace.path("policy_input_inventory.csv"), index=False, lineterminator="\n")
        alignment = pd.DataFrame([{
            "EvaluationStart": EVALUATION_START,
            "EvaluationEnd": END,
            "SseOpenDays": len(decisions),
            "MappedDays": mapped,
            "MissingDays": int(aligned["PolicyUncertaintyIndex"].isna().sum()),
            "StrictPrior": strict,
        }])
        alignment.to_csv(context.workspace.path("causal_alignment_summary.csv"), index=False, lineterminator="\n")
        passed = not issues
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if passed else ExperimentOutcome.FAIL,
            facts={
                "decision": (
                    "PROCEED_TO_POLICY_UNCERTAINTY_INFORMATION_AUDIT"
                    if passed
                    else "STOP_POLICY_UNCERTAINTY_DATA_GATE"
                ),
                "issues": issues,
                "policy_rows": len(frame),
                "mapped_decision_days": mapped,
                "input_sha256": policy.identity.content_sha256,
            },
            diagnostics={"reads_real_returns": False, "reads_sealed_validation": False},
            artifacts=(
                context.workspace.register_artifact(
                    "policy_input_inventory.csv", "FRED-policy-uncertainty-input-inventory"
                ),
                context.workspace.register_artifact(
                    "causal_alignment_summary.csv", "strict-prior-SSE-alignment-summary"
                ),
            ),
        )
