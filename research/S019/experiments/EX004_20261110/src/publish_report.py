"""Publish the unified-window opportunity evidence."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, validate_experiment
from dataflows import ProviderConfig

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]


def main():
    repo = RepositoryContext.discover(ROOT)
    context = create_research_context(repo, d.ResearchBatchRef("S019"), providers=ProviderConfig(bindings={}, equity_bindings={}))
    experiment = d.ExperimentRef("S019", WORK.name)
    result = json.loads((WORK / "others/results.json").read_text(encoding="utf-8"))
    paths = [ROOT / name for name in result["source_identity"]]
    paths.extend([Path(__file__), WORK / "others/results.json", WORK / "others/events.csv",
        WORK.parent / "EX001_20261110/src/load_data.py", WORK.parent / "EX001_20261110/src/prepare_data.py"])
    evidence = []
    for i, path in enumerate(paths):
        if path.relative_to(ROOT).as_posix() in result["source_identity"]:
            assert sha256(path.read_bytes()).hexdigest() == result["source_identity"][path.relative_to(ROOT).as_posix()]
        extension = path.suffix[1:]
        mime = {"py": "text/x-python", "md": "text/markdown", "json": "application/json", "csv": "text/csv"}[extension]
        evidence.append(publish_evidence(context, d.MaterialEvidenceWrite(experiment, f"material-{i:02d}-{path.stem}", path.read_bytes(), mime, extension)))
    report = publish_evidence(context, d.ExperimentReportWrite(experiment, sha256((WORK / "report.md").read_bytes()).hexdigest(), d.ExperimentOutcome.COMPLETED, tuple(evidence)))
    validation = validate_experiment(repo, d.ExperimentValidationRequest(experiment, d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status is d.ValidationStatus.PASS
    (WORK / "others/publication.json").write_bytes((json.dumps({"report": report.to_dict(), "validation": validation.to_dict()}, ensure_ascii=False, indent=2) + "\n").encode())
    print(validation.status.value, report.sha256)


if __name__ == "__main__":
    main()
