"""Use the catalogue-confirmed vendor identifier for the same approved index."""
import json
from dataflows import DataRequest,Dataset
from czsc_trader.research_tools import EvidenceRef
from inputs import ROOT,EXPERIMENT,RUN,previous,old_csv,fetch_pinned


def request():
    identity=json.loads((EXPERIMENT/'others/vendor_identity.json').read_text(encoding='utf-8'))
    if identity['status']!='PASS' or identity['canonical_symbol']!='000813.CSI':
        raise RuntimeError('Same-index identity must be established')
    return DataRequest(Dataset.DOMESTIC_INDEX_DAILY,'000813.CSI','2020-01-01','2026-10-15','2026-10-15')


def indices(prior):
    market=json.loads(EvidenceRef.from_dict(prior['evidence']['upstream-verification']).resolve(ROOT).read_text(encoding='utf-8'))
    sector=json.loads((EXPERIMENT/'others/upstream_verification_resolved.json').read_text(encoding='utf-8'))
    return fetch_pinned(market,'000001.SH'),fetch_pinned(sector,'000813.CSI')
