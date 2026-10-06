"""Publish, validate, seal and update only S012 through public platform APIs."""

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
EXP = ROOT / "experiments/S012/EX031_20261006"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main():
    proof = json.loads(
        (EXP / "artifacts/verification/independent.json").read_text(encoding="utf-8")
    )
    if proof["status"] != "PASS":
        raise ValueError("independent audit not PASS")
    repo = RepositoryContext.discover(ROOT)
    package = types.ModuleType("s012_gvz_preliminary_publication")
    package.__path__ = [str(EXP)]
    sys.modules[package.__name__] = package
    delivery = importlib.import_module(package.__name__ + ".delivery").PreliminaryComponents(ROOT)
    content = delivery.build()
    print("CONTENT", len(content.payload.components), len(content.facts), flush=True)
    receipt = assemble_delivery(repo, delivery)
    checked = validate_delivery(repo, receipt.reference)
    write(
        ROOT / "research/S012/materials/gvz_preliminary_components_validation_20261006.json",
        checked.to_dict(),
    )
    write(
        ROOT / "research/S012/materials/gvz_preliminary_components_reference_20261006.json",
        receipt.reference.to_dict(),
    )
    if checked.status.value != "PASS":
        raise RuntimeError("delivery FULL not PASS")
    loaded = load_experiment(EXP)
    meta = {
        "experiment_id": EXP.name,
        "strategy_id": "S012",
        "symbol": "518850.SH",
        "development_cutoff": "2026-09-30",
        "outcome": "INCONCLUSIVE",
        "purpose": "完整GVZ与有限美元篮子初步验证完成；新增成熟有效收益组件0，整体阶段二继续。",
        "platform_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "definition_sha256": loaded.definition.sha256,
        "source_sha256": loaded.binding.source_sha256,
        "delivery": receipt.reference.to_dict(),
    }
    build_experiment_manifest(EXP, meta)
    archive = validate_archives(repo, archive=EXP)
    write(
        ROOT / "research/S012/materials/gvz_preliminary_archive_validation_20261006.json",
        asdict(archive),
    )
    if archive.status != "PASS":
        raise RuntimeError("archive not PASS")
    integrity = validate_delivery(repo, receipt.reference, scope=DeliveryValidationScope.INTEGRITY)
    write(
        ROOT / "research/S012/materials/gvz_preliminary_sealed_integrity_20261006.json",
        integrity.to_dict(),
    )
    if integrity.status.value != "PASS":
        raise RuntimeError("sealed delivery not PASS")
    family = json.loads(
        (ROOT / "research/registrations/S012/family.json").read_text(encoding="utf-8")
    )
    intent = family["research_intent"]
    for eid in ("EX030_20261006", "EX031_20261006"):
        if eid not in intent["experiments"]:
            intent["experiments"].append(eid)
    for source in (
        "research/S012/materials/dev_gvz_usdollar_acceptance_20261006.json",
        "research/S012/materials/gvz_usdollar_preliminary_authorization_20261006.json",
    ):
        if source not in intent["confirmation_sources"]:
            intent["confirmation_sources"].append(source)
    intent.update(
        stage="COMPONENTS",
        status="IN_PROGRESS",
        delivery=receipt.reference.to_dict(),
        next_stage="初步验证完成；建议后继拆分低VIX/GVZ信息来源、检验年度及延迟反证；整体阶段二继续。",
        pending=[
            "新增成熟有效收益组件0；低比值与美元趋势仅为后继线索，阶段三未批准。",
            "USDOLLAR止于2023-06-01，不外推2023年6月后；新增美元资源须另获批准。",
            "原账户三项目标未复验，真实历史发布时间未逐条核实；保留全部反证和已见选择历史。",
        ],
        confirmed_data_and_resources="已授权既有S012资源及FRED/CBOE GVZ完整2020-01-01至2026-09-30窗口、Tushare USDOLLAR有限2020-01-01至2023-06-01窗口；新增付费/来源另确认。",
        research_summary="EX030原排序局限保留，EX031九假设260路径1820年度初步验证完成。高VIX/GVZ避险5日净-0.1333%、低比值0.5500%，后者延迟匹配增量转负；美元走弱趋势10日净0.2572%、匹配+0.2019pp，但潜在成交接近零。九项增量区间均跨零，新增成熟有效收益组件0。独立233009字段、FULL及档案PASS，整体阶段二IN_PROGRESS。",
    )
    path = ROOT / ".tmp/s012-gvz-preliminary-corrected-20261006/final_intent.json"
    write(path, {"research_state": "RESEARCHING", "research_intent": intent})
    updated = update_research_intent(
        repo,
        "S012",
        path,
        actor="RSCH",
        reason="按本轮明确授权完成GVZ及有限美元初步验证与增量面板，继续阶段二",
    )
    write(
        ROOT / "research/S012/materials/gvz_preliminary_completion_result_20261006.json",
        asdict(updated),
    )
    print(
        "DELIVERY",
        receipt.reference.content_sha256,
        "FULL",
        checked.status.value,
        "ARCHIVE",
        archive.status,
        flush=True,
    )


if __name__ == "__main__":
    main()
