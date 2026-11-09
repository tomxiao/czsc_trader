"""TDR-02: ownership needs genuine preparation, not replay or publication.

Market/computation crossings have separate E2E coverage. This boundary has no
market branch; use one real handle and verify its lifecycle without executing it.
"""
from dataclasses import replace

import pytest

from czsc_trader.research_tools import ResearchExecutionSession
from czsc_trader.research_tools.account_preparation import require_account




def test_TDR_02_C01_account_handle_01(tmp_path, monkeypatch):
    from account_parity_support import setup_account
    from strategy_runtime import ExecutionResources
    from dataflows import MarketId, BarFrequency
    context, proposal = setup_account(tmp_path, MarketId.CN, BarFrequency.DAILY)
    context.evaluation.resources = ExecutionResources(1)
    experiment = proposal.experiment
    access = context.evaluation
    from czsc_trader.research_tools import equity_replay
    def no_replay(*args, **kwargs):
        raise AssertionError('ownership checks must not calculate accounts')
    monkeypatch.setattr(equity_replay, '_compute_account', no_replay)
    with ResearchExecutionSession(context, experiment=experiment) as execution:
        bound = access.prepare(proposal, execution=execution)
        assert require_account(access, bound, execution) is bound.request


def test_TDR_02_C02_account_handle_02(tmp_path, monkeypatch):
    from account_parity_support import setup_account
    from strategy_runtime import ExecutionResources
    from dataflows import MarketId, BarFrequency
    context, proposal = setup_account(tmp_path, MarketId.CN, BarFrequency.DAILY)
    context.evaluation.resources = ExecutionResources(1)
    experiment = proposal.experiment
    access = context.evaluation
    from czsc_trader.research_tools import equity_replay
    def no_replay(*args, **kwargs):
        raise AssertionError('ownership checks must not calculate accounts')
    monkeypatch.setattr(equity_replay, '_compute_account', no_replay)
    with ResearchExecutionSession(context, experiment=experiment) as execution:
        bound = access.prepare(proposal, execution=execution)
    with ResearchExecutionSession(context, experiment=experiment) as other:
        with pytest.raises(ValueError, match='not issued'):
            require_account(access, bound, other)


def test_TDR_02_C03_account_handle_03(tmp_path, monkeypatch):
    from account_parity_support import setup_account
    from strategy_runtime import ExecutionResources
    from dataflows import MarketId, BarFrequency
    context, proposal = setup_account(tmp_path, MarketId.CN, BarFrequency.DAILY)
    context.evaluation.resources = ExecutionResources(1)
    experiment = proposal.experiment
    access = context.evaluation
    from czsc_trader.research_tools import equity_replay
    def no_replay(*args, **kwargs):
        raise AssertionError('ownership checks must not calculate accounts')
    monkeypatch.setattr(equity_replay, '_compute_account', no_replay)
    with ResearchExecutionSession(context, experiment=experiment) as execution:
        bound = access.prepare(proposal, execution=execution)
    with pytest.raises(RuntimeError, match='context manager'):
        require_account(access, bound, execution)


def test_TDR_02_C04_account_handle_04(tmp_path, monkeypatch):
    from account_parity_support import setup_account
    from strategy_runtime import ExecutionResources
    from dataflows import MarketId, BarFrequency
    context, proposal = setup_account(tmp_path, MarketId.CN, BarFrequency.DAILY)
    context.evaluation.resources = ExecutionResources(1)
    experiment = proposal.experiment
    access = context.evaluation
    from czsc_trader.research_tools import equity_replay
    def no_replay(*args, **kwargs):
        raise AssertionError('ownership checks must not calculate accounts')
    monkeypatch.setattr(equity_replay, '_compute_account', no_replay)
    with ResearchExecutionSession(context, experiment=experiment) as execution:
        bound = access.prepare(proposal, execution=execution)
        with pytest.raises(ValueError, match='not issued'):
            require_account(access, replace(bound), execution)


def test_TDR_02_C05_account_handle_05(tmp_path, monkeypatch):
    from account_parity_support import setup_account
    from strategy_runtime import ExecutionResources
    from dataflows import MarketId, BarFrequency
    context, proposal = setup_account(tmp_path, MarketId.CN, BarFrequency.DAILY)
    context.evaluation.resources = ExecutionResources(1)
    experiment = proposal.experiment
    from czsc_trader.research_tools import equity_replay
    def no_replay(*args, **kwargs):
        raise AssertionError('ownership checks must not calculate accounts')
    monkeypatch.setattr(equity_replay, '_compute_account', no_replay)
    with ResearchExecutionSession(context, experiment=experiment):
        with pytest.raises(RuntimeError, match='active execution session'):
            with ResearchExecutionSession(context, experiment=experiment):
                pass
