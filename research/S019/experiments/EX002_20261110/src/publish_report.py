"""Publish the first-round diagnostics and verify the selected materials."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, validate_experiment
from dataflows import ProviderConfig

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
EXP = d.ExperimentRef("S019", "EX002_20261110")


def main():
    repo = RepositoryContext.discover(ROOT)
    context = create_research_context(repo, d.ResearchBatchRef("S019"), providers=ProviderConfig(bindings={}, equity_bindings={}))
    source = ROOT / "research/S019/experiments/EX001_20261110"
    evidence = []
    materials = (
        ("analysis-source", WORK / "src/analyze.py", "text/x-python", "py"),
        ("publication-source", Path(__file__), "text/x-python", "py"),
        ("first-round-protocol", WORK / "protocols/first_round.md", "text/markdown", "md"),
        ("analysis-results", WORK / "others/results.json", "application/json", "json"),
        ("event-observations", WORK / "others/events.csv", "text/csv", "csv"),
        ("return-components", WORK / "others/return_components.csv", "text/csv", "csv"),
        ("daily-data-identity", source / "others/daily_preparation.json", "application/json", "json"),
        ("m30-data-identity", source / "others/m30_preparation.json", "application/json", "json"),
        ("shared-read-source", source / "src/load_data.py", "text/x-python", "py"),
        ("shared-request-source", source / "src/prepare_data.py", "text/x-python", "py"),
        ("canonical-fill-source", ROOT / "packages/execution_channels/src/execution_channels/historical/fills.py", "text/x-python", "py"),
    )
    for name, path, mime, extension in materials:
        evidence.append(publish_evidence(context, d.MaterialEvidenceWrite(EXP, name, path.read_bytes(), mime, extension)))
    pointer = WORK / "report_ref.json"
    previous = d.EvidenceRef.from_dict(json.loads(pointer.read_text(encoding="utf-8"))["report"]) if pointer.exists() else None
    report = publish_evidence(context, d.ExperimentReportWrite(EXP, sha256((WORK / "report.md").read_bytes()).hexdigest(), d.ExperimentOutcome.COMPLETED, tuple(evidence), previous=previous))
    validation = validate_experiment(repo, d.ExperimentValidationRequest(EXP, d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status is d.ValidationStatus.PASS
    result = {"report": report.to_dict(), "evidence": [ref.to_dict() for ref in evidence], "validation": validation.to_dict()}
    (WORK / "others/publication.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(validation.status.value, report.sha256)


if __name__ == "__main__":
    main()
