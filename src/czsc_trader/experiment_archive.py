"""Tracked, portable archives for formal research rounds."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re

from .identity import normalized_text_sha256, raw_file_sha256


REQUIRED_DOCUMENTS = (
    "01_goal.md",
    "02_design.md",
    "03_execution.md",
    "04_conclusion.md",
)
MANIFEST_NAME = "experiment_manifest.json"
GOVERNANCE_SIDECARS = {"evaluation_acceptance.json"}
TEXT_SUFFIXES = {".csv", ".html", ".json", ".md", ".py", ".svg", ".txt"}
STRATEGY_EXPERIMENT_PATTERN = re.compile(
    r"(?P<date>[0-9]{8})_(?P<strategy_id>S[0-9]{3})_EX[0-9]{2}$"
)
STRATEGY_ID_PATTERN = re.compile(r"S[0-9]{3}$")


def iter_experiment_dirs(root: Path) -> tuple[Path, ...]:
    """Return every archive below the strategy-organized experiment root."""
    root = Path(root).resolve()
    if not root.is_dir():
        return ()
    directories = sorted(
        {path.parent for path in root.rglob(MANIFEST_NAME)},
        key=lambda path: path.relative_to(root).as_posix(),
    )
    identities: dict[str, Path] = {}
    for directory in directories:
        relative = directory.relative_to(root)
        if len(relative.parts) > 2:
            raise ValueError(f"experiment archive is nested too deeply: {relative.as_posix()}")
        previous = identities.setdefault(directory.name, directory)
        if previous != directory:
            raise ValueError(f"duplicate experiment_id directory: {directory.name}")
    return tuple(directories)


def resolve_experiment_dir(root: Path, experiment_id: str) -> Path:
    """Resolve one globally unique experiment ID without exposing path traversal."""
    if not experiment_id or Path(experiment_id).name != experiment_id:
        raise ValueError("experiment must be a single experiment ID")
    root = Path(root).resolve()
    direct = root / experiment_id
    matches = (
        [direct] if direct.is_dir() and not STRATEGY_ID_PATTERN.fullmatch(experiment_id) else []
    )
    matches.extend(
        strategy_root / experiment_id
        for strategy_root in root.iterdir()
        if strategy_root.is_dir() and (strategy_root / experiment_id).is_dir()
    )
    if not matches:
        raise ValueError(f"experiment does not exist: {experiment_id}")
    if len(matches) > 1:
        raise ValueError(f"experiment ID is ambiguous: {experiment_id}")
    return matches[0]


def experiment_repository_reference(experiments_root: Path, experiment_dir: Path) -> str:
    """Return the repository-relative reference for an archive directory."""
    root = Path(experiments_root).resolve()
    directory = Path(experiment_dir).resolve()
    relative = directory.relative_to(root)
    return f"experiments/{relative.as_posix()}"


def resolve_repository_experiment_reference(repository_root: Path, reference: str) -> Path:
    """Resolve current and historical ``experiments/<id>/...`` references."""
    root = Path(repository_root).resolve()
    relative = Path(reference)
    if ".." in relative.parts:
        raise ValueError("repository reference must not contain parent traversal")
    if relative.is_absolute() or not relative.parts or relative.parts[0] != "experiments":
        return (root / relative).resolve()
    direct = (root / relative).resolve()
    if direct.exists() or len(relative.parts) < 2:
        return direct
    experiment = resolve_experiment_dir(root / "experiments", relative.parts[1])
    resolved = experiment.joinpath(*relative.parts[2:]).resolve()
    resolved.relative_to(experiment)
    return resolved


def create_experiment_dir(root: Path, run_date: date, strategy_id: str) -> Path:
    """Create the next strategy-owned ``YYYYMMDD_SXXX_EXnn`` directory."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if not STRATEGY_ID_PATTERN.fullmatch(strategy_id):
        raise ValueError("strategy_id must match S plus three digits")
    strategy_root = root / strategy_id
    strategy_root.mkdir(exist_ok=True)
    prefix = f"{run_date:%Y%m%d}_{strategy_id}_EX"
    pattern = re.compile(rf"{re.escape(prefix)}(\d{{2}})")
    numbers = [
        int(match.group(1))
        for path in strategy_root.iterdir()
        if path.is_dir() and (match := pattern.fullmatch(path.name))
    ]
    revision = max(numbers, default=0) + 1
    if revision > 99:
        raise RuntimeError(f"{prefix} has already reached EX99")
    experiment_dir = strategy_root / f"{prefix}{revision:02d}"
    experiment_dir.mkdir(exist_ok=False)
    return experiment_dir


def _file_record(path: Path) -> dict[str, object]:
    if path.suffix.lower() in TEXT_SUFFIXES:
        normalized = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        return {"bytes": len(normalized), "sha256": normalized_text_sha256(path)}
    return {"bytes": path.stat().st_size, "sha256": raw_file_sha256(path)}


def _is_managed_file(experiment_dir: Path, path: Path) -> bool:
    relative = path.relative_to(experiment_dir)
    return (
        path.is_file()
        and path.name != MANIFEST_NAME
        and path.name not in GOVERNANCE_SIDECARS
        and "__pycache__" not in relative.parts
        and path.suffix.lower() != ".pyc"
        and (not relative.parts or relative.parts[0] != "runtime")
    )


def _validate_strategy_experiment_identity(
    experiment_dir: Path, metadata: dict[str, object]
) -> None:
    match = STRATEGY_EXPERIMENT_PATTERN.fullmatch(experiment_dir.name)
    if match is None:
        return
    if metadata.get("experiment_id") != experiment_dir.name:
        raise ValueError("experiment_id must equal the strategy experiment directory")
    if metadata.get("strategy_id") != match.group("strategy_id"):
        raise ValueError("strategy_id must equal the strategy experiment owner")
    if STRATEGY_ID_PATTERN.fullmatch(experiment_dir.parent.name) and (
        experiment_dir.parent.name != match.group("strategy_id")
    ):
        raise ValueError("strategy experiment directory must match the strategy owner")
    if not isinstance(metadata.get("symbol"), str) or not metadata["symbol"]:
        raise ValueError("strategy experiment must declare symbol")
    try:
        date.fromisoformat(str(metadata["development_cutoff"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("strategy experiment must declare development_cutoff") from exc


def validate_experiment_manifest_metadata(
    experiment_dir: Path, metadata: dict[str, object]
) -> None:
    """Validate static archive metadata without writing a manifest."""

    experiment_dir = Path(experiment_dir).resolve()
    if not isinstance(metadata, dict):
        raise TypeError("experiment manifest metadata must be a dict")
    try:
        serialized = json.dumps(metadata, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("experiment manifest metadata must be JSON-safe") from exc
    if "outputs/" in serialized or re.search(r"_R\d{2}", serialized):
        raise ValueError("experiment manifest must not reference outputs revisions")
    _validate_strategy_experiment_identity(experiment_dir, metadata)


def build_experiment_manifest(
    experiment_dir: Path,
    metadata: dict[str, object],
) -> dict[str, object]:
    """Write a deterministic manifest for every managed file in an archive."""
    experiment_dir = Path(experiment_dir).resolve()
    validate_experiment_manifest_metadata(experiment_dir, metadata)
    files = {
        path.relative_to(experiment_dir).as_posix(): _file_record(path)
        for path in sorted(experiment_dir.rglob("*"))
        if _is_managed_file(experiment_dir, path)
    }
    manifest = {"schema_version": 1, **metadata, "files": files}
    serialized = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if "outputs/" in serialized or re.search(r"_R\d{2}", serialized):
        raise ValueError("experiment manifest must not reference outputs revisions")
    (experiment_dir / MANIFEST_NAME).write_text(serialized, encoding="utf-8")
    return manifest


def _validate_integrity_repair(
    experiment_dir: Path,
    manifest: dict[str, object],
    files: dict[str, object],
) -> None:
    """Verify that a resealed archive preserves and explains its original manifest."""
    schema_version = manifest.get("schema_version")
    repair_identity = manifest.get("integrity_repair")
    if schema_version == 1:
        if repair_identity is not None:
            raise ValueError("schema v1 experiment manifest must not declare integrity repair")
        return
    if schema_version != 2 or not isinstance(repair_identity, dict):
        raise ValueError("resealed experiment manifest must use schema v2 integrity repair")

    required = {
        "record",
        "record_sha256",
        "supersedes",
        "supersedes_sha256",
    }
    if set(repair_identity) != required:
        raise ValueError("integrity repair identity is incomplete")
    record_name = str(repair_identity["record"])
    original_name = str(repair_identity["supersedes"])
    if Path(record_name).name != record_name or Path(original_name).name != original_name:
        raise ValueError("integrity repair files must be archive-root filenames")
    for name, hash_key in (
        (record_name, "record_sha256"),
        (original_name, "supersedes_sha256"),
    ):
        current = files.get(name)
        if not isinstance(current, dict):
            raise ValueError(f"integrity repair file is absent from manifest: {name}")
        if current.get("sha256") != repair_identity[hash_key]:
            raise ValueError(f"integrity repair hash differs from manifest: {name}")

    try:
        original = json.loads((experiment_dir / original_name).read_text(encoding="utf-8"))
        repair = json.loads((experiment_dir / record_name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read integrity repair chain: {exc}") from exc
    if not isinstance(original, dict) or not isinstance(repair, dict):
        raise ValueError("integrity repair chain files must contain JSON objects")
    experiment_id = manifest.get("experiment_id")
    if (
        original.get("experiment_id") != experiment_id
        or repair.get("experiment_id") != experiment_id
    ):
        raise ValueError("integrity repair experiment identity differs")
    if repair.get("decision") != "PRESERVE_ORIGINAL_MANIFEST_AND_RESEAL_CURRENT_ARCHIVE":
        raise ValueError("integrity repair decision is invalid")

    original_identity = repair.get("original_manifest")
    if not isinstance(original_identity, dict):
        raise ValueError("integrity repair lacks original manifest identity")
    if original_identity.get("path") != original_name:
        raise ValueError("integrity repair original manifest path differs")
    original_record = files[original_name]
    if original_identity.get("bytes") != original_record.get("bytes") or original_identity.get(
        "sha256"
    ) != original_record.get("sha256"):
        raise ValueError("integrity repair original manifest identity differs")

    original_files = original.get("files")
    corrections = repair.get("corrected_files")
    if not isinstance(original_files, dict) or not isinstance(corrections, list):
        raise ValueError("integrity repair corrections are invalid")
    correction_records: dict[str, dict[str, object]] = {}
    for item in corrections:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("integrity repair correction is invalid")
        name = str(item["path"])
        if name in correction_records:
            raise ValueError(f"duplicate integrity repair correction: {name}")
        correction_records[name] = item

    changed_names = {
        name for name, old_record in original_files.items() if files.get(name) != old_record
    }
    if set(correction_records) != changed_names:
        raise ValueError("integrity repair does not exactly explain manifest differences")
    for name, correction in correction_records.items():
        if correction.get("original_record") != original_files.get(name):
            raise ValueError(f"integrity repair original record differs: {name}")
        if correction.get("current_record") != files.get(name):
            raise ValueError(f"integrity repair current record differs: {name}")


def validate_experiment_archive(experiment_dir: Path) -> dict[str, object]:
    """Validate required documents and every file declared by the manifest."""
    experiment_dir = Path(experiment_dir).resolve()
    manifest_path = experiment_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError(f"missing experiment manifest: {MANIFEST_NAME}")
    serialized = manifest_path.read_text(encoding="utf-8")
    if "outputs/" in serialized or re.search(r"_R\d{2}", serialized):
        raise ValueError("experiment manifest must not reference outputs revisions")
    manifest = json.loads(serialized)
    _validate_strategy_experiment_identity(experiment_dir, manifest)
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("experiment manifest files must be an object")
    actual_names = {
        path.relative_to(experiment_dir).as_posix()
        for path in experiment_dir.rglob("*")
        if _is_managed_file(experiment_dir, path)
    }
    undeclared = sorted(actual_names - set(files))
    if undeclared:
        raise ValueError(f"experiment files not declared by manifest: {undeclared}")

    for name in REQUIRED_DOCUMENTS:
        if name not in files or not (experiment_dir / name).is_file():
            raise ValueError(f"missing required document: {name}")

    for relative_name, expected in files.items():
        relative = Path(str(relative_name))
        if relative.is_absolute():
            raise ValueError(f"manifest path must be relative: {relative_name}")
        path = (experiment_dir / relative).resolve()
        try:
            path.relative_to(experiment_dir)
        except ValueError as exc:
            raise ValueError(f"manifest path escapes archive: {relative_name}") from exc
        if not path.is_file():
            raise ValueError(f"missing declared experiment file: {relative_name}")
        actual = _file_record(path)
        if actual["bytes"] != expected.get("bytes"):
            raise ValueError(f"file size differs from manifest: {relative_name}")
        if actual["sha256"] != expected.get("sha256"):
            raise ValueError(f"SHA-256 differs from manifest: {relative_name}")
    _validate_integrity_repair(experiment_dir, manifest, files)
    return manifest
