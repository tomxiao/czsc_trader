"""Aggregate authenticated fixed-neighborhood and cost evidence using public SE APIs."""

from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
from research_experiment import (
    ResearchExperiment,
    ExperimentDefinition,
    ExperimentMode,
    ExperimentDataScope,
    ExperimentStage,
    ExperimentProtocol,
    ExperimentDependency,
    ExperimentCapabilities,
    ExperimentResult,
    ExperimentOutcome,
    ExperimentPrecheckResult,
    ExperimentPreflightCheck,
    ExperimentPreflightStatus,
)
from strategy_evaluator import (
    AssessmentEvidence,
    AssessmentCandidate,
    PerturbationLink,
    SelfCheckProtocol,
    QuantileMethod,
    CandidateAssessmentRequest,
    assess_candidates,
)
from strategy_runtime import canonical_sha256

ROOT = Path(__file__).resolve().parent
INPUTS = json.loads((ROOT / "inputs.json").read_text(encoding="utf-8"))


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2,
            experiment_id=ROOT.name,
            strategy_id="S011",
            mode=ExperimentMode.FORMAL,
            data_scope=ExperimentDataScope.DEVELOPMENT,
            development_cutoff=date(2026, 9, 28),
            random_seed=20261002,
            subjects=("159326.SZ",),
            research_question="What do the completed fixed diagnostics imply for C0621?",
            hypothesis="Local and cost sensitivity can be quantified under current identities.",
            falsification_conditions=("Incomplete or mismatched evidence",),
            allowed_datasets=("etf.ohlcv", "etf.unadjusted_daily", "calendar.trading_sessions"),
            dependencies=tuple(ExperimentDependency(**x) for x in INPUTS["dependencies"]),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            protocol=ExperimentProtocol(
                ExperimentStage.ROBUSTNESS,
                ("Previously selected candidate and development sample",),
                ("Read authenticated predecessor artifacts; public SE assessment",),
                ("16 fixed joint points and center 10bp/20bp accounts",),
                ("Quantile degradation, cost loss, goal coverage",),
                ("No new account execution or candidate selection",),
                tuple(INPUTS["predecessors"]),
            ),
        )

    def synthetic_precheck(self):
        batch = read(ROOT / "batch_result.json")
        assert not batch["errors"] and len(batch["trials"]) == 16
        assert all(x["state"] == "COMPLETE" for x in batch["trials"])
        assert len({x["pid"] for x in batch["completed"]}) == 8
        assert read(ROOT / "parallel_precheck.json")["status"] == "PASS"
        assert (
            sha256((ROOT / "perturbation_protocol.json").read_bytes()).hexdigest()
            == INPUTS["perturbation_protocol_sha256"]
        )
        for name, digest in INPUTS["source_evidence"].items():
            assert sha256((ROOT / name).read_bytes()).hexdigest() == digest
        return ExperimentPrecheckResult(
            (
                ExperimentPreflightCheck(
                    "FIXED_COVERAGE",
                    ExperimentPreflightStatus.PASS,
                    "16 complete fixed trials and 8 isolated process owners",
                ),
            ),
            ExperimentResult(ExperimentOutcome.PASS, {"trials": 16}, {}),
        )

    def execute(self, context):
        evidence, relations, summaries = [], [], []
        for ex in INPUTS["predecessors"]:
            source = ROOT.parent / ex / "artifacts"
            summaries.extend(read(source / "summaries.json"))
            relations.extend(read(source / "derivations.json"))
            for path in sorted((source / "assessment").glob("*.json")):
                evidence.extend(AssessmentEvidence.from_dict(v) for v in read(path))
        assert len(evidence) == 18 and len(relations) == 16
        center = AssessmentCandidate("S011-C0621", INPUTS["content_sha256"])
        links = tuple(
            PerturbationLink(
                center,
                AssessmentCandidate(
                    "S011-" + r["candidate_id"], r["derivation"]["child_content_sha256"]
                ),
                1.0,
                canonical_sha256(r["derivation"]),
            )
            for r in relations
        )
        protocol = SelfCheckProtocol(
            "S011-c0621-current-selfcheck-v1",
            "full",
            "standard",
            "fee_20bp",
            60,
            1,
            QuantileMethod.LINEAR,
            16,
            1,
            5000,
            20,
            20261001,
            1e-6,
            10,
        )
        request = CandidateAssessmentRequest((center,), protocol, links, tuple(evidence))
        panel = assess_candidates(request)
        assert len(panel.rows) == 1
        standard = next(
            x
            for x in summaries
            if x["candidate_id"] == "S011-C0621" and x["scenario"] == "standard"
        )
        stress = next(
            x
            for x in summaries
            if x["candidate_id"] == "S011-C0621" and x["scenario"] == "fee_20bp"
        )
        neighbors = [x for x in summaries if x["candidate_id"] != "S011-C0621"]
        annual = np.array([x["cagr"] for x in neighbors])
        drawdown = np.array([abs(x["metrics"]["max_drawdown"]) for x in neighbors])
        summary = dict(
            center=standard,
            stress=stress,
            neighbors=neighbors,
            neighbor_pass_count=sum(x["all_targets_met"] for x in neighbors),
            neighbor_count=16,
            neighbor_annual_min=float(annual.min()),
            neighbor_annual_median=float(np.median(annual)),
            neighbor_annual_max=float(annual.max()),
            neighbor_annual_q10=float(np.quantile(annual, 0.1)),
            annual_degradation=max(0, standard["cagr"] - float(np.quantile(annual, 0.1))),
            neighbor_drawdown_q90=float(np.quantile(drawdown, 0.9)),
            drawdown_degradation=max(
                0, float(np.quantile(drawdown, 0.9)) - abs(standard["metrics"]["max_drawdown"])
            ),
            cost_annual_loss=standard["cagr"] - stress["cagr"],
            neighbor_failed_targets={
                k: sum(not x["targets"][k] for x in neighbors) for k in standard["targets"]
            },
            limitations=[
                "Seen development sample and historical selection bias; no independent validation",
                "Historical adjusted-data publication timing remains unverified",
                "Fixed 16-point joint design is not an exhaustive neighborhood or independent sample",
                "Full search-family PBO and DSR are not recomputed",
                "No full stage-four delivery, stage-five approval, freezing or deployment",
            ],
        )
        metrics = {x.metric.value: x for x in panel.rows[0].diagnostics}
        for key, metric in [
            ("annual_degradation", "PARAMETER_RETURN_DEGRADATION"),
            ("drawdown_degradation", "PARAMETER_DRAWDOWN_DEGRADATION"),
            ("cost_annual_loss", "STRESS_ANNUAL_LOSS"),
        ]:
            assert metrics[metric].value is not None
            assert abs(summary[key] - metrics[metric].value) < 1e-12
        artifacts = []
        for name, value in [
            ("assessment_request.json", request.to_dict()),
            ("assessment_panel.json", panel.to_dict()),
            ("selfcheck_summary.json", summary),
            ("derivation_map.json", relations),
        ]:
            context.workspace.path(name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            artifacts.append(context.workspace.register_artifact(name, "selfcheck_aggregation"))
        return ExperimentResult(
            ExperimentOutcome.PASS,
            {
                "diagnostic_accounts": 18,
                "neighbor_pass_count": summary["neighbor_pass_count"],
                "neighbor_count": 16,
                "cost_annual_loss": summary["cost_annual_loss"],
            },
            {"development_only": True, "new_economic_gates": False},
            tuple(artifacts),
        )
