"""Private spawn transport; only the parent owns formal context and evidence."""

import copyreg
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
import pickle
import shutil
from types import MappingProxyType

from threadpoolctl import threadpool_limits
from dataflows import Dataflows, DataSpace, ProviderConfig


@dataclass(frozen=True)
class PlatformEvaluator:
    base_dir: Path
    space: DataSpace

    def __call__(self, request):
        from .evaluation import _evaluate_strategy
        if set(request.input_bindings) != {item.window_id for item in request.windows}:
            raise ValueError("evaluation worker requires parent-prepared input bindings")
        if Path(request.repository_root).resolve() != self.base_dir.resolve():
            raise ValueError("evaluation worker repository differs from request")
        return _evaluate_strategy(request, dataflows=Dataflows(
            base_dir=self.base_dir, space=self.space, providers=ProviderConfig(bindings={}),
        ))


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
    # Only calculation context is per-worker; managed DFLS assets stay in the
    # host-selected shared data space and are read by their parent-bound refs.
    root = create_temporary_directory(request.repository_root, "evaluation-workers",
                                      repository_root=request.repository_root)
    request = replace(request, execution_data=replace(request.execution_data, root=root))
    expected_parent = (request.repository_root / ".tmp" / "evaluation-workers").resolve()
    if root.resolve().parent != expected_parent:
        raise ValueError("evaluation workspace escaped its managed temporary root")
    try:
        with threadpool_limits(limits=native_threads):
            result = evaluator(request)
        return pack(result)
    finally:
        shutil.rmtree(root)
