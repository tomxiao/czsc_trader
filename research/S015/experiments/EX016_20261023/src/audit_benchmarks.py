"""Complete the independent center audit with executable BuyHold ledgers."""
import numpy as np
import pandas as pd
from suite import ROOT,HOME,read,save,EvidenceRef


def main():
    summary=read(HOME/'others/ten_round_audit.json')
    records=[]
    for item in summary['rows']:
        value=read(EvidenceRef.from_dict(item['evidence']).resolve(ROOT))
        old=read(ROOT/f"research/S015/experiments/{item['experiment']}/others/results.json")
        declared=next(r for r in old['rows'] if r['candidate_id']==item['candidate_id'])
        for run in value['runs']:
            sid=run['window_id']
            a=pd.DataFrame(run['ledgers']['account_daily']['data'])
            b=pd.DataFrame(run['buyhold']['account_daily']['data'])
            assert a.date.astype(str).str[:10].tolist()==b.date.astype(str).str[:10].tolist()
            assert float(b.cash_before.iloc[0])==100000. and int(b.quantity_before.iloc[0])==0
            eq=np.r_[100000.,b.equity.to_numpy(float)]
            cagr=float((eq[-1]/100000)**(252/len(b))-1)
            dd=float((1-eq/np.maximum.accumulate(eq)).max())
            assert cagr>0.,'This dataset uses positive-baseline target branch'
            assert abs(cagr-declared['runs'][sid]['benchmark_cagr'])<1e-14
            assert abs(dd-declared['runs'][sid]['benchmark_dd'])<1e-14
            checks=declared['runs'][sid]['checks']
            assert checks['return']==(declared['runs'][sid]['cagr']>=1.5*cagr)
            assert checks['relative_drawdown']==(declared['runs'][sid]['dd']<=.8*dd)
            records.append({'round':item['round'],'candidate_id':item['candidate_id'],'window':sid,
                'sessions':len(b),'benchmark_cagr':cagr,'benchmark_dd':dd})
    save(HOME/'others/benchmark_audit.json',{'status':'PASS','scenarios':len(records),
        'scope':'Independently recalculate actual LimitBuyHold equity/CAGR/DD and exact dates against each scenario, completing the primary center audit.',
        'records':records})
    print({'benchmark_audit':'PASS','scenarios':len(records)},flush=True)


if __name__=='__main__':
    main()
