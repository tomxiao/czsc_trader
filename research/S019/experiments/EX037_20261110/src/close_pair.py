"""Publish both completed joint searches and preserve the remaining authorization."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, assemble_delivery, create_research_context,
    get_research_overview, publish_evidence, update_research_intent,
    CandidateRegistrationRequest, register_candidate, load_candidate,
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
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef("S019")
    context = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
    exp = d.ExperimentRef("S019", WORK.name)
    assert not (BATCH / "deliveries/CANDIDATES/3/receipt.json").exists(), "Inspect published state before retry"
    save(WORK / "others/closing_overview.json", get_research_overview(repo, batch).to_dict())
    materials, searches, entries, rows, registrations = {}, [], [], [], []

    def material(path):
        key = path.relative_to(ROOT).as_posix()
        if key not in materials:
            ext = path.suffix[1:]
            materials[key] = publish_evidence(context, d.MaterialEvidenceWrite(exp, f"joint-{len(materials):03}-{path.stem}",
                path.read_bytes(), {"json": "application/json", "md": "text/markdown", "py": "text/x-python"}[ext], ext))
        return materials[key]

    for number in (36, 37):
        work = BATCH / f"experiments/EX{number:03}_20261110"
        config, design, summary, review, publication = [read(work / p) for p in
            ("protocols/config.json", "protocols/search.json", "others/summary.json", "others/search_review.json", "others/publication.json")]
        assert publication["validation"]["status"] == "PASS" and read(work / "others/center_parity.json")["status"] == "PASS"
        trials = read(work / "others/trials.json")["trials"]
        assert len(trials) == 48 and all(t["state"] == "COMPLETE" for t in trials)
        assert len(summary) == len(config["candidates"]) == review["unique_configurations"]
        evidence = [d.EvidenceRef.from_dict(publication["report"])]
        for path in [*sorted((work / "src").glob("*.py")), *sorted((work / "protocols").glob("*")),
                     *sorted((work / "others").glob("*.json"))]:
            if path.name not in {"publication.json", "closing_overview.json"}:
                evidence.append(material(path))
        eligible = []
        for name, row in summary.items():
            ref = d.EvidenceRef.from_dict(row["account"])
            raw = ref.resolve(ROOT).read_bytes()
            assert sha256(raw).hexdigest() == ref.sha256
            head, definition = json.loads(raw), read(work / f"others/{name}_definition.json")
            assert head["request"]["candidate_definition"] == definition
            assert definition["source_sha256"] == equity_source_hash(work / "src", tuple(definition["source_files"]))
            assert row["candidate"]["eligible"] == all(row["candidate"]["gates"].values())
            evidence.append(ref)
            if row["candidate"]["eligible"]:
                key = CandidateKey("S019", row["id"])
                candidate = EquityStrategyCandidate("S019", row["id"], EquityStrategyDefinition.from_dict(definition), work / "src")
                registration = register_candidate(repo, CandidateRegistrationRequest(candidate, d.ExperimentRef("S019", work.name),
                    (ref,), tuple(candidate.definition.dependencies)))
                loaded = load_candidate(repo, key)
                assert json.loads(json.dumps(loaded.definition.to_dict())) == definition
                registrations.append(registration.to_dict())
                entry = d.CandidateEntry(d.CandidateIdentityRef(key, head["request"]["content_sha256"]),
                    f"承接{design['parent']}结构的联合参数配置", "完整账户通过全部中心经济及频率门槛；正式稳健性自检尚待授权",
                    (d.EvaluationEvidenceRef(ref, (head["evaluation_id"],)),))
                entries.append((row["candidate"]["nar"], entry))
                eligible.append(row["id"])
        rows.append({"round": config["round"], "experiment": work.name, "parent": design["parent"],
            "proposals": len(trials), "unique_configurations": len(summary),
            "candidate_accounts": review["candidate_accounts"], "benchmark_accounts": review["benchmark_accounts"],
            "eligible_ids": eligible, "protocol_sha256": sha256((work / "protocols/plan.md").read_bytes()).hexdigest()})
        searches.append(d.SearchSummary(f"JOINT-{design['parent']}",
            "Optuna4.9.0多变量约束TPE；启动16次、48次提议、4个一批固定顺序反馈；完整账户无剪枝",
            f"{work.name}；{len(design['space'])}维空间绑定search.json；2022-01-03至2026-10-30已见历史",
            len(trials), len(summary), "六项中心硬门全部通过后按未舍入NAR降序",
            ("重复使用的开发历史", "48次预算的有限探索，未穷尽空间", "两研究族搜索维度不同", "正式五项自检未开展"), tuple(evidence)))
    budget = {"authorization_decision": "S019-JOINT-20261110", "authorized_rounds": 10, "used_rounds": 2,
        "remaining_rounds": 8, "proposals": sum(r["proposals"] for r in rows),
        "unique_configurations": sum(r["unique_configurations"] for r in rows),
        "candidate_accounts": sum(r["candidate_accounts"] for r in rows),
        "benchmark_accounts": sum(r["benchmark_accounts"] for r in rows), "eligible_candidates": len(entries), "rounds": rows}
    save(WORK / "others/budget.json", budget)
    save(WORK / "others/candidate_registrations.json", registrations)
    for path in (Path(__file__), WORK / "others/budget.json", WORK / "others/candidate_registrations.json",
        WORK / "others/closing_overview.json", WORK / "others/closing_decision.json", BATCH / "materials/joint_search_comparison.md",
        BATCH / "experiments/EX036_20261110/src/joint_search.py", BATCH / "experiments/EX036_20261110/protocols/authorization.md",
        BATCH / "experiments/EX013_20261110/src/runner.py", BATCH / "experiments/EX003_20261110/src/data_window.py",
        BATCH / "experiments/EX003_20261110/others/preparation.json", BATCH / "experiments/EX001_20261110/src/load_data.py",
        BATCH / "experiments/EX001_20261110/src/prepare_data.py"):
        material(path)
    save(WORK / "others/material_manifest.json", {k: v.to_dict() for k, v in materials.items()})
    manifest = material(WORK / "others/material_manifest.json")
    predecessor = d.DeliveryReference.from_dict(read(BATCH / "deliveries/PROTOTYPES/2/receipt.json")["reference"])
    report = (BATCH / "materials/joint_search_comparison.md").read_text(encoding="utf-8").replace("../experiments/", "../../../experiments/")
    entries.sort(key=lambda x: x[0], reverse=True)
    selected = tuple(entry for _, entry in entries)
    result = assemble_delivery(repo, d.DeliveryDefinition(batch, d.DeliveryStage.CANDIDATES, 3, (predecessor,)),
        d.DeliveryContent(d.CandidateSet(selected, tuple(x.identity.key for x in selected), tuple(searches),
            f"完成两轮联合搜索，96次提议，中心达标{len(entries)}个；新增十轮额度剩余8轮，正式自检尚未开展。"),
            d.DeliveryStatus.COMPLETE, (), (), report=report, evidence=(manifest, *[v for v in materials.values() if v != manifest])))
    save(WORK / "others/stage_publication.json", result.to_dict())
    assert result.validation.status is d.ValidationStatus.PASS and result.validation.scope is d.DeliveryValidationScope.INTEGRITY
    intent = read(ROOT / "research/registrations/S019/family.json")["research_intent"]
    intent.update(stage="STAGE_THREE", joint_search_status="PAIR_COMPLETE", joint_search_budget=budget,
        joint_search_delivery=result.receipt.reference.to_dict(), latest_experiment_report=read(WORK / "others/publication.json")["report"],
        stage_four_approval="PENDING_USER_APPROVAL" if entries else "NOT_REQUESTED_NO_ELIGIBLE_CANDIDATE",
        next_action=read(WORK / "others/closing_decision.json")["next_action"])
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="完成用户要求的C0067和C0101各一轮联合搜索，保存全部达标配置、负面证据及剩余额度")
    print("PAIR_DELIVERY", result.receipt.reference.content_sha256, result.validation.scope.value, result.validation.status.value, flush=True)


if __name__ == "__main__":
    main()
