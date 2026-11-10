"""Publish fixed prototype comparisons, including negative and technical evidence."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, create_research_context,
    publish_evidence, update_research_intent, validate_experiment,
)
from dataflows import ProviderConfig

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]


def main():
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef("S019")
    context = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
    experiment = d.ExperimentRef("S019", WORK.name)
    summary = json.loads((WORK / "others/summary.json").read_text(encoding="utf-8"))
    evidence = [d.EvidenceRef.from_dict(row["account"]) for row in summary.values()]
    evidence.append(d.EvidenceRef.from_dict(json.loads((WORK.parent / "EX003_20261110/others/reference_account.json").read_text(encoding="utf-8"))))
    paths = [*sorted((WORK / "src").glob("*.py")), WORK / "protocols/prototypes.md",
        *sorted((WORK / "others").glob("*.json")),
        WORK.parent / "EX003_20261110/others/preparation.json",
        WORK.parent / "EX003_20261110/src/data_window.py",
        WORK.parent / "EX001_20261110/src/load_data.py",
        WORK.parent / "EX001_20261110/src/prepare_data.py",
        WORK.parent / "EX004_20261110/others/events.csv"]
    for i, path in enumerate(paths):
        if path.name == "publication.json":
            continue
        extension = path.suffix[1:]
        mime = {"py": "text/x-python", "md": "text/markdown", "json": "application/json", "csv": "text/csv"}[extension]
        evidence.append(publish_evidence(context, d.MaterialEvidenceWrite(experiment,
            f"material-{i:02d}-{path.stem}", path.read_bytes(), mime, extension)))
    report = publish_evidence(context, d.ExperimentReportWrite(experiment,
        sha256((WORK / "report.md").read_bytes()).hexdigest(), d.ExperimentOutcome.COMPLETED, tuple(evidence)))
    validation = validate_experiment(repo, d.ExperimentValidationRequest(experiment, d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status is d.ValidationStatus.PASS
    family = json.loads((ROOT / "research/registrations/S019/family.json").read_text(encoding="utf-8"))
    intent = {**family["research_intent"], "latest_experiment_report": report.to_dict(),
        "next_action": "阶段二继续比较行业回落后1/3/5日持有及连续下跌损失路径；首轮四原型均未达标，暂缓阶段三。"}
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="完成统一窗口四个原型对照，保留负面经济结果和完整账户核验，继续已授权阶段二。")
    (WORK / "others/publication.json").write_bytes((json.dumps({"report": report.to_dict(), "validation": validation.to_dict()}, ensure_ascii=False, indent=2) + "\n").encode())
    print(validation.status.value, report.sha256)


if __name__ == "__main__":
    main()
