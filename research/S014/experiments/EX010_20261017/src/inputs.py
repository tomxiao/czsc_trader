"""S014 public, immutable predecessor inputs and approved sector request."""
import importlib.util
import json
from pathlib import Path
from uuid import UUID
import pandas as pd
import requests
from dataflows import DataRequest,Dataset,PreparedDataRef
from czsc_trader.application import RepositoryContext,create_research_context,validate_delivery
from czsc_trader.research_tools import ResearchBatchRef,DeliveryReference,EvidenceRef,ValidationStatus

ROOT=Path(__file__).resolve().parents[5]
EXPERIMENT=Path(__file__).resolve().parents[1]
RUN=ROOT/'research/S014/assets/runs/EX010_20261017/first'


def previous():
    path=ROOT/'research/S014/experiments/EX009_20261017'
    result=json.loads((path/'others/result.json').read_text(encoding='utf-8'))
    if validate_delivery(RepositoryContext.discover(ROOT),DeliveryReference.from_dict(result['delivery'])).status is not ValidationStatus.PASS:
        raise RuntimeError('Predecessor validation failed')
    source=EvidenceRef.from_dict(result['evidence']['inputs']).resolve(ROOT)
    if source.read_bytes()!=(path/'src/inputs.py').read_bytes():
        raise RuntimeError('Published input reader changed')
    spec=importlib.util.spec_from_file_location('s014_ex009_reader',path/'src/inputs.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    loaded,_=module.previous()
    return loaded,result


def old_csv(result,name):
    return pd.read_csv(EvidenceRef.from_dict(result['evidence'][f'run-{name}']).resolve(ROOT))


def request():
    return DataRequest(Dataset.DOMESTIC_INDEX_DAILY,'000813.SH','2020-01-01','2026-10-15','2026-10-15')


def fetch_pinned(ready,symbol):
    if ready['status']!='PASS':
        raise RuntimeError('Verification must pass first')
    value=ready['reference']
    bound=PreparedDataRef(UUID(value['space_id']),UUID(value['preparation_id']),value['manifest_sha256'])
    context=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'))
    req=DataRequest(Dataset.DOMESTIC_INDEX_DAILY,symbol,'2020-01-01','2026-10-15','2026-10-15')
    original=requests.sessions.Session.request
    def prohibit(*args,**kwargs):
        raise RuntimeError('No new source calls in analysis')
    requests.sessions.Session.request=prohibit
    try:
        result=context.data.fetch(req,prepared=bound)
    finally:
        requests.sessions.Session.request=original
    if not result.ready or result.identity.content_sha256!=ready['identity']['content_sha256']:
        raise RuntimeError('Pinned index identity failed')
    return result.dataframe.sort_values('Date').reset_index(drop=True)


def indices(prior):
    ready=json.loads(EvidenceRef.from_dict(prior['evidence']['upstream-verification']).resolve(ROOT).read_text(encoding='utf-8'))
    sector=json.loads((EXPERIMENT/'others/upstream_verification.json').read_text(encoding='utf-8'))
    return fetch_pinned(ready,'000001.SH'),fetch_pinned(sector,'000813.SH')
