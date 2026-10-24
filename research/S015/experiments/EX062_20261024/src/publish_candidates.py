"""S015 stage-three publication helper, using public APIs only.

Usage (paths relative to repository root):
  python -B .tmp/s015_stage3_publish.py schema
  python -B .tmp/s015_stage3_publish.py check path/to/reviewed_manifest.json
  python -B .tmp/s015_stage3_publish.py publish path/to/reviewed_manifest.json --output .tmp/unique_receipt.json

`schema` emits a skeleton. `check` is read-only: authenticates sources, identifies
the selected executable candidates, checks typed records and existing registrations;
it never registers, publishes, evaluates an account, or writes a check file.
`publish` additionally requires reviewed_for_publication=true and a new .tmp receipt.
It publishes explicit materials/reports, registers selected candidates, reloads and
identifies them, then assembles CANDIDATES/6 with FULL verification. This does not
authorize stage four, restore historical qualification, or decide research judgments.

Manifest fields:
  result_sources: one per completed experiment; results/protocol_refs are {path,sha256};
    source_root is the exact runtime root; dependencies is [{name,version}];
    results_alias names an automatically prepared results material; search contains
    search_id,method,scope,selection,limitations (human-reviewed prose).
  references: alias->{ref: complete EvidenceRef.to_dict()} OR
    alias->{file: relative JSON path,pointer:[keys/indices]}; existing evidence only.
  materials: [{alias,experiment_id,path,sha256,name(optional)}].
  reports: [{experiment_id,sha256,outcome,evidence:[aliases],previous:alias|null}].
  candidates: [{candidate_id,payload:{path,sha256},hypothesis,judgment,
    handoff:bool,support:[optional additional account aliases]}]. All center passes
    and the global four-objective nondominated set must appear; extra retained
    candidates require retention_reason. All listed candidates are registered.
    Handoff may contain center passes only. No unassessed old candidate is promoted.
  conclusion: researcher-authored CandidateSet conclusion.
  delivery: {revision:6,report:{path,sha256},status,incomplete_items,evidence:[aliases]}.

Generated account aliases are `account:EX058_20261024:C5800`. All material/report
paths must be S015-relative within the repository. Search evaluations count formal
account scenarios only; unique_configurations count distinct effective content
identities within that experiment, with technical repetitions recorded separately.
Exact predecessor references are frozen below and checked against public and asset
receipts. Their full transitive evidence is authenticated by assemble_delivery.
After partial failure, retain the receipt; immutable same-content APIs may reuse
published objects on a reviewed retry with a fresh receipt path. Never overwrite
or delete previous publications to make this helper pass.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from hashlib import sha256
from importlib.metadata import version as installed_version
import json
import math
import os
from pathlib import Path, PurePosixPath
import sys

sys.dont_write_bytecode = True
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
for env_name in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[env_name] = "1"

# ruff: noqa: E402
from strategy_manager import CandidateKey
from strategy_runtime import ImplementationDependency, StrategyCandidate, StrategyRuntime
from czsc_trader.application import (
    CandidateRegistrationRequest,
    RepositoryContext,
    assemble_delivery,
    create_research_context,
    load_candidate,
    publish_evidence,
    register_candidate,
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
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "research/S015").is_dir())
BATCH = ResearchBatchRef("S015")
MIME = {"py": "text/x-python", "json": "application/json", "md": "text/markdown", "csv": "text/csv"}
PREDECESSORS = (
    ("PROTOTYPES", 1, "463ae84ebc118b683d25ce4318e508f7594d5971b4e0077c79a72c80da169688"),
    ("MANDATE", 3, "5563c98c1a2ed876b6d75b775437f35ec2c31777818ad0f9b67e89c90d30d90a"),
    ("CANDIDATES", 5, "a41bbbda40606a2c8ca8a9e93bc046a501b6601f1de33fb37b4bc3d9ec1cdefc"),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_path(relative, *, temporary=False):
    require(isinstance(relative, str), "Path must be a relative string")
    value = PurePosixPath(relative.replace("\\", "/"))
    require(
        not value.is_absolute() and ".." not in value.parts and ":" not in relative,
        "Unsafe relative path",
    )
    target = ROOT.joinpath(*value.parts).resolve()
    allowed = ROOT / (".tmp" if temporary else "research/S015")
    require(target.is_relative_to(allowed.resolve()), "Path is outside the authorized S015 scope")
    return target


def manifest_path(relative):
    normalized = relative.replace("\\", "/")
    return safe_path(relative, temporary=normalized.startswith(".tmp/"))


def read(path):
    return json.loads(path.read_bytes())


def frozen(spec, *, temporary=False):
    target = safe_path(spec["path"], temporary=temporary)
    content = target.read_bytes()
    require(sha256(content).hexdigest() == spec["sha256"], f"Reviewed file changed: {spec['path']}")
    return target, content


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def evidence(value):
    ref = EvidenceRef.from_dict(value)
    require(ref.experiment.strategy_id == "S015", "Other research batches are outside scope")
    ref.resolve(ROOT)
    return ref


def select_reference(spec):
    if set(spec) == {"ref"}:
        return evidence(spec["ref"])
    require(set(spec) == {"file", "pointer"}, "Unknown evidence selector")
    value = read(safe_path(spec["file"]))
    for key in spec["pointer"]:
        value = value[key]
    return evidence(value)


def material(alias, experiment_id, path, content, refs, writes, name=None):
    require(alias not in refs, f"Duplicate reference alias: {alias}")
    suffix = path.suffix[1:]
    write = MaterialEvidenceWrite(
        ExperimentRef("S015", experiment_id), name or path.stem, content, MIME[suffix], suffix
    )
    digest = sha256(content).hexdigest()
    ref = EvidenceRef(write.experiment, f"{digest}.{suffix}", digest, write.media_type, write.name)
    refs[alias] = ref
    writes.append((alias, write))
    return ref


def exact_predecessors():
    values = []
    for stage, revision, digest in PREDECESSORS:
        relative = f"research/S015/deliveries/{stage}/{revision}/receipt.json"
        public = safe_path(relative)
        asset = safe_path(relative.replace("/deliveries/", "/assets/deliveries/"))
        require(
            public.read_bytes() == asset.read_bytes(), "Public/asset predecessor receipts differ"
        )
        receipt = d.DeliveryReceipt.from_dict(read(public))
        expected = d.DeliveryReference(BATCH, d.DeliveryStage(stage), revision, digest)
        require(receipt.reference == expected, f"Predecessor identity changed: {stage}/{revision}")
        values.append(expected)
    return tuple(values)


def center_pass(row):
    full, common = row["runs"]["full"], row["runs"]["s011_common"]
    fields = (
        "net_return",
        "cagr",
        "dd",
        "benchmark_cagr",
        "benchmark_dd",
        "frequency_median",
        "frequency_good",
        "frequency_windows",
    )
    require(
        all(math.isfinite(v[k]) for v in (full, common) for k in fields),
        "Nonfinite economic metric",
    )
    require(
        full["frequency_windows"] == 375 and common["frequency_windows"] == 356,
        "Evaluation window changed",
    )
    require(
        math.isclose(full["benchmark_cagr"], 0.16938742022084918, rel_tol=0, abs_tol=1e-12)
        and math.isclose(full["benchmark_dd"], 0.36289990457799626, rel_tol=0, abs_tol=1e-12),
        "Frozen standard-cost development benchmark changed",
    )
    checks = {
        "return": full["cagr"] >= 1.5 * full["benchmark_cagr"]
        if full["benchmark_cagr"] > 0
        else full["cagr"] > 0,
        "relative_drawdown": full["dd"] <= 0.8 * full["benchmark_dd"],
        "absolute_drawdown": full["dd"] <= 0.25,
        "frequency_median": full["frequency_median"] >= 6,
        "frequency_coverage": full["frequency_good"] * 10 >= 9 * full["frequency_windows"],
    }
    require(checks == full["checks"], "Reported full-window checks differ from metrics")
    result = (
        all(checks.values())
        and common["net_return"] > 0.9158029150000013
        and common["dd"] < 0.07248663749114126
    )
    require(
        type(row["both_center_pass"]) is bool and row["both_center_pass"] == result,
        "Reported joint center pass differs",
    )
    return result


def vector(row):
    return tuple(
        value
        for window in ("full", "s011_common")
        for value in (row["runs"][window]["net_return"], -row["runs"][window]["dd"])
    )


def frontier(rows):
    vectors = {key: vector(item["row"]) for key, item in rows.items()}
    return {
        key
        for key, values in vectors.items()
        if not any(
            other != key
            and all(a >= b for a, b in zip(candidate, values, strict=True))
            and any(a > b for a, b in zip(candidate, values, strict=True))
            for other, candidate in vectors.items()
        )
    }


def account_candidate(ref, value, candidate, identity):
    require(
        (ref.schema, ref.schema_version) == ("account_evaluation", 7),
        "Candidate support must be account schema7",
    )
    validate_evaluation_evidence(value)  # Numeric authentication; does not run a new account.
    request = value["request_identity"]
    require(
        request["symbol"] == "159326.SZ"
        and request["asset_type"] == "etf"
        and request["initial_cash"] == 100000.0
        and request["data_cutoff"] == "2026-10-21"
        and request["price_basis"] == "HFQ_RESEARCH"
        and request["execution_mode"] == "FULL",
        "Selected account differs from authorized economic context",
    )
    require(
        request["costs"]
        == [{"measurement_tier": "FORMAL", "one_way_cost": 0.001, "scenario_id": "standard"}],
        "Only standard-cost formal accounts support stage-three centers",
    )
    require(
        request["windows"]
        == [
            {"end": "2026-10-21", "start": "2025-01-02", "window_id": "full"},
            {"end": "2026-10-21", "start": "2025-02-06", "window_id": "s011_common"},
        ],
        "Selected account windows differ from frozen mandate",
    )
    require(
        value["request_identity"]["experiment_id"] == ref.experiment.experiment_id,
        "Account experiment differs",
    )
    expected = CandidateKey("S015", candidate.candidate_id).to_dict()
    require(
        bool(value["runs"])
        and all(
            run["identity"]["candidate"] == expected
            and run["identity"]["content_sha256"] == identity.content_sha256
            for run in value["runs"]
        ),
        "Account/candidate content mismatch",
    )


def prepare(manifest):
    require(manifest["schema_version"] == 1, "Unsupported helper manifest schema")
    refs = {key: select_reference(spec) for key, spec in manifest["references"].items()}
    writes, rows, searches, experiment_counts = [], {}, [], []
    result_specs = manifest["result_sources"]
    require(bool(result_specs), "Explicit completed stage-three experiment scope required")
    seen_experiments = set()
    for spec in result_specs:
        ex = ExperimentRef("S015", spec["experiment_id"])
        require(ex.experiment_id not in seen_experiments, "Duplicate experiment search")
        seen_experiments.add(ex.experiment_id)
        result_path, result_bytes = frozen(spec["results"])
        require(
            result_path.parent.parent == ex.resolve(ROOT),
            "Results must belong to declared experiment",
        )
        result = json.loads(result_bytes)
        require(result["new_configurations"] == len(result["rows"]), "Configuration count mismatch")
        require(
            result["formal_accounts"] == 2 * len(result["rows"]), "Formal account count mismatch"
        )
        require(
            all(t["state"] == "TrialState.COMPLETE" for t in result["optuna"])
            and len(result["optuna"]) == len(result["rows"]),
            "Search trials incomplete",
        )
        _, protocol_bytes = frozen(spec["protocol_refs"])
        protocol_refs = json.loads(protocol_bytes)
        frozen_source_paths = set()
        for relative, raw_ref in protocol_refs.items():
            local = safe_path(relative)
            ref = evidence(raw_ref)
            require(
                local.read_bytes() == ref.resolve(ROOT).read_bytes(),
                f"Prospective source/protocol changed: {relative}",
            )
            frozen_source_paths.add(local)
        source_root = safe_path(spec["source_root"])
        protocol_path = ex.resolve(ROOT) / "protocols/accounts.json"
        require(protocol_path in frozen_source_paths, "Prospective account protocol is missing")
        require(
            read(protocol_path)["stage"] == 3,
            "Only stage-three result sources may populate this selection",
        )
        dependencies = tuple(ImplementationDependency(**x) for x in spec["dependencies"])
        for dependency in dependencies:
            require(
                installed_version(dependency.name) == dependency.version,
                "Runtime dependency version changed",
            )
        source_ids = set()
        for row in result["rows"]:
            key = row["candidate_id"]
            require(key not in rows, "Candidate ID repeated across declared result sources")
            ref = evidence(row["evidence"])
            require(ref.experiment == ex, "Result account belongs to another experiment")
            alias = f"account:{ex.experiment_id}:{key}"
            require(alias not in refs, "Generated account alias already supplied")
            refs[alias] = ref
            require(
                set(row["runs"]) == {"full", "s011_common"}, "Exact two-window contract required"
            )
            passed = center_pass(row)
            content_hash = row["identity"]["content_sha256"]
            source_ids.add(content_hash)
            rows[key] = {
                "row": row,
                "experiment": ex,
                "source_root": source_root,
                "dependencies": dependencies,
                "frozen_source_paths": frozen_source_paths,
                "alias": alias,
                "center_pass": passed,
            }
        require(
            result["center_pass_count"]
            == sum(rows[r["candidate_id"]]["center_pass"] for r in result["rows"]),
            "Center count mismatch",
        )
        result_ref = material(
            spec["results_alias"],
            ex.experiment_id,
            result_path,
            result_bytes,
            refs,
            writes,
            "stage3-results",
        )
        search = spec["search"]
        searches.append(
            d.SearchSummary(
                search["search_id"],
                search["method"],
                search["scope"],
                result["formal_accounts"],
                len(source_ids),
                search["selection"],
                tuple(search["limitations"]),
                (result_ref,),
            )
        )
        experiment_counts.append(
            {
                "experiment_id": ex.experiment_id,
                "declared_configurations": len(result["rows"]),
                "unique_content_identities": len(source_ids),
                "formal_accounts": result["formal_accounts"],
                "technical_accounts": result["technical_accounts"],
            }
        )
    for spec in manifest["materials"]:
        source, content = frozen(spec)
        material(
            spec["alias"], spec["experiment_id"], source, content, refs, writes, spec.get("name")
        )
    passing = {key for key, item in rows.items() if item["center_pass"]}
    nondominated = frontier(rows)
    selected = {item["candidate_id"] for item in manifest["candidates"]}
    require(len(selected) == len(manifest["candidates"]), "Duplicate selected candidate")
    require(
        passing | nondominated <= selected <= rows.keys(),
        "Selection must retain every joint center pass and every four-objective frontier",
    )
    repo, runtime = RepositoryContext.discover(ROOT), StrategyRuntime()
    registrations, entries, handoff, identities = [], [], [], []
    for item in manifest["candidates"]:
        key = item["candidate_id"]
        selected_row = rows[key]
        row = selected_row["row"]
        if key not in passing | nondominated:
            require(
                bool(item.get("retention_reason", "").strip()),
                "Additional retained candidate needs a reason",
            )
        _, payload_bytes = frozen(item["payload"])
        payload = json.loads(payload_bytes)
        require(payload["parameters"] == row["parameters"], "Payload/result parameters differ")
        candidate = StrategyCandidate("S015", key, payload, selected_row["source_root"])
        for source in payload["runtime"]["source_files"]:
            require(
                (candidate.source_root / source).resolve() in selected_row["frozen_source_paths"],
                "Runtime source lacks prospective authenticated reference",
            )
        identity = runtime.identify(candidate, dependencies=selected_row["dependencies"])
        require(
            identity.content_sha256 == row["identity"]["content_sha256"],
            "Live runtime identity differs from evaluated content",
        )
        aliases = [selected_row["alias"], *item.get("support", [])]
        supporting = tuple(refs[alias] for alias in aliases)
        for position, ref in enumerate(supporting):
            account = read(ref.resolve(ROOT))
            if position == 0:
                require(
                    account["request_hash"] == row["request_hash"]
                    and account["result_hash"] == row["result_hash"],
                    "Result row hashes differ from primary account evidence",
                )
            account_candidate(ref, account, candidate, identity)
        request = CandidateRegistrationRequest(
            candidate, selected_row["experiment"], supporting, selected_row["dependencies"]
        )
        registrations.append((request, identity))
        entries.append(
            d.CandidateEntry(
                d.CandidateIdentityRef(CandidateKey("S015", key), identity.content_sha256),
                item["hypothesis"],
                item["judgment"],
                tuple(d.EvaluationEvidenceRef(ref, ()) for ref in supporting),
            )
        )
        require(type(item["handoff"]) is bool, "handoff must be boolean")
        require(
            not item["handoff"] or key in passing,
            "A nonpassing frontier cannot be placed in the center-passing handoff",
        )
        if item["handoff"]:
            handoff.append(CandidateKey("S015", key))
        # Existing registration must load and match. Absence is an ordinary new candidate.
        candidate_record = ROOT / "research/registrations/S015/candidates" / f"{key}.json"
        if candidate_record.exists():
            loaded = load_candidate(repo, CandidateKey("S015", key))
            require(
                runtime.identify(loaded, dependencies=selected_row["dependencies"]) == identity,
                "Existing registration content conflict",
            )
        identities.append(
            {
                "candidate_id": key,
                "identity": asdict(identity),
                "center_pass": key in passing,
                "frontier": key in nondominated,
                "handoff": item["handoff"],
            }
        )
    reports = []
    require(
        {item["experiment_id"] for item in manifest["reports"]} == seen_experiments
        and len(manifest["reports"]) == len(seen_experiments),
        "Every completed search experiment requires exactly one reviewed report publication request",
    )
    for item in manifest["reports"]:
        ex = ExperimentRef("S015", item["experiment_id"])
        require(
            ex.experiment_id in seen_experiments,
            "Report outside completed stage-three search scope",
        )
        _, _ = frozen(
            {
                "path": f"research/S015/experiments/{ex.experiment_id}/report.md",
                "sha256": item["sha256"],
            }
        )
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
    delivery = manifest["delivery"]
    require(delivery["revision"] == 6, "This reviewed continuation targets CANDIDATES/6 only")
    _, report_bytes = frozen(delivery["report"])
    definition = d.DeliveryDefinition(
        BATCH, d.DeliveryStage.CANDIDATES, 6, exact_predecessors(), schema_version=8
    )
    panel = d.CandidateSet(tuple(entries), tuple(handoff), tuple(searches), manifest["conclusion"])
    content = d.DeliveryContent(
        panel,
        d.DeliveryStatus(delivery["status"]),
        (),
        (),
        tuple(delivery["incomplete_items"]),
        report=report_bytes.decode("utf-8"),
        evidence=tuple(refs[key] for key in delivery["evidence"]),
    )
    summary = {
        "experiments": experiment_counts,
        "center_passes": sorted(passing),
        "four_objective_frontier": sorted(nondominated),
        "selected": identities,
        "predecessors": [ref.to_dict() for ref in definition.predecessors],
        "scientific_limit": "Center eligibility is not stage-four qualification; no new account or independent sample was created.",
        "identity_limit": "Content identities are not independent economic strategies; same economic paths and noninfluential parameters require researcher disclosure.",
    }
    return refs, writes, reports, registrations, definition, content, summary


def skeleton():
    return {
        "schema_version": 1,
        "reviewed_for_publication": False,
        "references": {},
        "result_sources": [
            {
                "experiment_id": "EX058_20261024",
                "results": {
                    "path": "research/S015/experiments/EX058_20261024/others/results.json",
                    "sha256": "REVIEWED_SHA256",
                },
                "protocol_refs": {
                    "path": "research/S015/experiments/EX058_20261024/others/protocol_refs.json",
                    "sha256": "REVIEWED_SHA256",
                },
                "source_root": "research/S015/experiments/EX058_20261024/src/strategy_runtime",
                "dependencies": [],
                "results_alias": "ex058_results",
                "search": {
                    "search_id": "S015_stage3_EX058",
                    "method": "RSCH填写",
                    "scope": "RSCH填写",
                    "selection": "全部联合中心达标与四目标非支配前沿",
                    "limitations": [
                        "重复开发样本；两个窗口重叠；技术重复不是独立证据",
                        "不同内容身份可能具有相同经济行为；非影响参数不能算作扰动维度，具体由RSCH填写",
                    ],
                },
            }
        ],
        "materials": [],
        "reports": [
            {
                "experiment_id": "EX058_20261024",
                "sha256": "REVIEWED_SHA256",
                "outcome": "COMPLETED",
                "evidence": ["ex058_results"],
                "previous": None,
            }
        ],
        "candidates": [
            {
                "candidate_id": "C5800",
                "payload": {
                    "path": "research/S015/experiments/EX058_20261024/others/C5800_payload.json",
                    "sha256": "REVIEWED_SHA256",
                },
                "hypothesis": "RSCH填写",
                "judgment": "RSCH填写",
                "handoff": False,
                "support": [],
            }
        ],
        "conclusion": "RSCH审阅后的完整阶段三结论，不自动进入阶段四",
        "delivery": {
            "revision": 6,
            "report": {
                "path": "research/S015/materials/stage3_report.md",
                "sha256": "REVIEWED_SHA256",
            },
            "status": "COMPLETE",
            "incomplete_items": [],
            "evidence": ["ex058_results"],
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=("schema", "check", "publish"))
    parser.add_argument("manifest", nargs="?")
    parser.add_argument("--output", help="New .tmp receipt path, publish only")
    args = parser.parse_args()
    if args.command == "schema":
        print(json.dumps(skeleton(), ensure_ascii=False, indent=2))
        return
    require(bool(args.manifest), "Reviewed manifest path required")
    manifest_bytes = manifest_path(args.manifest).read_bytes()
    manifest = json.loads(manifest_bytes)
    if args.command == "publish":
        require(
            manifest.get("reviewed_for_publication") is True,
            "Manifest is not marked reviewed for publication",
        )
        require(bool(args.output), "Publication requires a new receipt path")
        output = safe_path(args.output, temporary=True)
        require(not output.exists(), "Preserve previous receipt; choose a new path")
    refs, writes, reports, requests, definition, content, summary = prepare(manifest)
    if args.command == "check":
        require(args.output is None, "Check is read-only; omit --output")
        print(
            json.dumps(
                {"status": "READ_ONLY_PLAN_CHECK_PASS", **summary}, ensure_ascii=False, indent=2
            )
        )
        return
    repo = RepositoryContext.discover(ROOT)
    resources = ExecutionResources(4, 1, 13)
    context = create_research_context(repo, BATCH, resources=resources)
    journal = {
        "status": "STARTED",
        "manifest_sha256": sha256(manifest_bytes).hexdigest(),
        "summary": summary,
        "references": {k: v.to_dict() for k, v in refs.items()},
        "reports": [],
        "registrations": [],
    }
    save(output, journal)
    for alias, write in writes:
        published = publish_evidence(context, write)
        require(published == refs[alias], "Published material differs from reviewed bytes")
    report_refs = []
    for request in reports:
        ref = publish_evidence(context, request)
        checked = validate_experiment(
            repo,
            ExperimentValidationRequest(
                request.experiment, ExperimentValidationScope.REPORT_PUBLICATION
            ),
        )
        journal["reports"].append({"reference": ref.to_dict(), "validation": checked.to_dict()})
        save(output, journal)
        require(checked.status.value == "PASS", "Experiment report validation failed")
        report_refs.append(ref)
    runtime = StrategyRuntime()
    for request, expected in requests:
        registered = register_candidate(repo, request)
        loaded = load_candidate(repo, registered.key)
        actual = runtime.identify(loaded, dependencies=request.dependencies)
        require(
            actual == expected and registered.content_sha256 == expected.content_sha256,
            "Registered candidate reload identity mismatch",
        )
        journal["registrations"].append(
            {"registration": registered.to_dict(), "load_identify": asdict(actual)}
        )
        save(output, journal)
    content = replace(content, evidence=tuple(dict.fromkeys((*content.evidence, *report_refs))))
    assembled = assemble_delivery(repo, definition, content, resources=resources)
    require(
        assembled.validation.status is d.ValidationStatus.PASS
        and assembled.validation.scope is d.DeliveryValidationScope.FULL,
        "Candidate delivery did not return FULL PASS",
    )
    journal.update({"status": "CANDIDATES_FULL_PUBLICATION_PASS", "assembly": assembled.to_dict()})
    save(output, journal)
    print(
        json.dumps(
            {
                "status": journal["status"],
                "reference": assembled.receipt.reference.to_dict(),
                "registered": len(requests),
                "handoff": len(content.payload.handoff),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
