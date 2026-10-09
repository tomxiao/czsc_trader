"""Restore private copies of real, already prepared synthetic evaluation inputs."""

from dataclasses import replace
from pathlib import Path

from dataflows import Dataflows, DataSpace, ProviderConfig
from czsc_trader.application import RepositoryContext
from public_backtest_support import research_context


def relocate_request(request, root):
    """Only repository paths change; prepared identities and frames stay intact."""
    source = request.strategy.source_root.relative_to(request.repository_root)
    execution = request.execution_data
    if execution is not None:
        execution = replace(execution, root=root / execution.root.relative_to(request.repository_root))
    return replace(request, repository_root=root,
                   strategy=replace(request.strategy, source_root=root / source),
                   execution_data=execution)


def restored_context(root):
    repository = RepositoryContext.discover(root)
    flows = Dataflows(base_dir=root, space=DataSpace(Path("research/S900/assets/data")),
                     providers=ProviderConfig(bindings={}))
    return research_context(repository, flows)


def relocate_result(result, original_request, root):
    """Keep even diagnostic source locations inside the consumer's private copy."""
    def path(value):
        return None if value is None else root / value.relative_to(original_request.repository_root)

    runs = tuple(replace(run, signals=replace(run.signals,
        snapshot=replace(run.signals.snapshot, runtime_root=path(run.signals.snapshot.runtime_root)),
        strategy_source=replace(run.signals.strategy_source,
                               source_root=path(run.signals.strategy_source.source_root)),
        data_dir=path(run.signals.data_dir))) for run in result.runs)
    execution = replace(result.execution_data, root=path(result.execution_data.root))
    return replace(result, runs=runs, execution_data=execution)
