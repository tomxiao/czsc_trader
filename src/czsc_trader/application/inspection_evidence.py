"""Recheck saved PTE facts without loading or executing a strategy."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Mapping

from paper_trading_engine.inspection_contracts import PteArtifact, PteCheckpointExpectation
from paper_trading_engine.inspection_runner import _assert_checkpoint, _comparison_snapshot
from strategy_manager.freeze_contracts import CandidateInspectionReport, ResearchEvidenceRef


def _read(reference, root):
    return json.loads(reference.resolve(root).read_text(encoding="utf-8"))


def _schedule(scenario):
    """The declared event order, including synchronous submission observations."""
    events = []
    for step in scenario["decisions"]:
        events.append((datetime.fromisoformat(step["decision_at"]), 0, step["step_id"] + ":decision"))
        if step["repeat_decision"]:
            events.append((datetime.fromisoformat(step["decision_at"]), 1, step["step_id"] + ":repeat"))
        events.append((datetime.fromisoformat(step["submit_at"]), 2, step["step_id"] + ":submit"))
    for event in scenario["channel_events"]:
        if "outcome" not in event:
            events.append((datetime.fromisoformat(event["observed_at"]), 4 if "source_event_id" in event else 3, event["event_id"]))
    result = [("LOAD", scenario["decisions"][0]["decision_at"])]
    for moment, priority, event_id in sorted(events):
        if priority == 2:
            step_id = event_id.removesuffix(":submit")
            result.extend((x["event_id"], moment.isoformat()) for x in scenario["channel_events"]
                          if "outcome" in x and x["order"]["decision_step_id"] == step_id)
        result.append((event_id, moment.isoformat()))
    return result


def _check_trace(scenario, result, *, fault=None):
    trace = result["trace"]
    expected = _schedule(scenario)
    if fault is not None:
        boundary = next((i for i, (event, _) in enumerate(expected) if event == fault["at_event_id"]), None)
        if boundary is None or not trace:
            raise ValueError("PTE fault boundary is missing")
        rejection = trace[-1]
        if (set(rejection) != {"event_id", "expected_rejection", "actual_error", "new_order_count"}
                or rejection["event_id"] != fault["at_event_id"]
                or rejection["expected_rejection"] != fault["fault"]
                or type(rejection["new_order_count"]) is not int or rejection["new_order_count"] != 0
                or not isinstance(rejection["actual_error"], str) or not rejection["actual_error"].strip()):
            raise ValueError("PTE fault has no matching rejection without new orders")
        trace, expected = trace[:-1], expected[:boundary]
    if [(row.get("event_id"), row.get("observed_at")) for row in trace] != expected:
        raise ValueError("PTE trace does not cover the declared event sequence")
    rows = {row["event_id"]: row["snapshot"] for row in trace}
    for checkpoint in scenario["checkpoints"]:
        if checkpoint["after_event_id"] in rows:
            try:
                _assert_checkpoint(PteCheckpointExpectation.from_dict(checkpoint), rows[checkpoint["after_event_id"]])
            except (AssertionError, KeyError, TypeError) as exc:
                raise ValueError("PTE checkpoint differs from saved facts") from exc
        elif fault is None:
            raise ValueError("PTE checkpoint trace is missing")
    # The runner proves repeat operations have no economic effect; recheck the
    # complete saved facts instead of relying on its capability flag.
    repeated = {x["event_id"] for x in scenario["channel_events"] if "source_event_id" in x}
    for before, after in zip(trace, trace[1:]):
        if after["event_id"].endswith(":repeat") or after["event_id"] in repeated:
            if _comparison_snapshot(before["snapshot"]) != _comparison_snapshot(after["snapshot"]):
                raise ValueError("PTE repeat changed saved account facts")
    return trace


def _capabilities(scenario, trace, *, restart):
    checkpoints = {x["after_event_id"] for x in scenario["checkpoints"]}
    snapshots = {x["event_id"]: x["snapshot"] for x in trace}
    capabilities = set()
    decisions = [x for x in trace if x["event_id"].endswith(":decision")]
    if any(x["event_id"] in checkpoints for x in decisions):
        capabilities.add("LOAD_PREPARE")
    repeated = {x["event_id"] for x in scenario["channel_events"] if "source_event_id" in x}
    if any((x["event_id"].endswith(":repeat") or x["event_id"] in repeated)
           and x["event_id"] in checkpoints for x in trace):
        capabilities.add("IDEMPOTENCE")
    updates = {x["event_id"]: x for x in scenario["channel_events"] if "status" in x}
    for event in scenario["channel_events"]:
        update = updates.get(event.get("source_event_id"), event)
        if update.get("status") in {"OPEN", "PARTIAL"} and event["event_id"] in checkpoints:
            capabilities.add("NO_OR_PARTIAL_FILL")
        if event.get("outcome") == "UNKNOWN":
            snapshot = snapshots[event["order"]["decision_step_id"] + ":submit"]
            if snapshot["health"] == "BLOCKED" and any(x["status"] == "SUBMISSION_UNCERTAIN" for x in snapshot["intents"]):
                capabilities.add("RELEVANT_FAILURE")
    final = trace[-1]["snapshot"]
    final_checkpoint = trace[-1]["event_id"] in checkpoints
    held = any(row["snapshot"]["position_quantity"] > 0 and not row["snapshot"]["expected_orders"]
               and row["event_id"] in checkpoints for row in decisions)
    positive_before_decision = any(before["snapshot"]["position_quantity"] > 0
                                  for before, after in zip(trace, trace[1:]) if after["event_id"].endswith(":decision"))
    if positive_before_decision and held and final_checkpoint and final["position_quantity"] == 0 and len(final["fills"]) >= 2:
        capabilities.add("ENTER_HOLD_EXIT")
    if (restart and final_checkpoint and any(event in checkpoints for event in scenario["restart_after"])
            and any(snapshots[event]["position_quantity"] > 0 or snapshots[event]["pending"] > 0
                    for event in scenario["restart_after"])):
        capabilities.add("RECOVERY")
    quantities = [row["snapshot"]["position_quantity"] for row in trace]
    changes = [(a, b) for a, b in zip(quantities, quantities[1:]) if a > 0 and b > 0 and a != b]
    targets = {row["snapshot"]["target_quantity"] for row in decisions}
    if any(a < b for a, b in changes) and any(a > b for a, b in changes) and len(targets) > 1:
        capabilities.add("POSITION_CHANGE")
    return capabilities


def validate_pte_facts(root: Path, report: CandidateInspectionReport,
                       normalized: Mapping, protocol: Mapping) -> None:
    """Authenticate named artifacts and independently recheck a PASS PTE goal.

    This reads only immutable evidence. It neither launches workers nor infers
    performance, strategy eligibility, or research conclusions.
    """
    cases = {case.case_id: case for case in report.pte_runtime.cases}
    if len(cases) != len(report.pte_runtime.cases) or "pte-coverage" not in cases:
        raise ValueError("passing PTE coverage evidence missing")
    coverage_case = cases["pte-coverage"]
    if not coverage_case.evidence:
        raise ValueError("passing PTE coverage evidence missing")
    coverage = _read(coverage_case.evidence[0], root)
    environment = _read(report.environment, root)
    pte = protocol["pte"]
    if (coverage["status"] != "PASS" or coverage["environment"] != environment
            or coverage["data_kind"] != normalized["data_kind"] or coverage["channel_kind"] != "SYNTHETIC"
            or any(environment[k] != v for k, v in pte["environment"].items())):
        raise ValueError("passing PTE environment or status differs")
    artifacts = {}
    for row in coverage.get("artifacts", ()):
        item = dict(row)
        reference = ResearchEvidenceRef.from_dict(item.pop("reference"))
        artifact = PteArtifact.from_dict(item)
        if (artifact.artifact_id in artifacts or reference.owner != report.owner
                or artifact.sha256 != reference.sha256 or reference not in coverage_case.evidence):
            raise ValueError("PTE artifact identity or evidence closure differs")
        reference.resolve(root)
        artifacts[artifact.artifact_id] = (artifact, reference)
    if set(coverage_case.evidence) != {coverage_case.evidence[0], *(ref for _, ref in artifacts.values())}:
        raise ValueError("PTE artifact manifest omits evidence")

    used = set()

    def artifact(artifact_id, path, schema, *, required=True):
        pair = artifacts.get(artifact_id)
        if pair is None:
            if required:
                raise ValueError(f"PTE named artifact missing: {artifact_id}")
            return None
        item, ref = pair
        if item.path != path or item.schema != schema or item.schema_version != 1:
            raise ValueError(f"PTE named artifact metadata differs: {artifact_id}")
        used.add(artifact_id)
        return ref

    summary = _read(artifact("pte-summary", "pte-summary.json", "pte.inspection.summary"), root)
    scenarios = {x["scenario_id"]: x for x in pte["scenarios"]}
    failures = {x["case_id"]: x for x in pte["failures"]}
    expected_ids = set(scenarios) | set(failures)
    summaries = {x["case_id"]: x for x in summary["scenarios"]}
    if (summary["status"] != "PASS" or summary["coverage"] != coverage["coverage"]
            or summary["channel_model"] != "RECORDED_FILLS_V1"
            or len(summaries) != len(summary["scenarios"]) or set(summaries) != expected_ids
            or set(cases) != expected_ids | {"pte-coverage"}):
        raise ValueError("PTE summary status or scenario closure differs")
    observed, applicable = {}, {}
    for case_id in sorted(expected_ids):
        fault = failures.get(case_id)
        scenario = scenarios[case_id if fault is None else fault["scenario_id"]]
        variants = ("restart", "continuous") if fault is None and scenario["restart_after"] else ("restart",)
        outputs, case_artifacts = [], set()
        for variant in variants:
            prefix, directory = f"{case_id}:{variant}:", f"scenarios/{case_id}/{variant}"
            result_ref = artifact(prefix + "result.json", directory + "/result.json", "pte.inspection.result")
            result = _read(result_ref, root)
            if result["status"] != "PASS" or result["code"] != ("OK" if fault is None else fault["fault"]):
                raise ValueError("PTE result status contradicts passing case")
            normal_trace = _check_trace(scenario, result, fault=fault)
            trace_ref = artifact(prefix + "trace.jsonl", directory + "/trace.jsonl", "pte.inspection.trace", required=bool(normal_trace))
            if trace_ref is not None:
                saved = [json.loads(line) for line in trace_ref.resolve(root).read_text(encoding="utf-8").splitlines() if line.strip()]
                if saved != normal_trace:
                    raise ValueError("PTE result trace differs from saved trace artifact")
            log_name = variant + "-worker.log"
            artifact(prefix + log_name, f"scenarios/{case_id}/{log_name}", "pte.inspection.log")
            case_artifacts.update(x for x in used if x.startswith(prefix))
            actual = {"RELEVANT_FAILURE"} if fault else _capabilities(scenario, normal_trace, restart=variant == "restart")
            if len(result["capabilities"]) != len(actual) or set(result["capabilities"]) != actual:
                raise ValueError("PTE claimed capabilities differ from saved facts")
            if fault is None and type(result.get("position_change_applicable")) is not bool:
                raise ValueError("PTE position applicability fact is missing")
            outputs.append((result, actual))
        if len(outputs) == 2:
            traces = [[(x["event_id"], _comparison_snapshot(x["snapshot"])) for x in result["trace"]] for result, _ in outputs]
            if traces[0] != traces[1] or outputs[0][0]["position_change_applicable"] != outputs[1][0]["position_change_applicable"]:
                raise ValueError("PTE restarted run differs from uninterrupted control")
        result, observed[case_id] = outputs[0]
        applicable[case_id] = result.get("position_change_applicable")
        recorded = summaries[case_id]
        if (recorded["status"] != "PASS" or recorded["code"] != result["code"]
                or len(recorded["artifact_ids"]) != len(case_artifacts) or set(recorded["artifact_ids"]) != case_artifacts
                or str(cases[case_id].status) != "PASS"
                or set(cases[case_id].evidence) != {coverage_case.evidence[0], *(artifacts[x][1] for x in case_artifacts)}):
            raise ValueError("PTE case result or artifact closure differs")
    if used != set(artifacts):
        raise ValueError("PTE manifest contains unexpected artifacts")
    if len(coverage["coverage"]) != len(pte["coverage"]):
        raise ValueError("PTE capability coverage differs")
    for declared, recorded in zip(pte["coverage"], coverage["coverage"], strict=True):
        if {k: recorded[k] for k in ("capability", "requirement", "scenario_ids", "reason")} != declared:
            raise ValueError("PTE coverage declaration differs")
        ids = list(declared["scenario_ids"])
        if declared["capability"] == "RELEVANT_FAILURE":
            ids.extend(x["case_id"] for x in failures.values() if x["scenario_id"] in ids)
        if declared["requirement"] == "NOT_APPLICABLE":
            ids = ids or list(scenarios)
            covered = bool(ids) and all(applicable[x] is False for x in ids)
        else:
            covered = any(declared["capability"] in observed[x] for x in ids)
        if recorded["covered"] is not True or not covered:
            raise ValueError("PTE covered flag is unsupported by saved facts")
