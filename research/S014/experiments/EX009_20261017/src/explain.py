"""Outcome attribution only: never feed future market movement into decisions."""
import json
import numpy as np
import pandas as pd
from inputs import ROOT, EXPERIMENT, RUN, previous, prior_csv, load_index


def main():
    target=EXPERIMENT/'others/attribution_result.json'
    if target.exists():
        raise RuntimeError('Preserve existing attribution')
    (data,dates,observation,*_),prior=previous()
    index=load_index()
    frame=pd.read_csv(RUN/'predictions.csv')
    _,prices,*_=observation
    entries=prior_csv(prior,'entries').set_index('signal')
    rows=[]
    for r in frame.loc[frame.status.eq('CLOSED')&frame.gap_down_repair.eq(1)].to_dict('records'):
        s,e,m,q=(int(r[k]) for k in ('signal','entry','maturity','quantity'))
        buy,sell=float(r['entry_price']),float(r['exit_price'])
        first_close=float(prices[e,3])
        first=q*(first_close-buy)/100000
        later=q*(sell-first_close)/100000
        cost=q*(buy+sell)*.001/100000
        beta=float(r['beta'])
        market_first_log=float(np.log(index.Close.iloc[e]/index.Open.iloc[e]))
        market_later_log=float(np.log(index.Open.iloc[m]/index.Close.iloc[e]))
        market_first=q*buy*np.expm1(beta*market_first_log)/100000
        market_later=q*first_close*np.expm1(beta*market_later_log)/100000
        entry_open=abs(buy-float(prices[e,0]))<1e-9
        exit_open=abs(sell-float(prices[m,0]))<1e-9
        assert abs(first+later-cost-r['net_return'])<1e-10
        rows.append({'signal':s,'year':int(r['year']),'horizon':int(r['horizon']),'entry':e,'maturity':m,
            'first_cash':first,'later_cash':later,'fees':cost,'net_return':r['net_return'],
            'beta':beta,'market_first_log':market_first_log,'market_later_log':market_later_log,
            'market_first_proxy':market_first,'market_later_proxy':market_later,
            'first_residual':first-market_first,'later_residual':later-market_later,
            'entry_at_open':entry_open,'exit_at_open':exit_open,
            'synchronous_open_endpoints':entry_open and exit_open})
    out=pd.DataFrame(rows)
    out.to_csv(RUN/'cash_attribution.csv',index=False,lineterminator='\n')
    annual=[]
    metrics=['first_cash','later_cash','fees','net_return','market_first_proxy','market_later_proxy','first_residual','later_residual']
    for (h,y),g in out.groupby(['horizon','year']):
        for mode,part in [('all-filled',g),('open-endpoints',g.loc[g.synchronous_open_endpoints])]:
            annual.append({'horizon':int(h),'year':int(y),'mode':mode,'n':len(part),
                **{k:float(part[k].mean()) if len(part) else None for k in metrics}})
    result={'annual':annual,'rows':len(out),'source_calls':0,'strategy_accounts':0,
        'limit':'Diagnostic additive cash identity, residual defined by subtraction. Fixed prior60beta does not prove causality. Future index moves explanatory only; index opening proxy for nonopening stock fills explicitly flagged; open-endpoint subset removes that timing mismatch. Index not traded and residual not attainable hedged profit.'}
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print('ATTRIBUTION_ROWS',len(out))


if __name__=='__main__':
    main()
