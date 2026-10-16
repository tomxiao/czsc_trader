"""Public S014 inputs pinned to immutable evidence and native preparations."""
import importlib.util
import json
from pathlib import Path
from uuid import UUID
import pandas as pd
import requests
from dataflows import DataRequest, Dataset, PreparedDataRef
from czsc_trader.application import RepositoryContext, create_research_context, validate_delivery
from czsc_trader.research_tools import ResearchBatchRef, DeliveryReference, EvidenceRef, ValidationStatus

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'research/S014/assets/runs/EX009_20261017/first'


def previous():
    path = ROOT / 'research/S014/experiments/EX008_20261017'
    result = json.loads((path / 'others/result.json').read_text(encoding='utf-8'))
    if validate_delivery(RepositoryContext.discover(ROOT), DeliveryReference.from_dict(result['delivery'])).status is not ValidationStatus.PASS:
        raise RuntimeError('Predecessor validation failed')
    source = EvidenceRef.from_dict(result['evidence']['inputs']).resolve(ROOT)
    if source.read_bytes() != (path / 'src/inputs.py').read_bytes():
        raise RuntimeError('Published reader changed')
    spec = importlib.util.spec_from_file_location('s014_ex008_inputs', path / 'src/inputs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load(), result


def prior_csv(result, name):
    return pd.read_csv(EvidenceRef.from_dict(result['evidence'][f'run-{name}']).resolve(ROOT))


def request():
    return DataRequest(Dataset.DOMESTIC_INDEX_DAILY, '000001.SH', '2020-01-01', '2026-10-15', '2026-10-15')


def load_index():
    ready = json.loads((EXPERIMENT / 'others/upstream_verification.json').read_text(encoding='utf-8'))
    if ready['status'] != 'PASS':
        raise RuntimeError('Upstream coverage must pass first')
    value = ready['reference']
    ref = PreparedDataRef(UUID(value['space_id']), UUID(value['preparation_id']), value['manifest_sha256'])
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'))
    original = requests.sessions.Session.request
    def prohibit(*args, **kwargs):
        raise RuntimeError('No new source calls in analysis')
    requests.sessions.Session.request = prohibit
    try:
        result = context.data.fetch(request(), prepared=ref)
    finally:
        requests.sessions.Session.request = original
    if not result.ready or result.identity.content_sha256 != ready['identity']['content_sha256']:
        raise RuntimeError('Pinned index identity changed')
    return result.dataframe.sort_values('Date').reset_index(drop=True)
