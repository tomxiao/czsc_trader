"""Authenticate saved S015 accounts and perform the declared SE stage-four checks.

This script never executes a strategy account, fetches market data, registers a
candidate, or modifies an existing research publication. All outputs are derived
work products beneath this experiment's assets/runs directory.
"""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import argparse
from dataclasses import replace
from hashlib import sha256
import json
from multiprocessing import get_context
from pathlib import Path
import os
import time

for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[variable] = "1"

import numpy as np  # noqa: E402

from czsc_trader.application import RepositoryContext, validate_delivery  # noqa: E402
from czsc_trader.research_tools import EvidenceRef, ParameterEvaluationPlan  # noqa: E402
from czsc_trader.research_tools import delivery as d  # noqa: E402
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence  # noqa: E402
from czsc_trader.research_tools.parameter_evaluation import (  # noqa: E402
    ParameterEvaluationBinding, read_parameter_plan, validate_parameter_contract,
)
from strategy_evaluator import (  # noqa: E402
    annualized_sharpe, assess_candidates, compare_candidates, effective_trial_count,
)
from strategy_evaluator import research_models as m  # noqa: E402
from strategy_runtime import canonical_sha256  # noqa: E402


ROOT = Path(__file__).resolve().parents[5]
WORK = ROOT / "research/S015/assets/runs/EX005_20261022/assessment"
MANDATE_SHA256 = "997d7b956b4f30871b92e9e4bd4a25f7081af15bdb58d19f6a24d1b72c5c58f2"
PROTOCOL_SHA256 = "3e605e9761c39d541bb928d4f677e49e9e84c9ec0c62bb2cdd6374893fdaa416"
VERSION = "S015-EX005-standard-v1"
EXPERIMENTS = {"EX003_20261021", "EX004_20261022", "EX005_20261022"}
DEGENERATE_CENTERS = {"C0030", "C0062"}
FAMILY_FILES = (
    "EX003_20261021/strategy_study/grid_results.json",
    "EX003_20261021/strategy_study/extension_results.json",
    "EX004_20261022/range_weights/initial_results.json",
    "EX004_20261022/range_weights/followup_results.json",
    "EX004_20261022/range_weights/boundary_results.json",
)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(name, value):
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / name).open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        stream.write("\n")


def self_check_protocol():
    return m.SelfCheckProtocol(
        version=VERSION, baseline_window="full", standard_scenario="standard",
        stress_scenario="fee_x2", rolling_window_days=252, rolling_step_days=21,
        quantile_method=m.QuantileMethod.LINEAR, minimum_perturbations=32,
        minimum_rolling_windows=1, bootstrap_repetitions=2000,
        bootstrap_block_length=10, seed=13, reconciliation_tolerance=1e-7,
        pbo_blocks=10, parameter_protocol=m.ParameterPerturbationProtocol(),
        frequency_min_closed_cycles=3,
    )


def comparison_policy():
    metrics = (*m.BENCHMARK_METRICS, *m.WITHIN_LAYER_METRICS, m.ResearchMetric.FREQUENCY_MEDIAN)
    resolutions = {m.ResearchMetric.PROFIT_CONCENTRATION: .01,
                   m.ResearchMetric.FREQUENCY_MEDIAN: 1.}
    bins = tuple(m.MetricBinSpec(metric, resolutions.get(metric, .001), 0., m.BinRounding.FLOOR)
                 for metric in metrics)
    sensitivities = (
        m.ComparisonVariant("bins_half", tuple(replace(item, resolution=item.resolution * .5)
                                               for item in bins)),
        m.ComparisonVariant("bins_double", tuple(replace(item, resolution=item.resolution * 2.)
                                                 for item in bins)),
        *(m.ComparisonVariant(f"adjacent_swap_{index}", bins, index) for index in range(5)),
    )
    return m.ComparisonPolicy(VERSION, bins, m.ParetoBasis.RAW,
                              m.MissingEvidencePolicy.REQUIRE_COMPLETE, sensitivities)


def authenticated_protocol(protocol, policy):
    reference = EvidenceRef.from_dict(load(
        ROOT / "research/S015/experiments/EX005_20261022/others/protocol_ref.json"))
    if reference.sha256 != PROTOCOL_SHA256:
        raise ValueError("prospective protocol reference changed")
    frozen = load(reference.resolve(ROOT))
    if frozen["version"] != VERSION or frozen["parameter_protocol"] != protocol.parameter_protocol.to_dict():
        raise ValueError("assessment protocol differs from prospective publication")
    for key, value in frozen["protocol"].items():
        if hasattr(protocol, key) and getattr(protocol, key) != value:
            raise ValueError(f"assessment protocol field differs: {key}")
    declared = frozen["comparison"]
    if (declared["version"] != policy.version or declared["pareto_basis"] != policy.pareto_basis.value
            or declared["missing_evidence_policy"] != policy.missing_evidence_policy.value
            or declared["sensitivities"] != [variant.name for variant in policy.sensitivities]):
        raise ValueError("comparison policy differs from prospective publication")
    for item in policy.bins:
        resolution_key = ("concentration_resolution" if item.metric is m.ResearchMetric.PROFIT_CONCENTRATION
                          else "rolling_frequency_median_resolution" if item.metric is m.ResearchMetric.FREQUENCY_MEDIAN
                          else "rate_resolution")
        if (item.resolution != declared[resolution_key] or item.origin != declared["origin"]
                or item.rounding.value != declared["rounding"]):
            raise ValueError("ranking bin differs from prospective publication")
    return {item["candidate_id"]: item for item in frozen["geometry"]}


def mandate_targets():
    folder = ROOT / "research/S015/assets/deliveries/MANDATE/2"
    receipt = d.DeliveryReceipt.from_dict(load(folder / "receipt.json"))
    if receipt.reference.content_sha256 != MANDATE_SHA256:
        raise ValueError("stage-one mandate identity changed")
    repository = RepositoryContext.discover(ROOT, explicit_root=ROOT)
    validation = validate_delivery(repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    if validation.status is not d.ValidationStatus.PASS:
        raise ValueError(f"mandate authentication failed: {validation.to_dict()}")
    mandate = d.ResearchMandate.from_dict(load(folder / "delivery.json")["content"]["payload"])
    targets = tuple(target for item in mandate.items if isinstance(item.requirement, d.PerformanceRequirement)
                    for target in item.requirement.targets)
    frequency = [item for item in mandate.items if isinstance(item.requirement, d.NumericRequirement)
                 and item.requirement.metric == "frequency_window_days"]
    if len(frequency) != 1 or (frequency[0].requirement.lower, frequency[0].requirement.upper) != (60., 60.):
        raise ValueError("mandate does not bind the expected 60-session frequency window")
    if not targets:
        raise ValueError("mandate has no typed performance targets")
    bindings = {target.target_id: item.item_id for item in mandate.items
                if isinstance(item.requirement, d.PerformanceRequirement)
                for target in item.requirement.targets}
    return m.ResearchTargets(targets, 60), {
        "reference": receipt.reference.to_dict(), "validation": validation.to_dict(),
        "target_bindings": bindings, "frequency_window_item_id": frequency[0].item_id,
    }


class AuthenticatedAccounts:
    """Retain only numeric projections and compact identities after each file read."""

    def __init__(self):
        self.evidence = {}
        self.metadata = {}
        # Promotion through get() retains the original serial request ordering.
        self.preloaded = {}

    def _check_cached(self, row, result, metadata, plan, plan_ref):
        if metadata["evidence"] != row["evidence"]:
            raise ValueError("evaluation ID reused with another publication")
        if result.candidate.candidate_id != f"S015-{row['candidate_id']}":
            raise ValueError("cached evaluation candidate differs")
        for key in ("request_hash", "result_hash"):
            if key in row and row[key] != metadata[key]:
                raise ValueError(f"cached result {key} differs")
        if "input_bindings" in row and canonical_sha256(row["input_bindings"]) != metadata["input_bindings_sha256"]:
            raise ValueError("cached result input bindings differ")
        if plan is None:
            if result.parameter_point is not None or metadata["verified_parameter_plan_sha256"] is not None:
                raise ValueError("parameter account cache requires its verified plan")
        else:
            if (metadata["verified_parameter_plan_sha256"] != plan_ref.sha256
                    or metadata["verified_parameter_plan_identity_sha256"] != canonical_sha256(plan.to_dict())):
                raise ValueError("cached parameter account was not authenticated against this plan")
            point = result.parameter_point
            if (point is None or point != plan.design.bind_point(point.point_index)
                    or result.parent != plan.design.center
                    or result.candidate != plan.children[point.point_index].candidate):
                raise ValueError("cached parameter point or candidate differs from verified plan")

    def get(self, row, *, plan=None, plan_ref=None):
        if (plan is None) != (plan_ref is None):
            raise ValueError("parameter authentication requires both plan and publication reference")
        reference = EvidenceRef.from_dict(row["evidence"])
        if (reference.experiment.strategy_id != "S015"
                or reference.experiment.experiment_id not in EXPERIMENTS):
            raise ValueError("account reference is outside the approved S015 experiments")
        evaluation_id = row["evaluation_id"]
        if evaluation_id in self.evidence or evaluation_id in self.preloaded:
            result = self.evidence[evaluation_id] if evaluation_id in self.evidence else self.preloaded[evaluation_id]
            self._check_cached(row, result, self.metadata[evaluation_id], plan, plan_ref)
            if evaluation_id in self.preloaded:
                self.evidence[evaluation_id] = self.preloaded.pop(evaluation_id)
            return result
        path = reference.resolve(ROOT)
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != reference.sha256:
            raise ValueError("published bytes changed after reference verification")
        payload = json.loads(raw)
        del raw
        validate_evaluation_evidence(payload)
        if len(payload["assessment_evidence"]) != 1:
            raise ValueError("one account coordinate is required per result row")
        result = m.AssessmentEvidence.from_dict(payload["assessment_evidence"][0])
        if (result.evaluation_id != evaluation_id
                or result.candidate.candidate_id != f"S015-{row['candidate_id']}"):
            raise ValueError("result row differs from authenticated account identity")
        for key in ("request_hash", "result_hash", "input_bindings"):
            if key in row and row[key] != payload[key]:
                raise ValueError(f"result row {key} differs from published account")
        if (result.window_id != "full" or result.frequency_window_days != 60
                or result.initial_cash != 100000 or result.opening_quantity != 0
                or len(result.account) != 434
                or result.account[0].session != "2025-01-02"
                or result.account[-1].session != "2026-10-21"):
            raise ValueError("account differs from fixed S015 evaluation contract")
        if plan is not None:
            binding = ParameterEvaluationBinding.from_dict(payload["request_identity"]["parameter_binding"])
            if binding.plan != plan_ref:
                raise ValueError("parameter account points to another published plan")
            validate_parameter_contract(payload["request_identity"], plan, binding)
        elif result.parameter_point is not None or payload["request_identity"]["parameter_binding"] is not None:
            raise ValueError("parameter account requires full plan authentication")
        self.evidence[evaluation_id] = result
        self.metadata[evaluation_id] = {
            "evidence": reference.to_dict(), "candidate": result.candidate.to_dict(),
            "evaluation_id": evaluation_id, "request_hash": payload["request_hash"],
            "result_hash": payload["result_hash"], "scenario": result.scenario_id,
            "closed_cycles": len(result.closed_cycles), "fills": len(result.fills),
            "input_bindings_sha256": canonical_sha256(payload["input_bindings"]),
            "verified_parameter_plan_sha256": None if plan_ref is None else plan_ref.sha256,
            "verified_parameter_plan_identity_sha256": None if plan is None else canonical_sha256(plan.to_dict()),
        }
        return result


def authenticate_task(task):
    """Spawn-safe public authentication; no evaluation, publication or data fetch."""
    row, reference_payload = task
    reference = None if reference_payload is None else EvidenceRef.from_dict(reference_payload)
    plan = None if reference is None else read_parameter_plan(reference, ROOT)
    accounts = AuthenticatedAccounts()
    result = accounts.get(row, plan=plan, plan_ref=reference)
    return result, accounts.metadata[result.evaluation_id]


def complete_authentication_tasks(*, wait_for_accounts):
    """Do not overlap a new authentication pool with the account-producing phase."""
    centers = load(WORK / "centers.json")
    if len(centers) != 98 or len({row["candidate_id"] for row in centers}) != 98:
        raise ValueError("authentication requires the98 original centers")
    announced = False
    while True:
        try:
            tail = load(WORK / "parallel_tail_state.json")
        except (FileNotFoundError, json.JSONDecodeError):
            tail = {}
        for name in ("failure.json", "publication_failure.json", "parallel_tail_failure.json"):
            if (WORK / name).exists():
                if (name == "parallel_tail_failure.json" and tail.get("status") == "COMPLETE"
                        and tail.get("execution_mode") == "resumed_by_forward_after_tail_failure"):
                    # Historical failed tail evidence remains intact; complete
                    # forward recovery plus all3170 records is checked below.
                    continue
                raise ValueError(f"account producer reported {name}; stop authentication")
        ready, new_tasks = True, []
        for center in centers:
            cid = center["candidate_id"]
            plan_path, result_path = WORK / "plans" / f"{cid}.json", WORK / "results" / f"{cid}.json"
            try:
                plan_record, rows = load(plan_path), load(result_path)
            except (FileNotFoundError, json.JSONDecodeError):
                ready = False
                break
            expected = 1 if cid in DEGENERATE_CENTERS else 33
            if len(rows) > expected:
                raise ValueError(f"extra account records for {cid}")
            if len(rows) != expected:
                ready = False
                break
            if len({(row["kind"], row["point_index"]) for row in rows}) != expected:
                raise ValueError(f"duplicate parameter/stress coordinates for {cid}")
            for row in rows:
                if row["parent_id"] != cid or row["kind"] not in ("parameter", "stress"):
                    raise ValueError("authentication task has invalid parent or kind")
                reference = plan_record["reference"] if row["kind"] == "parameter" else None
                new_tasks.append((row, reference))
        tail_path = WORK / "parallel_tail_state.json"
        try:
            tail = load(tail_path)
            tail_ready = (tail["status"] == "COMPLETE" and tail["boundary_cache_restored"]
                          and (ROOT / ".tmp/s015_stage4/requests/C0307.pkl").exists()
                          and not (ROOT / ".tmp/s015_stage4/parallel_tail/C0307.pkl").exists())
        except (FileNotFoundError, json.JSONDecodeError):
            tail_ready = False
        if ready and tail_ready:
            if len(new_tasks) != 3170 or len({row["evaluation_id"] for row, _ in new_tasks}) != 3170:
                raise ValueError("parallel authentication requires3170 unique completed new accounts")
            break
        if not wait_for_accounts:
            raise ValueError("all3170 accounts and completed tail/cache restoration are required before parallel authentication")
        if not announced:
            print(json.dumps({"waiting_for_all_accounts_before_authentication": 3170}), flush=True)
            announced = True
        time.sleep(5)
    family = [row for relative in FAMILY_FILES for row in load(ROOT / "research/S015/assets/runs" / relative)]
    if len(family) != 181:
        raise ValueError("family authentication requires181 original standard accounts")
    tasks = [(row, None) for row in sorted(family, key=lambda row: row["candidate_id"])] + new_tasks
    if len({row["evaluation_id"] for row, _ in tasks}) != 3351:
        raise ValueError("authentication task identities are not unique")
    return tasks


def preload_authentication(accounts, tasks, workers):
    if not 1 <= workers <= 8:
        raise ValueError("authentication workers must be in1..8")
    if accounts.evidence or accounts.preloaded or accounts.metadata:
        raise ValueError("parallel preloading requires an empty authenticated account cache")
    results = {}
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
        remaining = iter(enumerate(tasks))
        pending = {}
        for _ in range(min(workers, len(tasks))):
            index, task = next(remaining)
            pending[pool.submit(authenticate_task, task)] = index
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                index = pending.pop(future)
                result, metadata = future.result()
                if result.evaluation_id != tasks[index][0]["evaluation_id"]:
                    raise ValueError("authentication worker returned another account")
                results[index] = (result, metadata)
                if len(results) % 32 == 0 or len(results) == len(tasks):
                    print(json.dumps({"authenticated_parallel": len(results), "total": len(tasks),
                                      "workers": workers}), flush=True)
                next_item = next(remaining, None)
                if next_item is not None:
                    next_index, task = next_item
                    pending[pool.submit(authenticate_task, task)] = next_index
    for index in range(len(tasks)):
        result, metadata = results.pop(index)
        accounts.preloaded[result.evaluation_id] = result
        accounts.metadata[result.evaluation_id] = metadata


def family_matrix(accounts):
    rows = [row for relative in FAMILY_FILES
            for row in load(ROOT / "research/S015/assets/runs" / relative)]
    if len(rows) != 181 or len({row["candidate_id"] for row in rows}) != 181:
        raise ValueError("research-family coverage must retain all 84+97 configurations")
    evidence = [accounts.get(row) for row in sorted(rows, key=lambda row: row["candidate_id"])]
    contexts = {(item.context_sha256, item.metric_version, item.scenario_context) for item in evidence}
    if len(contexts) != 1 or any(item.scenario_id != "standard" for item in evidence):
        raise ValueError("family account comparison contexts differ")
    sessions = tuple(point.session for point in evidence[0].account)
    if any(tuple(point.session for point in item.account) != sessions for item in evidence):
        raise ValueError("family account calendars differ")
    returns = []
    for item in evidence:
        equity = np.asarray([point.equity for point in item.account], dtype=float)
        returns.append(equity / np.r_[item.initial_cash, equity[:-1]] - 1)
    matrix = np.asarray(returns).T
    sharpes = np.asarray([annualized_sharpe(column) for column in matrix.T])
    if not np.isfinite(sharpes).all():
        raise ValueError("family diagnostic selection has a nonfinite Sharpe")
    selected_index = int(np.argmax(sharpes))
    limitations = (
        "raw_trial_count=181 counts retained executable configurations in EX003(84)+EX004(97), not independent hypotheses or every physical execution.",
        "EX002 previously inspected 1092 feature/label comparisons; these are not account return paths and cannot be added directly to 181. Broader adaptive selection is not fully measured.",
        "All observations are development data. No independent holdout or future-success probability is established.",
        "The highest full-sample Sharpe column is selected only for DSR diagnostics, not a user candidate choice or the stage-four ranking rule.",
        "Repeated economic paths and zero-variance configurations remain in the family; unavailable PBO/DSR results are retained rather than repaired by dropping configurations.",
    )
    family = m.FamilyReturnEvidence(
        tuple(item.candidate for item in evidence), sessions,
        tuple(tuple(float(value) for value in row) for row in matrix),
        evidence[selected_index].candidate, 181, limitations,
    )
    try:
        effective = {"status": "AVAILABLE", "value": effective_trial_count(matrix), "reason": None}
    except (ValueError, FloatingPointError, ZeroDivisionError) as error:
        effective = {"status": "INSUFFICIENT_DATA", "value": None, "reason": str(error)}
    summary = {
        "raw_trial_count": 181, "matrix_columns": 181, "matrix_sessions": len(sessions),
        "selected_for_dsr_only": family.selected.to_dict(),
        "selected_sharpe": float(sharpes[selected_index]),
        "zero_variance_columns": int(np.sum(np.std(matrix, axis=0, ddof=1) == 0)),
        "distinct_exact_return_paths": len({column.tobytes() for column in matrix.T}),
        "effective_trial_count": effective, "limitations": list(limitations),
    }
    return family, summary


def build_request(accounts, protocol, geometry, *, wait_for_accounts=False):
    center_rows = load(WORK / "centers.json")
    if len(center_rows) != 98 or len({row["candidate_id"] for row in center_rows}) != 98:
        raise ValueError("stage-four center set must contain the 98 declared original identities")
    family, family_summary = family_matrix(accounts)
    centers, links, designs, failures, plan_refs = [], [], [], {}, []
    for center_row in sorted(center_rows, key=lambda row: row["candidate_id"]):
        cid = center_row["candidate_id"]
        if wait_for_accounts:
            expected_count = 1 if cid in DEGENERATE_CENTERS else 33
            plan_path = WORK / "plans" / f"{cid}.json"
            result_path = WORK / "results" / f"{cid}.json"
            waiting_announced = False
            while True:
                for failure_name in ("failure.json", "publication_failure.json"):
                    if (WORK / failure_name).exists():
                        raise ValueError(f"account producer reported {failure_name}; stop assessment")
                if plan_path.exists() and result_path.exists():
                    try:
                        ready_rows = load(result_path)
                    except json.JSONDecodeError:
                        # The producer writes its checkpoint after each published block.
                        # An incomplete write is still in progress, never account evidence.
                        ready_rows = []
                    if len(ready_rows) == expected_count:
                        break
                    if len(ready_rows) > expected_count:
                        raise ValueError(f"unexpected extra account rows for {cid}")
                if not waiting_announced:
                    print(json.dumps({"waiting_for_published_accounts": cid}), flush=True)
                    waiting_announced = True
                time.sleep(5)
        central = accounts.get(center_row)
        centers.append(central.candidate)
        plan_record = load(WORK / "plans" / f"{cid}.json")
        plan = reference = None
        if plan_record["status"] == "COMPLETE":
            if cid in DEGENERATE_CENTERS:
                raise ValueError("declared degenerate center must not acquire a substitute design")
            reference = EvidenceRef.from_dict(plan_record["reference"])
            plan = read_parameter_plan(reference, ROOT)
            if plan != ParameterEvaluationPlan.from_dict(plan_record["plan"]):
                raise ValueError("local plan differs from its authenticated publication")
            if (plan.design != m.ParameterPerturbationDesign.from_dict(plan_record["design"])
                    or plan_record["design"] != geometry[cid]["design"]
                    or plan.design.center != central.candidate
                    or plan.center_request_sha256 != central.request_sha256
                    or plan.design.protocol != protocol.parameter_protocol):
                raise ValueError("parameter design differs from the original center/protocol")
            designs.append(plan.design)
            plan_refs.append(reference.to_dict())
        else:
            if (cid not in DEGENERATE_CENTERS or plan_record["status"] != "NOT_APPLICABLE"
                    or plan_record["reason"] != geometry[cid]["reason"]):
                raise ValueError(f"unexpected design failure: {cid}")
            failures[cid] = {"status": plan_record["status"], "reason": plan_record["reason"]}
        rows = load(WORK / "results" / f"{cid}.json")
        expected = 33 if plan is not None else 1
        if len(rows) != expected:
            raise ValueError(f"{cid}: requires {expected} retained results, received {len(rows)}")
        stress_count, indices = 0, set()
        for row in rows:
            if row["parent_id"] != cid:
                raise ValueError("result belongs to another center")
            kind = row["kind"]
            if kind == "parameter":
                if plan is None:
                    raise ValueError("parameter account has no valid prescribed design")
                point_index = row["point_index"]
                item = accounts.get(row, plan=plan, plan_ref=reference)
                if (item.scenario_id != "standard" or item.parent != central.candidate
                        or item.candidate != plan.children[point_index].candidate
                        or item.parameter_point != plan.design.bind_point(point_index)
                        or point_index in indices):
                    raise ValueError("parameter result point/identity differs from plan")
                indices.add(point_index)
                links.append(m.PerturbationLink(central.candidate, item.candidate, 1.,
                                                item.derivation_sha256, item.parameter_point))
            elif kind == "stress":
                item = accounts.get(row)
                if (item.candidate != central.candidate or item.scenario_id != "fee_x2"
                        or item.scenario_context.one_way_cost != .002 or item.parameter_point is not None):
                    raise ValueError("stress account changed center identity or prescribed cost")
                stress_count += 1
            else:
                raise ValueError(f"unknown assessment account kind: {kind}")
        if stress_count != 1 or (plan is not None and indices != set(range(32))):
            raise ValueError("stress or parameter-point coverage is incomplete")
        print(json.dumps({"authenticated_center": cid, "account_projections": len(accounts.evidence)}), flush=True)
    if len(designs) != 96 or set(failures) != DEGENERATE_CENTERS:
        raise ValueError("declared stage-four design coverage changed")
    request = m.CandidateAssessmentRequest(
        tuple(centers), protocol, tuple(links), tuple(accounts.evidence.values()),
        family_returns=family, parameter_designs=tuple(designs),
    )
    return request, family_summary, failures, plan_refs


def concise_rows(panel, comparison):
    assessments = {row.candidate: row for row in panel.rows}
    values = []
    for row in comparison.rows:
        assessment = assessments[row.candidate]
        values.append({
            "candidate_id": row.candidate.candidate_id,
            "content_sha256": row.candidate.content_sha256,
            "status": row.status.value, "acceptance_status": row.acceptance_status.value,
            "pareto_layer": row.pareto_layer, "rank_in_layer": row.rank_in_layer,
            "rank_min": row.rank_min, "rank_max": row.rank_max,
            "reasons": list(row.reasons), "coverage_gaps": list(assessment.coverage_gaps),
            "diagnostics": {item.metric.value: {"value": item.value, "status": item.status.value,
                                                "reason": item.reason} for item in assessment.diagnostics},
            "uncertainty": assessment.uncertainty.to_dict(),
            "target_checks": [{"target_id": check.target.target_id, "status": check.status.value,
                                "reason": check.reason,
                                **({"valid_points": check.valid_points, "joint_passes": check.joint_passes}
                                   if isinstance(check, m.ParameterGroupCheck) else {})}
                               for check in row.target_checks],
        })
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-for-accounts", action="store_true")
    parser.add_argument("--authentication-workers", type=int, choices=range(1, 9), default=1)
    args = parser.parse_args()
    protocol, policy = self_check_protocol(), comparison_policy()
    geometry = authenticated_protocol(protocol, policy)
    targets, mandate = mandate_targets()
    accounts = AuthenticatedAccounts()
    if args.authentication_workers > 1:
        tasks = complete_authentication_tasks(wait_for_accounts=args.wait_for_accounts)
        preload_authentication(accounts, tasks, args.authentication_workers)
        del tasks
    request, family, failures, plan_refs = build_request(
        accounts, protocol, geometry, wait_for_accounts=args.wait_for_accounts)
    if accounts.preloaded:
        raise ValueError("parallel authentication left unused account projections")
    save("authenticated_sources.json", {"accounts": list(accounts.metadata.values()),
                                        "parameter_plans": plan_refs, "mandate": mandate})
    save("assessment_request.json", request.to_dict())
    print(json.dumps({"operation": "assess_candidates", "centers": len(request.centers),
                      "evidence": len(request.evidence)}), flush=True)
    panel = assess_candidates(request)
    save("assessment_panel.json", panel.to_dict())
    comparison_request = m.CandidateComparisonRequest(request.centers, targets, panel, policy)
    save("comparison_request.json", comparison_request.to_dict())
    comparison = compare_candidates(comparison_request)
    save("comparison.json", comparison.to_dict())
    if any(row.status in (m.ComparisonStatus.RANKED, m.ComparisonStatus.TIED,
                          m.ComparisonStatus.PARTIALLY_ORDERED)
           for row in comparison.rows if row.candidate.candidate_id.split("-")[-1] in failures):
        raise ValueError("a center without the required parameter design entered the ranking")
    summary = {
        "assessment_request_sha256": request.sha256, "comparison_request_sha256": comparison_request.sha256,
        "center_count": len(request.centers), "parameter_design_count": len(request.parameter_designs),
        "parameter_account_count": len(request.perturbations), "stress_account_count": len(request.centers),
        "authenticated_account_count": len(accounts.evidence),
        "status_counts": dict(Counter(row.status.value for row in comparison.rows)),
        "acceptance_counts": dict(Counter(row.acceptance_status.value for row in comparison.rows)),
        "design_failures": failures, "family": family,
        "family_diagnostics": [item.to_dict() for item in panel.family_diagnostics],
        "rows": concise_rows(panel, comparison),
        "sensitivities": [{"name": variant.name, "rows": [
            {"candidate_id": row.candidate.candidate_id, "status": row.status.value,
             "pareto_layer": row.pareto_layer, "rank_min": row.rank_min, "rank_max": row.rank_max}
            for row in variant.rows]} for variant in comparison.sensitivities],
        "limitations": [
            "All account conclusions use the approved daily price-range execution model without volume limits.",
            "Frequency and concentration use retained complete cash-flow cycles; partial buys/sells do not create extra completed cycles.",
            "C0030/C0062 lack a valid 32-point design and cannot enter recommendation ranking.",
            "No candidate selection, registration, freezing, stage-five inspection or production activation is performed.",
        ],
    }
    save("summary.json", summary)
    print(json.dumps({key: summary[key] for key in ("center_count", "parameter_design_count",
                     "parameter_account_count", "authenticated_account_count", "status_counts",
                     "acceptance_counts")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
