"""Prepare reviewed frozen implementations for the explicit history contract.

Preparation creates a new candidate workspace, never a release, registration,
deployment or account result. Source packages and their registries stay intact.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, fields, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4

from strategy_manager import StrategyRegistry, StrategyVersion, CandidateKey, canonical_sha256
from strategy_manager import freeze_contracts as f
from strategy_manager.freeze_contracts import FrozenVersionReference
from strategy_manager.write_lock import RegistryWriteLock
from strategy_runtime import (
    DecisionFeedback, RuntimeBinding, RuntimeDefinition, StrategyCandidate,
    StrategyDefinition, StrategyRuntime, implementation_sha256,
)

from .context import RepositoryContext
from .runtime_acceptance import prospective_release
from .strategy_runtime_service import validate_release_package


_SUPPORTED = {
    "S001-v1": ("strategies/s001_common.py", "S001Base"),
    "S001-v2": ("strategies/s001_common.py", "S001Base"),
    "S002-v1": ("strategies/s002_v1.py", "S002V1"),
    "S003-v1": ("strategies/s003_v1.py", "S003V1"),
    "S007-v1": ("strategies/s007_v1.py", "S007V1"),
    "S011-v1": ("strategies/s011_reversal.py", "S011Reversal"),
}


@dataclass(frozen=True, slots=True)
class FrozenRuntimeMigrationRequest:
    reference: str
    candidate_id: str
    output_directory: Path

    def __post_init__(self):
        if self.reference not in _SUPPORTED:
            raise ValueError("frozen runtime migration has no reviewed adapter for this version")
        if not isinstance(self.candidate_id, str) or not re.fullmatch(r"C[0-9]{4}", self.candidate_id):
            raise ValueError("migration candidate identity must be C plus four ASCII digits")
        if not isinstance(self.output_directory, Path):
            raise TypeError("output_directory must be Path")


@dataclass(frozen=True, slots=True)
class PreparedFrozenRuntimeMigration:
    candidate: StrategyCandidate
    metadata_path: Path
    original_package_sha256: str
    original_source_sha256: str
    migrated_source_sha256: str
    migrated_content_sha256: str
    equivalence_status: str


def _method(node: ast.ClassDef, name: str) -> ast.FunctionDef:
    matches = [item for item in node.body if isinstance(item, ast.FunctionDef) and item.name == name]
    if len(matches) != 1:
        raise ValueError(f"reviewed frozen adapter requires exactly one {name}")
    return matches[0]


def _rewrite(source: str, reference: str, class_name: str) -> str:
    """Transform only the explicitly reviewed class and kernel source spans."""
    tree = ast.parse(source)
    classes = [item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == class_name]
    if len(classes) != 1:
        raise ValueError("reviewed frozen implementation class differs")
    cls = classes[0]
    if len(cls.bases) != 1 or not isinstance(cls.bases[0], ast.Name) or cls.bases[0].id != "StrategyImplementation":
        raise ValueError("reviewed frozen implementation base differs")
    lines = source.splitlines(keepends=True)
    old = _method(cls, "calculate_history")
    window = next((item for item in cls.body if isinstance(item, ast.FunctionDef) and item.name == "calculate_window_history"), None)
    selected = window if reference in {"S002-v1", "S011-v1"} else old
    body = "".join(lines[selected.body[0].lineno - 1:selected.end_lineno])
    header = (
        "    def calculate_context_history(self, inputs, context: HistoryCalculationContext):\n"
        "        sessions = context.sessions\n"
    )
    if reference == "S002-v1":
        if body.count("            states.reindex(requested),") != 1:
            raise ValueError("reviewed S002 market-intent replay differs")
        body = body.replace(
            "            states.reindex(requested),",
            "            states if context.mode is SignalHistoryMode.CONTINUOUS else states.reindex(requested),",
        )
        body = body.replace("        return history\n", "        return history.reindex(requested)\n")
    edits = [(old.lineno - 1, old.end_lineno, header + body)]
    if window is not None:
        edits.append((window.lineno - 1, window.end_lineno, ""))
    base = cls.bases[0]
    base_line = lines[base.lineno - 1]
    edits.append((base.lineno - 1, base.lineno, base_line[:base.col_offset] + "StrategyImplementationV2" + base_line[base.end_col_offset:]))
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start:end] = [replacement]
    transformed = "".join(lines)
    insertion = next(item.end_lineno for item in tree.body if isinstance(item, ast.ImportFrom) and item.module == "__future__")
    transformed_lines = transformed.splitlines(keepends=True)
    names = "HistoryCalculationContext, StrategyImplementationV2"
    if reference == "S002-v1":
        names += ", SignalHistoryMode"
    transformed_lines.insert(insertion, f"from strategy_runtime import {names}\n")
    result = "".join(transformed_lines)
    compile(result, reference, "exec")
    return result


def prepare_frozen_runtime_migration(
    context: RepositoryContext, request: FrozenRuntimeMigrationRequest,
) -> PreparedFrozenRuntimeMigration:
    """Authenticate one frozen package and prepare a new, unregistered candidate.

    All preparations require subsequent numerical and execution equivalence
    evidence. S007 retains its declared canonical market-intent reconstruction;
    independently initialized execution accounts do not inherit its holdings.
    """
    if not isinstance(context, RepositoryContext) or not isinstance(request, FrozenRuntimeMigrationRequest):
        raise TypeError("migration requires RepositoryContext and FrozenRuntimeMigrationRequest")
    destination = request.output_directory
    if not destination.is_absolute():
        destination = context.root / destination
    # Workspace creation is deliberately confined to repository scratch storage.
    scratch = context.root.resolve() / ".tmp"
    if destination.is_symlink() or not destination.resolve().is_relative_to(scratch) or destination.resolve() == scratch:
        raise ValueError("migration output must be a new directory under repository .tmp")
    for parent in (destination, *destination.parents):
        if parent == context.root:
            break
        if parent.is_symlink() or parent.is_junction():
            raise ValueError("migration workspace must not contain filesystem links")
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError("migration output already exists; retain it and choose a new workspace")
    strategy_id, version = request.reference.rsplit("-", 1)
    registry = StrategyRegistry(context.strategy_root)
    stored = registry.get_version(strategy_id, version)
    if request.candidate_id == stored.source_candidate:
        raise ValueError("migration must use a new candidate identity")
    manifest, binding, source = validate_release_package(context, request.reference)
    release = prospective_release(stored)
    if release.payload["runtime"]["contract_version"] == 2:
        raise ValueError("frozen version already implements contract version 2; retain its committed migration evidence")
    relative, class_name = _SUPPORTED[request.reference]
    transformed = _rewrite((source / relative).read_text(encoding="utf-8"), request.reference, class_name)
    protected = {name: sha256((source / name).read_bytes()).hexdigest() for name in binding["source_files"]}
    payload = json.loads(json.dumps(dict(release.payload), default=dict))
    target = destination / "strategy_runtime"
    target.mkdir(parents=True)
    for name in binding["install_files"]:
        output = target / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, output)
    (target / relative).write_text(transformed, encoding="utf-8", newline="\n")
    descriptor = payload["runtime"]
    descriptor["contract_version"] = 2
    descriptor["source_sha256"] = implementation_sha256(tuple(descriptor["source_files"]), source_root=target)
    payload["decision_feedback"] = "MARKET_INTENT"
    candidate = StrategyCandidate(strategy_id, request.candidate_id, payload, target)
    runtime = StrategyRuntime()
    identity = runtime.identify(candidate, dependencies=())
    definition = runtime.describe(candidate)
    status = "NOT_YET_NUMERICALLY_VERIFIED"
    metadata = {
        "schema_version": 1,
        "status": "PREPARED_UNREGISTERED",
        "original_reference": request.reference,
        "original_release_sha256": release.release_hash,
        "original_package_sha256": manifest["package_hash"],
        "original_source_sha256": binding["implementation_sha256"],
        "candidate_id": request.candidate_id,
        "candidate_identity": asdict(identity),
        "equivalence_status": status,
        "decision_feedback": "MARKET_INTENT",
        "decision_feedback_review": "REVIEWED_MARKET_INTENT_NO_ACTUAL_FILL_DEPENDENCY",
        "market_intent_history": definition.history.mode,
        "requires": ["numerical_signal_equivalence", "order_fill_fee_cash_position_equivalence", "TDR_PTE_execution_equivalence"],
        "registered": False,
        "frozen": False,
        "deployed": False,
        "protected_source_files": protected,
    }
    if any(sha256((source / name).read_bytes()).hexdigest() != digest for name, digest in protected.items()):
        raise ValueError("original frozen source changed during migration preparation")
    payload_path = destination / "candidate_payload.json"
    payload_path.write_text(json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metadata_path = destination / "migration.json"
    metadata_path.write_text(json.dumps(metadata, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return PreparedFrozenRuntimeMigration(candidate, metadata_path, manifest["package_hash"], binding["implementation_sha256"], identity.source_sha256, identity.content_sha256, status)


def validate_frozen_runtime_migration(
    context: RepositoryContext, original: FrozenVersionReference, candidate: StrategyCandidate,
) -> RuntimeDefinition:
    """Authenticate the reviewed conversion without changing a file or registry.

    This proves source and business-contract provenance. Numerical equivalence
    requires separately authenticated real-input evidence and inspection.
    """
    if (type(context) is not RepositoryContext or type(original) is not FrozenVersionReference
            or type(candidate) is not StrategyCandidate):
        raise TypeError("migration validation requires typed repository, frozen source and candidate")
    reference = f"{original.strategy_id}-{original.version}"
    if reference not in _SUPPORTED or candidate.strategy_family_id != original.strategy_id:
        raise ValueError("migration source is unsupported or belongs to another family")
    if candidate.source_root is None or not candidate.source_root.is_relative_to(context.root.resolve()):
        raise ValueError("migration candidate requires repository-owned source")
    stored, manifest, binding, source = _migration_original(context, original)
    release = prospective_release(stored)
    relative, class_name = _SUPPORTED[reference]
    converted = _rewrite((source / relative).read_text(encoding="utf-8"), reference, class_name).encode("utf-8")
    source_files = tuple(release.payload["runtime"]["source_files"])
    expected_files = {name: converted if name == relative else (source / name).read_bytes()
                      for name in binding["install_files"]}
    actual_files = set()
    for path in candidate.source_root.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("migration source closure must not contain links")
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        name = path.relative_to(candidate.source_root).as_posix()
        actual_files.add(name)
        if name not in expected_files or path.read_bytes() != expected_files[name]:
            raise ValueError("migration source differs from the reviewed conversion")
    if not set(source_files) <= actual_files:
        raise ValueError("migration source closure omits required files")
    digest = sha256()
    for name in sorted(source_files):
        digest.update(name.encode("utf-8") + b"\0" + expected_files[name] + b"\0")
    payload = json.loads(json.dumps(dict(release.payload), default=dict))
    payload["runtime"]["contract_version"] = 2
    payload["runtime"]["source_sha256"] = digest.hexdigest()
    payload["decision_feedback"] = "MARKET_INTENT"
    if json.loads(json.dumps(dict(candidate.payload), default=dict)) != payload:
        raise ValueError("migration payload changes original parameters or reviewed contracts")
    runtime = StrategyRuntime()
    before = runtime.describe(release, source_root=source, runtime_binding=RuntimeBinding.from_dict(binding))
    after = runtime.describe(candidate)
    if after.decision_feedback is not DecisionFeedback.MARKET_INTENT:
        raise ValueError("migration requires MARKET_INTENT feedback")
    if any(getattr(before, item.name) != getattr(after, item.name) for item in fields(StrategyDefinition)):
        raise ValueError("migration changes the original business definition")
    return after


def _trading_source_tree(data, class_name):
    """Exclude only the reviewed observation extension points from source comparison."""
    tree = ast.parse(data)

    class Declaration(ast.NodeTransformer):
        count = 0

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == "StrategyDefinition":
                for keyword in node.keywords:
                    if keyword.arg == "observation":
                        keyword.value = ast.Constant("<observation>")
                        self.count += 1
            return self.generic_visit(node)

    declaration = Declaration()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            node.body = [item for item in node.body if not (
                isinstance(item, ast.FunctionDef)
                and item.name in {"observation_definition", "observation_history"})]
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    declaration.visit(item)
    if declaration.count != 1:
        raise ValueError("observation upgrade requires one explicit StrategyDefinition observation declaration")
    return ast.dump(tree, include_attributes=False)


def validate_frozen_observation_upgrade(
    context: RepositoryContext, original: FrozenVersionReference, candidate: StrategyCandidate,
) -> RuntimeDefinition:
    """Authenticate observation-only source/contract changes; numerical proof is separate.

    Existing trading code is retained, apart from the observation declaration
    expression in __init__. New code belongs to the two observation methods
    and observation_* sidecar modules, imported locally by those methods.
    """
    if (type(context) is not RepositoryContext or type(original) is not FrozenVersionReference
            or type(candidate) is not StrategyCandidate):
        raise TypeError("observation upgrade requires typed source and candidate")
    if candidate.strategy_family_id != original.strategy_id:
        raise ValueError("observation upgrade candidate family differs")
    if candidate.source_root is None or not candidate.source_root.is_relative_to(context.root.resolve()):
        raise ValueError("observation upgrade requires repository-owned source")
    stored, _, binding, source = _migration_original(context, original)
    release = prospective_release(stored)
    old_payload = json.loads(json.dumps(dict(release.payload), default=dict))
    new_payload = json.loads(json.dumps(dict(candidate.payload), default=dict))
    for value in (old_payload, new_payload):
        value["runtime"].pop("source_sha256")
        value["runtime"].pop("source_files")
    if new_payload != old_payload or new_payload["runtime"]["contract_version"] != 2:
        raise ValueError("observation upgrade changes parameters or execution descriptors")
    old_files = set(release.payload["runtime"]["source_files"])
    new_files = set(candidate.payload["runtime"]["source_files"])
    if not old_files <= new_files:
        raise ValueError("observation upgrade removes trading source files")
    actual = set()
    for path in candidate.source_root.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("observation upgrade source must not contain links")
        if path.is_file() and "__pycache__" not in path.parts:
            actual.add(path.relative_to(candidate.source_root).as_posix())
    if actual != set(binding["install_files"]) | new_files:
        raise ValueError("observation upgrade source closure differs")
    module = release.payload["runtime"]["module"].removeprefix("strategy_runtime.").replace(".", "/") + ".py"
    class_name = release.payload["runtime"]["qualname"]
    for name in actual:
        data = (candidate.source_root / name).read_bytes()
        if name in binding["install_files"]:
            old = (source / name).read_bytes()
            if name == module:
                if _trading_source_tree(data, class_name) != _trading_source_tree(old, class_name):
                    raise ValueError("observation upgrade changes trading source")
            elif data != old:
                raise ValueError("observation upgrade changes original dependencies")
        elif not Path(name).name.startswith("observation_") or not name.endswith(".py"):
            raise ValueError("observation upgrade adds a non-observation source file")
    if implementation_sha256(tuple(candidate.payload["runtime"]["source_files"]),
                              source_root=candidate.source_root) != candidate.payload["runtime"]["source_sha256"]:
        raise ValueError("observation upgrade source hash differs")
    runtime = StrategyRuntime()
    before = runtime.describe(release, source_root=source, runtime_binding=RuntimeBinding.from_dict(binding))
    after = runtime.describe(candidate)
    for name in ("parameters", "inputs", "decision", "execution", "monitoring", "capabilities",
                 "tradable_symbol", "state_mode", "history", "decision_feedback"):
        if getattr(before, name) != getattr(after, name):
            raise ValueError(f"observation upgrade changes trading contract: {name}")
    if (after.observation.signal_panel is None
            or before.observation.series != after.observation.series
            or before.observation.facts != after.observation.facts):
        raise ValueError("observation upgrade must retain a panel while preserving legacy observations")
    if candidate.payload["runtime"]["source_sha256"] == release.payload["runtime"]["source_sha256"]:
        raise ValueError("observation upgrade requires a changed observation implementation or declaration")
    return after


@dataclass(frozen=True, slots=True)
class FrozenRuntimeUpgradeRequest:
    original: FrozenVersionReference
    candidate: CandidateKey
    inspection: f.ResearchEvidenceRef
    confirmation: f.ResearchEvidenceRef
    output_directory: Path

    def __post_init__(self):
        for name, kind in (("original", FrozenVersionReference), ("candidate", CandidateKey),
                           ("inspection", f.ResearchEvidenceRef), ("confirmation", f.ResearchEvidenceRef),
                           ("output_directory", Path)):
            if not isinstance(getattr(self, name), kind):
                raise TypeError(f"{name} requires {kind.__name__}")
        if self.original.strategy_id != self.candidate.strategy_id:
            raise ValueError("upgrade source and candidate family differ")


@dataclass(frozen=True, slots=True)
class PreparedFrozenRuntimeUpgrade:
    plan_path: Path
    plan_sha256: str
    original: FrozenVersionReference
    migrated: FrozenVersionReference

    def __post_init__(self):
        if not isinstance(self.plan_path, Path):
            raise TypeError("plan_path requires Path")
        if type(self.plan_sha256) is not str or re.fullmatch(r"[a-f0-9]{64}", self.plan_sha256) is None:
            raise ValueError("plan_sha256 requires lowercase SHA-256")
        if type(self.original) is not FrozenVersionReference or type(self.migrated) is not FrozenVersionReference:
            raise TypeError("upgrade identities require FrozenVersionReference")
        if ((self.original.strategy_id, self.original.version) != (self.migrated.strategy_id, self.migrated.version)
                or self.original == self.migrated):
            raise ValueError("runtime upgrade must change content while preserving family/version")


@dataclass(frozen=True, slots=True)
class FrozenRuntimeUpgradeReceipt:
    status: f.FreezeStatus
    original: FrozenVersionReference
    migrated: FrozenVersionReference
    archive_path: Path
    receipt_path: Path

    def __post_init__(self):
        if self.status is not f.FreezeStatus.COMMITTED:
            raise TypeError("successful runtime upgrade receipt requires FreezeStatus.COMMITTED")
        if type(self.original) is not FrozenVersionReference or type(self.migrated) is not FrozenVersionReference:
            raise TypeError("upgrade identities require FrozenVersionReference")
        if not isinstance(self.archive_path, Path) or not isinstance(self.receipt_path, Path):
            raise TypeError("upgrade receipt paths require Path")
        if (self.original.strategy_id, self.original.version) != (self.migrated.strategy_id, self.migrated.version):
            raise ValueError("runtime upgrade receipt must preserve family/version")


def _upgrade_json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n").encode("utf-8")


def _upgrade_write(path, data, scratch):
    temporary = scratch / ("write-" + uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _upgrade_files(root):
    result = {}
    if root.is_symlink() or root.is_junction():
        raise ValueError("runtime upgrade paths must not contain links")
    for path in root.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("runtime upgrade paths must not contain links")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha256(path.read_bytes()).hexdigest()
    return result


def _validated_upgrade_archive(context, original, *, plan_sha256=None):
    """Resolve only the explicit committed content-addressed historical revision."""
    reference = f"{original.strategy_id}-{original.version}"
    archive = context.strategy_root / "revisions" / reference / original.release_hash
    receipt = json.loads((archive / "upgrade_receipt.json").read_bytes())
    snapshot = json.loads((archive / "snapshot.json").read_bytes())
    plan_bytes = (archive / "upgrade_plan.json").read_bytes()
    plan = json.loads(plan_bytes)
    digest = sha256(plan_bytes).hexdigest()
    if (receipt.get("status") != "COMMITTED" or receipt.get("original") != original.to_dict()
            or snapshot.get("original") != original.to_dict() or plan.get("original") != original.to_dict()
            or receipt.get("plan_sha256") != digest or snapshot.get("plan_sha256") != digest
            or (plan_sha256 is not None and digest != plan_sha256)
            or receipt.get("migrated") != plan.get("migrated")):
        raise ValueError("runtime upgrade archive receipt/snapshot identity differs")
    actual = _upgrade_files(archive)
    actual.pop("snapshot.json")
    actual.pop("upgrade_receipt.json")
    if actual != snapshot["files"]:
        raise ValueError("runtime upgrade archived file identities differ")
    archived_context = replace(context, strategy_root=archive / "strategies")
    stored = StrategyRegistry(archived_context.strategy_root).get_version(original.strategy_id, original.version)
    manifest, binding, source = validate_release_package(archived_context, reference)
    if (stored.release_hash != original.release_hash or manifest["package_hash"] != original.package_hash
            or sha256((archived_context.strategy_root / original.strategy_id / "versions" /
                       f"{original.version}.json").read_bytes()).hexdigest() != plan["original_version_sha256"]):
        raise ValueError("runtime upgrade archive differs from original frozen CAS identity")
    deployment = archived_context.strategy_root / "deployments" / f"{reference}.json"
    if (sha256(deployment.read_bytes()).hexdigest() if deployment.exists() else None) != plan["original_deployment_sha256"]:
        raise ValueError("runtime upgrade archive deployment differs from original CAS identity")
    return archived_context, stored, manifest, binding, source, receipt


def _migration_original(context, original):
    reference = f"{original.strategy_id}-{original.version}"
    stored = StrategyRegistry(context.strategy_root).get_version(original.strategy_id, original.version)
    if stored.release_hash == original.release_hash:
        manifest, binding, source = validate_release_package(context, reference)
    else:
        archive = context.strategy_root / "revisions" / reference / original.release_hash
        if not (archive / "upgrade_receipt.json").is_file():
            raise ValueError("migration frozen source release/package identity differs")
        _, stored, manifest, binding, source, _ = _validated_upgrade_archive(context, original)
    if manifest["strategy_version_hash"] != original.release_hash or manifest["package_hash"] != original.package_hash:
        raise ValueError("migration frozen source release/package identity differs")
    return stored, manifest, binding, source


def _upgrade_inputs(context, request):
    from .candidate_service import load_candidate
    from .research_evidence import validate_inspection, read_decision

    report = validate_inspection(context.root, request.inspection)
    if report.status is not f.InspectionStatus.PASS or report.plan is None:
        raise ValueError("runtime upgrade requires a complete passing technical inspection")
    selection = read_decision(context.root, report.selection)
    if (type(selection.subject) not in (f.FrozenMigrationSelectionSubject, f.FrozenObservationUpgradeSelectionSubject)
            or selection.subject.original != request.original
            or selection.subject.candidate != request.candidate
            or report.plan.version != request.original.version
            or selection.confirmation_source != request.confirmation
            or request.confirmation.owner.strategy_id != request.original.strategy_id):
        raise ValueError("runtime upgrade inspection/source/confirmation identity differs")
    request.confirmation.resolve(context.root)
    candidate = load_candidate(context, request.candidate)
    validator = (validate_frozen_observation_upgrade
                 if type(selection.subject) is f.FrozenObservationUpgradeSelectionSubject
                 else validate_frozen_runtime_migration)
    validator(context, request.original, candidate)
    reference = f"{request.original.strategy_id}-{request.original.version}"
    manifest, binding, source = validate_release_package(context, reference)
    if (manifest["strategy_version_hash"], manifest["package_hash"]) != (request.original.release_hash, request.original.package_hash):
        raise ValueError("runtime upgrade requires current original frozen CAS identity")
    registry = StrategyRegistry(context.strategy_root)
    stored = registry.get_version(request.original.strategy_id, request.original.version)
    if (report.plan.parent_version, report.plan.selection_data_cutoff.isoformat(), report.plan.forward_start.isoformat()) != (
            stored.parent_version, stored.selection_data_cutoff, stored.forward_start):
        raise ValueError("same-version upgrade must preserve frozen origin and dates")
    return report, candidate, stored, manifest, binding, source


def prepare_frozen_runtime_upgrade(
    context: RepositoryContext, request: FrozenRuntimeUpgradeRequest,
) -> PreparedFrozenRuntimeUpgrade:
    """Stage an authenticated same-version replacement; no frozen files change.

    The inspection proves technical migration. Its human confirmation must
    explicitly authorize in-place upgrade; selection never grants PTE access.
    """
    if type(context) is not RepositoryContext or type(request) is not FrozenRuntimeUpgradeRequest:
        raise TypeError("runtime upgrade preparation requires typed repository and request")
    destination = request.output_directory
    if not destination.is_absolute():
        destination = context.root / destination
    scratch = context.root.resolve() / ".tmp"
    if not destination.resolve().is_relative_to(scratch) or destination.resolve() == scratch:
        raise ValueError("runtime upgrade preparation must stay under repository .tmp")
    for path in (destination, *destination.parents):
        if path == context.root:
            break
        if path.is_symlink() or path.is_junction():
            raise ValueError("runtime upgrade workspace must not contain links")
    if destination.exists():
        raise FileExistsError("runtime upgrade preparation already exists")
    report, candidate, stored, manifest, binding, source = _upgrade_inputs(context, request)
    # Publish the exact package that passed both technical goals, preserving the
    # original version metadata through the migration-specific version builder.
    release = report.release
    version = StrategyVersion.from_dict(json.loads(release.version_record.resolve(context.root).read_bytes()))
    family, number = stored.strategy_id, stored.version
    reference = stored.release_id
    stage_root = destination / "staged"
    package = stage_root / family / "releases" / number
    package.mkdir(parents=True)
    for item in release.files:
        target = package / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.source.resolve(context.root).read_bytes())
    manifest_bytes = release.manifest.resolve(context.root).read_bytes()
    (package / "release_manifest.json").write_bytes(manifest_bytes)
    new_manifest = json.loads(manifest_bytes)
    version_path = stage_root / family / "versions" / f"{number}.json"
    version_path.parent.mkdir(parents=True)
    version_path.write_bytes(release.version_record.resolve(context.root).read_bytes())
    deployment_path = context.strategy_root / "deployments" / f"{reference}.json"
    old_deployment = None
    if deployment_path.exists():
        from strategy_runtime import load_strategy_deployment
        deployment = load_strategy_deployment(context.strategy_root, reference)
        if deployment.release_hash != request.original.release_hash or deployment.package_hash != request.original.package_hash:
            raise ValueError("runtime upgrade installed receipt differs from the frozen source")
        old_deployment = deployment_path.read_bytes()
        value = json.loads(old_deployment)
        value.update(strategy_version_hash=version.release_hash, package_hash=new_manifest["package_hash"])
        value.pop("receipt_hash")
        value["receipt_hash"] = canonical_sha256(value)
        target = stage_root / "deployments" / deployment_path.name
        target.parent.mkdir(parents=True)
        target.write_bytes(_upgrade_json(value))
    staged_context = replace(context, strategy_root=stage_root)
    validate_release_package(staged_context, reference, expected_release=prospective_release(version))
    migrated = FrozenVersionReference(family, number, version.release_hash, new_manifest["package_hash"])
    old_version = context.strategy_root / family / "versions" / f"{number}.json"
    plan = {"schema_version": 1, "status": "PREPARED_SAME_VERSION_UPGRADE",
        "original": request.original.to_dict(), "migrated": migrated.to_dict(),
        "candidate": request.candidate.to_dict(), "inspection": request.inspection.to_dict(),
        "confirmation": request.confirmation.to_dict(), "files": _upgrade_files(stage_root),
        "original_version_sha256": sha256(old_version.read_bytes()).hexdigest(),
        "original_deployment_sha256": sha256(old_deployment).hexdigest() if old_deployment is not None else None,
        "qualification": "RESEARCH", "production_writes": 0}
    path = destination / "upgrade_plan.json"
    path.write_bytes(_upgrade_json(plan))
    return PreparedFrozenRuntimeUpgrade(path, sha256(path.read_bytes()).hexdigest(), request.original, migrated)


def apply_frozen_runtime_upgrade(
    context: RepositoryContext, prepared: PreparedFrozenRuntimeUpgrade,
) -> FrozenRuntimeUpgradeReceipt:
    """CAS replace local frozen content with archived provenance and rollback.

    This operation never changes lifecycle records, PTE state or production.
    A partial write is restored before raising; interrupted processes remain
    explicitly nonterminal in the archive and require investigation.
    """
    if type(context) is not RepositoryContext or type(prepared) is not PreparedFrozenRuntimeUpgrade:
        raise TypeError("runtime upgrade apply requires typed repository and preparation")
    plan_path = prepared.plan_path
    if (not plan_path.resolve().is_relative_to(context.root / ".tmp")
            or sha256(plan_path.read_bytes()).hexdigest() != prepared.plan_sha256):
        raise ValueError("runtime upgrade plan identity/path differs")
    plan = json.loads(plan_path.read_bytes())
    if plan["original"] != prepared.original.to_dict() or plan["migrated"] != prepared.migrated.to_dict():
        raise ValueError("runtime upgrade preparation identity differs")
    stage = plan_path.parent / "staged"
    if _upgrade_files(stage) != plan["files"]:
        raise ValueError("runtime upgrade staged file identity differs")
    request = FrozenRuntimeUpgradeRequest(prepared.original, CandidateKey(**plan["candidate"]),
        f.ResearchEvidenceRef.from_dict(plan["inspection"]), f.ResearchEvidenceRef.from_dict(plan["confirmation"]),
        plan_path.parent)
    family, number = prepared.original.strategy_id, prepared.original.version
    reference = f"{family}-{number}"
    archive = context.strategy_root / "revisions" / reference / prepared.original.release_hash
    receipt_path = archive / "upgrade_receipt.json"
    package = context.strategy_root / family / "releases" / number
    version_path = context.strategy_root / family / "versions" / f"{number}.json"
    deployment_path = context.strategy_root / "deployments" / f"{reference}.json"
    with RegistryWriteLock(context.strategy_root).hold():
        if receipt_path.exists():
            _, _, _, _, _, receipt = _validated_upgrade_archive(context, prepared.original,
                                                                 plan_sha256=prepared.plan_sha256)
            if receipt["migrated"] != prepared.migrated.to_dict():
                raise ValueError("runtime upgrade receipt migrated identity differs")
            current, _, _ = validate_release_package(context, reference)
            if (current["strategy_version_hash"], current["package_hash"]) != (
                    prepared.migrated.release_hash, prepared.migrated.package_hash):
                raise ValueError("committed runtime upgrade differs from current frozen content")
            if plan["original_deployment_sha256"] is not None:
                from strategy_runtime import load_strategy_deployment
                deployment = load_strategy_deployment(context.strategy_root, reference)
                if (deployment.release_hash, deployment.package_hash) != (prepared.migrated.release_hash, prepared.migrated.package_hash):
                    raise ValueError("committed runtime upgrade deployment identity differs")
            return FrozenRuntimeUpgradeReceipt(f.FreezeStatus.COMMITTED, prepared.original, prepared.migrated, archive, receipt_path)
        report, candidate, stored, old_manifest, binding, _ = _upgrade_inputs(context, request)
        before_version = version_path.read_bytes()
        before_deployment = deployment_path.read_bytes() if deployment_path.exists() else None
        if (sha256(before_version).hexdigest() != plan["original_version_sha256"]
                or (sha256(before_deployment).hexdigest() if before_deployment is not None else None)
                != plan["original_deployment_sha256"]):
            raise ValueError("runtime upgrade original version/deployment changed after preparation")
        # Rebuild exact staged semantics rather than trusting caller-written hashes.
        expected_version = replace(stored, strategy_payload=json.loads(json.dumps(dict(candidate.payload), default=dict)), release_hash="0" * 64)
        expected_version = replace(expected_version, release_hash=canonical_sha256(expected_version.release_payload()))
        staged_version = stage / family / "versions" / f"{number}.json"
        if (staged_version.read_bytes() != report.release.version_record.resolve(context.root).read_bytes()
                or StrategyVersion.from_dict(json.loads(staged_version.read_bytes())) != expected_version):
            raise ValueError("runtime upgrade changes frozen history fields")
        staged_context = replace(context, strategy_root=stage)
        staged_manifest, staged_binding, staged_source = validate_release_package(
            staged_context, reference, expected_release=prospective_release(expected_version))
        if staged_manifest["package_hash"] != prepared.migrated.package_hash:
            raise ValueError("runtime upgrade staged package identity differs")
        expected_manifest = json.loads(report.release.manifest.resolve(context.root).read_bytes())
        if (staged_manifest != expected_manifest or staged_manifest["package_hash"] != report.release.package_sha256
                or expected_version.release_hash != report.release.release_sha256):
            raise ValueError("runtime upgrade differs from the inspected package")
        from .research_evidence import read_decision
        observation_upgrade = (hasattr(report, "selection") and
            type(read_decision(context.root, report.selection).subject) is f.FrozenObservationUpgradeSelectionSubject)
        changed_binding_fields = {"release_hash", "implementation_sha256"}
        if observation_upgrade:
            changed_binding_fields |= {"observation_sha256", "source_files", "install_files"}
            expected_install = set(binding["install_files"]) | set(candidate.payload["runtime"]["source_files"])
            if (set(staged_binding["install_files"]) != expected_install
                    or staged_binding["source_files"] != list(candidate.payload["runtime"]["source_files"])):
                raise ValueError("observation upgrade binding source closure differs")
        if {key: value for key, value in staged_binding.items() if key not in changed_binding_fields} != {
                key: value for key, value in binding.items() if key not in changed_binding_fields}:
            raise ValueError("runtime upgrade changes original binding contracts")
        for name in staged_binding["install_files"]:
            expected = ((candidate.source_root / name).read_bytes() if name in candidate.payload["runtime"]["source_files"]
                        else (package / old_manifest["runtime_root"] / name).read_bytes())
            if (staged_source / name).read_bytes() != expected:
                raise ValueError("runtime upgrade staged source differs from reviewed conversion")
        expected_stage_files = {f"{family}/releases/{number}/{name}" for name in staged_manifest["files"]}
        expected_stage_files.update({f"{family}/releases/{number}/release_manifest.json",
                                     f"{family}/versions/{number}.json"})
        if before_deployment is not None:
            from strategy_runtime import load_strategy_deployment
            deployment = load_strategy_deployment(stage, reference)
            if deployment.package_hash != prepared.migrated.package_hash:
                raise ValueError("runtime upgrade staged deployment differs")
            expected_stage_files.add(f"deployments/{reference}.json")
        if set(plan["files"]) != expected_stage_files:
            raise ValueError("runtime upgrade staged publication closure differs")
        if archive.exists():
            raise ValueError("runtime upgrade has a prior nonterminal archive; explicit investigation required")
        archive.mkdir(parents=True)
        old_strategy_root = archive / "strategies"
        old_package = old_strategy_root / family / "releases" / number
        shutil.copytree(package, old_package)
        old_version_path = old_strategy_root / family / "versions" / f"{number}.json"
        old_version_path.parent.mkdir(parents=True)
        old_version_path.write_bytes(before_version)
        if before_deployment is not None:
            old_deployment_path = old_strategy_root / "deployments" / deployment_path.name
            old_deployment_path.parent.mkdir(parents=True)
            old_deployment_path.write_bytes(before_deployment)
        (archive / "upgrade_plan.json").write_bytes(plan_path.read_bytes())
        snapshot = {"original": prepared.original.to_dict(), "plan_sha256": prepared.plan_sha256,
                    "files": _upgrade_files(archive)}
        (archive / "snapshot.json").write_bytes(_upgrade_json(snapshot))
        if _upgrade_files(old_package) != _upgrade_files(package):
            raise ValueError("runtime upgrade archive failed verification")
        for path in archive.rglob("*"):
            if path.is_file():
                with path.open("r+b") as stream:
                    os.fsync(stream.fileno())
        backup = plan_path.parent / "displaced_release"
        next_package = plan_path.parent / "publishing_release"
        shutil.copytree(stage / family / "releases" / number, next_package)
        displaced = installed = False
        try:
            os.replace(package, backup)
            displaced = True
            os.replace(next_package, package)
            installed = True
            _upgrade_write(version_path, staged_version.read_bytes(), plan_path.parent)
            if before_deployment is not None:
                _upgrade_write(deployment_path, (stage / "deployments" / deployment_path.name).read_bytes(), plan_path.parent)
            manifest, _, _ = validate_release_package(context, reference)
            if manifest["package_hash"] != prepared.migrated.package_hash:
                raise ValueError("runtime upgrade post-write package differs")
            if before_deployment is not None:
                from strategy_runtime import load_strategy_deployment
                deployment = load_strategy_deployment(context.strategy_root, reference)
                if deployment.package_hash != prepared.migrated.package_hash:
                    raise ValueError("runtime upgrade post-write deployment differs")
            if StrategyRegistry(context.strategy_root).current_qualification(family, number).value != "RESEARCH":
                raise ValueError("runtime upgrade must start at RESEARCH qualification")
            receipt = {"status": "COMMITTED", "original": prepared.original.to_dict(),
                       "migrated": prepared.migrated.to_dict(), "plan_sha256": prepared.plan_sha256,
                       "inspection": plan["inspection"], "confirmation": plan["confirmation"],
                       "qualification": "RESEARCH", "production_writes": 0}
            _upgrade_write(receipt_path, _upgrade_json(receipt), plan_path.parent)
            _validated_upgrade_archive(context, prepared.original, plan_sha256=prepared.plan_sha256)
        except BaseException as error:
            try:
                receipt_path.unlink(missing_ok=True)
                if installed:
                    os.replace(package, plan_path.parent / "failed_release")
                if displaced:
                    os.replace(backup, package)
                if version_path.read_bytes() != before_version:
                    _upgrade_write(version_path, before_version, plan_path.parent)
                if before_deployment is not None and deployment_path.read_bytes() != before_deployment:
                    _upgrade_write(deployment_path, before_deployment, plan_path.parent)
                validate_release_package(context, reference)
                (archive / "rollback.json").write_bytes(_upgrade_json({"status": "ROLLED_BACK", "error": str(error)}))
            except BaseException as rollback_error:
                raise RuntimeError(f"runtime upgrade failed; rollback incomplete: {rollback_error}") from error
            raise RuntimeError(f"runtime upgrade failed and original content restored: {error}") from error
    return FrozenRuntimeUpgradeReceipt(f.FreezeStatus.COMMITTED, prepared.original, prepared.migrated, archive, receipt_path)
