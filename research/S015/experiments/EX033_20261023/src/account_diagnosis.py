"""Explicit RSCH ledger arithmetic, not a counterfactual fee-free account."""
import pandas as pd
import numpy as np
from run import HERE,ROOT,read,save,EvidenceRef
def main():
    result=read(HERE/'others/results.json');out={};cycles=[]
    weighted=pd.read_csv(HERE/'others/signals_1.csv');weighted['day']=pd.to_datetime(weighted.iloc[:,0]).dt.strftime('%Y-%m-%d');targets=weighted.set_index('day').target_position
    for row in result['rows']:
        EvidenceRef.from_dict(row['evidence']).resolve(ROOT)
        cid=row['candidate_id']
        for window in ('full','s011_common'):
            prefix=f'{cid}_{window}'
            a=pd.read_csv(HERE/f'others/{prefix}_account_daily.csv');f=pd.read_csv(HERE/f'others/{prefix}_fills.csv');t=pd.read_csv(HERE/f'others/{prefix}_trades.csv')
            assert int(a.quantity.iloc[-1])==0 and t.status.eq('CLOSED').all()
            gross=float((f.loc[f.side=='SELL','price']*f.loc[f.side=='SELL','quantity']).sum()-(f.loc[f.side=='BUY','price']*f.loc[f.side=='BUY','quantity']).sum())
            fees=float(f.fees.sum());net=float(a.equity.iloc[-1]-100000)
            np.testing.assert_allclose(gross-fees,net,atol=1e-6,rtol=0)
            amounts=[]
            for cycle,g in f.groupby('cycle_id',sort=False):
                g=g.sort_values('fill_time',kind='stable');initial=g.iloc[0];assert initial.side=='BUY'
                day=str(initial.signal_date)[:10];state='weak_locked' if targets.loc[day]==.5 else 'expansion_locked'
                buy=float((g.loc[g.side=='BUY','price']*g.loc[g.side=='BUY','quantity']).sum());sell=float((g.loc[g.side=='SELL','price']*g.loc[g.side=='SELL','quantity']).sum());fee=float(g.fees.sum())
                trade=t[t.cycle_id==cycle];assert len(trade)==1
                v={'candidate':cid,'window':window,'cycle':cycle,'state_group':state,'entry_date':str(trade.entry_date.iloc[0]),'exit_date':str(trade.exit_date.iloc[0]),'buy_notional':buy,'sell_notional':sell,'gross_yuan':sell-buy,'fees_yuan':fee,'net_yuan':sell-buy-fee,'fills':len(g),'additional_buy_fills':int(g.side.eq('BUY').sum()-1),'partial_sell_fills':int(g.side.eq('SELL').sum()-1)}
                amounts.append(v);cycles.append(v)
            q=pd.DataFrame(amounts);groups={}
            for name,g in q.groupby('state_group'):
                groups[name]={'closed':len(g),'gross_yuan':float(g.gross_yuan.sum()),'fees_yuan':float(g.fees_yuan.sum()),'net_yuan':float(g.net_yuan.sum()),'positive_cycles':int((g.net_yuan>0).sum()),'negative_cycles':int((g.net_yuan<0).sum())}
            out[prefix]={'gross_yuan':gross,'fees_yuan':fees,'net_yuan':net,'end_quantity':0,'closed':len(t),'fills':len(f),'additional_buy_fills':int(q.additional_buy_fills.sum()),'partial_sell_fills':int(q.partial_sell_fills.sum()),'groups':groups}
    pd.DataFrame(cycles).to_csv(HERE/'others/cycle_accounting.csv',index=False)
    out['difference']={}
    for w in ('full','s011_common'):
        a=out[f'C3300_{w}'];b=out[f'C3301_{w}'];out['difference'][w]={'net_improvement_yuan':b['net_yuan']-a['net_yuan'],'gross_difference_yuan':b['gross_yuan']-a['gross_yuan'],'fee_saving_yuan':a['fees_yuan']-b['fees_yuan']}
    save(HERE/'others/account_diagnosis.json',out);print(out)
if __name__=='__main__':main()
