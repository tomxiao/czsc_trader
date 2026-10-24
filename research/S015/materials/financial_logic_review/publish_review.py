"""Publish the authorized retrospective review; never execute strategy accounts."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import RepositoryContext, assemble_delivery
from czsc_trader.research_tools import ExecutionResources, ResearchBatchRef
from czsc_trader.research_tools import delivery as d

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
HOME = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "publish"))
    parser.add_argument("--report", required=True, help="Repository-relative reviewed report")
    args = parser.parse_args()
    report_path = (ROOT / args.report).resolve()
    if not report_path.is_relative_to(ROOT):
        raise ValueError("Report must remain inside this repository")
    packages = {}
    refs = {}
    hashes = {}
    for stage, revision in (("PROTOTYPES", 1), ("CANDIDATES", 7), ("ASSESSMENT", 4)):
        folder = ROOT / f"research/S015/assets/deliveries/{stage}/{revision}"
        packages[stage] = read(folder / "delivery.json")
        refs[stage] = d.DeliveryReference.from_dict(read(folder / "receipt.json")["reference"])
        hashes[(folder / "delivery.json").relative_to(ROOT).as_posix()] = sha256(
            (folder / "delivery.json").read_bytes()
        ).hexdigest()
    payload = deepcopy(packages["PROTOTYPES"]["content"]["payload"])
    judgments = {
        "P_MEAN_FIXED": "保留背景与折让的组合证据；固定三信号日尚无与机会完成、失效或衰减对应的依据，暂不推荐继续寻优。",
        "P_MEDIAN_FIXED": "保留同一机制的中位定义对照；固定退出缺口相同，不因替代定义盈利而认为完整原型逻辑已成立。",
        "P_MEDIAN_REPAIR": "修复退出具有业务含义；移动中心可下降到价格，折让消失未必代表盈利修复，且历史收益代价真实存在。",
        "P_MEDIAN_RISK": "保留修复/背景失效竞争解释；低回撤不能抵消收益不足，过早退出反例尚未解决。",
        "P_DAILY_MID": "作为日线信息简化对照保留；盘中数据必要性未证实，固定退出缺口未解决。",
        "P_FIRST": "作为状态切换对照保留，不视为完整获支持的收益路线；原收益与频率代价仍有效。",
        "P_LATE": "仅是均值原型的共同起点对照，并非独立机制；继承固定退出缺口，不替代原评价窗口。",
        "P_OLD_BP": "停止独立发展，保留历史基线；三日收益预测本身不能替代金融逻辑，已有完整账户和资格证据不支持继续该路线。",
    }
    next_steps = {
        "P_MEAN_FIXED": "先区分价格修复、中心上移和交易队列贡献，再决定是否构建新的完整原型。",
        "P_MEDIAN_FIXED": "作为预先选定的代表定义，检查机制诊断能否重复，不单独继续调参。",
        "P_MEDIAN_REPAIR": "区分价格回升与中心下降造成的修复，并检查修复后的持有价值；不直接重跑旧退出规则。",
        "P_MEDIAN_RISK": "复用原过早退出反例与盈利代价，检验状态定义，不通过扩展确认天数寻找达标。",
        "P_DAILY_MID": "保留信息必要性对照，避免把中心替换或盘中数据包装为新收益机制。",
        "P_FIRST": "仅在持有/新机会状态诊断中作为竞争解释，不独立扩大搜索。",
        "P_LATE": "仅供同起点历史比较，不计作独立可发展原型。",
        "P_OLD_BP": "停止当前表达的优化，保留对照；有不同可检验机制后另行提出方案。",
    }
    inventory = []
    for item in payload["prototypes"]:
        previous = item["disposition"]
        if item["prototype_id"] in judgments:
            key = item["prototype_id"]
            item["disposition"] = "STOP" if key == "P_OLD_BP" else "INVESTIGATE"
            item["judgment"] = judgments[key]
            item["next_step"] = next_steps[key]
        item["sources"] = [
            {
                "type": "PrototypeReference",
                "delivery": refs["PROTOTYPES"].to_dict(),
                "prototype_id": item["prototype_id"],
            }
        ]
        item["limitations"].append(
            "本轮仅依据既有证据复评金融逻辑，没有新增账户或独立验证；原账户结果及身份保持。"
        )
        inventory.append(
            {
                "prototype_id": item["prototype_id"],
                "identity": item["identity"],
                "previous_disposition": previous,
                "disposition": item["disposition"],
            }
        )
    for component in payload["components"]:
        if component["component_id"] == "fixed3":
            component["judgment"] = (
                "可执行的历史对照容器；现有证据没有解释三信号日如何对应机会衰减、完成、失效或资金约束，暂不足以支撑拟发展原型的核心退出。历史测试事实保留。"
            )
    conclusion = "复评完成：18项已有原型中DEVELOP 0、INVESTIGATE 7、STOP 11；背景与折让保留机制研究价值，尚无推荐直接推进的完整原型。阶段四16个数值合格事实保持，暂缓C6105阶段五推荐。建议用户批准阶段二持有状态与收益来源诊断。新实验、新配置和策略账户均为0。"
    payload["conclusion"] = conclusion
    panel = d.PrototypePanel.from_dict(payload)
    counts = Counter(p.disposition.value for p in panel.prototypes)
    assert counts == {"INVESTIGATE": 7, "STOP": 11}, counts
    centers = read(ROOT / "research/S015/experiments/EX066_20261024/others/centers.json")
    center_ids = {c["candidate_id"] for c in centers}
    candidates = [
        c
        for c in packages["CANDIDATES"]["content"]["payload"]["candidates"]
        if c["identity"]["key"]["candidate_id"] in center_ids
    ]
    assert len(centers) == len(candidates) == 16
    assert {c["candidate_id"] for c in centers} == {
        c["identity"]["key"]["candidate_id"] for c in candidates
    }
    assert all(c["parameters"]["lookback"] == c["parameters"]["hold"] == 3 for c in centers)
    definition = d.DeliveryDefinition(
        ResearchBatchRef("S015"), d.DeliveryStage.PROTOTYPES, 2, tuple(refs.values())
    )
    # Reuse P1's direct evidence with exact provenance; later stages remain typed predecessors.
    old_content = packages["PROTOTYPES"]["content"]
    from czsc_trader.research_tools import EvidenceRef

    content = d.DeliveryContent(
        panel,
        d.DeliveryStatus.COMPLETE,
        (),
        (),
        report=report_path.read_text(encoding="utf-8"),
        evidence=tuple(EvidenceRef.from_dict(e) for e in old_content["evidence"]),
    )
    for candidate in candidates:
        assert candidate["identity"]["key"]["candidate_id"] in content.report
    for item in inventory:
        assert item["prototype_id"] in content.report
    journal = {
        "status": "TYPED_REVIEW_CHECK_PASS",
        "guide_commit": "6c90c24d",
        "guide_sha256": sha256((ROOT / "research/RSCH_AGENT.md").read_bytes()).hexdigest(),
        "source_packages_sha256": hashes,
        "report_sha256": sha256(content.report.encode()).hexdigest(),
        "new_experiments": 0,
        "new_configurations": 0,
        "new_strategy_accounts": 0,
        "inventory": inventory,
        "candidate_identities": [c["identity"] for c in candidates],
        "disposition_counts": dict(counts),
        "definition": definition.to_dict(),
    }
    check_path = HOME / "review_check.json"
    if args.command == "check":
        save(check_path, journal)
        print(
            json.dumps(
                {"status": journal["status"], "counts": dict(counts), "candidates": len(candidates)}
            ),
            flush=True,
        )
        return
    if read(check_path) != journal:
        raise ValueError("Inputs changed since reviewed check")
    receipt_path = HOME / "publication_receipt.json"
    if receipt_path.exists():
        raise FileExistsError("Inspect existing publication before attempting a repeat")
    last = [None, 0]

    def progress(value):
        if value.phase != last[0] or value.elapsed_seconds - last[1] >= 30:
            print(json.dumps(value.to_dict(), ensure_ascii=False), flush=True)
            last[:] = [value.phase, value.elapsed_seconds]

    result = assemble_delivery(
        RepositoryContext.discover(ROOT),
        definition,
        content,
        resources=ExecutionResources(4, 1, 13),
        on_progress=progress,
    )
    journal["assembly"] = result.to_dict()
    journal["status"] = (
        "FULL_PUBLICATION_PASS" if result.validation.status is d.ValidationStatus.PASS else "FAIL"
    )
    save(receipt_path, journal)
    assert journal["status"] == "FULL_PUBLICATION_PASS"
    for relative, expected in hashes.items():
        assert sha256((ROOT / relative).read_bytes()).hexdigest() == expected
    print(
        json.dumps({"status": journal["status"], "reference": result.receipt.reference.to_dict()}),
        flush=True,
    )


if __name__ == "__main__":
    main()
