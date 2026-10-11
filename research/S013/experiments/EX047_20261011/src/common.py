"""S013 retained prepared inputs only, no evaluation entry point."""
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
import gzip
import json
import pickle
from dataflows import Dataset, ProviderBinding, ProviderConfig
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef, EvaluationResources
from czsc_trader.research_tools.context import ExperimentRef

SRC = Path(__file__).resolve().parent
ROOT = SRC.parents[4]
PROTOCOLS = SRC.parent / 'protocols'
RUNS = ROOT / 'research/S013/assets/runs' / SRC.parent.name
EXPERIMENT = ExperimentRef('S013', SRC.parent.name)
SOURCE_CALLS = []
TRANSPORT = ROOT / '.tmp/s013-mechanism-EX043/parameters'
OUTPUT = ROOT / '.tmp/ex047-coordinate-diagnosis/diagnosis.json'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def cache_read(path):
    with gzip.open(path, 'rb') as stream:
        return pickle.load(stream)


def restore_mapping(value):
    return MappingProxyType(value)


def forbidden(request):
    SOURCE_CALLS.append(str(request))
    raise RuntimeError('Only existing prepared S013 assets: ' + str(request))


def context(workers=1):
    bindings = {item: ProviderBinding(str(item), 'S013-EX047-existing-only', forbidden) for item in
                (Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY)}
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S013'),
        providers=ProviderConfig(bindings=bindings), resources=EvaluationResources(workers, 1, 13))
