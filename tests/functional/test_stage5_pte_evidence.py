"""Saved PTE coverage must be reproducible from named, authenticated facts."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from strategy_manager.freeze_contracts import ResearchEvidenceOwner, ResearchEvidenceRef
from czsc_trader.application.inspection_evidence import validate_pte_facts


def _fixture(root, *, alter=None, omit=None, claimed="LOAD_PREPARE", restart=False, fault=False):
    owner = ResearchEvidenceOwner("S999", "20261022_S999_EX01")

    def save(value, *, raw=False):
        content = value.encode() if raw else json.dumps(value, sort_keys=True).encode()
        digest = hashlib.sha256(content).hexdigest()
        ref = ResearchEvidenceRef(owner, "inspection/" + digest, digest)
        path = root / ref.repository_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return ref

    snapshot = dict(position_quantity=0, available_cash="10000.0000", frozen_cash="0.0000",
                    cycle_target_quantity=None, target_quantity=0, health="OK", cumulative_order_count=0,
                    expected_orders=[], decision_count=0, fills=[], intents=[], pending=0, channel={"orders": []})
    scenario = dict(scenario_id="case", initial_cash="10000", decisions=[dict(step_id="day",
                    decision_at="2026-10-20T16:00:00+08:00", submit_at="2026-10-21T09:30:00+08:00", repeat_decision=False)],
                    channel_events=[], checkpoints=[dict(checkpoint_id="decided", after_event_id="day:decision",
                    **{k: snapshot[k] for k in ("position_quantity", "available_cash", "frozen_cash", "cycle_target_quantity",
                                               "health", "cumulative_order_count", "expected_orders")})],
                    restart_after=["day:decision"] if restart else [])
    trace = [dict(event_id=event, observed_at=moment, snapshot=deepcopy(snapshot)) for event, moment in (
        ("LOAD", scenario["decisions"][0]["decision_at"]), ("day:decision", scenario["decisions"][0]["decision_at"]),
        ("day:submit", scenario["decisions"][0]["submit_at"]))]
    requirement = dict(capability=claimed, requirement="REQUIRED", scenario_ids=["case"], reason="test declared facts")
    coverage_rows = [{**requirement, "covered": True}]
    failures = [dict(case_id="bad", scenario_id="case", fault="INPUT_UNAVAILABLE", at_event_id="day:decision")] if fault else []
    protocol = {"pte": dict(environment={}, scenarios=[scenario], failures=failures, coverage=[requirement])}
    manifest, case_refs, summaries = [], {}, []

    def add(artifact_id, path, schema, value, *, raw=False):
        if artifact_id == omit:
            return None
        ref = save(value, raw=raw)
        manifest.append(dict(artifact_id=artifact_id, path=path, schema=schema, schema_version=1,
                             sha256=ref.sha256, reference=ref.to_dict()))
        return ref

    for case_id in ("case", "bad") if fault else ("case",):
        ids, refs = [], []
        for variant in ("restart", "continuous") if restart and case_id == "case" else ("restart",):
            result = dict(status="PASS", code="OK", trace=deepcopy(trace), capabilities=["LOAD_PREPARE"], position_change_applicable=False)
            if case_id == "bad":
                result = dict(status="PASS", code="INPUT_UNAVAILABLE", capabilities=["RELEVANT_FAILURE"], trace=[deepcopy(trace[0]),
                    dict(event_id="day:decision", expected_rejection="INPUT_UNAVAILABLE", actual_error="input unavailable", new_order_count=0)])
            if alter:
                alter(case_id, variant, result)
            entries = [
                ("result.json", f"scenarios/{case_id}/{variant}/result.json", "pte.inspection.result", result, False),
                ("trace.jsonl", f"scenarios/{case_id}/{variant}/trace.jsonl", "pte.inspection.trace",
                 "\n".join(json.dumps(row) for row in result["trace"] if "snapshot" in row), True),
                (variant + "-worker.log", f"scenarios/{case_id}/{variant}-worker.log", "pte.inspection.log", "", True),
            ]
            for name, path, schema, value, raw in entries:
                artifact_id = f"{case_id}:{variant}:{name}"
                ref = add(artifact_id, path, schema, value, raw=raw)
                if ref:
                    refs.append(ref)
                    ids.append(artifact_id)
        case_refs[case_id] = refs
        summaries.append(dict(case_id=case_id, status="PASS", code="OK" if case_id == "case" else "INPUT_UNAVAILABLE", artifact_ids=ids))
    summary = dict(status="PASS", coverage=coverage_rows, scenarios=summaries, channel_model="RECORDED_FILLS_V1")
    add("pte-summary", "pte-summary.json", "pte.inspection.summary", summary)
    environment = save({})
    coverage = save(dict(status="PASS", environment={}, data_kind="SYNTHETIC", channel_kind="SYNTHETIC", artifacts=manifest, coverage=coverage_rows))
    cases = [SimpleNamespace(case_id=key, status="PASS", evidence=(coverage, *refs)) for key, refs in case_refs.items()]
    cases.append(SimpleNamespace(case_id="pte-coverage", status="PASS", evidence=(coverage, *(ResearchEvidenceRef.from_dict(x["reference"]) for x in manifest))))
    return SimpleNamespace(owner=owner, environment=environment, pte_runtime=SimpleNamespace(cases=cases)), {"data_kind": "SYNTHETIC"}, protocol


@pytest.mark.parametrize("restart,fault", [(False, False), (True, False), (False, True)])
def test_named_results_and_traces_are_rechecked_without_execution(tmp_path, restart, fault):
    validate_pte_facts(tmp_path, *_fixture(tmp_path, restart=restart, fault=fault))


def test_forged_covered_summary_is_rejected(tmp_path):
    args = _fixture(tmp_path, claimed="ENTER_HOLD_EXIT")
    with pytest.raises(ValueError, match="covered flag"):
        validate_pte_facts(tmp_path, *args)


def test_omitted_named_result_is_rejected_even_when_summary_omits_it(tmp_path):
    args = _fixture(tmp_path, omit="case:restart:result.json")
    with pytest.raises(ValueError, match="named artifact missing"):
        validate_pte_facts(tmp_path, *args)


def test_real_failed_result_cannot_be_promoted_by_summary(tmp_path):
    args = _fixture(tmp_path, alter=lambda case, variant, result: result.update(status="FAIL"))
    with pytest.raises(ValueError, match="result status contradicts"):
        validate_pte_facts(tmp_path, *args)


def test_checkpoint_is_rechecked_against_trace(tmp_path):
    def alter(case, variant, result):
        result["trace"][1]["snapshot"]["position_quantity"] = 100
    args = _fixture(tmp_path, alter=alter)
    with pytest.raises(ValueError, match="checkpoint differs"):
        validate_pte_facts(tmp_path, *args)


def test_restart_trace_must_match_continuous_control(tmp_path):
    def alter(case, variant, result):
        if variant == "continuous":
            result["trace"][-1]["snapshot"]["available_cash"] = "9999.0000"
    args = _fixture(tmp_path, alter=alter, restart=True)
    with pytest.raises(ValueError, match="uninterrupted control"):
        validate_pte_facts(tmp_path, *args)


def test_fault_cannot_claim_success_with_new_order(tmp_path):
    def alter(case, variant, result):
        if case == "bad":
            result["trace"][-1]["new_order_count"] = 1
    args = _fixture(tmp_path, alter=alter, fault=True)
    with pytest.raises(ValueError, match="without new orders"):
        validate_pte_facts(tmp_path, *args)
