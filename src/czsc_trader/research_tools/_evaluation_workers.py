"""Private spawn transport; only the parent owns formal context and evidence."""

import copyreg
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
import pickle
from types import MappingProxyType

from threadpoolctl import threadpool_limits
from dataflows import Dataflows, LocalCacheConfig


@dataclass(frozen=True)
class PlatformEvaluator:
    env_file: Path
    cache: LocalCacheConfig | None

    def __call__(self, request):
        from .evaluation import evaluate_strategy
        return evaluate_strategy(request, dataflows=Dataflows(env_file=self.env_file, cache=self.cache))


def _mapping(value):
    return MappingProxyType(value)


def _reduce_mapping(value):
    return _mapping, (dict(value),)


def pack(value):
    """Serialize immutable mappings without changing global pickle behavior."""
    buffer = BytesIO()
    pickler = pickle.Pickler(buffer, protocol=pickle.HIGHEST_PROTOCOL)
    pickler.dispatch_table = {**copyreg.dispatch_table, MappingProxyType: _reduce_mapping}
    pickler.dump(value)
    return buffer.getvalue()


def compute(payload):
    # Bytes originate exclusively from the parent process, never external artifacts.
    evaluator, request, native_threads = pickle.loads(payload)
    from ..temp_workspace import create_temporary_directory
    # SRT prepared spaces are mutable. Parallel attempts must never replace the
    # same directory, even when they evaluate identical candidates and windows.
    root = create_temporary_directory(request.repository_root, "evaluation-workers")
    request = replace(request, execution_data=replace(request.execution_data, root=root))
    with threadpool_limits(limits=native_threads):
        result = evaluator(request)
    return pack(result)
