from __future__ import annotations

import gzip
import json

from research_experiment import (
    ExperimentCapabilities,
    ExperimentCapability,
    ExperimentDefinition,
    ExperimentMode,
    ExperimentOutcome,
    ExperimentProtocol,
    ExperimentResult,
    ExperimentStage,
    ResearchExperiment,
)


PREDECESSOR_ID = "20260924_S008_EX67"
PREDECESSOR_RECEIPT = "b5677eb58d844166dd8e255a4afa04e9c07569ab3b613b54a360da6af784056b"
EXPECTED_DECISION = "PROCEED_TO_UPSIDE_PARTICIPATION_INFORMATION_AUDIT"


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260924_S008_EX68",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Can EX67 evidence be resumed into a valid archive?",
            hypothesis="The archive failure is isolated from the receipted research facts.",
            falsification_conditions=(
                "The predecessor receipt cannot be restored",
                "The predecessor facts differ from the frozen decision",
                "The successor archive fails platform validation",
            ),
            development_cutoff=__import__("datetime").date(2024, 12, 31),
            random_seed=2026096801,
            allowed_datasets=("etf.ohlcv",),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.MECHANISM_DISCOVERY,
                first_principles=(
                    "A technical archive failure must not be interpreted as financial evidence",
                    "A successor may proceed only from an exact platform receipt",
                ),
                information_paths=(
                    "EX67 execution envelope -> verified ExperimentInput -> EX68 receipt",
                ),
                stage_objectives=("Repair only the experiment archive boundary",),
                observation_metrics=("predecessor receipt identity", "archive validation"),
                methodology=(
                    "Load the exact predecessor receipt and preserve its decision facts without recomputation",
                ),
                predecessor_experiment_ids=(PREDECESSOR_ID,),
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def execute(self, context) -> ExperimentResult:
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        predecessor = context.predecessors[PREDECESSOR_ID]
        if predecessor.receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX67 receipt identity differs")
        facts = dict(predecessor.facts)
        if facts.get("decision") != EXPECTED_DECISION:
            raise ValueError("EX67 decision differs from the technical successor contract")
        required = {
            "valid_trial_count",
            "return_gate_pass_count",
            "drawdown_gate_pass_count",
            "drawdown_gate_pass_rate",
            "maximum_annualized_return",
            "buyhold_annualized_return",
            "required_annualized_return",
            "best_prior_causal_representative",
            "best_prior_causal_annualized_return",
            "oracle_feasible",
            "main_gap",
        }
        if not required.issubset(facts):
            raise ValueError("EX67 facts are incomplete")

        evidence = {
            "schema_version": 1,
            "experiment_id": self.definition.experiment_id,
            "decision": EXPECTED_DECISION,
            "predecessor_experiment_id": PREDECESSOR_ID,
            "predecessor_receipt_sha256": predecessor.receipt_sha256,
            "inherited_facts": facts,
            "archive_contract": {
                "symbol": "518880.SH",
                "development_cutoff": "2024-12-31",
                "credential_id": "SGC-S008-001",
            },
            "recomputed_financial_evidence": False,
            "reads_sealed_validation": False,
        }
        payload = (
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        path = context.workspace.path("successor_evidence.json.gz")
        path.write_bytes(gzip.compress(payload, compresslevel=9, mtime=0))
        artifact = context.workspace.register_artifact(
            "successor_evidence.json.gz", "technical-successor-evidence"
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={
                "decision": EXPECTED_DECISION,
                "predecessor_receipt_sha256": predecessor.receipt_sha256,
                **{key: facts[key] for key in sorted(required)},
            },
            diagnostics={
                "recomputed_financial_evidence": False,
                "reads_sealed_validation": False,
                "search_started": False,
                "candidate_created": False,
                "platform_mutated": False,
            },
            artifacts=(artifact,),
        )
