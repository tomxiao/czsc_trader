from __future__ import annotations

from datetime import date
from pathlib import Path
import shutil
import json

from czsc_trader.experiment_archive import (
    build_experiment_manifest,
    create_experiment_dir,
)

import pytest
from dataclasses import asdict
from czsc_trader.application import RepositoryContext, validate_archives, ValidationError
from czsc_trader.application.errors import UsageError


def test_ft_t07_archive_validation_is_portable_and_detects_tampering(
    minimal_repo: Path,
) -> None:
    archive = minimal_repo / "experiments" / "0904_ARCHIVE"
    archive.mkdir(parents=True)
    for name in ("01_goal.md", "02_design.md", "03_execution.md", "04_conclusion.md"):
        (archive / name).write_text("document\n", encoding="utf-8")
    runner = archive / "run_experiment.py"
    runner.write_bytes(b"print('research')\n")
    chart = archive / "diagnostic.svg"
    chart.write_bytes(b"<svg>\n<text>research</text>\n</svg>\n")
    cache = archive / "__pycache__"
    cache.mkdir()
    bytecode = cache / "run_experiment.cpython-312.pyc"
    bytecode.write_bytes(b"runtime-cache")
    manifest = build_experiment_manifest(
        archive, {"experiment_id": "0904_ARCHIVE", "status": "COMPLETE"}
    )
    runner.write_bytes(b"print('research')\r\n")
    chart.write_bytes(b"<svg>\r\n<text>research</text>\r\n</svg>\r\n")
    context = RepositoryContext.discover(minimal_repo)
    first = asdict(validate_archives(context, (archive,)))
    assert first["result"] == {
        "validated_count": 1,
        "experiments": ["0904_ARCHIVE"],
    }
    assert "__pycache__/run_experiment.cpython-312.pyc" not in manifest["files"]
    bytecode.write_bytes(b"changed-runtime-cache")
    (archive / "evaluation_acceptance.json").write_text(
        '{"status":"PAPER_ACTIVE"}\n', encoding="utf-8"
    )
    assert validate_archives(context, (archive,)).status == "PASS"

    relocated = minimal_repo.parent / "relocated-archive-repository"
    shutil.copytree(minimal_repo, relocated)
    relocated_result = validate_archives(
        RepositoryContext.discover(relocated),
        (relocated / "experiments" / archive.name,),
    )
    assert relocated_result.status == "PASS" and relocated_result.result == first["result"]

    (archive / "04_conclusion.md").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="04_conclusion.md") as failure:
        validate_archives(context, (archive,))
    assert failure.value.code == "experiment_archive_invalid"


def test_archive_validates_only_explicit_selection(
    minimal_repo: Path,
) -> None:
    experiments = minimal_repo / "experiments"
    created: list[str] = []
    selected: list[Path] = []
    for strategy_id in ("S001", "S002"):
        archive = create_experiment_dir(experiments, date(2026, 9, 11), strategy_id)
        created.append(archive.name)
        selected.append(archive.relative_to(minimal_repo))
        for name in ("01_goal.md", "02_design.md", "03_execution.md", "04_conclusion.md"):
            (archive / name).write_text("document\n", encoding="utf-8")
        build_experiment_manifest(
            archive,
            {
                "experiment_id": archive.name,
                "status": "COMPLETE",
                "strategy_id": strategy_id,
                "symbol": "588080.SH" if strategy_id == "S001" else "510500.SH",
                "development_cutoff": "2026-09-10",
            },
        )

    (experiments / "unselected").mkdir()
    (experiments / "unselected/experiment_manifest.json").write_text("invalid")
    result = asdict(
        validate_archives(RepositoryContext.discover(minimal_repo), tuple(selected))
    )
    assert result["result"] == {
        "validated_count": 2,
        "experiments": created,
    }


@pytest.mark.parametrize("schema", [2, 0, True, "1"])
def test_archive_rejects_unsupported_schema_without_writing(tmp_path, schema):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "evidence.txt").write_bytes(b"original")
    with pytest.raises(ValueError, match="schema_version must be 1"):
        build_experiment_manifest(archive, {"schema_version": schema})
    assert not (archive / "experiment_manifest.json").exists()
    assert (archive / "evidence.txt").read_bytes() == b"original"


@pytest.mark.parametrize("archives", [(), None, Path("missing"), [Path("missing")], ("missing",)])
def test_archive_selection_requires_nonempty_typed_paths(minimal_repo, archives):
    context = RepositoryContext.discover(minimal_repo)
    before = set(minimal_repo.rglob("*"))
    with pytest.raises(UsageError) as error:
        validate_archives(context, archives)
    assert error.value.code == "archive_selection_invalid"
    assert set(minimal_repo.rglob("*")) == before


@pytest.mark.parametrize("paths", [(Path("missing"),), (Path("same"), Path("same")),
                                    (Path("../outside"),)])
def test_archive_invalid_selection_fails_without_writes(minimal_repo, paths):
    context = RepositoryContext.discover(minimal_repo)
    before = set(minimal_repo.rglob("*"))
    with pytest.raises(ValidationError) as error:
        validate_archives(context, paths)
    assert error.value.code == "experiment_archive_invalid"
    assert set(minimal_repo.rglob("*")) == before


def test_archive_identity_survives_folder_rename(minimal_repo):
    archive = minimal_repo / "caller-layout/arbitrary/deep/original-name"
    archive.mkdir(parents=True)
    for name in ("01_goal.md", "02_design.md", "03_execution.md", "04_conclusion.md"):
        (archive / name).write_text("document\n", encoding="utf-8")
    build_experiment_manifest(archive, {"experiment_id": "EX001_20261003", "strategy_id": "S900",
                                       "symbol": "588080.SH", "development_cutoff": "2026-09-30"})
    relocated = archive.with_name("different-name")
    archive.rename(relocated)
    result = validate_archives(RepositoryContext.discover(minimal_repo), (relocated.relative_to(minimal_repo),))
    assert result.result == {"validated_count": 1, "experiments": ["EX001_20261003"]}


@pytest.mark.parametrize("metadata", [{"experiment_id": "../bad"},
                                      {"experiment_id": "id", "strategy_id": "BAD"},
                                      {"experiment_id": "20261003_S901_EX01", "strategy_id": "S900"}])
def test_archive_identity_is_checked_independently_of_directory_name(tmp_path, metadata):
    archive = tmp_path / "arbitrary-name"
    archive.mkdir()
    with pytest.raises(ValueError):
        build_experiment_manifest(archive, metadata)
    assert not (archive / "experiment_manifest.json").exists()


@pytest.mark.parametrize("descriptor", [
    [], None, 7, {"bytes": 1}, {"bytes": True, "sha256": "a" * 64},
    {"bytes": -1, "sha256": "a" * 64}, {"bytes": 1, "sha256": "invalid"},
    {"bytes": 1, "sha256": "a" * 64, "extra": 1},
])
def test_archive_malformed_descriptor_returns_validation_error_without_writes(minimal_repo, descriptor):
    archive = minimal_repo / "chosen-archive"
    archive.mkdir()
    for name in ("01_goal.md", "02_design.md", "03_execution.md", "04_conclusion.md"):
        (archive / name).write_text("document\n", encoding="utf-8")
    manifest = build_experiment_manifest(archive, {"experiment_id": "EX001_20261005"})
    manifest["files"]["01_goal.md"] = descriptor
    (archive / "experiment_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    before = {p.relative_to(minimal_repo): p.read_bytes() for p in minimal_repo.rglob("*") if p.is_file()}
    with pytest.raises(ValidationError, match="invalid manifest file descriptor") as error:
        validate_archives(RepositoryContext.discover(minimal_repo), (archive,))
    assert error.value.code == "experiment_archive_invalid"
    assert {p.relative_to(minimal_repo): p.read_bytes() for p in minimal_repo.rglob("*") if p.is_file()} == before
