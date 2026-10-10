"""Recover eight exact saved results and trials; zero native account evaluation."""
from copy import deepcopy
from strategy_runtime import canonical_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import EvaluationEvidenceWrite
from common import ROOT, PROTOCOLS, RUNS, EXPERIMENT, cache_read, cache_write, read, write, context, file_hash
from account_reference import verify_account
from direction_oracle import audit_direction
from parameter_execution_validation import parameter_execution_check
from run_parameters_v3 import TRANSPORT, CHECKPOINT, source_check


def main():
    correction=parameter_execution_check()
    source_check()
    assert not CHECKPOINT.exists() and not (TRANSPORT/'study_v3.pkl.gz').exists()
    manifest=read(PROTOCOLS/'parameter_plans.json')
    state=deepcopy(read(PROTOCOLS/'parameter_execution_failure.json')['checkpoint'])
    assert len(state['rows'])==32 and state['actual_run_evaluations']==7
    assert state['inflight']==[f'N0-P{i:02d}' for i in range(1,8)]
    assert len(manifest['centers'])==2 and len(manifest['reused_rows'])==32
    study=cache_read(TRANSPORT/'study.pkl.gz')
    assert len(study.trials)==32 and all(t.state.name=='RUNNING' for t in study.trials)
    assert [t.params['point'] for t in study.trials]==list(range(32))
    prepared=cache_read(TRANSPORT/'prepared.pkl.gz')
    record=next(r for r in manifest['centers'] if r['label']=='N0')
    transport=next(r for r in prepared if r['label']=='N0')
    ctx=context(1)
    proofs=[]
    for i in range(8):
        cfg=record['children'][i]
        bound,result=cache_read(TRANSPORT/(cfg['label']+'.pkl.gz'))
        expected=transport['children'][i]
        assert cfg['label']==f'N0-P{i:02d}'
        assert canonical_sha256(bound.lineage.derivation.to_dict())==canonical_sha256(expected.lineage.derivation.to_dict())
        assert result.runs[0].identity.content_sha256==cfg['content_sha256']
        assert ctx.runtime.identify(bound.strategy,dependencies=bound.dependencies).content_sha256==cfg['content_sha256']
        verify_account(bound,result)
        audit=audit_direction(ctx,bound,result.runs[0].execution.decisions,bound.strategy.payload['parameters'])
        assert audit['status']=='PASS'
        ref=publish_evidence(ctx,EvaluationEvidenceWrite(EXPERIMENT,'parameter-account-'+cfg['label'].lower(),bound,result))
        assert ref.repository_path in correction['existing_formal_evidence']
        assert correction['existing_formal_evidence'][ref.repository_path]==ref.sha256==file_hash(ref.resolve(ROOT))
        study.tell(i,float(result.runs[0].observation.net_cagr))
        state['rows'].append({'label':cfg['label'],'center':'N0','point_index':i,'candidate_id':cfg['candidate_id'],
            'content_sha256':cfg['content_sha256'],'status':'SUCCEEDED','reference':ref.to_dict(),
            'request_hash':result.request_hash,'result_hash':result.result_hash})
        proofs.append({'label':cfg['label'],'reference':ref.to_dict(),'native_audit':audit,'already_published_exact':True})
    assert len(state['rows'])==40 and len(manifest['reused_rows'])==32
    assert [t.state.name for t in study.trials]==['COMPLETE']*8+['RUNNING']*24
    state.update(status='PARTIAL',inflight=None,recovered_prefix_results=8,zero_account_replay=True)
    cache_write(TRANSPORT/'study_v3.pkl.gz',study)
    write(CHECKPOINT,state)
    write(RUNS/'parameter_recovery.json',{'status':'PASS','new_account_evaluations':0,'reused_saved_results':8,
        'already_published_accounts':proofs,'remaining_fixed_points':24,'original_failure_retained':True})
    print({'prefix_recovery':'PASS','saved_results':8,'account_reruns':0,'remaining_points':24},flush=True)


if __name__=='__main__':
    main()
