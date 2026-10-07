import json
import time
import pandas as pd
from common import ROOT,BASE,context,request,save,cache_read,cache_write
from economics import summarize

def main():
    research=context()
    original,result=cache_read(ROOT/'.tmp/s013-stage3/precheck.pkl.gz')
    requests=tuple(research.evaluation.prepare(request(number,parameters,original.execution_data))
                   for number,parameters in [(2,BASE),(3,dict(BASE,acf_min=-.1))])
    start=time.perf_counter()
    outcomes=research.evaluation.evaluate_many(requests)
    rows=[]
    for bound,outcome in zip(requests,outcomes,strict=True):
        if outcome.status.value!='SUCCEEDED':
            raise RuntimeError(str(outcome.error))
        rows.append(summarize(outcome.result))
        cache_write(ROOT/f'.tmp/s013-stage3/C{int(bound.strategy.candidate_id[1:]):04}.pkl.gz',outcome.result)
    duplicate=outcomes[0].result.runs[0]
    first=result.runs[0]
    pd.testing.assert_frame_equal(duplicate.execution.account_daily,first.execution.account_daily)
    for table in ('orders','fills','trades'):
        a=getattr(first.execution,table).drop(columns=['order_id','fill_id','decision_id','cycle_id'],errors='ignore')
        b=getattr(duplicate.execution,table).drop(columns=['order_id','fill_id','decision_id','cycle_id'],errors='ignore')
        pd.testing.assert_frame_equal(a,b)
    save('batch_precheck.json',{'status':'PASS','workers':2,'native_threads':1,'api':'TDR.evaluate_many FULL',
        'seconds':time.perf_counter()-start,'distinct_request_hashes':len({o.request_hash for o in outcomes}),
        'same_configuration_account_orders_fills_trades':'EXACT','original':summarize(result),'rows':rows})
    print(json.dumps({'batch_precheck':'PASS','seconds':time.perf_counter()-start,
        'original':{k:summarize(result)[k] for k in ('net_cagr','return_threshold','closed_trades','min_dd_margin','gates')},
        'rows':[{k:r[k] for k in ('candidate_id','net_cagr','closed_trades','min_dd_margin','gates')} for r in rows]}),flush=True)

if __name__=='__main__':
    main()
