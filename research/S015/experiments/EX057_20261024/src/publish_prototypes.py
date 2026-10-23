"""Publish an RSCH-reviewed S015 phase-two manifest within user authorization.

Default command is read-only check. `publish` writes only public evidence/delivery APIs.
The reviewed manifest is retained in this experiment's others/final_manifest.json.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from strategy_manager import CandidateKey
from czsc_trader.application import (
    RepositoryContext,
    assemble_delivery,
    create_research_context,
    publish_evidence,
    validate_experiment,
)
from czsc_trader.research_tools import (
    EvidenceRef,
    ExecutionResources,
    ExperimentOutcome,
    ExperimentRef,
    ExperimentReportWrite,
    ExperimentValidationRequest,
    ExperimentValidationScope,
    MaterialEvidenceWrite,
    ResearchBatchRef,
)
from czsc_trader.research_tools import delivery as d

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
BATCH = ResearchBatchRef("S015")
MIME = {"py": "text/x-python", "json": "application/json", "md": "text/markdown", "csv": "text/csv"}


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def path(relative, *, output=False):
    """Restrict this helper to S015 and its task-local temporary area."""
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError(f"Expected repository-relative path: {relative}")
    target = (ROOT / value).resolve()
    allowed = [ROOT / ".tmp", ROOT / "research/S015"]
    if not any(target.is_relative_to(base.resolve()) for base in allowed):
        raise ValueError(f"Path is outside S015 scope: {relative}")
    if output and not target.is_relative_to((ROOT / ".tmp").resolve()):
        raise ValueError("Publication receipt/check output must be under .tmp")
    return target


def experiment(name):
    return ExperimentRef("S015", name)


def existing_reference(spec):
    """Resolve a full reference, JSON pointer, or unique candidate result row."""
    if set(spec) == {"ref"}:
        value = spec["ref"]
    elif set(spec) == {"file", "pointer"}:
        value = read(path(spec["file"]))
        for key in spec["pointer"]:
            value = value[key]
    elif set(spec) == {"results", "candidate_id"}:
        rows = read(path(spec["results"]))["rows"]
        matches = [row for row in rows if row["candidate_id"] == spec["candidate_id"]]
        if len(matches) != 1:
            raise ValueError("Candidate result selector must match exactly one row")
        value = matches[0]["evidence"]
    else:
        raise ValueError(f"Unknown reference selector fields: {set(spec)}")
    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != "S015":
        raise ValueError("Other research batches are outside this manifest scope")
    ref.resolve(ROOT)  # Authenticate the selected published bytes before any writes.
    return ref


def definition(value, refs):
    return d.ExperimentDefinitionRef(refs[value["evidence"]], value["entrypoint"])


def account_identity(evaluations):
    identities = set()
    for evaluation in evaluations:
        value = read(evaluation.evidence.resolve(ROOT))
        for run in value["runs"]:
            item = run["identity"]
            key = item["candidate"]
            identities.add((key["strategy_id"], key["candidate_id"], item["content_sha256"]))
    if len(identities) != 1:
        raise ValueError("Selected accounts must have exactly one candidate/content identity")
    strategy, candidate, content_hash = identities.pop()
    if strategy != "S015":
        raise ValueError("Prototype identity is outside S015")
    return d.CandidateIdentityRef(CandidateKey(strategy, candidate), content_hash)


def build_panel(manifest, refs):
    components = []
    for item in manifest["components"]:
        tests = tuple(
            d.ComponentTestResult(
                test["test_id"],
                test["experiment_id"],
                refs[test["protocol"]],
                d.ComponentTestStatus(test["status"]),
                test["explanation"],
                tuple(refs[key] for key in test["evidence"]),
                (),
            )
            for test in item["tests"]
        )
        components.append(
            d.ComponentEntry(
                item["component_id"],
                definition(item["definition"], refs),
                item["role"],
                item["label"],
                item["horizon"],
                item["control"],
                item["availability"],
                item["price_basis"],
                item["applicability"],
                item["judgment"],
                tests,
            )
        )
    prototypes = []
    for item in manifest["prototypes"]:
        evaluations = tuple(d.EvaluationEvidenceRef(refs[key], ()) for key in item["evaluations"])
        identity = (
            account_identity(evaluations)
            if evaluations
            else d.CandidateIdentityRef.from_dict(item["identity"])
        )
        if identity.key.strategy_id != "S015":
            raise ValueError("Prototype identity is outside S015")
        sources = tuple(
            d.PrototypeReference.from_dict(source) for source in item.get("sources", [])
        )
        prototypes.append(
            d.PrototypeEntry(
                item["prototype_id"],
                identity,
                definition(item["definition"], refs),
                item["hypothesis"],
                tuple(d.PrototypeComponentUse(**use) for use in item["components"]),
                evaluations,
                d.PrototypeDisposition(item["disposition"]),
                item["judgment"],
                tuple(item["limitations"]),
                item["next_step"],
                tuple(refs[key] for key in item["evidence"]),
                item.get("missing_evaluation_reason"),
                sources,
            )
        )
    comparisons = tuple(
        d.PrototypeComparison(
            item["comparison_id"],
            item["subject_id"],
            item["control_id"],
            item["question"],
            refs[item["protocol"]],
            tuple(refs[key] for key in item["evidence"]),
            item["conclusion"],
        )
        for item in manifest["comparisons"]
    )
    return d.PrototypePanel(
        tuple(prototypes), tuple(components), comparisons, manifest["conclusion"]
    )


def prepare(manifest):
    refs = {key: existing_reference(value) for key, value in manifest["references"].items()}
    writes = []
    for item in manifest["materials"]:
        key = item["alias"]
        if key in refs:
            raise ValueError(f"Duplicate reference alias: {key}")
        source = path(item["path"])
        data = source.read_bytes()
        if sha256(data).hexdigest() != item["sha256"]:
            raise ValueError(f"Reviewed material changed: {item['path']}")
        suffix = source.suffix[1:]
        write = MaterialEvidenceWrite(
            experiment(item["experiment_id"]),
            item.get("name", source.stem),
            data,
            MIME[suffix],
            suffix,
        )
        ref = EvidenceRef(
            write.experiment,
            f"{item['sha256']}.{suffix}",
            item["sha256"],
            write.media_type,
            write.name,
        )
        refs[key] = ref
        writes.append((key, write))
    reports = []
    for item in manifest["reports"]:
        ex = experiment(item["experiment_id"])
        source = path(f"research/S015/experiments/{ex.experiment_id}/report.md")
        if sha256(source.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"Reviewed report changed: {ex.experiment_id}")
        previous = refs[item["previous"]] if item.get("previous") else None
        reports.append(
            ExperimentReportWrite(
                ex,
                item["sha256"],
                ExperimentOutcome(item["outcome"]),
                tuple(refs[key] for key in item["evidence"]),
                previous,
            )
        )
    value = manifest["delivery"]
    predecessors = tuple(d.DeliveryReference.from_dict(ref) for ref in value["predecessors"])
    delivery_definition = d.DeliveryDefinition(
        BATCH, d.DeliveryStage.PROTOTYPES, value["revision"], predecessors, schema_version=10
    )
    report_bytes = path(value["report_path"]).read_bytes()
    if sha256(report_bytes).hexdigest() != value["report_sha256"]:
        raise ValueError("Reviewed delivery report changed")
    content = d.DeliveryContent(
        build_panel(manifest, refs),
        d.DeliveryStatus(value["status"]),
        (),
        (),
        tuple(value["incomplete_items"]),
        report=report_bytes.decode("utf-8"),
        evidence=tuple(refs[key] for key in value["evidence"]),
    )
    return refs, writes, reports, delivery_definition, content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="Repository-relative reviewed manifest JSON")
    parser.add_argument("command", choices=("check", "publish"), nargs="?", default="check")
    parser.add_argument("--output", default=".tmp/s015_prototype_publication.json")
    args = parser.parse_args()
    manifest_path = path(args.manifest)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if args.command == "publish" and manifest.get("reviewed_for_publication") is not True:
        raise ValueError("Only an explicitly reviewed manifest may be published")
    refs, writes, reports, delivery_definition, content = prepare(manifest)
    output = path(args.output, output=True)
    journal = {
        "manifest": manifest_path.relative_to(ROOT).as_posix(),
        "manifest_sha256": sha256(manifest_bytes).hexdigest(),
        "mode": args.command,
        "research_judgments": "RSCH-reviewed manifest within authorized stage two; technical checks do not establish efficacy or qualification.",
        "references": {key: ref.to_dict() for key, ref in refs.items()},
        "reports": [],
        "definition": delivery_definition.to_dict(),
        "content": content.to_dict(),
    }
    if args.command == "check":
        journal["status"] = "TYPED_MANIFEST_CHECK_ONLY"
        save(output, journal)
        print(
            json.dumps(
                {
                    "status": journal["status"],
                    "prototypes": len(content.payload.prototypes),
                    "materials_to_publish": len(writes),
                    "reports_to_publish": len(reports),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return
    if output.exists():
        raise FileExistsError("Use a fresh --output for publication; retain earlier receipts")
    repo = RepositoryContext.discover(ROOT)
    resources = ExecutionResources(1, 1, 13)
    ctx = create_research_context(repo, BATCH, resources=resources)
    journal["status"] = "STARTED"
    save(output, journal)
    for key, write in writes:
        published = publish_evidence(ctx, write)
        if published != refs[key]:
            raise ValueError("Material publication differs from reviewed bytes")
    for report in reports:
        published = publish_evidence(ctx, report)
        validation = validate_experiment(
            repo,
            ExperimentValidationRequest(
                report.experiment, ExperimentValidationScope.REPORT_PUBLICATION
            ),
        )
        journal["reports"].append(
            {"reference": published.to_dict(), "validation": validation.to_dict()}
        )
        save(output, journal)
        if validation.status.value != "PASS":
            raise ValueError(f"Report publication validation failed: {validation.issues}")
    assembled = assemble_delivery(repo, delivery_definition, content, resources=resources)
    # assemble_delivery itself completes FULL authentication/recomputation/final recheck.
    if (
        assembled.validation.status is not d.ValidationStatus.PASS
        or assembled.validation.scope is not d.DeliveryValidationScope.FULL
    ):
        raise ValueError("Delivery assembly did not return FULL PASS")
    journal["assembly"] = assembled.to_dict()
    journal["status"] = "FULL_PUBLICATION_PASS"
    save(output, journal)
    print(
        json.dumps(
            {"status": journal["status"], "reference": assembled.receipt.reference.to_dict()},
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
