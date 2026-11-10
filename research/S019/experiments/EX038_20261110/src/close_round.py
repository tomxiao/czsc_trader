"""Register every center-qualified configuration and publish round-three evidence."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, assemble_delivery, create_research_context,
    publish_evidence, update_research_intent, CandidateRegistrationRequest,
    register_candidate, load_candidate,
)
from dataflows import ProviderConfig
from strategy_runtime import equity_source_hash, EquityStrategyCandidate, EquityStrategyDefinition
from strategy_manager import CandidateKey

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
BATCH = ROOT / "research/S019"


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def main():
    repo, batch = RepositoryContext.discover(ROOT), d.ResearchBatchRef("S019")
    context = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
    exp = d.ExperimentRef("S019", WORK.name)
    assert not (BATCH / "deliveries/CANDIDATES/4/receipt.json").exists(), "Inspect published state before retry"
    config, design, summary, review, publication = [read(WORK / p) for p in
        ("protocols/config.json", "protocols/search.json", "others/summary.json", "others/search_review.json", "others/publication.json")]
    assert publication["validation"]["status"] == read(WORK / "others/center_parity.json")["status"] == "PASS"
    report_ref = d.EvidenceRef.from_dict(publication["report"])
    report_payload = report_ref.resolve(ROOT).read_bytes()
    assert sha256(report_payload).hexdigest() == report_ref.sha256
    assert sha256((WORK / "report.md").read_bytes()).hexdigest() == json.loads(report_payload)["report_sha256"]
    trials = read(WORK / "others/trials.json")["trials"]
    assert len(trials) == design["trial_budget"] == 48 and all(t["state"] == "COMPLETE" for t in trials)
    assert len(summary) == len(config["candidates"]) == review["unique_configurations"]
    assert review["candidate_accounts"] == len(summary)
    audit = read(WORK / "others/semantic_audit.json")
    assert audit["manifest_sha256"] == sha256((WORK / "others/audit_manifest.json").read_bytes()).hexdigest()
    assert audit["audit_source_sha256"] == sha256((WORK / "src/semantic_audit.py").read_bytes()).hexdigest()
    assert all(x["business_rules"] == x["signal_availability"] == x["holding_and_position_feedback"] == "PASS" for x in audit["results"])
    materials, entries, registrations = {}, [], []
    evidence = [d.EvidenceRef.from_dict(publication["report"])]
    for name, row in summary.items():
        ref = d.EvidenceRef.from_dict(row["account"])
        raw = ref.resolve(ROOT).read_bytes()
        assert sha256(raw).hexdigest() == ref.sha256
        head, definition = json.loads(raw), read(WORK / f"others/{name}_definition.json")
        assert head["request"]["candidate_definition"] == definition
        assert definition["source_sha256"] == equity_source_hash(WORK / "src", tuple(definition["source_files"]))
        assert row["candidate"]["eligible"] == all(row["candidate"]["gates"].values())
        evidence.append(ref)
        if row["candidate"]["eligible"]:
            key = CandidateKey("S019", row["id"])
            candidate = EquityStrategyCandidate("S019", row["id"], EquityStrategyDefinition.from_dict(definition), WORK / "src")
            registration = register_candidate(repo, CandidateRegistrationRequest(candidate, exp,
                (ref,), tuple(candidate.definition.dependencies)))
            loaded = load_candidate(repo, key)
            assert json.loads(json.dumps(loaded.definition.to_dict())) == definition
            registrations.append(registration.to_dict())
            entry = d.CandidateEntry(d.CandidateIdentityRef(key, head["request"]["content_sha256"]),
                "前日下跌后首30分钟恢复入场；成交参与和季度相对走势联合仓位，ATR跟踪及五日退出",
                "完整连续账户通过全部中心经济与频率门槛；正式稳健性自检尚待授权",
                (d.EvaluationEvidenceRef(ref, (head["evaluation_id"],)),))
            entries.append((row["candidate"]["nar"], entry))
    entries.sort(key=lambda x: x[0], reverse=True)
    assert [x.identity.key.candidate_id for _, x in entries] == review["eligible_ids_by_nar"]
    previous = read(BATCH / "experiments/EX037_20261110/others/budget.json")
    this_round = {"round": 3, "experiment": WORK.name, "parent": "C0196", "proposals": len(trials),
        "unique_configurations": len(summary), "candidate_accounts": review["candidate_accounts"],
        "benchmark_accounts": review["benchmark_accounts"], "eligible_ids": review["eligible_ids_by_nar"],
        "protocol_sha256": sha256((WORK / "protocols/plan.md").read_bytes()).hexdigest()}
    budget = {**previous, "used_rounds": 3, "remaining_rounds": 7,
        "proposals": previous["proposals"] + len(trials),
        "unique_configurations": previous["unique_configurations"] + len(summary),
        "candidate_accounts": previous["candidate_accounts"] + review["candidate_accounts"],
        "benchmark_accounts": previous["benchmark_accounts"] + review["benchmark_accounts"],
        "eligible_candidates": len(entries), "rounds": [*previous["rounds"], this_round]}
    signatures = []
    for number in (36, 37, 38):
        old_work = BATCH / f"experiments/EX{number:03}_20261110"
        for name in read(old_work / "others/summary.json"):
            definition = read(old_work / f"others/{name}_definition.json")
            signatures.append((definition["source_sha256"],
                json.dumps(json.loads(definition["parameters_json"]), sort_keys=True)))
    budget.update(configuration_count_basis="unique_configurations sums within-round unique counts; exact cross-round repetition reported separately",
        distinct_configurations_across_rounds=len(set(signatures)),
        repeated_configurations_across_rounds=len(signatures)-len(set(signatures)))
    save(WORK / "others/budget.json", budget)
    save(WORK / "others/candidate_registrations.json", registrations)

    def material(path):
        key = path.relative_to(ROOT).as_posix()
        if key not in materials:
            ext = path.suffix[1:]
            materials[key] = publish_evidence(context, d.MaterialEvidenceWrite(exp,
                f"round-three-{len(materials):03}-{path.stem}", path.read_bytes(),
                {"json": "application/json", "md": "text/markdown", "py": "text/x-python"}[ext], ext))
        return materials[key]

    for path in [*sorted((WORK / "src").glob("*.py")), *sorted((WORK / "protocols").glob("*")),
                 *sorted((WORK / "others").glob("*.json"))]:
        if path.name not in {"publication.json", "stage_publication.json", "material_manifest.json"}:
            evidence.append(material(path))
    for path in config["controls"]:
        evidence.append(d.EvidenceRef.from_dict(read(ROOT / path)))
    for path in (BATCH / "experiments/EX036_20261110/protocols/authorization.md",
                 BATCH / "experiments/EX037_20261110/others/budget.json",
                 BATCH / "deliveries/CANDIDATES/3/receipt.json",
                 BATCH / "materials/joint_search_comparison.md"):
        evidence.append(material(path))
    save(WORK / "others/material_manifest.json", {k: v.to_dict() for k, v in materials.items()})
    manifest = material(WORK / "others/material_manifest.json")
    search = d.SearchSummary("C0196-SHORT-SPAN-JOINT",
        "Optuna4.9.0多变量约束TPE；48提议、16启动、4并发；完整账户无剪枝",
        "下跌1日持有5日固定；五维域及3—20日跨度见绑定方案；同MANDATE/2已见历史",
        len(trials), len(summary), "全部六项中心硬门通过后按未舍入NAR降序",
        ("已见开发历史与自适应选择", "有限48次提议覆盖", "正式五项自检尚待授权"), tuple(evidence))
    predecessor = d.DeliveryReference.from_dict(read(BATCH / "deliveries/PROTOTYPES/2/receipt.json")["reference"])
    selected = tuple(entry for _, entry in entries)
    narrative = read(WORK / "others/interpretation.json")
    report = "# S019阶段三：C0196短跨度联合扩展\n\n" + narrative["conclusion"] + "\n\n" + narrative["findings"]
    report += "\n\n" + narrative["next"] + "\n\n"
    report += f"新增授权已用3/10轮、剩余7轮；本轮48次提议、{len(summary)}个不同配置；全部中心达标{len(entries)}个。"
    report += "中心达标配置全部登记、按原始NAR降序；正式参数扰动、费用压力与阶段四五项自检尚待批准。\n\n"
    report += "[本轮完整报告](../../../experiments/EX038_20261110/report.md) · [前两轮交付](../3/report.md) · [额度](../../../experiments/EX038_20261110/others/budget.json)\n\n"
    report += "|候选|NAR|MDD|Calmar|\n|---|---:|---:|---:|\n"
    for name in sorted(summary, key=lambda n: summary[n]["candidate"]["nar"], reverse=True):
        row = summary[name]
        if row["candidate"]["eligible"]:
            m = row["candidate"]
            report += f"|{row['id']}|{m['nar']:.6%}|{m['drawdown']:.6%}|{m['calmar']:.8f}|\n"
    result = assemble_delivery(repo, d.DeliveryDefinition(batch, d.DeliveryStage.CANDIDATES, 4, (predecessor,)),
        d.DeliveryContent(d.CandidateSet(selected, tuple(x.identity.key for x in selected), (search,),
            f"第3轮完成；中心达标{len(entries)}个，全部留存；10轮额度剩余7轮。"),
            d.DeliveryStatus.COMPLETE, (), (), report=report,
            evidence=(manifest, *[value for value in materials.values() if value != manifest])))
    save(WORK / "others/stage_publication.json", result.to_dict())
    assert result.validation.status is d.ValidationStatus.PASS and result.validation.scope is d.DeliveryValidationScope.INTEGRITY
    intent = read(ROOT / "research/registrations/S019/family.json")["research_intent"]
    intent.update(stage="STAGE_THREE", joint_search_status="ROUND_THREE_COMPLETE", joint_search_budget=budget,
        joint_search_delivery=result.receipt.reference.to_dict(), latest_experiment_report=publication["report"],
        stage_four_approval="PENDING_USER_APPROVAL" if entries else "NOT_REQUESTED_NO_ELIGIBLE_CANDIDATE",
        next_action=narrative["next"])
    intent.pop("active_round_budget", None)
    intent.pop("active_experiment", None)
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="完成批准的C0196短跨度联合扩展，登记全部中心达标配置并保留7轮额度。")
    print("ROUND_THREE_DELIVERY", len(entries), result.validation.status.value, result.receipt.reference.content_sha256, flush=True)


if __name__ == "__main__":
    main()
