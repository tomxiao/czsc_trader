"""Tracked, portable archives for formal research rounds."""

from __future__ import annotations

from datetime import date
import json
from hashlib import sha256
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
    r"(?P<date>[0-9]{8})_(?P<strategy_id>S[0-9]{3})_EX(?P<number>[0-9]{2,})$"
)
EXPERIMENT_DIRECTORY_PATTERN = re.compile(r"EX(?P<number>(?!000_)[0-9]{3})_(?P<date>[0-9]{8})")
STRATEGY_ID_PATTERN = re.compile(r"S[0-9]{3}$")


def resolve_experiment_dir(root: Path, experiment_id: str, *, strategy_id: str | None = None) -> Path:
    """Resolve an experiment; require its strategy when names are ambiguous."""
    if not experiment_id or Path(experiment_id).name != experiment_id:
        raise ValueError("experiment must be a single experiment ID")
    root = Path(root).resolve()
    if strategy_id is not None:
        if not STRATEGY_ID_PATTERN.fullmatch(strategy_id):
            raise ValueError("strategy_id must match S plus three digits")
        target = (root / strategy_id / experiment_id).resolve()
        target.relative_to(root)
        if not target.is_dir():
            raise ValueError(f"experiment does not exist: {strategy_id}/{experiment_id}")
        return target
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


def create_experiment_dir(root: Path, run_date: date, strategy_id: str) -> Path:
    """Reserve EX001..EX999 monotonically across dates within one strategy."""
    if type(run_date) is not date:
        raise TypeError("run_date must be a date")
    if not STRATEGY_ID_PATTERN.fullmatch(strategy_id):
        raise ValueError("strategy_id must match S plus three digits")
    root = Path(root).resolve()
    strategy_root = (root / strategy_id).resolve()
    strategy_root.relative_to(root)
    strategy_root.mkdir(parents=True, exist_ok=True)
    # Exclusive allocation lock also prevents equal sequence numbers with
    # different dates. There is no hidden wait, retry or stale-lock recovery.
    lock_root = root.parent / ".tmp" / "experiment-allocation"
    lock_root.mkdir(parents=True, exist_ok=True)
    key = sha256(str(strategy_root).encode()).hexdigest()
    lock = lock_root / f"{key}.lock"
    lock.open("x", encoding="utf-8").close()
    try:
        numbers = []
        for path in strategy_root.iterdir():
            if not path.is_dir():
                continue
            match = EXPERIMENT_DIRECTORY_PATTERN.fullmatch(path.name)
            if match is None:
                match = STRATEGY_EXPERIMENT_PATTERN.fullmatch(path.name)
                if match is None or match.group("strategy_id") != strategy_id:
                    continue
            numbers.append(int(match.group("number")))
        number = max(numbers, default=0) + 1
        if number > 999:
            raise ValueError("experiment sequence exhausted at EX999")
        directory = strategy_root / f"EX{number:03d}_{run_date:%Y%m%d}"
        directory.mkdir(exist_ok=False)
    finally:
        lock.unlink()
    return directory


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


def _validate_archive_identity(metadata: dict[str, object]) -> None:
    identity = metadata.get("experiment_id")
    if not isinstance(identity, str) or not identity or identity in {".", ".."} or any(
        c in '/\\:<>"|?*' or ord(c) < 32 for c in identity
    ):
        raise ValueError("experiment_id must be a safe nonempty logical identity")
    if "strategy_id" not in metadata:
        return
    owner = metadata["strategy_id"]
    if not isinstance(owner, str) or not STRATEGY_ID_PATTERN.fullmatch(owner):
        raise ValueError("strategy_id must match S plus three digits")
    match = STRATEGY_EXPERIMENT_PATTERN.fullmatch(identity)
    if match is not None and match.group("strategy_id") != owner:
        raise ValueError("experiment identity strategy differs from strategy_id")
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
    if "schema_version" in metadata and (type(metadata["schema_version"]) is not int or metadata["schema_version"] != 1):
        raise ValueError("experiment manifest schema_version must be 1")
    if "integrity_repair" in metadata or "files" in metadata:
        raise ValueError("experiment manifest metadata contains managed fields")
    try:
        serialized = json.dumps(metadata, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("experiment manifest metadata must be JSON-safe") from exc
    if "outputs/" in serialized or re.search(r"_R\d{2}", serialized):
        raise ValueError("experiment manifest must not reference outputs revisions")
    _validate_archive_identity(metadata)


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
    path = experiment_dir / MANIFEST_NAME
    if path.exists():
        existing = validate_experiment_archive(experiment_dir)
        if existing != manifest:
            raise ValueError("sealed experiment manifest cannot be overwritten")
        return existing
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(serialized)
    return manifest


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
    if not isinstance(manifest, dict):
        raise ValueError("experiment manifest must be an object")
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ValueError("experiment manifest schema_version must be 1")
    if "integrity_repair" in manifest:
        raise ValueError("experiment manifest must not declare integrity repair")
    _validate_archive_identity(manifest)
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("experiment manifest files must be an object")
    for name, record in files.items():
        if (
            not isinstance(record, dict)
            or set(record) != {"bytes", "sha256"}
            or type(record["bytes"]) is not int
            or record["bytes"] < 0
            or not isinstance(record["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None
        ):
            raise ValueError(f"invalid manifest file descriptor: {name}")
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
        if actual["bytes"] != expected["bytes"]:
            raise ValueError(f"file size differs from manifest: {relative_name}")
        if actual["sha256"] != expected["sha256"]:
            raise ValueError(f"SHA-256 differs from manifest: {relative_name}")
    return manifest
