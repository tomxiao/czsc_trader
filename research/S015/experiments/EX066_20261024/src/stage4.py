"""Prospective bounded local applicability evaluation; unchanged S015 candidate sources."""

# ruff: noqa: E402
import os

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
from datetime import date
from dataclasses import replace
import importlib.util
import json
import pickle
from pathlib import Path
import pandas as pd
from czsc_trader.application import (
    RepositoryContext,
    create_research_context,
    load_candidate,
    publish_evidence,
    publish_evidence_many,
    open_research_execution,
)
from czsc_trader.research_tools import (
    ResearchBatchRef,
    ExperimentRef,
    ExecutionResources,
    EvidenceRef,
    MaterialEvidenceWrite,
    EvaluationRequest,
    EvaluationWindow,
    EvaluationCost,
    EvaluationBenchmark,
    LimitBuyHold,
    EvaluationEvidenceWrite,
    ParameterEvaluationPlan,
    EvaluationLineage,
)
from czsc_trader.research_tools import delivery as d
from strategy_manager import (
    CandidateKey,
    CandidateDerivation,
    CandidateDerivationKind,
    CandidateEvidence,
)
from strategy_runtime import StrategyRuntime, StrategyCandidate
from strategy_evaluator import research_models as m
from strategy_evaluator.parameter_neighborhood import (
    ParameterAxis,
    RealDomain,
    IntegerDomain,
    BoundedLocalStep,
    RelativeChangeLimit,
    ParameterNeighborhoodSpace,
    ParameterNeighborhoodProtocol,
    ParameterNeighborhoodRequest,
    build_parameter_neighborhood_design,
)

ROOT = Path(__file__).resolve().parents[5]
EX = ExperimentRef("S015", "EX066_20261024")
HOME = EX.resolve(ROOT)
OUT = HOME / "others"
BATCH = ResearchBatchRef("S015")
VERSION = "S015-EX066-stage4-bounded-applicability-v2"
CENTERS = (
    "C5806",
    "C5901",
    "C5902",
    "C6015",
    "C6016",
    "C6017",
    "C6018",
    "C6101",
    "C6104",
    "C6105",
    "C6116",
    "C6117",
    "C6201",
    "C6202",
    "C6203",
    "C6206",
)
CACHE = ROOT / ".tmp/s015_ex066"


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def ctx(workers=8):
    return create_research_context(
        RepositoryContext.discover(ROOT), BATCH, resources=ExecutionResources(workers, 1, 13)
    )


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def material(context, path, name=None):
    mime = {
        ".json": "application/json",
        ".py": "text/x-python",
        ".md": "text/markdown",
        ".csv": "text/csv",
    }
    return publish_evidence(
        context,
        MaterialEvidenceWrite(
            EX, name or path.stem, path.read_bytes(), mime[path.suffix], path.suffix[1:]
        ),
    )


def predecessor(stage, revision, expected):
    folder = ROOT / f"research/S015/assets/deliveries/{stage}/{revision}"
    receipt = d.DeliveryReceipt.from_dict(read(folder / "receipt.json"))
    assert receipt.reference.content_sha256 == expected
    return receipt.reference, read(folder / "delivery.json")["content"]["payload"]


def plain(value):
    from collections.abc import Mapping

    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def request(context, candidate):
    return context.evaluation.prepare(
        EvaluationRequest(
            ROOT,
            EX.experiment_id,
            candidate,
            {
                "candidate_id": candidate.reference_id,
                "source_files": list(candidate.payload["runtime"]["source_files"]),
                "implementation_sha256": candidate.payload["runtime"]["source_sha256"],
            },
            "159326.SZ",
            "etf",
            (EvaluationWindow("full", date(2025, 1, 2), date(2026, 10, 21)),),
            date(2026, 10, 21),
            100000.0,
            (EvaluationCost("standard", 0.001, "FORMAL"),),
            benchmark=EvaluationBenchmark(LimitBuyHold(100, 0.01, 0.001, 0.1, 1000000)),
        )
    )


def prepare():
    assert not (OUT / "plan_refs.json").exists()
    context = ctx(1)
    mandate = read(OUT / "mandate_reference.json")
    cref, payload = predecessor(
        "CANDIDATES", 7, "b614f360e2d5448e5ad81a5c3f47b6f2271ddfff5b8b7639f3337bc8bedeb4e1"
    )
    assert {x["candidate_id"] for x in payload["handoff"]} == set(CENTERS)
    rows = read(HOME.parent / "EX063_20261024/others/centers.json")
    save(OUT / "centers.json", rows)
    mapping = {
        "version": VERSION,
        "payload_root": "parameters",
        "axes": {
            "allocation": {
                "unit": "fraction",
                "relative_limit": 0.05,
                "domain": "(0,1]",
                "meaning": "entry-cycle cash allocation",
            },
            "lookback": {
                "unit": "sessions",
                "minimum_legal_step": 1,
                "relative_limit": 0.05,
                "domain": "integer[2,10]",
            },
            "hold": {
                "unit": "sessions",
                "minimum_legal_step": 1,
                "relative_limit": 0.05,
                "domain": "integer[1,30]",
            },
            "confirmation": {
                "unit": "sessions",
                "minimum_legal_step": 1,
                "relative_limit": 0.05,
                "domain": "integer[1,5]",
                "active": "confirmed_guard, including joint activation",
            },
        },
        "fixed": "all undeclared payload leaves and original source; mode/exit/rearm are structure; inactive concentration/failure_buffer/max_hold remain fixed",
        "comparison": "Use exact design comparison_sha256; no forced pooling across boundary shapes or axes.",
    }
    feasibility = {
        "version": VERSION,
        "constraints": ["0 < allocation <= 1", "hold <= original max_hold when max_hold present"],
        "method": "Complete Cartesian product includes all centers, excludes only overall center and declared illegal values; no clipping, rounding, sampling or behavior-based deduplication.",
    }
    save(HOME / "protocols/mapping.json", mapping)
    save(HOME / "protocols/feasibility.json", feasibility)
    mapref = material(context, HOME / "protocols/mapping.json")
    feasref = material(context, HOME / "protocols/feasibility.json")
    CACHE.mkdir(parents=True, exist_ok=True)
    # Local transport only; canonical evidence remains the public JSON plans/accounts.
    from czsc_trader.research_tools._evaluation_workers import pack

    records = []
    child_number = 8000
    for cid in CENTERS:
        row = next(x for x in rows if x["candidate_id"] == cid)
        candidate = load_candidate(RepositoryContext.discover(ROOT), CandidateKey("S015", cid))
        identity = StrategyRuntime().identify(candidate, dependencies=())
        assert identity.content_sha256 == row["identity"]["content_sha256"]
        parameters = plain(candidate.payload["parameters"])
        assert parameters == row["parameters"]
        center = request(context, candidate)
        axes = [
            ParameterAxis(
                "allocation",
                parameters["allocation"],
                RealDomain(0.0, 1.0, False, True),
                BoundedLocalStep(RelativeChangeLimit(0.05)),
                ("allocation",),
                "fraction",
            ),
            ParameterAxis(
                "lookback",
                parameters["lookback"],
                IntegerDomain(2, 10),
                BoundedLocalStep(RelativeChangeLimit(0.05)),
                ("lookback",),
                "sessions",
            ),
            ParameterAxis(
                "hold",
                parameters["hold"],
                IntegerDomain(1, 30),
                BoundedLocalStep(RelativeChangeLimit(0.05)),
                ("hold",),
                "sessions",
            ),
        ]
        if parameters["exit_mode"] == "confirmed_guard":
            axes.append(
                ParameterAxis(
                    "confirmation",
                    parameters["confirmation"],
                    IntegerDomain(1, 5),
                    BoundedLocalStep(RelativeChangeLimit(0.05)),
                    ("confirmation",),
                    "sessions",
                )
            )
        space = ParameterNeighborhoodSpace(tuple(axes), mapref.sha256, feasref.sha256)
        design = build_parameter_neighborhood_design(
            ParameterNeighborhoodRequest(
                m.AssessmentCandidate(candidate.reference_id, identity.content_sha256),
                ParameterNeighborhoodProtocol(),
                space,
            ),
            feasibility=lambda values: (
                {x.name: x.value for x in values}["hold"] <= parameters.get("max_hold", 30)
            ),
        ).design
        assert design is not None
        children = []
        for point in design.points:
            child = StrategyCandidate(
                "S015",
                f"C{child_number:04}",
                {
                    **plain(candidate.payload),
                    "parameters": {**parameters, **{x.name: x.value for x in point.values}},
                },
                candidate.source_root,
            )
            child_number += 1
            children.append(
                context.evaluation.prepare(
                    replace(
                        center,
                        strategy=child,
                        runtime_binding={
                            **center.runtime_binding,
                            "candidate_id": child.reference_id,
                        },
                        input_bindings={},
                    )
                )
            )
        plan = ParameterEvaluationPlan.create(
            design,
            center,
            tuple(children),
            mapping_evidence=mapref,
            feasibility_evidence=feasref,
            dataflows=context.data,
        )
        path = HOME / f"protocols/plans/{cid}.json"
        save(path, plan.to_dict())
        planref = material(context, path, "plan_" + cid)
        bound = []
        for index, child in enumerate(children):
            derivation = CandidateDerivation(
                CandidateKey("S015", cid),
                identity.content_sha256,
                CandidateKey("S015", child.strategy.candidate_id),
                plan.children[index].candidate.content_sha256,
                CandidateDerivationKind.PARAMETERS,
                {x.name: x.value for x in design.points[index].values},
                design.protocol.sha256,
                CandidateEvidence(planref.repository_path, planref.sha256),
            )
            bound.append(
                replace(
                    child,
                    lineage=EvaluationLineage(
                        derivation, plan.bind_point(planref, index, repository_root=ROOT)
                    ),
                )
            )
        (CACHE / f"{cid}.pkl").write_bytes(pack((center, tuple(bound))))
        records.append(
            {
                "candidate_id": cid,
                "design": design.to_dict(),
                "plan": plan.to_dict(),
                "plan_reference": planref.to_dict(),
            }
        )
        print("PLAN", cid, design.point_count, flush=True)
    assert child_number == 8024
    save(OUT / "plan_refs.json", records)
    protocol = {
        "version": VERSION,
        "authorization": "有意义就好。请继续自主完成阶段四",
        "source_candidates": cref.to_dict(),
        "source_mandate": mandate,
        "centers": list(CENTERS),
        "formal_accounts": {"centers": 16, "neighbors": 24},
        "technical_duplicates": 2,
        "criteria": "All N points valid; joint passes >= ceil(13*N/16); every point drawdown <=25%; preserve original inner economics and all center goals.",
        "data": "434 days 2025-01-02..2026-10-21, fixed original inputs/cutoff/cost/benchmark/capital; original415 gate and16 stress accounts reused, authenticated. No new sample.",
        "selection": "No neighbor promotion; all16 centers tested to completion. Authenticate original176 plus EX065207 full-window sources. Exclude EX065 repeat proposals and known old-content/inactive-field aliases from expanded family; retain original historical columns and disclose their dependence. Fixed stage4 points are not promoted or added to search family.",
        "resources": {"workers": 8, "native_threads": 1, "seed": 13},
        "parameter_policy": "Relative change cap .05, nearest lawful integer step over cap held fixed; continuous allocation endpoints relative to center, no clipping. All active parameters and potentially jointly active confirmation retained in designs. Original economic goals unchanged; prior out-of-cap negatives remain disclosed.",
        "ranking_policy": "Raw Pareto first, preserve original bins and sensitivity variants; research-ranking-v4 floors only for whole-item NOT_APPLICABLE; incomparable actual neighborhood shapes get separate supplemental rankings, no invented global winner.",
        "family_policy": "Expanded family returns use all retained standard434 sources; same seed13, PBO10blocks, bootstrap2000/block10. Report raw/effective-trial DSR and historical coverage gap. No diagnostics become new gates.",
        "limits": "Development sample only; official attribution remains unsupported; no stage5/freeze/PTE/new structural search.",
    }
    save(OUT / "protocol.json", protocol)
    refs = {}
    for path in (
        Path(__file__),
        OUT / "protocol.json",
        OUT / "centers.json",
        OUT / "plan_refs.json",
        HOME / "protocols/mapping.json",
        HOME / "protocols/feasibility.json",
    ):
        refs[path.relative_to(ROOT).as_posix()] = material(context, path).to_dict()
    save(OUT / "protocol_refs.json", refs)
    print("PROTOCOL_FROZEN", len(records), 24, flush=True)


def assert_protocol():
    for path, ref in read(OUT / "protocol_refs.json").items():
        assert EvidenceRef.from_dict(ref).resolve(ROOT).read_bytes() == (ROOT / path).read_bytes()


def run():
    assert_protocol()
    context = ctx()
    tasks = []
    for cid in CENTERS:
        center, children = pickle.loads((CACHE / f"{cid}.pkl").read_bytes())
        tasks.append((None, center))
        tasks.extend((cid, child) for child in children)
    assert len(tasks) == 40
    completed = read(OUT / "results.json")["rows"] if (OUT / "results.json").exists() else []
    completed_ids = {x["candidate_id"] for x in completed}
    for row in completed:
        EvidenceRef.from_dict(row["evidence"]).resolve(ROOT)
    # Serial-versus-pool equivalence before the full run, one fixed center and one confirmation child.
    pilots = (tasks[0], next(x for x in tasks if x[0] == "C5901"))
    if not (OUT / "equivalence.json").exists():
        comparisons = []
        serial_results = []
        for parent, req in pilots:
            serial = ctx(1).evaluation.evaluate(req)
            serialref = publish_evidence(
                context,
                EvaluationEvidenceWrite(EX, "serial_" + req.strategy.candidate_id, req, serial),
            )
            serial_results.append((serial, serialref))
        with open_research_execution(context, experiment=EX) as session:
            # Two tasks in one call force the pool/spawn path (a singleton is synchronous).
            pilot_outcomes = context.evaluation.evaluate_many(
                tuple(req for _, req in pilots), execution=session
            )
            for (parent, req), (serial, serialref), outcome in zip(
                pilots, serial_results, pilot_outcomes, strict=True
            ):
                assert outcome.status.value == "SUCCEEDED", outcome.error
                parallel = outcome.result
                assert parallel.result_hash == serial.result_hash
                for name in ("account_daily", "decisions", "orders", "fills", "trades"):
                    pd.testing.assert_frame_equal(
                        getattr(parallel.runs[0].execution, name),
                        getattr(serial.runs[0].execution, name),
                    )
                comparisons.append(
                    {
                        "candidate_id": req.strategy.candidate_id,
                        "status": "PASS",
                        "evidence": serialref.to_dict(),
                        "result_hash": serial.result_hash,
                        "ledgers": 5,
                    }
                )
                ref = publish_evidence(
                    context, EvaluationEvidenceWrite(EX, req.strategy.candidate_id, req, parallel)
                )
                saved = {
                    "candidate_id": req.strategy.candidate_id,
                    "parent_candidate_id": parent,
                    "request_hash": parallel.request_hash,
                    "result_hash": parallel.result_hash,
                    "evidence": ref.to_dict(),
                }
                if req.strategy.candidate_id in completed_ids:
                    assert (
                        next(x for x in completed if x["candidate_id"] == req.strategy.candidate_id)
                        == saved
                    )
                else:
                    completed.append(saved)
                completed_ids.add(req.strategy.candidate_id)
        save(OUT / "results.json", {"rows": completed})
        save(OUT / "equivalence.json", comparisons)
        print("EQUIVALENCE_PASS", 2, flush=True)
    pending = [x for x in tasks if x[1].strategy.candidate_id not in completed_ids]
    with open_research_execution(context, experiment=EX) as session:
        for start in range(0, len(pending), 8):
            block = pending[start : start + 8]
            outcomes = context.evaluation.evaluate_many(
                tuple(req for _, req in block), execution=session
            )
            assert all(out.status.value == "SUCCEEDED" for out in outcomes), [
                (out.status, str(out.error)) for out in outcomes
            ]
            writes = tuple(
                EvaluationEvidenceWrite(EX, req.strategy.candidate_id, req, out.result)
                for (_, req), out in zip(block, outcomes, strict=True)
            )
            publications = publish_evidence_many(context, writes, execution=session)
            for (parent, req), out, pub in zip(block, outcomes, publications, strict=True):
                assert pub.status.value == "PUBLISHED", pub
                completed.append(
                    {
                        "candidate_id": req.strategy.candidate_id,
                        "parent_candidate_id": parent,
                        "request_hash": out.result.request_hash,
                        "result_hash": out.result.result_hash,
                        "evidence": pub.reference.to_dict(),
                    }
                )
            save(OUT / "results.json", {"rows": completed})
            print("ACCOUNTS", len(completed), 40, flush=True)
    assert len(completed) == 40


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run"))
    {"prepare": prepare, "run": run}[parser.parse_args().action]()
