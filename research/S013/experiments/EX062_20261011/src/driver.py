"""Guarded EX062 public-TDR orchestrator. No financial action without frozen ref."""
# ruff: noqa: E402
from __future__ import annotations

import argparse
import os
import copyreg
import gzip
import json
import pickle
from hashlib import sha256
from dataclasses import replace
import importlib.util
import sys
from pathlib import Path
from types import MappingProxyType

for variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[variable] = "1"

from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import EvaluationCost, EvaluationEvidenceWrite, MaterialEvidenceWrite
from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
import robust_center_draft as draft
import selfcheck

WORK = draft.ROOT / ".tmp/s013-robust-center/run"
EXPERIMENT = ExperimentRef("S013", "EX062_20261011")
OLD_CACHE = draft.ROOT / ".tmp/s013-mechanism-EX058"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def cache_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as stream:
        writer = pickle.Pickler(stream, protocol=pickle.HIGHEST_PROTOCOL)
        writer.dispatch_table = {**copyreg.dispatch_table,
                                MappingProxyType: lambda value: (draft.restore_mapping, (dict(value),))}
        writer.dump(value)


def cache_read(path):
    with gzip.open(path, "rb") as stream:
        return pickle.load(stream)


def material(ctx, name, value):
    return publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, name,
        (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode(),
        "application/json", "json"))


def legacy_pickle_support():
    path = draft.EX058 / "src/common.py"
    if "common" in sys.modules:
        if Path(sys.modules["common"].__file__).resolve() != path.resolve():
            raise ValueError("Unknown common module cannot authenticate old pickle")
        return sys.modules["common"]
    spec = importlib.util.spec_from_file_location("common", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["common"] = module
    spec.loader.exec_module(module)
    return module


def frozen_account_audit(request, result):
    """Preserve EX058's known low-price issue; no repair or eligibility veto."""
    path = draft.EX058 / "src/account_reference.py"
    name = "_s013_ex062_frozen_ex058_account_reference"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name].verify_account(request, result)


def authenticated_existing(ctx, method):
    """Explicit execute-stage read of 33 original identities, never silent cloning."""
    legacy_pickle_support()
    refs = read(draft.ROOT / method["reuse_mapping"]["center_reference_manifest"])
    matrix = read(draft.ROOT / method["reuse_mapping"]["parameter_matrix"])
    if matrix["status"] != "COMPLETE":
        raise ValueError("Old full32 matrix incomplete")
    center = cache_read(OLD_CACHE / "N0.pkl.gz")
    center_ref = EvidenceRef.from_dict(refs["N0"])
    draft.authenticate_native(ctx, *center, center_ref)
    proposals, coordinates, config, _ = draft.metadata_queue()
    if (draft.plain(center[0].strategy.payload) != config["payload"]
            or center[0].strategy.source_root.resolve() != (draft.EX058 / "src" / config["source_directory"]).resolve()
            or center[0].strategy.candidate_id != "C8880"):
        raise ValueError("Frozen original C8880 source/payload differs")
    rows = sorted((row for row in matrix["rows"] if row["control_key"] == "N0"), key=lambda row: row["point_index"])
    if [row["point_index"] for row in rows] != list(range(32)):
        raise ValueError("Old native point coverage differs")
    points, references = [], []
    for row in rows:
        pair = cache_read(OLD_CACHE / "parameters/N0" / (row["label"] + ".pkl.gz"))
        reference = EvidenceRef.from_dict(row["reference"])
        identity = draft.authenticate_native(ctx, *pair, reference)
        if pair[0].strategy.candidate_id != row["candidate_id"] or pair[1].request_hash != row["request_hash"] or pair[1].result_hash != row["result_hash"] or identity.content_sha256 != row["content_sha256"]:
            raise ValueError("Old matrix/native identity mismatch")
        if pair[0].dependencies != center[0].dependencies or identity.source_sha256 != center[0].strategy.payload["runtime"]["source_sha256"]:
            raise ValueError("Old point source/dependency drift")
        points.append(pair)
        references.append(reference)
    prepared = cache_read(OLD_CACHE / "parameters/prepared.pkl.gz")
    old = next(record for record in prepared if record["control_key"] == "N0")
    old_plan = old["plan"]
    record = next(record for record in read(draft.EX058 / "protocols/parameter_plans.json")["centers"] if record["control_key"] == "N0")
    if old_plan.design.center.candidate_id != "S013-C8880" or record["candidate_id"] != "C8880":
        raise ValueError("Old authentic parameter center is not original C8880")
    if read_parameter_plan(EvidenceRef.from_dict(record["plan_reference"]), draft.ROOT) != old_plan:
        raise ValueError("Old exact plan differs")
    for index, (request, _) in enumerate(points):
        if request.strategy.candidate_id != f"C{8840 + index:04}":
            raise ValueError("Old original C8880 full32 child identity differs")
        if request.lineage.parameter_binding.point != old_plan.design.bind_point(index):
            raise ValueError("Old point binding mismatch")
        expected = draft.plain(center[0].strategy.payload)
        expected["parameters"] = draft.materialize(expected["parameters"], coordinates, old_plan.design.points[index].coordinates)
        if expected != draft.plain(request.strategy.payload):
            raise ValueError("Old point payload differs from all13 prescribed coordinates")
    return center, center_ref, tuple(points), tuple(references), old_plan


def authenticate_only(method_ref):
    method = draft.require_frozen_method(method_ref)
    ctx = draft.existing_only_context(method_ref)
    center, center_ref, points, refs, plan = authenticated_existing(ctx, method)
    output = {"status": "AUTHENTICATED_OLD_NATIVE_ONLY", "native_unique_accounts": 33,
        "new_account_evaluations": 0, "preparations": 0, "provider_calls": 0,
        "center": center_ref.to_dict(), "points": [ref.to_dict() for ref in refs],
        "old_plan": plan.to_dict(), "method_reference": method_ref.to_dict()}
    write(WORK / "authentication.json", output)
    return output


def declare(method_ref):
    method = draft.require_frozen_method(method_ref)
    if (WORK / "checkpoint.json").exists() or (WORK / "prepared.pkl.gz").exists():
        raise RuntimeError("Existing declaration/state cannot be overwritten; use declared resume stages")
    ctx = draft.existing_only_context(method_ref)
    center, center_ref, points, refs, old_plan = authenticated_existing(ctx, method)
    proposals, coordinates, _, _ = draft.metadata_queue()
    if [draft.plain(proposal.parameters) for proposal in proposals] != [row["parameters"] for row in method["queue"]]:
        raise ValueError("Frozen queue differs from deterministic metadata interpolation")
    mapping, feasibility = old_plan.mapping_evidence, old_plan.feasibility_evidence
    records, child_number, new_number = [], 600, 591
    for index, proposal in enumerate(proposals):
        pair = center if index == 0 else points[0] if index == 1 else points[20] if index == 2 else None
        reference = center_ref if index == 0 else refs[0] if index == 1 else refs[20] if index == 2 else None
        request = pair[0] if pair else draft.prepare_new_center(ctx, center[0], proposal.parameters,
                    f"C{new_number:04}", method_ref, center_ref)
        if pair is None:
            new_number += 1
        identity = ctx.runtime.identify(request.strategy, dependencies=request.dependencies)
        design = draft.design_for(request.strategy, identity, coordinates, mapping, feasibility)
        if index == 0:
            if design != old_plan.design:
                raise ValueError("Baseline new design differs from exact old native design")
            children, plan, plan_ref = tuple(pair[0] for pair in points), old_plan, points[0][0].lineage.parameter_binding.plan
        else:
            identifiers = [f"C{number:04}" for number in range(child_number, child_number + 32)]
            child_number += 32
            if index == 2:
                identifiers[0] = "C0621"  # Exact P00:P21 payload; C0632 is deliberately unused.
            view, children, plan = draft.prepare_point_plan(ctx, request, design, coordinates,
                        identifiers, mapping, feasibility, method_ref)
            plan_ref = material(ctx, f"center-{index:02}-prospective-plan", plan.to_dict())
            if view.strategy != request.strategy or view.input_bindings != request.input_bindings:
                raise ValueError("View changed source/parameters/data")
        records.append({"queue_index": index, "label": proposal.label, "center": request,
            "center_pair": pair, "center_reference": reference, "children": children,
            "design": design, "plan": plan, "plan_reference": plan_ref,
            "reused_points": points if index == 0 else None,
            "reused_point_references": refs if index == 0 else None,
            "native_center_request_hash": pair[1].request_hash if pair else None,
            "prospective_center_view_request_hash": plan.center_request_sha256})
        print(json.dumps({"stage": "PREPARED_NOT_EVALUATED", "center": proposal.label,
                          "center_reused": pair is not None, "points": 32,
                          "point_native_reuse": index == 0}), flush=True)
    if child_number != 856 or new_number != 597:
        raise ValueError("Reserved account budget drift")
    cache_write(WORK / "prepared.pkl.gz", tuple(records))
    state = {"status": "DECLARED", "method_reference": method_ref.to_dict(),
             "roles": 297, "reused_roles": 35, "reused_native_unique": 33,
             "maximum_new_business": 262, "maximum_unique_business": 295,
             "planned_unique_new_business": 261, "planned_unique_total_business": 294,
             "binding_duplicate_roles": 1, "unused_reserved_id": "C0632",
             "evaluation_attempts": 0, "new_successful_business": 0,
             "technical_duplicates": 0, "completed_centers": [], "failure": None,
             "pressure_successful": 0,
             "points_not_paired_by_index_between_centers": True}
    write(WORK / "checkpoint.json", state)
    return state


def evaluate_and_retain(ctx, request, label, state):
    path = WORK / "native" / (label + ".pkl.gz")
    if path.exists():
        stored, result = cache_read(path)
        actual = serialize_evaluation_evidence(stored, result)
        expected = serialize_evaluation_evidence(request, result)
        validate_evaluation_evidence(expected)
        if actual != expected:
            raise ValueError("Resume cache differs from entire current request/evidence")
    else:
        state["evaluation_attempts"] += 1
        write(WORK / "checkpoint.json", {**state, "inflight": label})
        result = ctx.evaluation.evaluate(request)
        cache_write(path, (request, result))
        if label.startswith("fee-stress-"):
            state["pressure_successful"] += 1
        else:
            state["new_successful_business"] += 1
        write(WORK / "checkpoint.json", {**state, "inflight": None})
    reference = publish_evidence(ctx, EvaluationEvidenceWrite(EXPERIMENT, label, request, result))
    draft.authenticate_native(ctx, request, result, reference)
    return (request, result), reference


def evaluate_point_chunk(ctx, children, index, offset, state):
    items = [(point, children[point], f"center-{index:02}-point-{point:02}") for point in range(offset, offset + 8)]
    pending = [(point, request, label) for point, request, label in items
               if not (WORK / "native" / (label + ".pkl.gz")).exists()]
    if pending:
        state["evaluation_attempts"] += len(pending)
        write(WORK / "checkpoint.json", {**state, "inflight": [label for _, _, label in pending]})
        outcomes = ctx.evaluation.evaluate_many(tuple(request for _, request, _ in pending))
        failures = []
        for (_, request, label), outcome in zip(pending, outcomes, strict=True):
            if outcome.status.value == "SUCCEEDED":
                cache_write(WORK / "native" / (label + ".pkl.gz"), (request, outcome.result))
                state["new_successful_business"] += 1
            else:
                failures.append({"label": label, "status": outcome.status.value,
                                 "error": {"code": outcome.error.code, "message": outcome.error.message}})
        write(WORK / "checkpoint.json", {**state, "inflight": None,
              "failures": failures, "status": "FAILED" if failures else state["status"]})
        if failures:
            state["failure"] = {"stage": "native_parameter_chunk", "failures": failures}
            write(WORK / "checkpoint.json", state)
            raise RuntimeError("Native failures preserved; no retry/replacement")
    points, refs = [], []
    for _, request, label in items:
        # Cache already exists, so this validates and publishes without evaluation.
        pair, reference = evaluate_and_retain(ctx, request, label, state)
        points.append(pair)
        refs.append(reference)
    return points, refs


def verify_binding_duplicate(ctx, repeated, reference):
    import pandas as pd
    original = cache_read(WORK / "native/center-01-point-21.pkl.gz")
    if repeated[0].strategy != original[0].strategy or repeated[0].lineage == original[0].lineage:
        raise ValueError("Duplicate must preserve candidate identity with distinct legitimate binding")
    if repeated[1].request_hash == original[1].request_hash:
        raise ValueError("Distinct declared lineage must have distinct native request hashes")
    left, right = original[1].runs[0], repeated[1].runs[0]
    pd.testing.assert_frame_equal(left.signals.decisions, right.signals.decisions, check_exact=True)
    for a, b in ((left.execution, right.execution), (left.buyhold.execution, right.buyhold.execution)):
        for field in ("decisions", "orders", "fills", "account_daily", "trades"):
            pd.testing.assert_frame_equal(getattr(a, field), getattr(b, field), check_exact=True)
    proof = {"status": "PASS", "same_candidate_id": "C0621", "unused_reserved_id": "C0632",
             "first_role": "P00:P21", "second_role": "P20:P00", "complete_native_economic_frames_exact": True,
             "first_request_sha": original[1].request_hash, "second_request_sha": repeated[1].request_hash,
             "original_binding": original[0].lineage.parameter_binding.to_dict(),
             "second_binding": repeated[0].lineage.parameter_binding.to_dict(),
             "second_native_reference": reference.to_dict(), "native_lineages_not_projected": True}
    proof_ref = material(ctx, "same-content-different-plan-binding-proof", proof)
    write(WORK / "binding_duplicate.json", {**proof, "proof_reference": proof_ref.to_dict()})


def preflight(method_ref):
    draft.require_frozen_method(method_ref)
    state = read(WORK / "checkpoint.json")
    if state["failure"]:
        raise RuntimeError("Preserved failure requires a separately frozen correction")
    records = cache_read(WORK / "prepared.pkl.gz")
    ctx = draft.existing_only_context(method_ref, 1)
    request = records[3]["center"]
    if (WORK / "preflight.json").exists():
        proof = read(WORK / "preflight.json")
        if proof["status"] != "PASS":
            raise ValueError("Stored preflight not PASS")
        pair = cache_read(WORK / "native/center-03.pkl.gz")
        draft.authenticate_native(ctx, *pair, EvidenceRef.from_dict(proof["reference"]))
        return proof
    pair, reference = evaluate_and_retain(ctx, request, "center-03", state)
    outcome = draft.existing_only_context(method_ref, 8).evaluation.evaluate_many((request,))[0]
    state["evaluation_attempts"] += 1
    state["technical_duplicates"] += 1
    if outcome.status.value != "SUCCEEDED":
        raise RuntimeError(str(outcome.error))
    if pair[1].result_hash != outcome.result.result_hash or serialize_evaluation_evidence(*pair) != serialize_evaluation_evidence(request, outcome.result):
        raise ValueError("Serial/spawn full native evidence differs")
    cache_write(WORK / "native/preflight-spawn.pkl.gz", (request, outcome.result))
    proof = {"status": "PASS", "reference": reference.to_dict(),
             "actual_technical_duplicates": 1, "full_public_serialization_exact": True}
    material(ctx, "serial-spawn-preflight", proof)
    write(WORK / "preflight.json", proof)
    write(WORK / "checkpoint.json", {**state, "inflight": None})


def run(method_ref):
    draft.require_frozen_method(method_ref)
    if read(WORK / "preflight.json")["status"] != "PASS":
        raise ValueError("Exact serial/spawn preflight required")
    state = read(WORK / "checkpoint.json")
    if state["failure"]:
        raise RuntimeError("No automatic retries/replacements after failure")
    ctx = draft.existing_only_context(method_ref, 8)
    records = cache_read(WORK / "prepared.pkl.gz")
    study_path = WORK / "study.pkl.gz"
    if study_path.exists():
        study = cache_read(study_path)
    else:
        proposals, _, _, _ = draft.metadata_queue()
        study = draft.queue_study(proposals)
        cache_write(study_path, study)
    outputs = read(WORK / "centers.json") if (WORK / "centers.json").exists() else []
    for record in records[len(outputs):]:
        index = record["queue_index"]
        trial = study.trials[index]
        if trial.state.name == "WAITING":
            active = study.ask()
            if active.number != index or active.suggest_int("center_index", 0, len(records) - 1) != index:
                raise ValueError("Frozen Optuna queue drift")
            cache_write(study_path, study)
        elif trial.state.name not in {"RUNNING", "COMPLETE"} or trial.params.get("center_index") != index:
            raise ValueError("Optuna interrupted/failed trial requires explicit review")
        pair, reference = (record["center_pair"], record["center_reference"]) if record["center_pair"] else evaluate_and_retain(ctx, record["center"], f"center-{index:02}", state)
        if index == 0:
            points, point_refs = record["reused_points"], record["reused_point_references"]
        else:
            children = draft.bind_points(pair[0], reference, record["children"], record["plan"], record["plan_reference"])
            points, point_refs = [], []
            # One public evaluate_many call for at most eight pending native FULL accounts.
            for offset in range(0, 32, 8):
                actual, refs = evaluate_point_chunk(ctx, children, index, offset, state)
                points.extend(actual)
                point_refs.extend(refs)
                write(WORK / "checkpoint.json", {**state, "inflight": None})
            if index == 2:
                verify_binding_duplicate(ctx, points[0], point_refs[0])
        center_economics = {**selfcheck.economic_native(*pair), "ex058_account_audit": frozen_account_audit(*pair)}
        point_economics = [{**selfcheck.economic_native(*point), "ex058_account_audit": frozen_account_audit(*point)} for point in points]
        summary = draft.summarize_panel(center_economics, point_economics)
        values = (summary["joint_pass_count"], summary["q10_cagr"], summary["q90_drawdown"])
        if study.trials[index].state.name == "COMPLETE":
            if tuple(study.trials[index].values) != values:
                raise ValueError("Stored trial objective differs from complete native panel")
        else:
            study.tell(index, values)
        cache_write(study_path, study)
        row = {**summary, "label": record["label"], "queue_index": index,
               "center": center_economics, "points": point_economics,
               "center_reference": reference.to_dict(), "point_references": [ref.to_dict() for ref in point_refs],
               "plan_reference": record["plan_reference"].to_dict(),
               "native_center_request_hash": pair[1].request_hash,
               "prospective_view_request_hash": record["plan"].center_request_sha256}
        cache_write(WORK / f"complete-center-{index:02}.pkl.gz", {"center": pair,
                    "points": tuple(points), "design": record["design"]})
        material(ctx, f"center-{index:02}-complete-summary", row)
        outputs.append(row)
        write(WORK / "centers.json", outputs)
        state["completed_centers"].append(record["label"])
        state["status"] = "COMPLETE" if len(outputs) == len(records) else "PARTIAL"
        write(WORK / "checkpoint.json", {**state, "inflight": None})
        print(json.dumps({"completed_center": record["label"], "complete_points": 32,
                          "center_qualified": summary["center_qualified"],
                          "q10_cagr": summary["q10_cagr"], "q90_drawdown": summary["q90_drawdown"]}), flush=True)


def analyze(method_ref):
    draft.require_frozen_method(method_ref)
    state = read(WORK / "checkpoint.json")
    rows = read(WORK / "centers.json")
    if state["status"] != "COMPLETE" or len(rows) != 9:
        raise ValueError("Incomplete search is not a completed recommendation")
    output = {"status": "COMPLETE", "selection": draft.selection(rows), "centers": rows,
        "counts": state, "not_independent_validation": True,
        "limits": ["Seen development pool and selected endpoints; no independent validation",
                   "No same-index paired profit comparison across recentered designs",
                   "Center qualification remains exactly the original four gates",
                   "Relative degradation remains reported alongside absolute tails; no added veto",
                   "Existing five 30m high/low deviations are retained, never repaired. Frozen EX058 account audit reports its declared 2020-12-01 low-price potential-order exposure; it does not certify every bar or all limit-fill policies. Native public TXE accounts remain the actual economic evidence."]}
    write(WORK / "analysis.json", output)
    material(draft.existing_only_context(method_ref), "robust-center-search-analysis", output)
    return output


def selfchecks(method_ref):
    """Five independent checks on baseline and at most one preferred center."""
    draft.require_frozen_method(method_ref)
    analysis = read(WORK / "analysis.json")
    state = read(WORK / "checkpoint.json")
    if state["failure"]:
        raise RuntimeError("Failure requires separately frozen correction, no automatic retry")
    preferred = analysis["selection"]["preferred"]
    labels = ["BASE"] + ([preferred] if preferred else [])
    ctx = draft.existing_only_context(method_ref, 1)
    outputs = []
    for label in labels:
        row = next(row for row in analysis["centers"] if row["label"] == label)
        native = cache_read(WORK / f"complete-center-{row['queue_index']:02}.pkl.gz")
        original = native["center"][0]
        stress = replace(draft.plan_center_view(original), experiment_id=EXPERIMENT.experiment_id,
                         costs=(EvaluationCost("stress_20bp_per_side", .002, "STRESS"),))
        stress_pair, stress_ref = evaluate_and_retain(ctx, stress, f"fee-stress-{row['queue_index']:02}", state)
        checked = selfcheck.assess_native(center=selfcheck.NativeEvaluation(*native["center"]),
                  points=tuple(selfcheck.NativeEvaluation(*pair) for pair in native["points"]),
                  design=native["design"], stress=selfcheck.NativeEvaluation(*stress_pair))
        output = {"label": label, "request": checked.request.to_dict(), "panel": checked.panel.to_dict(),
                  "economics": checked.economics, "limitations": list(checked.limitations),
                  "stress_reference": stress_ref.to_dict(), "stress_changes_only_cost": True,
                  "all_other_qualified_centers_keep_qualification": True}
        ref = material(ctx, f"five-selfchecks-{row['queue_index']:02}", output)
        outputs.append({**output, "reference": ref.to_dict()})
    write(WORK / "selfchecks.json", {"status": "COMPLETE", "selected_checks": outputs,
                                    "pressure_successful": state["pressure_successful"]})
    write(WORK / "checkpoint.json", state)


def method_draft():
    """Metadata-only draft; root creates experiment and publishes final exact bytes."""
    proposals, coordinates, config, record = draft.metadata_queue()
    rows = []
    all_payloads = {}
    mapping = type("Hash", (), {"sha256": "1" * 64})()
    feasibility = type("Hash", (), {"sha256": "2" * 64})()
    for index, proposal in enumerate(proposals):
        strategy = type("Strategy", (), {"reference_id": "S013-" + (proposal.existing_candidate or f"C{591 + index - 3:04}"),
                                         "payload": {"parameters": proposal.parameters}})()
        identity = type("Identity", (), {"content_sha256": sha256(proposal.parameters_json.encode()).hexdigest()})()
        design = draft.design_for(strategy, identity, coordinates, mapping, feasibility)
        rows.append({"label": proposal.label, "queue_index": index, "parameters": proposal.parameters,
                     "existing_candidate": proposal.existing_candidate, "aliases": list(proposal.aliases)})
        for label, values in [("center", proposal.parameters), *((f"P{point.index:02}", draft.materialize(proposal.parameters, coordinates, point.coordinates)) for point in design.points)]:
            all_payloads.setdefault(canonical_parameters(values), []).append(f"{proposal.label}:{label}")
    duplicates = [aliases for aliases in all_payloads.values() if len(aliases) > 1]
    known = {frozenset(("BASE:P00", "P00:center")), frozenset(("BASE:P20", "P20:center")),
             frozenset(("P00:P21", "P20:P00"))}
    write(Path(__file__).resolve().parent / "duplicate_probe.json", {"status": "PURE_METADATA_ONLY", "unique": len(all_payloads), "duplicates": duplicates})
    if {frozenset(aliases) for aliases in duplicates} != known:
        raise ValueError("Additional payload duplicates need exact native-role reuse method; never replace points/IDs")
    sources = {path.relative_to(draft.ROOT).as_posix(): sha256(path.read_bytes()).hexdigest()
               for path in (Path(__file__), Path(draft.__file__), Path(selfcheck.__file__),
                            draft.EX058 / "src/common.py", Path(__file__).resolve().parent / "root_decision.json",
                            draft.EX058 / "src/account_reference.py",
                            Path(__file__).resolve().parent / "source_inventory.json")}
    for filename in ("focused_checks.py", "driver_checks.py", "selfcheck_checks.py", "selfcheck_method.json"):
        path = Path(__file__).resolve().parent / filename
        sources[path.relative_to(draft.ROOT).as_posix()] = sha256(path.read_bytes()).hexdigest()
    for relative, digest in read(draft.EX058 / "protocols/plan.json")["source_files"].items():
        path = draft.EX058 / "src" / relative
        sources[path.relative_to(draft.ROOT).as_posix()] = digest
    metadata = (draft.EX058 / "protocols/plan.json", draft.EX058 / "protocols/geometry.json",
                draft.EX058 / "protocols/parameter_plans.json",
                draft.ROOT / "research/S013/assets/runs/EX058_20261011/account_references.json",
                draft.ROOT / "research/S013/assets/runs/EX058_20261011/parameter_matrix.json")
    for path in metadata:
        sources[path.relative_to(draft.ROOT).as_posix()] = sha256(path.read_bytes()).hexdigest()
    reservations = [f"C{i:04}" for i in (*range(591, 597), *range(600, 856))]
    for identifier in reservations:
        if (draft.ROOT / f"research/S013/assets/candidates/{identifier}").exists() or (draft.ROOT / f"research/registrations/S013/candidates/{identifier}.json").exists():
            raise ValueError("ID collision: " + identifier)
    method = {"status": "DRAFT_NOT_FROZEN", "experiment": EXPERIMENT.to_dict(),
        "queue": rows, "coordinates": coordinates, "public_se": draft.PROTOCOL.to_dict(),
        "sources": sources, "candidate_reservation": reservations,
        "fixed_contract": {"source": config["source_directory"], "source_experiment": "EX058_20261011",
                           "mechanism": draft.MECHANISM, "only_numeric_parameters_change": True,
                           "fees": .001, "price_basis": "HFQ_RESEARCH", "benchmark": "unchanged fixed1% LimitBuyHold",
                           "warmup": "max(original parent, regime_window+2); missing existing history FAILED; full domains unchanged"},
        "budget": {"center_roles": 9, "parameter_roles": 288, "total_roles": 297,
                   "old_reused_roles": 35, "old_unique_native_accounts": 33,
                   "new_business_maximum": 262, "total_unique_business_maximum": 295,
                   "new_unique_content_accounts": 261, "total_unique_content_accounts": 294,
                   "same_content_new_plan_binding_technical_duplicate": 1,
                   "technical_duplicate": 1, "optional_pressure_accounts_maximum": 2,
                   "no_center_or_point_pruning": True},
        "sampling": "9 fixed queue: C8880, native P00/C8840, P20/C8860, six whole13 interpolation centers alpha .25/.5/.75; INTEGER np.rint HALF_EVEN; payload deduplicate",
        "ranking": {"optuna_directions": ["maximize", "maximize", "minimize"],
                    "objectives": ["joint_four_gate_pass_count_among32", "absolute_Q10_CAGR_LINEAR", "absolute_Q90_wholeDD_LINEAR"],
                    "center_eligibility": "original four gates ONLY",
                    "preference": "Qualified improvement centers with Q10>=baseline and Q90<=baseline, at least one strict; then joint count/Q10/Q90/fixedqueue",
                    "all_qualified_centers_and_pareto_retained": True, "no_added_neighbor_veto": True,
                    "relative_degradation_also_reported": True},
        "reuse_mapping": {"center_reference_manifest": metadata[3].relative_to(draft.ROOT).as_posix(),
                         "parameter_matrix": metadata[4].relative_to(draft.ROOT).as_posix(),
                         "known_role_duplicates": duplicates,
                         "binding_duplicate": "P00:P21 and P20:P00 same candidate C0621; C0632 unused. Second role receives distinct real native request/evaluation under its own published plan. All economic native frames must be exact; no artificial parent/point-binding projection.",
                         "rule": "exact original native request/result/ref/identity/source/dependencies/lineage/serialized full evidence; no original-account clone or re-evaluation",
                         "old_point_center_view": "Only plan input strips old parameter_binding, derivation retained; view and native request hashes separately recorded; view never serialized as old account"},
        "failure_policy": "All technical/account/missing-data failures retained, no automatic retry, replacement, percentile dropping, proxy acceleration or provider fallback",
        "five_selfchecks": "Only BASE and at most one preferred four-gate-qualified center. Independent standard center/32, time/concentration/CI reuse same baseline account; center cost-only .002 stress adds at most two full accounts; no parameter-by-cost cross test. Stress preserves source/params/dependencies and removes only a stale baseline point binding if needed for independent cost scenario, never rewrites original native.",
        "data_quality_limitations": "Existing 5 30m High/Low deviations remain unchanged. Frozen EX058 verify_account is retained for every center/point, including specific known_low_error_potential_orders. New selfcheck economics is cash/fill/equity/cycle audit only, not a replacement for independent limit-fill/market-quality certification. No repair, no new gate, native TXE profits remain authoritative.",
        "selection_history": "Seen S013 development pool; P00/P20 selected after known negative-year passing but low CAGR. Parameter-center optimization is adaptive in-sample; no independent validation, no mechanism change, no yearly exceptions.",
        "paired_comparison_limit": "Each center rebuilds full13-domain public32; accepted directions can differ with feasibility/rounding. No same-index paired account-profit conclusions between centers.",
        "parent_plan": record["plan_reference"]}
    write(Path(__file__).resolve().parent / "method_draft.json", method)
    return method


def canonical_parameters(parameters):
    return json.dumps(parameters, sort_keys=True, separators=(",", ":"), allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("method-draft", "authenticate-only", "declare", "preflight", "run", "analyze", "selfchecks"))
    parser.add_argument("--method-reference", type=Path)
    args = parser.parse_args()
    if args.action == "method-draft":
        method_draft()
        return
    if args.method_reference is None:
        parser.error("A formally published frozen method reference is mandatory")
    reference = EvidenceRef.from_dict(read(args.method_reference))
    try:
        globals()[args.action.replace("-", "_")](reference)
    except Exception as exc:
        state = read(WORK / "checkpoint.json") if (WORK / "checkpoint.json").exists() else {}
        state.update(status="FAILED", failure={"action": args.action, "type": type(exc).__name__, "message": str(exc)})
        write(WORK / "failure.json", state)
        if (WORK / "checkpoint.json").exists():
            write(WORK / "checkpoint.json", state)
        raise


if __name__ == "__main__":
    main()
