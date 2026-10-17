"""Describe opportunity occupancy and realized annual P&L without new trials."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]
def main():
    inputs=json.loads((EX/'others/account_results.json').read_text(encoding='utf-8'))
    rows=[];drawdowns=[]
    for record in inputs['records']:
        value=json.loads(EvidenceRef.from_dict(record['evidence']).resolve(ROOT).read_text(encoding='utf-8'))['runs'][0]
        d=pd.DataFrame(value['ledgers']['account_daily']['data']);b=pd.DataFrame(value['buyhold']['account_daily']['data'])
        d['date']=pd.to_datetime(d.date);d['year']=d.date.dt.year
        d['pnl']=d.equity.diff().fillna(d.equity.iloc[0]-100000)
        d['bh_log_return']=np.log(b.equity/ b.equity.shift().fillna(100000))
        d['state']=np.select([d.quantity_before.eq(0)&d.quantity.eq(0),d.quantity_before.eq(0)&d.quantity.gt(0),
                             d.quantity_before.gt(0)&d.quantity.eq(0)],['flat','entry','exit'],default='holding')
        for year,g in d.groupby('year'):
            opening=float(g.equity.iloc[0]-g.pnl.iloc[0])
            for state,part in g.groupby('state'):
                rows.append({'variant':record['variant'],'year':int(year),'state':state,'days':len(part),
                    'account_pnl':float(part.pnl.sum()),'account_annual_return_contribution':float(part.pnl.sum()/opening),
                    'buyhold_log_return_sum':float(part.bh_log_return.sum()),
                    'buyhold_selected_days_compounded':float(np.expm1(part.bh_log_return.sum()))})
            nav=np.r_[opening,g.equity.to_numpy(float)];dd=nav/np.maximum.accumulate(nav)-1
            trough=int(np.argmin(dd));peak=int(np.argmax(nav[:trough+1]))
            drawdowns.append({'variant':record['variant'],'year':int(year),
                'peak':'year opening NAV' if peak==0 else g.date.iloc[peak-1].date().isoformat(),
                'trough':'year opening NAV' if trough==0 else g.date.iloc[trough-1].date().isoformat(),
                'drawdown':float(-dd[trough])})
    pd.DataFrame(rows).to_csv(EX/'others/occupancy_diagnosis.csv',index=False)
    pd.DataFrame(drawdowns).to_csv(EX/'others/drawdown_intervals.csv',index=False)
    print(pd.DataFrame(rows).query("variant=='high_H3' and state=='flat'").to_string(index=False))
    print(pd.DataFrame(drawdowns).query("variant=='high_H3'").to_string(index=False))

if __name__=='__main__':main()
