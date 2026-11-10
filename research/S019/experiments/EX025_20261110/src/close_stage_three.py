"""Publish the complete negative stage-three search; never launch another trial."""
from hashlib import sha256
import json
from pathlib import Path
import sys

from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, assemble_delivery, create_research_context,
    get_research_overview, publish_evidence, update_research_intent,
)
from dataflows import ProviderConfig
from strategy_runtime import equity_source_hash

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
BATCH = ROOT / "research/S019"
CONCLUSION = "阶段三十轮32个新策略账户全部完成，0个通过全部中心硬门。保留C0067研究前沿，建议停止继续细调当前结构并重新审视收益机制。"


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def experiments():
    return [BATCH / f"experiments/EX{i:03}_20261110" for i in range(16, 26)]


def prepare():
    rounds, all_rows = [], []
    for i, work in enumerate(experiments(), 1):
        config, summary, execution = [read(work / path) for path in
            ("protocols/config.json", "others/summary.json", "others/execution.json")]
        assert config["round"] == i and execution["failures"] == []
        stats = execution["equity_statistics"]
        assert stats["candidate_runs"] == len(config["candidates"]) == len(summary)
        assert stats["benchmark_runs"] == 1
        for row in summary.values():
            m = row["candidate"]
            assert m["eligible"] == all(m["gates"].values()) and not m["eligible"]
            all_rows.append((work.name, row))
        rounds.append({"round": i, "experiment": work.name, "candidate_accounts": stats["candidate_runs"],
            "benchmark_accounts": stats["benchmark_runs"], "eligible_ids": [],
            "protocol_sha256": sha256((work / "protocols/plan.md").read_bytes()).hexdigest()})
    assert len(all_rows) == 32 and len({r[1]["id"] for r in all_rows}) == 32
    save(WORK / "others/budget.json", {"authorization_decision": "S019-STAGE3-20261110", "authorized_rounds": 10,
        "used_rounds": 10, "remaining_rounds": 0, "candidate_accounts": 32, "benchmark_accounts": 10,
        "eligible_candidates": 0, "rounds": rounds})
    report_path = BATCH / "materials/stage_three_summary.md"
    lines = [report_path.read_text(encoding="utf-8").split("<!-- GENERATED_RESULTS -->")[0].rstrip(),
        "", "<!-- GENERATED_RESULTS -->", "", "## 附录：全部32个新策略账户", "",
        "按实际实验顺序列示，所有数值来自公开工具的完整账户；当前达标集合为空。", "",
        "|实验|配置|身份|NAR|MDD|Calmar|60日闭合中位数|至少3笔覆盖率|未通过中心门槛|",
        "|---|---|---|---:|---:|---:|---:|---:|---|"]
    labels = {"nar": "NAR", "calmar": "Calmar", "absolute_dd": "绝对MDD", "relative_dd": "相对MDD",
              "frequency_median": "频率中位数", "frequency_coverage": "频率覆盖"}
    for work in experiments():
        for name, row in read(work / "others/summary.json").items():
            m = row["candidate"]
            failed = "、".join(labels[k] for k, v in m["gates"].items() if not v)
            lines.append(f"|[{work.name[:5]}](../experiments/{work.name}/report.md)|{name}|{row['id']}|"
                f"{m['nar']:.4%}|{m['drawdown']:.4%}|{m['calmar']:.4f}|{m['frequency_median']:g}|"
                f"{m['frequency_coverage']:.4%}|{failed}|")
    lines += ["", "[授权依据](../experiments/EX016_20261110/protocols/authorization.md) · "
        "[额度与执行核对](../experiments/EX025_20261110/others/budget.json) · "
        "[独立逐决定业务核验](../experiments/EX025_20261110/others/semantic_audit.json)", "",
        "每个实验报告的不可变引用保存在report_ref.json，方案、完整配置、源码、账户引用及分析内聚保留。"
        "正式CANDIDATES/1保存空达标候选集合、全部十轮搜索概要与直接证据；该交付工作完整，目标仍未达成。"
        "账户、行情和执行资产位于本批次本地资产空间，远端同步状态尚未核验，恢复需同时保留数据资产。", ""]
    report_path.write_bytes("\n".join(lines).encode())
    print("BUDGET_PASS", len(all_rows), 10, 0, flush=True)


def publish():
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef("S019")
    experiment = d.ExperimentRef("S019", WORK.name)
    context = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
    assert not (BATCH / "deliveries/CANDIDATES/1/receipt.json").exists(), "Inspect published state before retry"
    save(WORK / "others/closing_overview.json", get_research_overview(repo, batch).to_dict())
    materials, searches, identities = {}, [], set()

    def material(path):
        key = path.relative_to(ROOT).as_posix()
        if key not in materials:
            ext = path.suffix[1:]
            materials[key] = publish_evidence(context, d.MaterialEvidenceWrite(experiment,
                f"stage3-{len(materials):03}-{path.stem}", path.read_bytes(),
                {"json": "application/json", "md": "text/markdown", "py": "text/x-python"}[ext], ext))
        return materials[key]

    for work in experiments():
        config, summary, publication = [read(work / path) for path in
            ("protocols/config.json", "others/summary.json", "others/publication.json")]
        assert publication["validation"]["status"] == "PASS"
        evidence = [d.EvidenceRef.from_dict(publication["report"]), material(work / "protocols/plan.md"),
                    material(work / "protocols/config.json"), material(work / "others/summary.json"),
                    material(work / "src/strategy.py"), material(work / "others/execution.json")]
        for name, row in summary.items():
            assert not row["candidate"]["eligible"]
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
        searches.append(d.SearchSummary(f"R{config['round']:02}",
            "逐轮自适应有限结构与参数对照；每轮先固定方案和配置，公共V4完整账户评价",
            f"{work.name}；当前配置全集见绑定协议和配置文件；2022-01-03至2026-10-30已见历史",
            len(summary), len(summary), "全部中心经济与频率硬门通过后按未舍入NAR排序；本轮达标集合为空",
            ("同一历史反复用于开发选择", "本次计新策略账户，买持与旧账户复用分别披露", "正式阶段四五项自检尚未开展"),
            tuple(evidence)))
    assert len(identities) == 32
    for path in (WORK / "src/close_stage_three.py", WORK / "src/semantic_audit.py", WORK / "others/audit_manifest.json",
                 WORK / "others/semantic_audit.json", WORK / "others/budget.json", WORK / "others/closing_overview.json",
                 BATCH / "materials/stage_three_summary.md",
                 BATCH / "experiments/EX016_20261110/protocols/authorization.md",
                 BATCH / "experiments/EX013_20261110/src/runner.py",
                 BATCH / "experiments/EX003_20261110/src/data_window.py",
                 BATCH / "experiments/EX003_20261110/others/preparation.json",
                 BATCH / "experiments/EX001_20261110/src/load_data.py",
                 BATCH / "experiments/EX001_20261110/src/prepare_data.py"):
        material(path)
    save(WORK / "others/material_manifest.json", {key: value.to_dict() for key, value in materials.items()})
    manifest = material(WORK / "others/material_manifest.json")
    predecessor = d.DeliveryReference.from_dict(read(BATCH / "deliveries/PROTOTYPES/1/receipt.json")["reference"])
    report = (BATCH / "materials/stage_three_summary.md").read_text(encoding="utf-8")
    report = report.replace("../experiments/", "../../../experiments/").replace("../deliveries/PROTOTYPES/", "../../PROTOTYPES/")
    result = assemble_delivery(repo, d.DeliveryDefinition(batch, d.DeliveryStage.CANDIDATES, 1, (predecessor,)),
        d.DeliveryContent(d.CandidateSet((), (), tuple(searches), CONCLUSION), d.DeliveryStatus.COMPLETE, (), (),
                          report=report, evidence=(manifest, *[v for v in materials.values() if v != manifest])))
    save(WORK / "others/stage_publication.json", result.to_dict())
    assert result.validation.status is d.ValidationStatus.PASS and result.validation.scope is d.DeliveryValidationScope.INTEGRITY
    reference = result.receipt.reference
    intent = read(ROOT / "research/registrations/S019/family.json")["research_intent"]
    intent.update(stage="STAGE_THREE", stage_three_status="COMPLETE", stage_four_approval="NOT_REQUESTED_NO_ELIGIBLE_CANDIDATE",
        stage_three_delivery=reference.to_dict(), stage_three_budget=read(WORK / "others/budget.json"),
        latest_experiment_report=read(WORK / "others/publication.json")["report"],
        next_action="32个新策略均未全门达标；保留C0067前沿，建议停止细调当前结构，等待用户决定机制重构或结束本路线。")
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="完成用户批准的阶段三及新增十轮额度，交付完整负面结果和前沿，保持原硬门")
    print("STAGE3_DELIVERY", reference.content_sha256, result.validation.scope.value, result.validation.status.value, flush=True)


if __name__ == "__main__":
    {"prepare": prepare, "publish": publish}[sys.argv[1]]()
