"""Execution ownership and typed checkpoint configuration for the V4 session."""
import pytest
from equity_test_support import setup_account_research
from czsc_trader.research_tools import ResearchExecutionSession, ExecutionCheckpointRequest


def test_execution_session_rejects_nested_and_expired_ownership(tmp_path):
    context, request, _, _ = setup_account_research(tmp_path)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        with pytest.raises(RuntimeError):
            with ResearchExecutionSession(context, experiment=request.experiment):
                pass
    with pytest.raises(RuntimeError):
        context.evaluation.evaluate_many((prepared,), execution=execution)


@pytest.mark.parametrize("run_id", [None, 1, "", "../escape", "a/b", "a.b", " x", "a" * 81])
def test_execution_checkpoint_run_id_requires_safe_typed_identifier(run_id):
    with pytest.raises(ValueError, match="run_id"):
        ExecutionCheckpointRequest(run_id)


def test_execution_checkpoint_mode_requires_enum():
    with pytest.raises(TypeError, match="CheckpointMode"):
        ExecutionCheckpointRequest("run", "RESUME")
