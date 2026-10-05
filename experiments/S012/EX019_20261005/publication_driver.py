"""Publish, verify and seal the S012 stage-two successor through public APIs."""

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
from research_experiment import load_experiment

ROOT = Path.cwd().resolve()
EXP = ROOT / "experiments/S012/EX019_20261005"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main():
    for name in (
        "confirmation_independent_verification_20261005.json",
        "confirmation_competition_verification_20261005.json",
    ):
        proof = json.loads((ROOT / "research/S012/materials" / name).read_text(encoding="utf-8"))
        if proof["status"] != "PASS":
            raise ValueError(f"independent audit failed: {name}")
    repo = RepositoryContext.discover(ROOT)
    package = types.ModuleType("s012_confirmation_publication")
    package.__path__ = [str(EXP)]
    sys.modules[package.__name__] = package
    delivery = importlib.import_module(package.__name__ + ".publish").create_delivery(ROOT)
    content = delivery.build()
    print(
        "CONTENT",
        len(content.payload.components),
        "records",
        len(content.facts),
        "facts",
        flush=True,
    )
    receipt = assemble_delivery(repo, delivery)
    verified = validate_delivery(repo, receipt.reference)
    write(
        ROOT / "research/S012/materials/confirmation_components_validation_20261005.json",
        {**verified.to_dict(), "reference": receipt.reference.to_dict()},
    )
    if verified.status.value != "PASS":
        raise RuntimeError("delivery FULL failed")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    archives = {}
    for number in (18, 19):
        folder = ROOT / f"experiments/S012/EX{number:03d}_20261005"
        loaded = load_experiment(folder)
        metadata = {
            "experiment_id": folder.name,
            "strategy_id": "S012",
            "symbol": "518850.SH",
            "development_cutoff": "2026-09-30",
            "outcome": "INCONCLUSIVE",
            "purpose": "阶段二机会内确认、风险上下文及竞争解释；研究角色按人工报告判断",
            "platform_commit": commit,
            "definition_sha256": loaded.definition.sha256,
            "source_sha256": loaded.binding.source_sha256,
        }
        if number == 19:
            metadata["delivery"] = receipt.reference.to_dict()
        build_experiment_manifest(folder, metadata)
        checked = validate_archives(repo, archive=folder)
        archives[folder.name] = asdict(checked)
        if checked.status != "PASS":
            raise RuntimeError(f"archive failed: {asdict(checked)}")
    write(ROOT / "research/S012/materials/confirmation_archives_validation_20261005.json", archives)
    family = json.loads(
        (ROOT / "research/registrations/S012/family.json").read_text(encoding="utf-8")
    )
    intent = family["research_intent"]
    for number in (18, 19):
        eid = f"EX{number:03d}_20261005"
        if eid not in intent["experiments"]:
            intent["experiments"].append(eid)
    intent.update(
        status="COMPLETE",
        delivery=receipt.reference.to_dict(),
        next_stage="阶段二职责覆盖与后继面板完成；建议用户审阅批准阶段三最小完整账户对照，检验O01有无Q07、N09及风险职责。",
        pending=[
            "用户审阅EX019后继组件报告并决定是否批准阶段三。",
            "完整账户三个经济目标未联合验证，限价触价与事件贡献不代表闭合交易和账户收益。",
            "Q07仅O01主5日有条件支持，容量/年度/延迟反证和已见开发池选择偏差保留。",
        ],
        research_summary="EX018/19完成480确认路径及12风险上下文、自身/同类竞争解释。后继39记录204事实，去重6独立职责组件：2条件机会、3风险状态、1仅O01的确认Q07。O01确认79到30事件，5日净1.6977%，条件提升0.9192pp，固定父贡献+0.2308pp、限价+0.1619pp；重排0.6645触价/60日。N09无推荐强制门。同类独立性不足；FULL和两个档案PASS，完整独立复算PASS；阶段三未进入。",
    )
    path = ROOT / ".tmp/s012-confirmation-20261005/final_intent.json"
    write(path, {"research_state": "RESEARCHING", "research_intent": intent})
    updated = update_research_intent(
        repo,
        "S012",
        path,
        actor="RSCH",
        reason="按用户授权完成阶段二职责补齐、竞争解释、复算与后继组件交付，下一阶段待批准",
    )
    write(
        ROOT / "research/S012/materials/confirmation_completion_result_20261005.json",
        asdict(updated),
    )
    print(
        "DELIVERY",
        verified.status.value,
        "ARCHIVES",
        len(archives),
        "HASH",
        receipt.reference.content_sha256,
        flush=True,
    )


if __name__ == "__main__":
    main()
