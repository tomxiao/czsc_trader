"""Publish the approved sample revision while preserving prior mandate evidence."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, assemble_delivery, create_research_context,
    publish_evidence, update_research_intent, validate_experiment,
)
from dataflows import ProviderConfig

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
EXP = d.ExperimentRef("S019", WORK.name)


def save(name, value):
    (WORK / "others" / name).write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def main():
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef("S019")
    context = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
    approval = {"source": "current_user_conversation", "date": "2026-11-10",
        "quote": "批准。就按这个方案划分数据样本",
        "approved_plan": {"warmup": "2021, checked against actual maximum lookback",
            "development_and_historical_acceptance": ["2022-01-03", "2026-10-30"],
            "diagnostics": "annual, rolling and continuous stages using inherited account state",
            "independent_validation": "252 prospective sessions after final rules and parameters are locked"},
        "revision_after": "EX002_20261110", "economic_targets": "unchanged"}
    save("sample_approval.json", approval)
    confirmation = publish_evidence(context, d.MaterialEvidenceWrite(EXP, "approved-sample-revision", (WORK / "others/sample_approval.json").read_bytes(), "application/json", "json"))
    receipt = json.loads((ROOT / "research/S019/deliveries/MANDATE/1/receipt.json").read_text(encoding="utf-8"))
    predecessor = d.DeliveryReference.from_dict(receipt["reference"])
    old = json.loads((ROOT / "research/S019/assets/deliveries/MANDATE/1/delivery.json").read_text(encoding="utf-8"))
    mandate = d.ResearchMandate.from_dict(old["content"]["payload"])
    items = tuple(replace(item,
        statement="Futu MU/SOXX日线及30分钟；2021预热，2022-01-03至2026-10-30统一开发、优化及历史验收。整体按已见样本管理；实际最大回看超出预热覆盖时向前补齐输入。",
        confirmation=d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, confirmation)) if item.item_id == "data" else item for item in mandate.items)
    evidence = [confirmation]
    evidence.extend(dict.fromkeys(item.confirmation.source for item in items if item.confirmation.source))
    evidence.append(d.EvidenceRef.from_dict(json.loads((WORK / "others/reference_account.json").read_text(encoding="utf-8"))))
    paths = (
        ("sample-agreement", ROOT / "research/S019/materials/stage1_agreement.md", "text/markdown", "md"),
        ("window-preparation", WORK / "others/preparation.json", "application/json", "json"),
        ("window-audit", WORK / "others/sample_audit.json", "application/json", "json"),
        ("reference-identity", WORK / "others/reference_identity.json", "application/json", "json"),
        ("reference-summary", WORK / "others/reference_summary.json", "application/json", "json"),
        ("reference-binding", WORK / "others/reference_input_binding.json", "application/json", "json"),
        ("window-source", WORK / "src/data_window.py", "text/x-python", "py"),
        ("reference-source", WORK / "src/replay_reference.py", "text/x-python", "py"),
        ("frozen-strategy-source", WORK / "src/reference/strategy.py", "text/x-python", "py"),
        ("publication-source", Path(__file__), "text/x-python", "py"),
    )
    for name, path, mime, extension in paths:
        evidence.append(publish_evidence(context, d.MaterialEvidenceWrite(EXP, name, path.read_bytes(), mime, extension)))
    evidence = tuple(dict.fromkeys(evidence))
    report_bytes = (WORK / "report.md").read_bytes()
    assembled = assemble_delivery(repo, d.DeliveryDefinition(batch, d.DeliveryStage.MANDATE, 2, (predecessor,)),
        d.DeliveryContent(d.ResearchMandate(items), d.DeliveryStatus.COMPLETE, (), (), report=report_bytes.decode(), evidence=evidence))
    assert assembled.validation.status is d.ValidationStatus.PASS
    report = publish_evidence(context, d.ExperimentReportWrite(EXP, sha256(report_bytes).hexdigest(), d.ExperimentOutcome.COMPLETED, evidence))
    validation = validate_experiment(repo, d.ExperimentValidationRequest(EXP, d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status is d.ValidationStatus.PASS
    family = json.loads((ROOT / "research/registrations/S019/family.json").read_text(encoding="utf-8"))
    intent = {**family["research_intent"], "mandate": assembled.receipt.reference.to_dict(),
        "development": {"history_start": "2021-01-01", "start": "2022-01-03", "end": "2026-10-30", "exposure": "SEEN_HISTORY"},
        "latest_experiment_report": report.to_dict(),
        "next_action": "围绕S019在统一窗口内发展机制与原型，重点检查持续下跌阶段的成交后收益。"}
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH", reason="用户明确批准2022起统一样本方案；预热和同窗基准已完成。")
    save("publication.json", {"mandate": assembled.receipt.reference.to_dict(), "mandate_validation": assembled.validation.to_dict(),
        "report": report.to_dict(), "report_validation": validation.to_dict()})
    print("MANDATE/2 PASS; EX003 PASS")


if __name__ == "__main__":
    main()
