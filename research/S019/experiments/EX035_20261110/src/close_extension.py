"""Reconcile the authorized ten rounds and publish the retained candidate set."""
from hashlib import sha256
import json
from pathlib import Path
import sys

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


def experiments():
    return [BATCH / f"experiments/EX{i:03}_20261110" for i in range(26, 36)]


def prepare():
    rounds, rows = [], []
    for i, work in enumerate(experiments(), 1):
        config = read(work / "protocols/config.json")
        assert config["round"] == i
        if i == 1:
            assert config["candidates"] == []
            count, benchmarks, eligible = 0, 0, []
        else:
            summary, execution = [read(work / p) for p in ("others/summary.json", "others/execution.json")]
            assert execution["failures"] == []
            stats = execution["equity_statistics"]
            count, benchmarks = stats["candidate_runs"], stats["benchmark_runs"]
            assert count == len(config["candidates"]) == len(summary) and benchmarks == 1
            eligible = []
            for name, row in summary.items():
                assert row["candidate"]["eligible"] == all(row["candidate"]["gates"].values())
                rows.append((work, name, row))
                if row["candidate"]["eligible"]:
                    eligible.append(row["id"])
        rounds.append({"round": i, "stage": config["stage"], "experiment": work.name,
            "candidate_accounts": count, "benchmark_accounts": benchmarks, "eligible_ids": eligible,
            "protocol_sha256": sha256((work / "protocols/plan.md").read_bytes()).hexdigest()})
    assert len(rows) == len({row["id"] for _, _, row in rows}) == 29
    qualified = sorted([r for _, _, r in rows if r["candidate"]["eligible"]], key=lambda r: r["candidate"]["nar"], reverse=True)
    budget = {"authorization_decision": "S019-REOPEN-20261110", "authorized_rounds": 10,
        "used_rounds": 10, "remaining_rounds": 0, "candidate_accounts": 29, "benchmark_accounts": 9,
        "eligible_candidates": len(qualified), "eligible_ids_by_nar": [r["id"] for r in qualified], "rounds": rounds}
    save(WORK / "others/budget.json", budget)
    report_path = BATCH / "materials/extension_summary.md"
    lines = [report_path.read_text(encoding="utf-8").split("<!-- GENERATED_RESULTS -->")[0].rstrip(),
        "", "<!-- GENERATED_RESULTS -->", "", "## 附录：全部29个新增策略账户", "",
        "第一轮复用既有账户诊断，新增账户0；后九轮29策略加9共享买持。按实际实验顺序保留全部结果。", "",
        "|实验|配置|身份|NAR|MDD|Calmar|60日闭合中位数|至少3笔覆盖率|未通过中心门槛|",
        "|---|---|---|---:|---:|---:|---:|---:|---|"]
    labels = {"nar": "NAR", "calmar": "Calmar", "absolute_dd": "绝对MDD", "relative_dd": "相对MDD",
              "frequency_median": "频率中位数", "frequency_coverage": "频率覆盖"}
    for work, name, row in rows:
        m = row["candidate"]
        failed = "、".join(labels[k] for k, v in m["gates"].items() if not v) or "全部通过"
        lines.append(f"|[{work.name[:5]}](../experiments/{work.name}/report.md)|{name}|{row['id']}|"
            f"{m['nar']:.4%}|{m['drawdown']:.4%}|{m['calmar']:.4f}|{m['frequency_median']:g}|"
            f"{m['frequency_coverage']:.4%}|{failed}|")
    lines += ["", "[授权](../experiments/EX026_20261110/protocols/authorization.md) · "
        "[额度核对](../experiments/EX035_20261110/others/budget.json) · "
        "[独立业务核验](../experiments/EX033_20261110/others/semantic_audit.json)", "",
        "每轮报告的正式引用保存在report_ref.json。源码、配置及全部账户证据内聚保存，未达标结果全部计入搜索历史。"
        "行情与回放资产保存在本地研究资产空间，恢复需同时保留数据资产；远端同步状态尚未核验。", ""]
    report_path.write_bytes("\n".join(lines).encode())
    print("BUDGET_PASS", budget["candidate_accounts"], budget["benchmark_accounts"], budget["eligible_candidates"], flush=True)


def publish():
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef("S019")
    experiment = d.ExperimentRef("S019", WORK.name)
    context = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
    assert not (BATCH / "deliveries/CANDIDATES/2/receipt.json").exists(), "Inspect publication state before retry"
    save(WORK / "others/closing_overview.json", get_research_overview(repo, batch).to_dict())
    materials, searches, identities, candidates = {}, [], set(), []

    def material(path):
        key = path.relative_to(ROOT).as_posix()
        if key not in materials:
            ext = path.suffix[1:]
            materials[key] = publish_evidence(context, d.MaterialEvidenceWrite(experiment,
                f"extension-{len(materials):03}-{path.stem}", path.read_bytes(),
                {"json": "application/json", "md": "text/markdown", "py": "text/x-python"}[ext], ext))
        return materials[key]

    for work in experiments():
        config, publication = [read(work / p) for p in ("protocols/config.json", "others/publication.json")]
        assert publication["validation"]["status"] == "PASS"
        evidence = [d.EvidenceRef.from_dict(publication["report"]), material(work / "protocols/plan.md"),
                    material(work / "protocols/config.json")]
        summary = read(work / "others/summary.json") if config["candidates"] else {}
        if summary:
            evidence += [material(work / "others/summary.json"), material(work / "src/strategy.py"),
                         material(work / "others/execution.json")]
        else:
            evidence += [material(work / "src/diagnose.py"), material(work / "others/diagnosis.json")]
        for name, row in summary.items():
            ref = d.EvidenceRef.from_dict(row["account"])
            raw = ref.resolve(ROOT).read_bytes()
            assert sha256(raw).hexdigest() == ref.sha256
            head = json.loads(raw)
            definition = read(work / f"others/{name}_definition.json")
            assert definition == head["request"]["candidate_definition"]
            assert definition["source_sha256"] == equity_source_hash(work / "src", tuple(definition["source_files"]))
            assert head["request"]["candidate_id"] == row["id"]
            identities.add(head["request"]["content_sha256"])
            evidence += [ref, material(work / f"others/{name}_definition.json")]
            if row["candidate"]["eligible"]:
                candidate = EquityStrategyCandidate("S019", row["id"], EquityStrategyDefinition.from_dict(definition), work / "src")
                register_candidate(repo, CandidateRegistrationRequest(candidate, d.ExperimentRef("S019", work.name), (ref,), ()))
                key = CandidateKey("S019", row["id"])
                loaded = load_candidate(repo, key)
                assert loaded.definition.to_dict() == definition
                entry = d.CandidateEntry(d.CandidateIdentityRef(key, head["request"]["content_sha256"]),
                    "早期恢复与成交参与仓位配置", "中心硬门通过，阶段四稳健性尚待授权检验",
                    (d.EvaluationEvidenceRef(ref, (head["evaluation_id"],)),))
                candidates.append((row["candidate"]["nar"], entry))
        searches.append(d.SearchSummary(f"EXT-R{config['round']:02}",
            "已知账户机制诊断" if not summary else "事前固定有限对照，公共V4完整账户评价",
            f"{work.name}；{config['stage']}；2022-01-03至2026-10-30已见历史",
            len(summary), len(summary), "全部中心硬门通过后按未舍入NAR降序；诊断复用不新增配置",
            ("同一历史反复用于开发选择", "共享买持及既有账户复用单独统计", "阶段四五项正式自检待授权"), tuple(evidence)))
    assert len(identities) == 29
    for path in (Path(__file__), WORK / "others/budget.json", WORK / "others/closing_overview.json",
        BATCH / "materials/extension_summary.md", BATCH / "experiments/EX026_20261110/protocols/authorization.md",
        BATCH / "experiments/EX033_20261110/src/semantic_audit.py", BATCH / "experiments/EX033_20261110/others/audit_manifest.json",
        BATCH / "experiments/EX033_20261110/others/semantic_audit.json", BATCH / "experiments/EX013_20261110/src/runner.py",
        WORK / "others/audit_manifest.json", WORK / "others/semantic_audit.json", WORK / "others/closing_decision.json",
        BATCH / "experiments/EX003_20261110/src/data_window.py", BATCH / "experiments/EX003_20261110/others/preparation.json",
        BATCH / "experiments/EX001_20261110/src/load_data.py", BATCH / "experiments/EX001_20261110/src/prepare_data.py"):
        material(path)
    save(WORK / "others/material_manifest.json", {key: value.to_dict() for key, value in materials.items()})
    manifest = material(WORK / "others/material_manifest.json")
    predecessor = d.DeliveryReference.from_dict(read(BATCH / "deliveries/PROTOTYPES/2/receipt.json")["reference"])
    report = (BATCH / "materials/extension_summary.md").read_text(encoding="utf-8")
    report = report.replace("../experiments/", "../../../experiments/").replace("../deliveries/PROTOTYPES/", "../../PROTOTYPES/")
    candidates.sort(key=lambda x: x[0], reverse=True)
    entries = tuple(entry for _, entry in candidates)
    conclusion = f"本次10轮全部完成，29新策略及9买持，中心达标{len(entries)}个；原目标保持，正式自检尚待授权。"
    result = assemble_delivery(repo, d.DeliveryDefinition(batch, d.DeliveryStage.CANDIDATES, 2, (predecessor,)),
        d.DeliveryContent(d.CandidateSet(entries, tuple(x.identity.key for x in entries), tuple(searches), conclusion),
                          d.DeliveryStatus.COMPLETE, (), (), report=report,
                          evidence=(manifest, *[v for v in materials.values() if v != manifest])))
    save(WORK / "others/stage_publication.json", result.to_dict())
    assert result.validation.status is d.ValidationStatus.PASS and result.validation.scope is d.DeliveryValidationScope.INTEGRITY
    intent = read(ROOT / "research/registrations/S019/family.json")["research_intent"]
    intent.update(stage="STAGE_THREE", extension_status="COMPLETE", extension_delivery=result.receipt.reference.to_dict(),
        extension_budget=read(WORK / "others/budget.json"), stage_four_approval="PENDING_USER_APPROVAL" if entries else "NOT_REQUESTED_NO_ELIGIBLE_CANDIDATE",
        latest_experiment_report=read(WORK / "others/publication.json")["report"],
        next_action=read(WORK / "others/closing_decision.json")["next_action"])
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="完成用户授权的阶段二/三自主十轮，保留全部证据和原硬门")
    print("EXTENSION_DELIVERY", result.receipt.reference.content_sha256, result.validation.scope.value, result.validation.status.value, flush=True)


if __name__ == "__main__":
    {"prepare": prepare, "publish": publish}[sys.argv[1]]()
