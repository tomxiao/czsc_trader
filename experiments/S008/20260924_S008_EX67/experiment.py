from __future__ import annotations

import csv
import gzip
from hashlib import sha256
import json
from pathlib import Path

from research_experiment import (
    ExperimentArtifact,
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


INPUTS = {
    "EX42_ORACLE_CONCLUSION": (
        "experiments/S008/20260923_S008_EX42/04_conclusion.md",
        "67546014dfa6e64e33cf6d928a6c151633a8f8376592d556176840ad117be4a9",
    ),
    "EX48_ORACLE_GAP": (
        "experiments/S008/20260923_S008_EX48/artifacts/oracle_gap_attribution.json",
        "1e7fb83f05f445b8867f8fd75a36607081eeb0a88465e137acc7930bc4c43cb4",
    ),
    "EX48_REPRESENTATIVES": (
        "experiments/S008/20260923_S008_EX48/artifacts/representative_selection.csv",
        "1d985ae13704017cbf4028d2053eeea4f2f91df8a2f5d88e5b976fbfe0172136",
    ),
    "EX66_SEARCH_EVIDENCE": (
        "experiments/S008/20260923_S008_EX66/artifacts/search_evidence.json",
        "affa05e4bec344e164efe024448c07506df49e5ed093976adf43d53bca35425c",
    ),
    "EX66_TRIAL_LEDGER": (
        "experiments/S008/20260923_S008_EX66/artifacts/search_trial_ledger.csv.gz",
        "870c0fd7655aa45e45a90c82357017e7ee28ddfc6ee3c765e411605bc49c6ae8",
    ),
}


def _verified_path(repository_root: Path, key: str) -> Path:
    relative, expected = INPUTS[key]
    target = repository_root / relative
    if not target.is_file():
        raise FileNotFoundError(f"declared legacy evidence is missing: {relative}")
    actual = sha256(target.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"declared legacy evidence hash differs: {relative}")
    return target


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260924_S008_EX67",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question=(
                "Does archived evidence support an upside-participation information audit?"
            ),
            hypothesis=(
                "The dominant gap is missed upside rather than insufficient drawdown control."
            ),
            falsification_conditions=(
                "EX66 contains a return-gate pass",
                "Fewer than 80 percent of EX66 valid trials pass the drawdown gate",
                "EX48 does not diagnose an upside-capture deficit",
                "EX42 does not establish oracle feasibility",
            ),
            development_cutoff=__import__("datetime").date(2024, 12, 31),
            random_seed=2026096701,
            allowed_datasets=("etf.ohlcv",),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.MECHANISM_DISCOVERY,
                first_principles=(
                    "A long-only timing strategy can exceed BuyHold only by avoiding losses without missing persistent rallies",
                    "Repeated defensive success with weak returns indicates an information-timing deficit",
                ),
                information_paths=(
                    "Archived trial ledger -> gate decomposition -> dominant gap",
                    "Oracle feasibility -> causal representative gap -> next falsifiable question",
                ),
                stage_objectives=(
                    "Choose between upside information audit, more risk filtering, or stopping",
                ),
                observation_metrics=(
                    "return gate pass count",
                    "drawdown gate pass rate",
                    "maximum causal annualized return",
                    "oracle feasibility",
                ),
                methodology=(
                    "Verify fixed legacy evidence hashes and apply the preregistered deterministic decision rule",
                ),
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def execute(self, context) -> ExperimentResult:
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        repository_root = Path(__file__).resolve().parents[3]
        oracle_text = _verified_path(repository_root, "EX42_ORACLE_CONCLUSION").read_text(
            encoding="utf-8"
        )
        gap = json.loads(
            _verified_path(repository_root, "EX48_ORACLE_GAP").read_text(encoding="utf-8")
        )
        with _verified_path(repository_root, "EX48_REPRESENTATIVES").open(
            encoding="utf-8", newline=""
        ) as stream:
            representatives = list(csv.DictReader(stream))
        search = json.loads(
            _verified_path(repository_root, "EX66_SEARCH_EVIDENCE").read_text(
                encoding="utf-8"
            )
        )
        ledger_path = _verified_path(repository_root, "EX66_TRIAL_LEDGER")

        valid: list[dict[str, float]] = []
        with gzip.open(ledger_path, mode="rt", encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if row["trial_state"] != "COMPLETE" or not row["primary_strategy_metrics_json"]:
                    continue
                metrics = json.loads(row["primary_strategy_metrics_json"])
                valid.append(
                    {
                        "annualized_return": float(metrics["annualized_return"]),
                        "maximum_drawdown_magnitude": float(
                            metrics["maximum_drawdown_magnitude"]
                        ),
                    }
                )
        if not valid:
            raise ValueError("EX66 contains no valid complete trials")

        buyhold_return = float(search["buyhold_primary"]["annualized_return"])
        buyhold_mdd = float(search["buyhold_primary"]["maximum_drawdown_magnitude"])
        target_return = buyhold_return * 1.5
        return_passes = sum(item["annualized_return"] >= target_return for item in valid)
        drawdown_passes = sum(
            item["maximum_drawdown_magnitude"] < buyhold_mdd for item in valid
        )
        max_return = max(item["annualized_return"] for item in valid)
        min_mdd = min(item["maximum_drawdown_magnitude"] for item in valid)
        max_return_with_drawdown_pass = max(
            item["annualized_return"]
            for item in valid
            if item["maximum_drawdown_magnitude"] < buyhold_mdd
        )
        best_representative = max(
            representatives, key=lambda item: float(item["annualized_return"])
        )
        oracle_feasible = "TARGET_FEASIBLE_UNDER_ORACLE" in oracle_text
        drawdown_pass_rate = drawdown_passes / len(valid)
        proceed = (
            return_passes == 0
            and drawdown_pass_rate >= 0.8
            and max_return < buyhold_return
            and gap["main_diagnosis"] == "UPSIDE_CAPTURE_DEFICIT"
            and oracle_feasible
        )
        decision = (
            "PROCEED_TO_UPSIDE_PARTICIPATION_INFORMATION_AUDIT"
            if proceed
            else "STOP_FOR_STAGE_OBJECTIVE_REVIEW"
        )
        review = {
            "schema_version": 1,
            "experiment_id": self.definition.experiment_id,
            "decision": decision,
            "input_sha256": {key: value[1] for key, value in INPUTS.items()},
            "hard_target": {
                "buyhold_annualized_return": buyhold_return,
                "required_annualized_return": target_return,
                "buyhold_maximum_drawdown_magnitude": buyhold_mdd,
            },
            "ex66": {
                "valid_trial_count": len(valid),
                "return_gate_pass_count": return_passes,
                "drawdown_gate_pass_count": drawdown_passes,
                "drawdown_gate_pass_rate": drawdown_pass_rate,
                "maximum_annualized_return": max_return,
                "minimum_maximum_drawdown_magnitude": min_mdd,
                "maximum_return_with_drawdown_pass": max_return_with_drawdown_pass,
            },
            "prior_causal_representative": {
                "name": best_representative["representative"],
                "annualized_return": float(best_representative["annualized_return"]),
                "maximum_drawdown_magnitude": float(
                    best_representative["maximum_drawdown_magnitude"]
                ),
            },
            "oracle": {
                "feasible": oracle_feasible,
                "main_diagnosis": gap["main_diagnosis"],
                "exposure_ratio": gap["oracle_exposure_ratio"],
                "positive_log_return_capture_ratio": gap[
                    "oracle_positive_log_return_capture_ratio"
                ],
                "negative_log_return_avoidance_ratio": gap[
                    "oracle_negative_log_return_avoidance_ratio"
                ],
            },
            "competing_hypotheses": {
                "H1": "Entry and re-entry confirmation lag misses the start of persistent gold rallies",
                "H2": "Existing macro, precious-metal and risk gates are defensive lagging filters",
                "H3": "No stable learnable rule exists under current information and execution constraints",
                "H0": "Oracle advantage is concentrated in a few development-period rallies",
            },
            "next_stage_scope": {
                "allowed": [
                    "audit leading upside-participation information available before T close",
                    "compare discovery and confirmation periods without selecting a strategy",
                    "request Tushare or DFLS capability only after an information-path rationale",
                ],
                "forbidden": [
                    "expand EX66 parameters",
                    "create a strategy prototype",
                    "start parameter search",
                    "read sealed validation",
                    "create a candidate",
                ],
            },
            "legacy_evidence_bridge": (
                "REX verified fixed archive hashes because EX42, EX48 and EX66 predate execution envelopes"
            ),
        }
        target = context.workspace.path("gap_review.json")
        target.write_text(
            json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        artifact: ExperimentArtifact = context.workspace.register_artifact(
            "gap_review.json", "stage-gap-review"
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if proceed else ExperimentOutcome.INCONCLUSIVE,
            facts={
                "decision": decision,
                "valid_trial_count": len(valid),
                "return_gate_pass_count": return_passes,
                "drawdown_gate_pass_count": drawdown_passes,
                "drawdown_gate_pass_rate": drawdown_pass_rate,
                "maximum_annualized_return": max_return,
                "buyhold_annualized_return": buyhold_return,
                "required_annualized_return": target_return,
                "best_prior_causal_representative": best_representative["representative"],
                "best_prior_causal_annualized_return": float(
                    best_representative["annualized_return"]
                ),
                "oracle_feasible": oracle_feasible,
                "main_gap": gap["main_diagnosis"],
            },
            diagnostics={
                "reads_sealed_validation": False,
                "search_started": False,
                "candidate_created": False,
                "platform_mutated": False,
            },
            artifacts=(artifact,),
        )
