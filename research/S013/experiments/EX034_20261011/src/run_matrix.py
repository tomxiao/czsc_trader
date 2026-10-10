"""Fixed one-business-account queue, exact prechecked result reuse."""
import optuna
from common import PROTOCOLS, RUNS, CACHE, SOURCE_CALLS, read, write, cache_read, cache_write


def main():
    assert read(RUNS/'precheck.json')['status']=='PASS' and not (RUNS/'matrix.json').exists()
    plan=read(PROTOCOLS/'plan.json')
    assert len(plan['configurations'])==1
    study=optuna.create_study(direction='maximize',study_name=plan['name'],sampler=optuna.samplers.RandomSampler(seed=13))
    study.enqueue_trial({'configuration':0})
    trial=study.ask()
    assert trial.suggest_int('configuration',0,0)==0
    cfg=plan['configurations'][0]
    bound,result=cache_read(CACHE/'N0.pkl.gz')
    assert bound.strategy.candidate_id==cfg['candidate_id'] and result.runs[0].identity.content_sha256==cfg['content_sha256']
    study.tell(trial,float(result.runs[0].observation.net_cagr))
    write(RUNS/'matrix.json',{'status':'COMPLETE','rows':[{'label':'N0','candidate_id':cfg['candidate_id'],
        'content_sha256':cfg['content_sha256'],'status':'SUCCEEDED','prechecked_reuse':True,
        'net_cagr':float(result.runs[0].observation.net_cagr),'request_hash':result.request_hash,'result_hash':result.result_hash}],
        'new_account_evaluations':2,'new_business_configurations':1,'historical_controls':1,'provider_calls':SOURCE_CALLS})
    assert not SOURCE_CALLS
    cache_write(CACHE/'study.pkl.gz',study)
    print({'matrix':'COMPLETE','new_business_accounts':1,'actual_evaluations':2},flush=True)


if __name__=='__main__':
    main()
