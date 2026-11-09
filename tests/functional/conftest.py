from __future__ import annotations

from pathlib import Path

import pytest
from current_contract_support import candidate_payload as candidate_payload
from managed_evaluation_support import fresh_managed_evaluation as fresh_managed_evaluation
from frozen_contract_support import (
    fresh_completed as fresh_completed,
    fresh_inspection as fresh_inspection,
    inspected_candidate as inspected_candidate,
)


@pytest.fixture(scope='session')
def actual_inspection_environment():
    """One real immutable installation inventory for unrelated host consumers.

    Platform-file/dependency detection is covered by SRT's environment tests.
    This fixture never replaces collection inside spawned inspection workers.
    """
    from strategy_runtime.inspection import collect_inspection_environment
    return collect_inspection_environment(Path(__file__).resolve().parents[2])


@pytest.fixture
def pinned_inspection_environment(monkeypatch, actual_inspection_environment):
    """Reuse installation facts without re-scanning every installed distribution."""
    monkeypatch.setattr('strategy_runtime.inspection.collect_inspection_environment',
                        lambda _root: actual_inspection_environment)
    # The host imports the function by value; pin that explicit dependency too.
    monkeypatch.setattr('czsc_trader.application.inspection_service.collect_inspection_environment',
                        lambda _root: actual_inspection_environment)
    return actual_inspection_environment


@pytest.fixture
def minimal_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src" / "czsc_trader").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname='czsc-trader-functional-test'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture(scope='session')
def account_fact_bytes(frozen_seed_root):
    """One authentic small result, immutable bytes for read/persistence consumers.

    Replay and lifecycle tests still build their own accounts. Downstream hash,
    projection and corruption tests must not perform a fresh market replay.
    """
    from equity_test_support import setup_account_research
    from czsc_trader.research_tools import ResearchExecutionSession
    from czsc_trader.research_tools._evaluation_workers import pack
    context, request, _, _ = setup_account_research(frozen_seed_root / 'account-facts')
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        assert outcome.result is not None, outcome.error
        return pack((prepared, outcome.result))


@pytest.fixture
def account_facts(account_fact_bytes):
    """Fresh mutable frames, no shared active execution session or writable ledger."""
    import pickle
    return pickle.loads(account_fact_bytes)
