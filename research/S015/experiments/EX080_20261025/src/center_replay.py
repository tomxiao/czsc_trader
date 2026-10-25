"""Materialize the exact already-frozen center requests; no parameter changes."""
from hashlib import sha256
import pandas as pd

from stage4 import ROOT, HOME, OUT, CACHE, EX, read, save, module, ctx, request, assert_protocol
from czsc_trader.application import RepositoryContext, load_candidate, open_research_execution, publish_evidence
from czsc_trader.research_tools import EvidenceRef, ParameterEvaluationPlan, EvaluationEvidenceWrite
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from strategy_manager import CandidateKey
from strategy_evaluator import research_models as m


def main():
    assert_protocol()
    assert not (OUT / 'center_replays.json').exists()
    c = ctx(8)
    plans = {r['candidate_id']: ParameterEvaluationPlan.from_dict(r['plan'])
             for r in read(OUT / 'plan_refs.json')}
    centers = read(OUT / 'centers.json')
    audit = module(HOME.parent / 'EX074_20261024/src/account_audit.py', 'center_arithmetic')
    projection = module(HOME.parent / 'EX066_20261024/src/audit.py', 'center_projection')
    jobs = [(row, request(c, load_candidate(RepositoryContext.discover(ROOT),
                                          CandidateKey('S015', row['candidate_id'])))) for row in centers]
    records, projections = [], []
    with open_research_execution(c, experiment=EX) as session:
        for start in range(0, len(jobs), 8):
            block = jobs[start:start + 8]
            outcomes = c.evaluation.evaluate_many(tuple(req for _, req in block), execution=session)
            for (row, req), outcome in zip(block, outcomes, strict=True):
                assert outcome.status.value == 'SUCCEEDED', outcome.error
                result = outcome.result
                cid = row['candidate_id']
                assert result.request_hash == plans[cid].center_request_sha256
                ref = publish_evidence(c, EvaluationEvidenceWrite(EX, 'center_' + cid, req, result))
                raw = read(ref.resolve(ROOT))
                validate_evaluation_evidence(raw)
                old = read(EvidenceRef.from_dict(row['evidence']).resolve(ROOT))
                old_run = next(x for x in old['runs'] if x['window_id'] == 'full')
                new_run, = raw['runs']
                for name in ('account_daily', 'decisions', 'orders', 'fills', 'trades'):
                    pd.testing.assert_frame_equal(audit.frame(old_run['ledgers'][name]),
                                                  audit.frame(new_run['ledgers'][name]), check_exact=True)
                assert old_run['signals'] == new_run['signals']
                item, = [m.AssessmentEvidence.from_dict(x) for x in raw['assessment_evidence']]
                old_item = next(m.AssessmentEvidence.from_dict(x) for x in old['assessment_evidence']
                                if x['window_id'] == 'full')
                identity_fields = {'experiment_id', 'attempt_id', 'request_sha256', 'result_sha256', 'evaluation_id'}
                assert {k:v for k,v in item.to_dict().items() if k not in identity_fields} == {
                    k:v for k,v in old_item.to_dict().items() if k not in identity_fields}
                summary = projection.projection_summary(raw['assessment_evidence'][0])
                description = audit.describe(new_run, summary)
                description.pop('cycles')
                records.append({'candidate_id': cid, 'source_role': 'center_replay',
                                'request_hash': result.request_hash, 'result_hash': result.result_hash,
                                'evidence': ref.to_dict(), 'evaluation_id': item.evaluation_id,
                                'content_sha256': item.candidate.content_sha256,
                                'old_evidence': row['evidence'], 'old_evaluation_id': old_item.evaluation_id,
                                'exact_five_ledgers': True, 'signals_equal': True,
                                'plan_request_matches': True, 'summary': summary,
                                'accounting_description': description})
                projections.append(item.to_dict())
            save(OUT / 'center_replay_progress.json', {'rows': records})
            print('EXACT_CENTER_REPLAYS', len(records), 29, flush=True)
    assert len(records) == 29
    cache = CACHE / 'center_accounts.json'
    save(cache, projections)
    save(OUT / 'center_replays.json', {'status': 'PASS', 'rows': records, 'new_accounts': 29,
         'projection_sha256': sha256(cache.read_bytes()).hexdigest(),
         'reason': 'Published plans bind exact single-window EX080 center requests; historic two-window requests cannot stand in for those hashes.',
         'scope': 'Unchanged candidate content, parameters, inputs and all five ledgers; technical materialization, not new search or independent evidence.'})


if __name__ == '__main__':
    main()
