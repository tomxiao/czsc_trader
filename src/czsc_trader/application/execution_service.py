"""Open an explicit caller-owned research execution session."""
from typing import Callable
from ..research_tools.context import ResearchContext, ExperimentRef
from ..research_tools.execution import ResearchExecutionSession, ExecutionCheckpointRequest, ExecutionProgress


def open_research_execution(context: ResearchContext, *, experiment: ExperimentRef,
                            checkpoint: ExecutionCheckpointRequest | None = None,
                            on_progress: Callable[[ExecutionProgress], None] | None = None) -> ResearchExecutionSession:
    return ResearchExecutionSession(context, experiment=experiment, checkpoint=checkpoint, on_progress=on_progress)
