"""Replay complete historical parameter universe with unchanged native V4 source."""
from dataclasses import replace
from time import perf_counter
from plan_context import *

def main():
    assert not (OUT/'results.json').exists()
    ctx,sources,spec=frozen_context()
    original=ROOT/'research/S015/experiments/EX092_20261105/others'
    template=EquityStrategyDefinition.from_dict(read(original/'definition_C9820.json')['equity_definition'])
    universe=read(HOME/'protocols/universe.json')['rows']
    candidates=[]; mapping=[]
    for row in universe:
        definition=replace(template,parameters_json=json.dumps(row['parameters']))
        candidate=EquityStrategyCandidate('S015',row['proposed_candidate_id'],definition,HOME/'src')
        mapping.append({**row,'content_sha256':candidate.content_identity.content_sha256})
        candidates.append(candidate)
    assert len({x.content_identity.content_sha256 for x in candidates})==164
    save(OUT/'content_mapping.json',{'original_configurations':164,'unique_native_content':164,'rows':mapping})
    print('UNIQUE_CONTENT',164,flush=True)
    center=read(original/'result_C9820_full_STANDARD.json')
    rows=[{**next(r for r in mapping if r['old_candidate_id']=='C9304'),'reference':center['reference'],'reused':True}]
    if (OUT/'resume_accounts.json').exists():
        rows=read(OUT/'resume_accounts.json')['accounts']
        for row in rows:
            current=next(r for r in mapping if r['proposed_candidate_id']==row['proposed_candidate_id'])
            assert current['content_sha256']==row['content_sha256']
    completed={r['proposed_candidate_id'] for r in rows}
    pending=[(c,r) for c,r in zip(candidates,mapping,strict=True) if c.candidate_id not in completed]
    started=perf_counter()
    with ResearchExecutionSession(ctx,experiment=EXP) as execution:
        for offset in range(0,len(pending),12):
            batch=pending[offset:offset+12]
            handles=tuple(ctx.evaluation.prepare(EquityEvaluationRequest(EXP,c,
                TimeInterval(at(date(2025,1,2),9,30),at(date(2026,10,21),15)),date(2024,9,9),sources,100000.,.001,
                window_id='full',scenario_id='STANDARD',measurement_tier='FORMAL',
                benchmark=EvaluationBenchmark(EquityBuyHold(spec)),drawdown_basis='SESSION_CLOSE',
                concentration_basis='TOP_DECILE'),execution=execution) for c,r in batch)
            outcomes=ctx.evaluation.evaluate_many(handles,execution=execution)
            failures=[]
            for (candidate,row),handle,outcome in zip(batch,handles,outcomes,strict=True):
                if outcome.result is None:
                    failures.append({'candidate_id':candidate.candidate_id,'error':str(outcome.error)})
                    continue
                ref=publish_evidence(ctx,EvaluationEvidenceWrite(EXP,candidate.candidate_id,handle,outcome.result),execution=execution)
                rows.append({**row,'reference':ref.to_dict(),'reused':False})
            save(OUT/'progress.json',{'accounts':rows,'failures':failures,'elapsed_seconds':perf_counter()-started})
            print('PROGRESS',len(rows),'/164',round(perf_counter()-started,1),'seconds',flush=True)
            if failures:raise RuntimeError(str(failures))
        save(OUT/'results.json',{'accounts':rows,'elapsed_seconds':perf_counter()-started,'statistics':str(execution.equity_statistics)})

if __name__=='__main__':main()
