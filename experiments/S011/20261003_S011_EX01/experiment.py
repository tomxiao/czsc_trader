from datetime import date
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json
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
    ExperimentPrecheckResult,
    ExperimentPreflightCheck,
    ExperimentPreflightStatus,
    ExperimentResult,
    ExperimentOutcome,
)
from strategy_evaluator import (
    AssessmentCandidate,
    AssessmentEvidence,
    PerturbationLink,
    SelfCheckProtocol,
    CandidateAssessmentRequest,
    FamilyReturnEvidence,
    DiagnosticStatus,
    assess_candidates,
    CandidateComparisonRequest,
    ResearchTargets,
    ComparisonPolicy,
    compare_candidates,
)
from .family_statistics import expanded_statistics

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
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
            research_question="Are all stage-four diagnostics and rankings complete for the 36 current handoff centers?",
            hypothesis="648 authenticated account coordinates support complete current-contract assessment.",
            falsification_conditions=(
                "Missing coordinate or incompatible evidence",
                "Identity, target or ranking-policy drift",
            ),
            allowed_datasets=("etf.ohlcv", "etf.unadjusted_daily", "calendar.trading_sessions"),
            dependencies=tuple(ExperimentDependency(**x) for x in INPUTS["dependencies"]),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            protocol=ExperimentProtocol(
                ExperimentStage.ROBUSTNESS,
                ("Known development sample; full handoff scope",),
                (
                    "Authenticated TDR evidence, public SE diagnostics and ranking, pinned historical numeric ledgers",
                ),
                ("36 centers, 576 fixed joint neighbors, 36 cost-stress accounts",),
                ("All five self-checks, ranking and uncertainty; preserve adverse evidence",),
                ("No adaptive search, no stage-five execution",),
                tuple(INPUTS["predecessors"]),
            ),
        )

    def synthetic_precheck(self):
        import pandas as pd

        empty = pd.DataFrame(columns=["fees", "quantity", "price"])
        assert np.allclose(
            empty.fees.to_numpy(float),
            empty.quantity.to_numpy(float) * empty.price.to_numpy(float) * 0.001,
            rtol=0,
            atol=1e-8,
        )
        for rel, digest in INPUTS["source_evidence"].items():
            assert sha256((REPO / rel).read_bytes()).hexdigest() == digest, rel
        for stage, expected in [("centers", 35), ("recovery", 420)]:
            batch = read(ROOT / f"{stage}_batch_result.json")
            assert not batch["errors"] and len(batch["trials"]) == expected
            assert all(t["state"] == "COMPLETE" for t in batch["trials"])
        original = read(ROOT / "neighbors_batch_result.json")
        successful = {x["candidate"] for x in original["trials"] if x["state"] == "COMPLETE"}
        restored = {x["candidate"] for x in read(ROOT / "recovery_batch_result.json")["trials"]}
        assert len(successful) == 140 and len(original["errors"]) == 6
        assert not successful & restored
        assert successful | restored == {
            x["candidate_id"] for x in read(ROOT / "neighborhood_mapping.json")
        }
        assert len(INPUTS["centers"]) == 36 and len(INPUTS["extensions"]) == 512
        return ExperimentPrecheckResult(
            (
                ExperimentPreflightCheck(
                    "COMPLETE_FIXED_INPUTS",
                    ExperimentPreflightStatus.PASS,
                    "All fixed slots completed by authenticated successor runs; initial technical failures retained",
                ),
            ),
            ExperimentResult(ExperimentOutcome.PASS, {"centers": 36, "neighbors": 576}, {}),
        )

    def execute(self, context):
        evidence = []
        summaries = []
        relations = []
        for ex in INPUTS["evaluation_experiments"]:
            source = ROOT.parent / ex / "artifacts"
            summaries.extend(read(source / "summaries.json"))
            relations.extend(read(source / "derivations.json"))
            for p in sorted((source / "assessment").glob("*.json")):
                evidence.extend(AssessmentEvidence.from_dict(x) for x in read(p))
        assert len(evidence) == 648 and len(relations) == 576
        centers = tuple(
            AssessmentCandidate("S011-" + x["candidate_id"], x["content_sha256"])
            for x in INPUTS["centers"]
        )
        standard = [x for x in evidence if x.scenario_id == "standard"]
        assert len(standard) == 612
        links = tuple(
            PerturbationLink(x.parent, x.candidate, 1.0, x.derivation_sha256)
            for x in standard
            if x.parent is not None
        )
        assert len(links) == 576 and set(
            Counter(x.parent.candidate_id for x in links).values()
        ) == {16}
        matrix = np.column_stack(
            [
                np.array([a.equity for a in x.account])
                / np.r_[x.initial_cash, [a.equity for a in x.account[:-1]]]
                - 1
                for x in standard
            ]
        )
        selected = next(c for c in centers if c.candidate_id == "S011-C0621")
        family = FamilyReturnEvidence(
            tuple(x.candidate for x in standard),
            tuple(a.session for a in standard[0].account),
            tuple(tuple(float(v) for v in row) for row in matrix),
            selected,
            612,
            (
                "Current diagnostic cohort only; full historical search correction supplied separately.",
                "Includes repeated economic behaviors; current replay does not add independent samples.",
            ),
        )
        policy = read(ROOT / "evaluation_policy.json")
        request = CandidateAssessmentRequest(
            centers,
            SelfCheckProtocol.from_dict(policy["selfcheck"]),
            links,
            tuple(evidence),
            family_returns=family,
        )
        panel = assess_candidates(request)
        assert len(panel.rows) == 36
        missing = [
            (r.candidate.candidate_id, d.metric.value, d.reason)
            for r in panel.rows
            for d in r.diagnostics
            if d.status is not DiagnosticStatus.AVAILABLE
        ]
        assert not missing, missing
        assert all(not r.coverage_gaps for r in panel.rows)
        assert all(x.status is DiagnosticStatus.AVAILABLE for x in panel.family_diagnostics)
        comparison_request = CandidateComparisonRequest(
            centers,
            ResearchTargets.from_dict(policy["targets"]),
            panel,
            ComparisonPolicy.from_dict(policy["comparison_policy"]),
        )
        comparison = compare_candidates(comparison_request)
        assert all(x.pareto_layer is not None for x in comparison.rows)
        artifacts = []

        def save(name, value):
            context.workspace.path(name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            artifacts.append(context.workspace.register_artifact(name, "stage_four_evidence"))

        print("Current cohort assessment and ranking complete", flush=True)
        expanded = expanded_statistics(
            REPO, REPO / INPUTS["historical_audit"], standard, INPUTS["extensions"]
        )
        coverage = dict(
            status="COMPLETE",
            centers=36,
            joint_points=576,
            joint_per_center=dict(Counter(x.parent.candidate_id for x in links)),
            standard_accounts=612,
            stress_accounts=36,
            unique_coordinates=648,
            missing_diagnostics=missing,
            layers=max(x.pareto_layer for x in comparison.rows),
            new_parameter_proposals=0,
        )
        current_by_id = {x.candidate_id: x for x in centers}
        goals = {
            c: sum(
                x["all_targets_met"]
                for x in summaries
                if x["candidate_id"]
                in {link.child.candidate_id for link in links if link.parent == current_by_id[c]}
            )
            for c in current_by_id
        }
        for name, value in [
            ("assessment_request.json", request.to_dict()),
            ("assessment_panel.json", panel.to_dict()),
            ("comparison_request.json", comparison_request.to_dict()),
            ("comparison.json", comparison.to_dict()),
            ("coverage_summary.json", coverage),
            ("all_summaries.json", summaries),
            ("derivation_map.json", relations),
            ("joint_goal_coverage.json", goals),
            ("expanded_family_statistics.json", expanded),
        ]:
            save(name, value)
        return ExperimentResult(
            ExperimentOutcome.PASS,
            coverage,
            {"development_only": True, "independent_samples": 0, "stage_five_started": False},
            tuple(artifacts),
        )
