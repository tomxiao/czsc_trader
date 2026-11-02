"""Register the complete approved training-qualified set without account replay."""
# Cache settings must precede runtime imports.
# ruff: noqa: E402
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".tmp/s017-stage3-candidates-20261102"
SCRATCH.mkdir(parents=True, exist_ok=True)
sys.pycache_prefix = str(SCRATCH / "pycache")
os.environ["TMP"] = os.environ["TEMP"] = str(SCRATCH)
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "1"

import copy
from hashlib import sha256
import json

from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, update_research_intent,
    CandidateRegistrationRequest, register_candidate, load_candidate,
)
from czsc_trader.research_tools import EvidenceRef, ExperimentRef, ResearchBatchRef
from strategy_evaluator import compare_candidates
from strategy_evaluator import research_models as m
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition

R = RepositoryContext.discover(ROOT)
B = ResearchBatchRef("S017")
E = ExperimentRef("S017", WORK.name)
PRIOR = ROOT / "research/S017/experiments/EX074_20261102"
KEYS = ("C0338", "C0339", "C0340", "C0341", "C0342", "C0352")
CENTER_IDS = {"center-net-calmar", "center-relative-dd", "center-absolute-dd", "frequency-median", "frequency-coverage"}


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def preflight():
    request = m.CandidateComparisonRequest.from_dict(read(PRIOR / "others/se_comparison_request.json"))
    target_contract = m.ResearchTargets.from_dict(read(ROOT / "research/S017/materials/STAGE1_FINAL_CONTRACT_20261102.json")["targets"])
    assert request.targets == target_contract and len(request.targets.requirements) == 11
    result = compare_candidates(request)
    assert result.to_dict() == read(PRIOR / "others/se_comparison.json")
    qualified = []
    for row in result.rows:
        center = [check for check in row.target_checks if check.target.target_id in CENTER_IDS]
        assert len(center) == 5
        if all(check.status is m.TargetCheckStatus.PASSED for check in center):
            qualified.append(row.candidate.candidate_id.split("-")[-1])
            assert row.acceptance_status is m.TargetCheckStatus.INDETERMINATE
    assert sorted(qualified) == list(KEYS)
    analysis = read(PRIOR / "others/analysis.json")
    assert analysis["new_training_center_qualifiers"] == list(KEYS)
    rows = {row["candidate_id"]: row for row in analysis["results"]}
    candidates = {}
    for key in KEYS:
        pack = read(PRIOR / "others/definitions" / (key + ".json"))
        definition = EquityStrategyDefinition.from_dict(pack["definition"])
        candidate = EquityStrategyCandidate("S017", key, definition, ROOT / pack["source_directory"])
        assert candidate.content_identity.content_sha256 == rows[key]["record"]["evaluation_identity"]["content_sha256"]
        assert json.loads(definition.parameters_json) == rows[key]["record"]["parameters"]
        for source in pack["source_files"]:
            assert sha256(source["utf8_content"].encode()).hexdigest() == source["sha256"]
            assert digest(candidate.source_root / source["path"]) == source["sha256"]
        candidates[key] = candidate
    save(WORK / "others/preflight.json", {"status": "PASS", "qualified": list(KEYS),
        "full_targets_preserved": 11, "source_configurations": len(result.rows),
        "all_previous_comparison_results_exactly_reproduced": True,
        "full_goal_status": "INDETERMINATE_NEIGHBORHOOD_AND_STRESS_NOT_RUN",
        "new_searches": 0, "new_financial_accounts": 0,
        "search_decision": "No outstanding center qualification gap; no search performed, not a permanent prohibition",
        "source_hashes": {p.relative_to(ROOT).as_posix(): digest(p) for p in (
            PRIOR / "others/analysis.json", PRIOR / "others/se_comparison_request.json",
            PRIOR / "others/se_comparison.json", ROOT / "research/S017/materials/STAGE1_FINAL_CONTRACT_20261102.json")}})
    return rows, candidates


def main():
    rows, candidates = preflight()
    intent = copy.deepcopy(read(ROOT / "research/registrations/S017/family.json")["research_intent"])
    intent["active_stage_three_candidates_20261102"] = {
        "status": "RUNNING_REGISTRATION_AND_SNAPSHOT_LOAD_CHECKS",
        "user_statement": "同意，请你自主推进阶段三，产出符合要求的候选",
        "source_prototypes": "PROTOTYPES/13", "source_experiment": "EX074_20261102",
        "experiment": E.experiment_id, "candidate_keys": list(KEYS),
        "stage_three_authorized": True, "search_not_prohibited": True,
        "current_search_decision": "not necessary given six center-qualified prototypes; no new search",
        "stage_four_authorized": False, "sealed_test_authorized": False,
        "freeze_or_production_authorized": False,
    }
    intent["next_action"] = "自主阶段三：完整登记六个中心达标配置，验证独立源码快照可加载并发布CANDIDATES/3，不自动阶段四或封存测试。"
    update_research_intent(R, B, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="用户明确自主阶段三授权；复算完整目标后承接六个训练中心达标原型，先完成正式候选产出而不无依据追加搜索")
    registrations = {"status": "RUNNING", "new_account_computes": 0, "new_searches": 0,
                     "strategy_step_invocations": 0, "records": {}}
    save(WORK / "others/registrations.json", registrations)
    for key in KEYS:
        print("REGISTERING", key, flush=True)
        candidate = candidates[key]
        account = EvidenceRef.from_dict(rows[key]["record"]["evidence"])
        record = register_candidate(R, CandidateRegistrationRequest(
            candidate, E, (account,), tuple(candidate.definition.dependencies)))
        loaded = load_candidate(R, candidate.key)
        loaded.verify()
        assert loaded.content_identity == candidate.content_identity
        assert loaded.definition.to_dict() == candidate.definition.to_dict()
        assert loaded.source_root != candidate.source_root
        assert loaded.source_root.is_relative_to(ROOT / "research/S017/assets/candidates" / key)
        for filename in loaded.definition.source_files:
            assert (loaded.source_root / filename).read_bytes() == (candidate.source_root / filename).read_bytes()
        with loaded.bind_replay() as bound:
            assert callable(bound.function)
            namespace = bound.namespace
        assert not any(name == namespace or name.startswith(namespace + ".") for name in sys.modules)
        registrations["records"][key] = {
            "registration": record.to_dict(), "record_sha256": record.record_sha256,
            "candidate_content_sha256": loaded.content_identity.content_sha256,
            "registered_source_root": loaded.source_root.relative_to(ROOT).as_posix(),
            "definition_unchanged": True, "source_bytes_unchanged": True,
            "public_verify": "PASS", "public_load_candidate": "PASS", "public_bind_replay_import": "PASS",
            "isolated_module_cleanup": "PASS", "strategy_step_invocations": 0,
            "source_account": account.to_dict(), "evaluation_id": rows[key]["record"]["evaluation_id"],
            "training_center_all_pass": True, "full_11_target_acceptance": "INDETERMINATE",
        }
        save(WORK / "others/registrations.json", registrations)
        print("REGISTERED_AND_LOADED", key, record.content_sha256, flush=True)
    registrations["status"] = "PASS"
    assert set(registrations["records"]) == set(KEYS)
    save(WORK / "others/registrations.json", registrations)
    print("ALL_SIX_REGISTERED_AND_LOADABLE_NO_REPLAY", flush=True)


if __name__ == "__main__":
    main()
