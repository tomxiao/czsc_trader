from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from czsc_trader.experiment_archive import (
    build_experiment_manifest,
    create_experiment_dir,
    resolve_experiment_dir,
)
from czsc_trader.identity import normalized_text_sha256

import pytest
from dataclasses import asdict
from czsc_trader.application import RepositoryContext, validate_archives, ValidationError


def test_ft_t07_archive_validation_is_portable_and_detects_tampering(
    functional_repo: Path, capsys
) -> None:
    archive = functional_repo / "experiments" / "0904_ARCHIVE"
    archive.mkdir()
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
    context = RepositoryContext.discover(functional_repo)
    first = asdict(validate_archives(context, archive))
    assert first["result"] == {
        "validated_count": 1,
        "experiments": ["0904_ARCHIVE"],
    }
    assert "__pycache__/run_experiment.cpython-312.pyc" not in manifest["files"]
    bytecode.write_bytes(b"changed-runtime-cache")
    (archive / "evaluation_acceptance.json").write_text(
        '{"status":"PAPER_ACTIVE"}\n', encoding="utf-8"
    )
    assert validate_archives(context, archive).status == "PASS"

    (archive / "04_conclusion.md").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="04_conclusion.md") as failure:
        validate_archives(context, archive)
    assert failure.value.code == "experiment_archive_invalid"

    experiment_root = functional_repo / "new-experiments"
    first = create_experiment_dir(experiment_root, date(2026, 9, 9), "S002")
    second = create_experiment_dir(experiment_root, date(2026, 9, 9), "S002")
    assert first.parent == experiment_root / "S002"
    assert first.name == "20260909_S002_EX01"
    assert second.name == "20260909_S002_EX02"
    for name in ("01_goal.md", "02_design.md", "03_execution.md", "04_conclusion.md"):
        (first / name).write_text("document\n", encoding="utf-8")
    build_experiment_manifest(
        first,
        {
            "experiment_id": first.name,
            "status": "COMPLETE",
            "strategy_id": "S002",
            "symbol": "510500.SH",
            "development_cutoff": "2026-09-08",
        },
    )
    assert resolve_experiment_dir(experiment_root, first.name) == first.resolve()


def test_ft_t07_archive_all_discovers_strategy_owned_directories(
    functional_repo: Path, capsys
) -> None:
    experiments = functional_repo / "experiments"
    created: list[str] = []
    for strategy_id in ("S001", "S002"):
        archive = create_experiment_dir(experiments, date(2026, 9, 11), strategy_id)
        created.append(archive.name)
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

    result = asdict(
        validate_archives(RepositoryContext.discover(functional_repo), all_archives=True)
    )
    assert result["result"] == {
        "validated_count": 2,
        "experiments": created,
    }


def test_ft_t07_resealed_archive_preserves_and_validates_original_manifest(
    functional_repo: Path, capsys
) -> None:
    archive = functional_repo / "experiments" / "0904_RESEALED"
    archive.mkdir()
    for name in ("01_goal.md", "02_design.md", "03_execution.md", "04_conclusion.md"):
        (archive / name).write_text("document\n", encoding="utf-8")
    runner = archive / "run_experiment.py"
    runner.write_text("print('before')\n", encoding="utf-8")
    original = build_experiment_manifest(
        archive, {"experiment_id": "0904_RESEALED", "status": "COMPLETE"}
    )
    original_path = archive / "experiment_manifest.v1.json"
    (archive / "experiment_manifest.json").rename(original_path)
    runner.write_text("print('after')\n", encoding="utf-8")
    runner_bytes = runner.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    original_bytes = original_path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    current_record = {
        "bytes": len(runner_bytes),
        "sha256": normalized_text_sha256(runner),
    }
    repair_path = archive / "integrity_repair.json"
    repair_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repair_id": "ARCHIVE-REPAIR-TEST",
                "experiment_id": "0904_RESEALED",
                "decision": "PRESERVE_ORIGINAL_MANIFEST_AND_RESEAL_CURRENT_ARCHIVE",
                "original_manifest": {
                    "path": original_path.name,
                    "bytes": len(original_bytes),
                    "sha256": normalized_text_sha256(original_path),
                },
                "corrected_files": [
                    {
                        "path": runner.name,
                        "original_record": original["files"][runner.name],
                        "current_record": current_record,
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    build_experiment_manifest(
        archive,
        {
            "schema_version": 2,
            "experiment_id": "0904_RESEALED",
            "status": "COMPLETE",
            "integrity_repair": {
                "record": repair_path.name,
                "record_sha256": normalized_text_sha256(repair_path),
                "supersedes": original_path.name,
                "supersedes_sha256": normalized_text_sha256(original_path),
            },
        },
    )

    result = asdict(validate_archives(RepositoryContext.discover(functional_repo), archive))
    assert result["result"] == {
        "validated_count": 1,
        "experiments": ["0904_RESEALED"],
    }

    repair = json.loads(repair_path.read_text(encoding="utf-8"))
    repair["corrected_files"][0]["current_record"]["bytes"] += 1
    repair_path.write_text(json.dumps(repair, indent=2) + "\n", encoding="utf-8")
    sealed_bytes = (archive / "experiment_manifest.json").read_bytes()
    with pytest.raises(ValueError):
        build_experiment_manifest(
            archive,
            {
                "schema_version": 2,
                "experiment_id": "0904_RESEALED",
                "status": "COMPLETE",
                "integrity_repair": {
                    "record": repair_path.name,
                    "record_sha256": normalized_text_sha256(repair_path),
                    "supersedes": original_path.name,
                    "supersedes_sha256": normalized_text_sha256(original_path),
                },
            },
        )
    assert (archive / "experiment_manifest.json").read_bytes() == sealed_bytes
    with pytest.raises(ValidationError):
        validate_archives(RepositoryContext.discover(functional_repo), archive)
