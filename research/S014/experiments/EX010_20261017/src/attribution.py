"""Cash attribution to known-exposure market/industry proxies, not decision data."""
import json
import numpy as np
import pandas as pd
from resolved_inputs import ROOT,EXPERIMENT,RUN,previous,indices


def main():
    target=EXPERIMENT/'others/attribution_result.json'
    if target.exists():
        raise RuntimeError('Preserve attribution')
    from czsc_trader.research_tools import EvidenceRef
    binding=json.loads((EXPERIMENT/'protocols/attribution_published.json').read_text(encoding='utf-8'))
    assert EvidenceRef.from_dict(binding['attribution']).resolve(ROOT).read_bytes()==__import__('pathlib').Path(__file__).read_bytes()
    (data,dates,observation,*_),prior=previous();market,sector=indices(prior)
    _,prices,*_=observation
    p=pd.read_csv(RUN/'predictions.csv')
    records=[]
    for r in p.loc[p.gap_down_repair.eq(1)&p.status.eq('CLOSED')].to_dict('records'):
        s,e,m,q=(int(r[k]) for k in ('signal','entry','maturity','quantity'))
        buy,sell=float(r['entry_price']),float(r['exit_price']);close=float(prices[e,3])
        first=q*(close-buy)/100000;later=q*(sell-close)/100000;fees=q*(buy+sell)*.001/100000
        mf=float(np.log(market.Close.iloc[e]/market.Open.iloc[e]));ml=float(np.log(market.Open.iloc[m]/market.Close.iloc[e]))
        sf=float(np.log(sector.Close.iloc[e]/sector.Open.iloc[e]));sl=float(np.log(sector.Open.iloc[m]/sector.Close.iloc[e]))
        onefirst=q*buy*np.expm1(r['beta']*mf)/100000;onelater=q*close*np.expm1(r['beta']*ml)/100000
        twofirst=q*buy*np.expm1(r['beta_market2']*mf+r['beta_sector2']*sf)/100000
        twolater=q*close*np.expm1(r['beta_market2']*ml+r['beta_sector2']*sl)/100000
        assert abs(first+later-fees-r['net_return'])<1e-10
        records.append({'signal':s,'year':int(r['year']),'horizon':int(r['horizon']),'entry':e,'maturity':m,
            'first_cash':first,'later_cash':later,'fees':fees,'net_return':r['net_return'],
            'market_first':onefirst,'market_later':onelater,'both_first':twofirst,'both_later':twolater,
            'market_first_residual':first-onefirst,'market_later_residual':later-onelater,
            'both_first_residual':first-twofirst,'both_later_residual':later-twolater,
            'beta_market2':r['beta_market2'],'beta_sector2':r['beta_sector2'],'alpha2':r['alpha2'],'condition':r['condition'],
            'open_endpoints':abs(buy-prices[e,0])<1e-9 and abs(sell-prices[m,0])<1e-9})
    out=pd.DataFrame(records);out.to_csv(RUN/'cash_attribution.csv',index=False,lineterminator='\n')
    annual=[]
    metrics=['first_cash','later_cash','fees','net_return','market_first','market_later','both_first','both_later',
        'market_first_residual','market_later_residual','both_first_residual','both_later_residual','beta_market2','beta_sector2','alpha2','condition']
    for (h,y),g in out.groupby(['horizon','year']):
        for mode,part in [('all-filled',g),('open-endpoints',g.loc[g.open_endpoints])]:
            annual.append({'horizon':int(h),'year':int(y),'mode':mode,'n':len(part),
                **{k:float(part[k].mean()) if len(part) else None for k in metrics},
                'market_later_residual_rmse':float(np.sqrt(np.mean(part.market_later_residual**2))) if len(part) else None,
                'both_later_residual_rmse':float(np.sqrt(np.mean(part.both_later_residual**2))) if len(part) else None})
    result={'annual':annual,'rows':len(out),'source_calls':0,'strategy_accounts':0,
        'limit':'Futureindexendpointsareexplanatoryonly;betasknownatsignal,interceptexcludedfromcommonfactorcash. Cashresidualidentityisnotcausalproof,actualhedgedprofitorexecutabletimingfornonopeningstockfills. Bothopeningstocksubsetseparatelyreported.'}
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print('ATTRIBUTION_COMPLETE',len(out))


if __name__=='__main__':
    main()
