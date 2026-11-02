"""Publish the RSCH-selected bounded method, preserving confirmed numerical gates."""
# ruff: noqa: E402
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
OUT = WORK / "others/bounded_v1"
SCRATCH = ROOT / ".tmp/s017-bounded-v1-mandate"
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = str(SCRATCH)
sys.pycache_prefix = str(SCRATCH / "pycache")

from dataclasses import replace
from hashlib import sha256
import json

from dataflows import ProviderConfig
from czsc_trader.application import (RepositoryContext, create_research_context,
    get_research_overview, publish_evidence, assemble_delivery)
from czsc_trader import research_tools as d
from strategy_evaluator import research_models as m
from strategy_runtime import ExecutionResources, canonical_sha256


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def main():
    if (OUT / "mandate_reference.json").exists():
        raise RuntimeError("Bounded mandate already published; inspect its immutable reference")
    repository = RepositoryContext.discover(ROOT)
    batch, experiment = d.ResearchBatchRef("S017"), d.ExperimentRef("S017", WORK.name)
    overview = get_research_overview(repository, batch)
    source = next(item.reference for item in overview.deliveries if item.stage is d.DeliveryStage.MANDATE)
    candidates = next(item.reference for item in overview.deliveries if item.stage is d.DeliveryStage.CANDIDATES)
    assert source.revision == 8 and source.content_sha256 == "63c77aced4cb43e4f317c6cbf787a0a629d7c8955e441358a9ca64a1b0513d74"
    assert candidates.revision == 3 and candidates.content_sha256 == "98eb8a596b0cf07a7f35e75d4e5e30d01d3dba374b97726543ba693911dd4f68"
    document = read(ROOT / "research/S017/assets/deliveries/MANDATE/8/delivery.json")
    previous = d.DeliveryContent.from_dict(document["content"])
    assert previous.status is d.DeliveryStatus.COMPLETE and not previous.incomplete_items
    targets = m.ResearchTargets.from_dict(read(WORK / "others/calmar_v2_targets.json"))
    accepted = read(WORK / "others/calmar_v2_rsch_acceptance.json")
    policy = m.ComparisonPolicy.from_dict(accepted["policy"])
    protocol = m.CalmarSelfCheckProtocol.from_dict(accepted["protocol"])
    inherited = {target.target_id: target for item in previous.payload.items
                 if isinstance(item.requirement, d.PerformanceRequirement) for target in item.requirement.targets}
    assert inherited == {target.target_id: target for target in targets.requirements}
    proposal = read(WORK / "others/bounded_parameter_check_proposal.json")
    construction_sha = canonical_sha256(proposal["construction"])
    assert construction_sha == "d7d8ce3141d97f7502bef9a7df5213e320c8388e037ac718c10fa682f9471534"
    point_sets = {key: {"source_full_design_sha256": value["source_full_design_sha256"],
        "source_point_indices": [point["source_full_plan_point_index"] for point in value["proposed_points"]],
        "N": value["proposed_N"], "minimum_joint_passes": value["proposed_required_joint_passes"]}
        for key, value in proposal["centers"].items()}
    assert sum(value["N"] for value in point_sets.values()) == 257
    for value in point_sets.values():
        assert len(set(value["source_point_indices"])) == value["N"]
        assert value["minimum_joint_passes"] == (13 * value["N"] + 15) // 16
    authorization = {"schema": "s017-user-stage4-continuation-authorization/v1",
        "user_instruction": "切换RSCH，继续完成阶段四", "source": "current user instruction relayed by parent agent",
        "interpretation": "resume stage four and allow RSCH to implement the reviewed bounded method autonomously",
        "user_numerical_targets_unchanged": True, "method_owner": "RSCH",
        "not_claiming_user_specified_each_of_257_points": True, "sealed_2026_data_authorized": False}
    protocol_value = {"schema": "s017-confirmed-bounded-stage4/v3", "role": "RSCH",
        "status": "ADOPTED_BY_RSCH_UNDER_USER_STAGE4_CONTINUATION_AUTHORIZATION",
        "source_mandate": source.to_dict(), "source_candidates": candidates.to_dict(),
        "overview_metadata_snapshot_sha256": overview.snapshot.content_sha256,
        "authorization": authorization, "scope": {"candidates": list(point_sets),
            "window": "TRAIN_2024_2025", "history_start": "2023-11-01", "initial_cash": 100000.,
            "standard_one_way_cost": .001, "pressure_one_way_cost": .002,
            "drawdown_basis": "BAR_CLOSE", "concentration_basis": "MAX_SINGLE",
            "sealed_2026_market_data_or_results_authorized": False},
        "construction": proposal["construction"], "construction_sha256": construction_sha,
        "construction_hash_algorithm": "strategy_runtime.canonical_sha256(construction)",
        "point_sets": point_sets, "targets": targets.to_dict(), "protocol": protocol.to_dict(),
        "policy": policy.to_dict(), "comparison": {"type": "DeclaredPointSetComparisonContract",
            "construction_sha256": construction_sha, "source_scale": m.CommonNeighborhoodComparisonContract(
                m.RelativeChangeLimit(.05), tuple(m.ZeroCenterAbsoluteLimit(name, m.AbsoluteChangeLimit(.05))
                    for name in ("g_when_u", "g_when_other", "g_when_mf"))).to_dict()},
        "budget": {"parameter_strategy_accounts": 257, "center_standard_accounts": 6,
            "center_pressure_accounts": 6, "maximum_strategy_accounts": 269, "maximum_shared_benchmark_accounts": 2,
            "historical_65_counted_as_current_execution": 0, "target_minutes": 45,
            "target_is_hard_deadline": False, "target_is_sla": False,
            "after_target": "record elapsed/remaining estimate and finish within the same declared workload; no extra search or point expansion",
            "max_workers": 12, "native_threads_per_worker": 1, "public_tdr_session_only": True,
            "suggested_batch_size": 12, "independent_audit_required": False},
        "historical_handling": {"old_65_not_automatically_compatible": True,
            "old_implementation_checkpoints_not_resumed": True, "old_account_bindings_not_resigned": True,
            "new_plans_required_for_current_execution": True,
            "old_failures_and_unfinished_2829_point_contract_preserved": True,
            "old_annual_gate_failure_not_itself_new_calmar_gate_failure": True,
            "posthoc_method_redesign_disclosed": True},
        "five_selfchecks": ["center and stress account completeness plus confirmed hard gates",
            "all 257 declared parameter points, joint counts, every-point DD and Q10/Q90",
            "same-ledger annual and rolling-252-step-21 time stability report",
            "pressure hard gates, Calmar loss, profit concentration and historical counterevidence",
            "paired uncertainty and family-data availability, schema15 FULL numerical delivery and RSCH recommendation"],
        "completion": {"all_candidates_must_pass": False, "technical_missing_is_not_completion": True,
            "unavailable_report_only_family_diagnostics_disclosed": True,
            "rsch_final_hard_gate_verification_required": True, "assessment_schema_version": 15,
            "sealed_test_or_stage5_or_freeze_automatic": False}}
    protocol_path = WORK / "protocols/confirmed_bounded_stage4_v3.json"
    save(protocol_path, protocol_value)
    save(OUT / "resume_authorization.json", authorization)
    benchmark = next(item.requirement.benchmark for item in previous.payload.items
                     if isinstance(item.requirement, d.BenchmarkRequirement))
    context = create_research_context(repository, batch, providers=ProviderConfig(bindings={}, equity_bindings={}),
        execution_spec=benchmark.execution.execution_spec, resources=ExecutionResources(1, 1, 17))
    refs = {}
    for name, path, mime in (
        ("bounded-stage4-v3-authorization", OUT / "resume_authorization.json", "application/json"),
        ("bounded-stage4-v3-protocol", protocol_path, "application/json"),
        ("bounded-stage4-v3-method", WORK / "protocols/confirmed_bounded_stage4_v3.md", "text/markdown"),
        ("bounded-stage4-v3-geometry", WORK / "others/bounded_parameter_check_proposal.json", "application/json"),
        ("bounded-stage4-v3-platform-acceptance", WORK / "others/dev_auditable_stage4_rsch_acceptance.json", "application/json")):
        refs[name] = publish_evidence(context, d.MaterialEvidenceWrite(experiment, name,
            path.read_bytes(), mime, path.suffix[1:]))
    confirmed = d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, refs["bounded-stage4-v3-protocol"])
    items = []
    for item in previous.payload.items:
        if item.item_id == "resources":
            item = replace(item, statement="用户已恢复阶段四；公共TDR会话最多12进程、每进程1线程、小批12，45分钟为目标及重估节点；硬上限269策略账户加最多2共享买持，不扩点或新增搜索",
                           confirmation=confirmed)
        elif item.item_id == "data":
            item = replace(item, statement="仅使用既定2024-2025训练及2023-11预热资料完成六候选阶段四；2026真实行情及结果仍封存，不授权阶段五、冻结或生产变更", confirmation=confirmed)
        elif item.item_id == "calmar-selfcheck-protocol-v2":
            item = replace(item, statement="既定CalmarSelfCheckProtocol/v8与v6数值规则不变；本轮输入为固定257点声明集合及共同构造合同，不冒称旧2829点全邻域完成；RSCH最终核验硬门，TDR只按显式输入计算", confirmation=confirmed)
        items.append(item)
    items.append(d.MandateItem("bounded-parameter-point-set-v3", d.MandateItemKind.EXECUTION,
        "全部合法单参数方向加每中心32个F=A×B×C×D×E联合点；N=43/42/43/43/42/44，等权声明全集；保留真实边界和原点编号；Q10/Q90仅指该集合", confirmed))
    mandate = d.ResearchMandate(tuple(items))
    inherited_after = {target.target_id: target for item in mandate.items
                       if isinstance(item.requirement, d.PerformanceRequirement) for target in item.requirement.targets}
    assert inherited_after == inherited
    report = (WORK / "protocols/confirmed_bounded_stage4_v3.md").read_text(encoding="utf-8")
    result = assemble_delivery(repository, d.DeliveryDefinition(batch, d.DeliveryStage.MANDATE, 9, (source,)),
        d.DeliveryContent(mandate, d.DeliveryStatus.COMPLETE, (), (), report=report,
            evidence=tuple(refs.values())), resources=ExecutionResources(1, 1, 17))
    assert result.validation.status is d.ValidationStatus.PASS
    save(OUT / "mandate_reference.json", result.receipt.reference.to_dict())
    save(OUT / "mandate_publication.json", {"status": "MANDATE_9_FULL_PASS", "reference": result.receipt.reference.to_dict(),
        "validation": result.validation.to_dict(), "protocol_reference": refs["bounded-stage4-v3-protocol"].to_dict(),
        "authorization_reference": refs["bounded-stage4-v3-authorization"].to_dict(),
        "targets_unchanged": True, "new_account_replays_in_publication": 0,
        "protocol_file_sha256": sha256(protocol_path.read_bytes()).hexdigest()})
    print("MANDATE_9_FULL_PASS", result.receipt.reference.content_sha256, construction_sha, flush=True)


if __name__ == "__main__":
    main()
