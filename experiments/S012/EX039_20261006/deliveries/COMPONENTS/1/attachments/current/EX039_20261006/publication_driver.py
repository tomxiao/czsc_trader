"""Publish the complete stage-two delivery, seal only the three new experiments."""

from dataclasses import asdict
import importlib
import json
from pathlib import Path
import subprocess
import sys
import types
from czsc_trader.application import (
    RepositoryContext,
    assemble_delivery,
    validate_delivery,
    validate_archives,
    update_research_intent,
)
from czsc_trader.experiment_archive import build_experiment_manifest
from czsc_trader.research_tools import DeliveryValidationScope
from research_experiment import load_experiment

ROOT = Path.cwd().resolve()
IDS = ("EX037_20261006", "EX038_20261006", "EX039_20261006")
EXP = ROOT / "experiments/S012/EX039_20261006"
MATERIAL = ROOT / "research/S012/materials"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main():
    for eid in IDS:
        if (
            read(ROOT / f"experiments/S012/{eid}/artifacts/verification/independent.json")["status"]
            != "PASS"
        ):
            raise ValueError("independent audit not PASS " + eid)
    if read(EXP / "artifacts/verification/completion_audit.json")["status"] != "PASS":
        raise ValueError("stage-two scientific completion audit not PASS")
    repo = RepositoryContext.discover(ROOT)
    package = types.ModuleType("s012_complete_publication")
    package.__path__ = [str(EXP)]
    sys.modules[package.__name__] = package
    delivery = importlib.import_module(package.__name__ + ".delivery").CompleteStageTwo(ROOT)
    content = delivery.build()
    print(
        "CONTENT",
        len(content.payload.components),
        len(content.facts),
        content.status.value,
        flush=True,
    )
    receipt = assemble_delivery(repo, delivery)
    write(
        MATERIAL / "stage2_complete_components_reference_20261006.json", receipt.reference.to_dict()
    )
    full = validate_delivery(repo, receipt.reference)
    write(MATERIAL / "stage2_complete_components_validation_20261006.json", full.to_dict())
    print("FULL", full.status.value, flush=True)
    if full.status.value != "PASS":
        raise RuntimeError("complete delivery FULL not PASS")
    checks = []
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    for eid in IDS:
        exp = ROOT / f"experiments/S012/{eid}"
        loaded = load_experiment(exp)
        meta = {
            "experiment_id": eid,
            "strategy_id": "S012",
            "symbol": "518850.SH",
            "development_cutoff": "2026-09-30",
            "outcome": "INCONCLUSIVE",
            "purpose": "阶段二完整收口：盘中收益竞争、原角色复验和全部日历相位，正负证据及限定职责保留",
            "platform_commit": commit,
            "definition_sha256": loaded.definition.sha256,
            "source_sha256": loaded.binding.source_sha256,
        }
        if eid == IDS[-1]:
            meta["delivery"] = receipt.reference.to_dict()
        build_experiment_manifest(exp, meta)
        check = validate_archives(repo, archive=exp)
        checks.append(asdict(check))
        print("ARCHIVE", eid, check.status, flush=True)
        if check.status != "PASS":
            raise RuntimeError("archive not PASS " + eid)
    write(MATERIAL / "stage2_complete_archives_validation_20261006.json", checks)
    integrity = validate_delivery(repo, receipt.reference, scope=DeliveryValidationScope.INTEGRITY)
    write(MATERIAL / "stage2_complete_sealed_integrity_20261006.json", integrity.to_dict())
    if integrity.status.value != "PASS":
        raise RuntimeError("sealed integrity not PASS")
    intent = read(ROOT / "research/registrations/S012/family.json")["research_intent"]
    for eid in IDS:
        if eid not in intent["experiments"]:
            intent["experiments"].append(eid)
    intent.update(
        stage="COMPONENTS",
        status="COMPLETE",
        delivery=receipt.reference.to_dict(),
        next_stage="等待用户批准阶段三：O01有无Q07、M05独立原型及两机会组合最小账户对照，N09为候选/删门对照；保持原三个经济目标。",
        pending=[
            "原账户净年化/回撤/闭合频率目标未重新验证，需阶段三新批准。",
            "6有边界角色；N09候选、并集年度集中、分钟门反证和全开发池选择历史保持。",
            "新来源/依赖、DEV、生产、合并/tag/推送均须相应授权。",
        ],
        research_summary="阶段二完整交付142研究记录，当前推荐6不同职责：O01/M05两机会、C01/C02/C03三风险、Q07仅O01确认；N09候选不作默认门。EX037—39正式新增594路径4158年度、独立复算580068字段，六相位并集小幅平均改善但去2025均转负，新分钟确认未支持；完整台账、角色及科学收口、FULL/三档案/封存核验齐备，账户目标未复验，等待阶段三批准。",
    )
    path = ROOT / ".tmp/s012-stage2-complete-20261006/final_intent.json"
    write(path, {"research_state": "RESEARCHING", "research_intent": intent})
    updated = update_research_intent(
        repo,
        "S012",
        path,
        actor="RSCH",
        reason="按用户自主完成阶段二授权，发布完整面板、台账、角色/反证及收口报告，等待阶段三批准",
    )
    write(MATERIAL / "stage2_complete_result_20261006.json", asdict(updated))
    print("DELIVERY", receipt.reference.content_sha256, "STATE COMPONENTS COMPLETE", flush=True)


if __name__ == "__main__":
    main()
