"""Same-batch public evidence access; no provider requests or account evaluation."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / '.tmp/s017-research' / WORK.name
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ['TEMP'] = os.environ['TMP'] = str(SCRATCH)
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'

from dataflows import ProviderConfig, BarFrequency
from strategy_runtime import (ResearchExecutionSpec, UsEquitySpec, AccountPolicy,
    CashAvailabilityPolicy, ExecutionResources)
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import ResearchBatchRef, ExperimentRef, EvidenceRef, MaterialEvidenceWrite

REPOSITORY = RepositoryContext.discover(ROOT)
BATCH = ResearchBatchRef('S017')
EXPERIMENT = ExperimentRef('S017', WORK.name)
INPUT_SHA = '2d2a98bfe9f04891e47cb6c938d0eb1b27bb28f41622f73aef010ae23d6d717c'
LABEL_SHA = '4b487cef6ec042ed2b58b99113b6657f8ecca3327e66a6535eae7328b18bf5e5'


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8', newline='\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_bytes(value):
    ref = value if type(value) is EvidenceRef else EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != 'S017':
        raise ValueError('Only authorized S017 evidence')
    raw = ref.resolve(ROOT).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref.sha256:
        raise ValueError('Evidence hash mismatch')
    return raw


def context():
    spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
        AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
    return create_research_context(REPOSITORY, BATCH,
        providers=ProviderConfig(bindings={}, equity_bindings={}),
        execution_spec=spec, resources=ExecutionResources(2, 1, 17))


def material(name, path):
    media = {'.json': 'application/json', '.md': 'text/markdown', '.py': 'text/x-python'}[path.suffix]
    return publish_evidence(context(), MaterialEvidenceWrite(EXPERIMENT, name,
        path.read_bytes(), media, path.suffix[1:]))


def account_input():
    record = read(ROOT / 'research/S017/experiments/EX056_20261031/others/accounts.json')['C0222']
    ref = EvidenceRef.from_dict(record['evidence'])
    envelope = json.loads(checked_bytes(ref))
    owned = envelope['input_ref']
    if owned != {'kind': 'equity_input', 'sha256': INPUT_SHA}:
        raise ValueError('Current approved training input required')
    # Only the dependency declared by this authenticated public account is resolved.
    path = ref.resolve(ROOT).parent / (owned['sha256'] + '.json')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != owned['sha256']:
        raise ValueError('Owned input bytes changed')
    value = json.loads(raw)
    bars = value['products']['bars']
    if len(bars) != 7017 or min(x['Date'][:10] for x in bars) < '2023-11-01' or max(x['Date'][:10] for x in bars) > '2025-12-31':
        raise ValueError('Warmup/train-only input required; sealed test prohibited')
    return value, ref.to_dict(), owned
