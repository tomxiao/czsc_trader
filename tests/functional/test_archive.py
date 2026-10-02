from __future__ import annotations

from datetime import date
from pathlib import Path

from czsc_trader.experiment_archive import (
    build_experiment_manifest,
    create_experiment_dir,
    resolve_experiment_dir,
)

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
    assert first.name == "EX001_20260909"
    assert second.name == "EX002_20260909"
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


@pytest.mark.parametrize("schema", [2, 0, True, "1"])
def test_archive_rejects_unsupported_schema_without_writing(tmp_path, schema):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "evidence.txt").write_bytes(b"original")
    with pytest.raises(ValueError, match="schema_version must be 1"):
        build_experiment_manifest(archive, {"schema_version": schema})
    assert not (archive / "experiment_manifest.json").exists()
    assert (archive / "evidence.txt").read_bytes() == b"original"
