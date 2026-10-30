"""Private spawn transport; only the parent owns formal context and evidence."""

import copyreg
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import pickle
from types import MappingProxyType

from threadpoolctl import threadpool_limits
from dataflows import Dataflows, DataSpace, ProviderConfig
from ..backtesting.benchmarks import BenchmarkReplayScope, BenchmarkReplaySeed


@dataclass(frozen=True)
class PlatformEvaluator:
    base_dir: Path
    space: DataSpace
    benchmark_seeds: tuple[BenchmarkReplaySeed, ...] = ()
    contract_content: bytes | None = None

    def __call__(self, request):
        from .evaluation import _evaluate_strategy
        if type(self.contract_content) is not bytes:
            raise TypeError("worker evaluation requires its parent-authenticated contract")
        if set(request.input_bindings) != {item.window_id for item in request.windows}:
            raise ValueError("evaluation worker requires parent-prepared input bindings")
        if Path(request.repository_root).resolve() != self.base_dir.resolve():
            raise ValueError("evaluation worker repository differs from request")
        return _evaluate_strategy(request, dataflows=Dataflows(
            base_dir=self.base_dir, space=self.space, providers=ProviderConfig(bindings={}),
        ), benchmark_scope=BenchmarkReplayScope.from_seeds(self.benchmark_seeds), prepared_contract=self.contract_content)


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
    # The prepared replay owns its input bindings and in-memory computation
    # facts. No per-account directory or binding manifest is needed by a worker.
    with threadpool_limits(limits=native_threads):
        return pack(evaluator(request))
