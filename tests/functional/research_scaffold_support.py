"""Private clones of a real, empty research scaffold for business tests."""
from dataclasses import dataclass
import json
from threading import Lock

from czsc_trader.application import (
    create_experiment, create_research_batch, create_research_context,
)
from czsc_trader.research_tools import ExperimentRef, ResearchBatchRef


@dataclass(frozen=True)
class _Scaffold:
    batch: ResearchBatchRef
    experiment: ExperimentRef
    directories: tuple[str, ...]
    files: tuple[tuple[str, bytes], ...]


_SCAFFOLDS: dict[str, _Scaffold] = {}
_SCAFFOLD_LOCK = Lock()


def seeded_research_context(repository, batch_request, experiment_request, *, actor, reason,
                            providers, execution_spec):
    """Clone only initialized governance and an empty DFLS database.

    The first caller creates both through public APIs. Immutable bytes preserve
    their real identities; each consumer receives independent files and fresh
    providers/runtime objects. Preparation, evaluation and publication are never
    cached. Tests of creation or distinct data-space identities use the APIs directly.
    """
    root = repository.root
    roots = (repository.research_root / batch_request.strategy_id,
             repository.research_registry_root / batch_request.strategy_id)
    for path in roots:
        if path.exists():
            raise ValueError(f'research scaffold destination already exists: {path}')
    key = json.dumps({
        'batch': batch_request.as_mapping(), 'actor': actor, 'reason': reason,
        'experiment': {'title': experiment_request.title, 'question': experiment_request.question,
                       'run_date': experiment_request.run_date.isoformat()},
    }, sort_keys=True, separators=(',', ':'))
    with _SCAFFOLD_LOCK:
        seed = _SCAFFOLDS.get(key)
        if seed is None:
            batch = create_research_batch(repository, batch_request, actor=actor, reason=reason)
            context = create_research_context(repository, batch, providers=providers, execution_spec=execution_spec)
            experiment = create_experiment(context, experiment_request)
            paths = tuple(path for parent in roots for path in (parent, *parent.rglob('*')))
            seed = _Scaffold(batch, experiment,
                tuple(sorted(path.relative_to(root).as_posix() for path in paths if path.is_dir())),
                tuple(sorted((path.relative_to(root).as_posix(), path.read_bytes())
                             for path in paths if path.is_file())))
            _SCAFFOLDS[key] = seed
            return context, experiment
    for relative in seed.directories:
        (root / relative).mkdir(parents=True, exist_ok=True)
    for relative, content in seed.files:
        with (root / relative).open('xb') as target:
            target.write(content)
    # Normal public construction authenticates the copied family and database
    # metadata and binds the caller's newly built provider objects to this root.
    context = create_research_context(repository, seed.batch, providers=providers, execution_spec=execution_spec)
    return context, seed.experiment
