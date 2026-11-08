"""Same visible real HFQ prefixes, old financial formula versus target strategy."""
from pathlib import Path
import os
import sys
import json

ROOT = Path(__file__).resolve().parents[5]
EXP = Path(__file__).resolve().parents[1]
TMP = ROOT/'.tmp/s018-target'
TMP.mkdir(parents=True, exist_ok=True)
os.environ.update(TEMP=str(TMP), TMP=str(TMP), PYTHONDONTWRITEBYTECODE='1')
sys.dont_write_bytecode = True

from czsc_trader.application import RepositoryContext, publish_evidence
from czsc_trader.research_tools import ExperimentRef, MaterialEvidenceWrite
from dataflows import EquityProduct, PriceAdjustment, PreparePolicy
from candidate import build_candidate
from data_inputs import build_data_context, MU, SOXX, request
from test_equivalence import financial_predicate_comparison


def main():
    candidate = build_candidate()
    repo = RepositoryContext.discover(ROOT)
    ctx, _, provenance = build_data_context(repo, candidate.definition.execution_spec)
    queries = tuple(request(instrument, EquityProduct.BARS, PriceAdjustment.BACKWARD) for instrument in (MU, SOXX))
    ready = ctx.data.prepare(queries, policy=PreparePolicy.REUSE)
    if not ready.ready:
        raise RuntimeError(tuple(x.error for x in ready.items))
    items = tuple(ctx.data.fetch(q, prepared=ready.reference) for q in queries)
    if not all(x.ready for x in items):
        raise RuntimeError(tuple(x.error for x in items))
    # Decisions in the 2023-01-03..2026-10-30 window consume the previous
    # completed session: 2022-12-30..2026-10-29, not the execution day's close.
    result = financial_predicate_comparison(items[0].dataframe, items[1].dataframe,
                                            start='2022-12-30', end='2026-10-29')
    result['inputs'] = [{'symbol':q.parameters.instrument.symbol,'content_sha256':x.identity.content_sha256}
                       for q,x in zip(queries,items)]
    result['candidate_content_sha256'] = candidate.content_identity.content_sha256
    result['entry_signal_points'] = sum(x['entry_signal'] for x in result['points'])
    result['limitations'] = ['Flat-state financial predicates only; no account-performance equivalence claim.',
                            *provenance['limitations']]
    content = (json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode()
    (EXP/'others/real_signal_comparison.json').write_bytes(content)
    reference = publish_evidence(ctx, MaterialEvidenceWrite(ExperimentRef('S018',EXP.name),
        'same-hfq-financial-predicates',content,'application/json','json'))
    (EXP/'others/signal_evidence_reference.json').write_text(json.dumps(reference.to_dict(),indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('points','limitations')},ensure_ascii=False))
    if result['differing_points']:
        raise AssertionError('financial predicate difference')


if __name__ == '__main__':
    main()
