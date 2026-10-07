from __future__ import annotations

from pathlib import Path

import pytest
from current_contract_support import candidate_payload as candidate_payload
from test_current_contracts import (
    fresh_completed as fresh_completed,
    fresh_inspection as fresh_inspection,
    freshly_frozen as freshly_frozen,
    inspected_candidate as inspected_candidate,
)


@pytest.fixture
def minimal_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src" / "czsc_trader").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname='czsc-trader-functional-test'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    return root
