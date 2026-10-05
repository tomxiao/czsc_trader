from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from czsc_trader.temp_workspace import (
    create_temporary_directory,
    replace_directory,
    temporary_root,
)


@pytest.mark.skipif(os.name != "nt", reason="Windows directory-lock regression")
def test_directory_publish_retries_transient_windows_lock(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    destination = tmp_path / "published"
    staging.mkdir()
    (staging / "evidence.json").write_text("{}", encoding="utf-8")
    original = Path.replace
    attempts = 0

    def transient_lock(path, target):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("transient Windows lock")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", transient_lock)
    monkeypatch.setattr("czsc_trader.temp_workspace.time.sleep", lambda _delay: None)

    replace_directory(staging, destination)

    assert attempts == 3
    assert (destination / "evidence.json").is_file()


def test_temporary_workspace_routes_and_rejects_unsafe_paths(
    minimal_repo: Path, tmp_path: Path
) -> None:
    (minimal_repo / "outputs").mkdir()
    (minimal_repo / "data" / "raw").mkdir(parents=True)
    first = create_temporary_directory(
        minimal_repo / "outputs", "backtest", prefix="run-"
    )
    second = create_temporary_directory(
        minimal_repo / "data" / "raw", "market-data", prefix="588080-"
    )
    external = create_temporary_directory(
        tmp_path / "external-output",
        "evaluation",
        repository_root=minimal_repo,
    )

    assert first.parent == minimal_repo / ".tmp" / "backtest"
    assert second.parent == minimal_repo / ".tmp" / "market-data"
    assert first != second
    assert external.parent == minimal_repo / ".tmp" / "evaluation"
    assert temporary_root(minimal_repo) == minimal_repo / ".tmp"

    with pytest.raises(ValueError, match="temporary namespace"):
        create_temporary_directory(minimal_repo, "../outside")
    with pytest.raises(ValueError, match="temporary prefix"):
        create_temporary_directory(minimal_repo, "backtest", prefix="../outside")

    shutil.rmtree(first)
    shutil.rmtree(second)
    shutil.rmtree(external)


def test_windows_temporary_directory_preserves_inherited_acl(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows ACL regression")

    created = create_temporary_directory(
        tmp_path,
        "acl-regression",
        repository_root=tmp_path,
    )
    result = subprocess.run(
        ["icacls", str(created)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "(I)" in result.stdout


def test_pytest_temporary_path_stays_inside_repository(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    marker.write_text("ok", encoding="utf-8")

    assert marker.read_text(encoding="utf-8") == "ok"
    assert tmp_path.parent.parent.name == "pytest"
    assert tmp_path.parent.parent.parent.name == ".tmp"
