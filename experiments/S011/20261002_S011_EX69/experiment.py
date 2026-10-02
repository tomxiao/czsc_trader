"""Fixed complete-cohort diagnostics through a process-owned formal context."""

from datetime import date
from hashlib import sha256
import json
from pathlib import Path

from dataflows import Dataset
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
from strategy_runtime import StrategyRuntime, StrategyCandidate, ImplementationDependency
from strategy_manager import (
    CandidateKey,
    CandidateDerivation,
    CandidateDerivationKind,
    CandidateEvidence,
    CandidateRegistrationOrigin,
)
from czsc_trader.application import (
    RepositoryContext,
    load_candidate,
    register_candidate,
    CandidateRegistrationRequest,
)

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
INPUTS = json.loads((ROOT / "inputs.json").read_text(encoding="utf-8"))
DEPS = tuple(ImplementationDependency(**x) for x in INPUTS["dependencies"])
START, END = date(2025, 2, 6), date(2026, 9, 28)


def child(spec, parent):
    payload = json.loads(json.dumps(dict(parent.payload), default=dict))
    payload["parameters"] = spec["parameters"]
    return StrategyCandidate("S011", spec["candidate_id"], payload, parent.source_root)


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2,
            experiment_id=ROOT.name,
            strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            data_scope=ExperimentDataScope.DEVELOPMENT,
            development_cutoff=END,
            random_seed=20261002,
            subjects=("159326.SZ",),
            research_question="Do all existing centers and their fixed neighborhoods retain their current-content account evidence?",
            hypothesis="Current-content diagnostics can quantify local degradation without changing center implementations.",
            falsification_conditions=(
                "Identity or account semantics differ",
                "A declared slot fails without retained evidence",
            ),
            allowed_datasets=tuple(
                x.value
                for x in (
                    Dataset.ETF_OHLCV,
                    Dataset.ETF_UNADJUSTED_DAILY,
                    Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,
                    Dataset.GLOBAL_INDEX_DAILY,
                    Dataset.TRADING_CALENDAR,
                )
            ),
            dependencies=tuple(ExperimentDependency(**x) for x in INPUTS["dependencies"]),
            capabilities=ExperimentCapabilities(creates_candidate=True),
            protocol=ExperimentProtocol(
                ExperimentStage.ROBUSTNESS,
                ("Seen development data, original fixed design",),
                ("DFLS, SRT, TDR managed evaluation, TXE accounts, typed SE evidence",),
                ("Fixed inputs; no adaptive selection or retries",),
                ("Joint parameter and cost sensitivity; diagnostics are not new economic gates",),
                ("Process-owned context, worker=1 and native thread=1",),
                tuple(INPUTS["predecessors"]),
            ),
        )

    def synthetic_precheck(self):
        context = RepositoryContext.discover(REPO)
        runtime = StrategyRuntime()
        for path, digest in INPUTS["source_evidence"].items():
            assert sha256((REPO / path).read_bytes()).hexdigest() == digest
        for spec in INPUTS["centers"]:
            item = load_candidate(context, CandidateKey("S011", spec["candidate_id"]))
            assert (
                runtime.identify(item, dependencies=DEPS).content_sha256 == spec["content_sha256"]
            )
            runtime.describe(item)
        for spec in INPUTS["neighbors"]:
            parent = load_candidate(context, CandidateKey("S011", spec["parent_candidate_id"]))
            assert (
                runtime.identify(parent, dependencies=DEPS).content_sha256
                == spec["parent_content_sha256"]
            )
            item = child(spec, parent)
            assert (
                runtime.identify(item, dependencies=DEPS).content_sha256 == spec["content_sha256"]
            )
            runtime.describe(item)
            previous = load_candidate(context, CandidateKey("S011", spec["previous_candidate_id"]))
            assert dict(item.payload["parameters"]) == dict(previous.payload["parameters"])
        return ExperimentPrecheckResult(
            (
                ExperimentPreflightCheck(
                    "FIXED_INPUTS",
                    ExperimentPreflightStatus.PASS,
                    "Current parent, fixed neighborhood, dependency and predecessor evidence match",
                ),
            ),
            ExperimentResult(ExperimentOutcome.PASS, {"slots": len(INPUTS["neighbors"])}, {}),
        )

    def execute(self, context):
        repository = RepositoryContext.discover(REPO)
        origin = CandidateRegistrationOrigin(
            ROOT.name,
            self.definition.sha256,
            sha256((ROOT / "experiment_binding.json").read_bytes()).hexdigest(),
            CandidateEvidence(
                (ROOT / "preflight.json").relative_to(REPO).as_posix(),
                sha256((ROOT / "preflight.json").read_bytes()).hexdigest(),
            ),
        )
        rows = []
        for spec in INPUTS["neighbors"]:
            key = CandidateKey("S011", spec["candidate_id"])
            path = REPO / f"research/registrations/S011/candidates/{spec['candidate_id']}.json"
            if path.exists():
                item = load_candidate(repository, key)
                assert (
                    StrategyRuntime().identify(item, dependencies=DEPS).content_sha256
                    == spec["content_sha256"]
                )
                rows.append(dict(candidate_id=item.reference_id, status="EXISTING_VERIFIED"))
                continue
            parent = load_candidate(repository, CandidateKey("S011", spec["parent_candidate_id"]))
            item = child(spec, parent)
            proof = REPO / spec["parent_record_path"]
            relation = CandidateDerivation(
                CandidateKey("S011", spec["parent_candidate_id"]),
                spec["parent_content_sha256"],
                key,
                spec["content_sha256"],
                CandidateDerivationKind.PARAMETERS,
                {
                    k: {"before": parent.payload["parameters"][k], "after": v}
                    for k, v in spec["parameters"].items()
                    if v != parent.payload["parameters"][k]
                },
                spec["perturbation_protocol_sha256"],
                CandidateEvidence(
                    proof.relative_to(REPO).as_posix(), sha256(proof.read_bytes()).hexdigest()
                ),
            )
            record = register_candidate(
                repository, CandidateRegistrationRequest(item, origin, DEPS, relation)
            )
            rows.append(
                dict(
                    candidate_id=item.reference_id,
                    status="REGISTERED",
                    record_sha256=record.record_sha256,
                )
            )
        context.workspace.path("registration_summary.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        return ExperimentResult(
            ExperimentOutcome.PASS,
            {"verified_candidates": len(rows)},
            {"market_evaluations": 0, "registration_owner": "single_process"},
            (
                context.workspace.register_artifact(
                    "registration_summary.json", "candidate_registrations"
                ),
            ),
        )
