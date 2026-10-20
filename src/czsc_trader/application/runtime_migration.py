"""Prepare reviewed frozen implementations for the explicit history contract.

Preparation creates a new candidate workspace, never a release, registration,
deployment or account result. Source packages and their registries stay intact.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil

from strategy_manager import StrategyRegistry
from strategy_runtime import StrategyCandidate, StrategyRuntime, implementation_sha256

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
    transformed_lines.insert(insertion, "from strategy_runtime import HistoryCalculationContext, StrategyImplementationV2\n")
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
