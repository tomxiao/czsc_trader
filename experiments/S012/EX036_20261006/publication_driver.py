"""Publish the stage-two increment, seal five archives, update S012 public intent."""

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
IDS = ("EX032_20261006", "EX033_20261006", "EX034_20261006", "EX035_20261006", "EX036_20261006")
EXP = ROOT / "experiments/S012/EX036_20261006"
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
    repo = RepositoryContext.discover(ROOT)
    package = types.ModuleType("s012_return_discovery_final_publication")
    package.__path__ = [str(EXP)]
    sys.modules[package.__name__] = package
    delivery = importlib.import_module(package.__name__ + ".delivery").ReturnDiscoveryComponents(
        ROOT
    )
    content = delivery.build()
    print("CONTENT", len(content.payload.components), len(content.facts), flush=True)
    receipt = assemble_delivery(repo, delivery)
    write(
        MATERIAL / "return_discovery_final_components_reference_20261006.json",
        receipt.reference.to_dict(),
    )
    full = validate_delivery(repo, receipt.reference)
    write(MATERIAL / "return_discovery_final_components_validation_20261006.json", full.to_dict())
    print("FULL", full.status.value, flush=True)
    if full.status.value != "PASS":
        raise RuntimeError("FULL delivery not PASS")
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
            "purpose": "阶段二收益深化；新增1有边界机会环境原M05，保留全部来源竞争和成交/年度反证。",
            "platform_commit": commit,
            "definition_sha256": loaded.definition.sha256,
            "source_sha256": loaded.binding.source_sha256,
        }
        if eid == IDS[-1]:
            meta["delivery"] = receipt.reference.to_dict()
        if eid == IDS[-1]:
            build_experiment_manifest(exp, meta)
        archive = validate_archives(repo, archive=exp)
        checks.append(asdict(archive))
        print("ARCHIVE", eid, archive.status, flush=True)
        if archive.status != "PASS":
            raise RuntimeError("archive not PASS " + eid)
    write(MATERIAL / "return_discovery_final_archives_validation_20261006.json", checks)
    integrity = validate_delivery(repo, receipt.reference, scope=DeliveryValidationScope.INTEGRITY)
    write(MATERIAL / "return_discovery_final_sealed_integrity_20261006.json", integrity.to_dict())
    if integrity.status.value != "PASS":
        raise RuntimeError("sealed integrity not PASS")
    family = read(ROOT / "research/registrations/S012/family.json")
    intent = family["research_intent"]
    for eid in IDS:
        if eid not in intent["experiments"]:
            intent["experiments"].append(eid)
    source = "research/S012/materials/stage2_return_discovery_authorization_20261006.json"
    if source not in intent["confirmation_sources"]:
        intent["confirmation_sources"].append(source)
    note = "research/S012/materials/return_discovery_scope_note_20261006.md"
    if note not in intent["confirmation_sources"]:
        intent["confirmation_sources"].append(note)
    intent.update(
        stage="COMPONENTS",
        status="IN_PROGRESS",
        delivery=receipt.reference.to_dict(),
        next_stage="继续在已授权日线/分钟线中研究收益形成与限价兼容机会；原资源新假设先固定后执行，阶段三另获批准。",
        pending=[
            "新增1有边界机会环境M05，原低频及年度/控制反证保留；完整账户目标未验证。",
            "原账户三个经济目标未复验；分钟内收益形成与限价兼容机会尚待深化。",
            "全部历史已见，逐条实际发布时刻未验证；新来源/依赖、DEV、阶段三、生产与合并tag推送另授权。",
        ],
        research_summary="EX032—36五轮正式收益深化，47主记录1152路径8064年度；新SUPPORTED为1有边界机会环境原M05。163事件5日净0.6345%、父内增量+0.2289pp、固定父限价贡献+0.1030pp，延期/双费用/去单年仍有改善；2021/24亏、低频1.329/60、延期OLS/区间反证保留。五项独立复算1050058字段、统一FULL与五档案PASS；阶段二IN_PROGRESS，原账户目标未复验。",
    )
    path = ROOT / ".tmp/s012-return-discovery-20261006/final_intent.json"
    write(path, {"research_state": "RESEARCHING", "research_intent": intent})
    updated = update_research_intent(
        repo,
        "S012",
        path,
        actor="RSCH",
        reason="按用户自主主导阶段二授权，交付五轮收益深化及完整反证，继续挖掘可成交收益机会",
    )
    write(MATERIAL / "return_discovery_final_completion_result_20261006.json", asdict(updated))
    print(
        "DELIVERY",
        receipt.reference.content_sha256,
        "INTEGRITY",
        integrity.status.value,
        flush=True,
    )


if __name__ == "__main__":
    main()
