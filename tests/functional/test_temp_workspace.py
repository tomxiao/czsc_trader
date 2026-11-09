# Risk ownership: INFRA-02
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from czsc_trader.temp_workspace import (
    create_temporary_directory,
    temporary_root,
)




def test_INFRA_02_C01_temporary_workspace_routes_and_rejects_unsafe_paths(
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

    governed_root = Path(__file__).resolve().parents[2] / '.tmp' / 'pytest'
    assert tmp_path.resolve().is_relative_to(governed_root.resolve())
    if os.name == 'nt':
        result = subprocess.run(['icacls', str(first)], check=False, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert '(I)' in result.stdout

    shutil.rmtree(first)
    shutil.rmtree(second)
    shutil.rmtree(external)






def test_INFRA_02_C02_dangerous_temporary_namespace_rejected(minimal_repo):
    before = tuple(minimal_repo.iterdir())
    with pytest.raises(ValueError, match='temporary namespace'):
        create_temporary_directory(minimal_repo, '../outside')
    assert tuple(minimal_repo.iterdir()) == before
