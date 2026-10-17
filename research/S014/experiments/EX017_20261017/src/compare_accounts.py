"""Annual targets and mechanism contrasts from four published continuous ledgers."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]

def annual(daily):
    d=daily.copy();d['date']=pd.to_datetime(d.date);d=d.set_index('date').sort_index()
    opening=100000.;rows=[]
    for year,g in d.groupby(d.index.year):
        nav=np.r_[opening,g.equity.to_numpy(float)]
        rows.append({'year':int(year),'opening_equity':opening,'ending_equity':float(nav[-1]),
            'return':float(nav[-1]/opening-1),'max_drawdown':float(-(nav/np.maximum.accumulate(nav)-1).min()),
            'sessions':len(g)})
        opening=float(nav[-1])
    return pd.DataFrame(rows).set_index('year')

def main():
    result=json.loads((EX/'others/account_results.json').read_text(encoding='utf-8'))
    expected=('parent_H1','parent_H3','high_H3','high_H3_low_H1')
    assert tuple(r['variant'] for r in result['records'])==expected, 'Require all four unique approved accounts'
    summaries=[];years=[];bench=None;all_daily={};all_trades={}
    for record in result['records']:
        assert record['status']=='SUCCEEDED'
        ref=EvidenceRef.from_dict(record['evidence'])
        data=json.loads(ref.resolve(ROOT).read_text(encoding='utf-8'))
        assert len(data['runs'])==1
        run=data['runs'][0]
        assert (run['window_id'],run['scenario_id'])==('full','baseline')
        assert record['candidate']=='S014-'+run['candidate_id']
        ledgers={k:pd.DataFrame(v['data']) for k,v in run['ledgers'].items()}
        daily=ledgers['account_daily'];trades=ledgers['trades'];fills=ledgers['fills'];orders=ledgers['orders']
        benchmark=pd.DataFrame(run['buyhold']['account_daily']['data'])
        if bench is None:bench=benchmark
        else:pd.testing.assert_frame_equal(bench,benchmark,check_exact=True)
        assert len(daily)==len(benchmark)==1642
        a=annual(daily);b=annual(benchmark)
        a['buyhold_return']=b['return'];a['buyhold_drawdown']=b.max_drawdown
        a['required_return']=np.where(b['return']>0,1.5*b['return'],0.)
        a['return_pass']=np.where(b['return']>0,a['return']>=1.5*b['return'],a['return']>0.)
        a['drawdown_pass']=a.max_drawdown<b.max_drawdown
        a['both_pass']=a.return_pass&a.drawdown_pass;a['variant']=record['variant']
        years.append(a.reset_index())
        closed=trades.loc[trades.status.eq('CLOSED')]
        equity=daily.equity.to_numpy(float);nav=np.r_[100000.,equity]
        frequency=60*len(closed)/len(daily)
        r={'variant':record['variant'],'candidate':record['candidate'],'ending_equity':float(equity[-1]),
            'total_return':float(equity[-1]/100000-1),'cagr':float((equity[-1]/100000)**(252/1642)-1),
            'full_max_drawdown':float(-(nav/np.maximum.accumulate(nav)-1).min()),
            'closed_trades':len(closed),'open_trades':int(trades.status.eq('OPEN').sum()),
            'frequency_per_60':frequency,'frequency_pass':frequency>=3,
            'annual_return_pass_count':int(a.return_pass.sum()),'annual_drawdown_pass_count':int(a.drawdown_pass.sum()),
            'annual_both_pass_count':int(a.both_pass.sum()),'all_targets_pass':bool(a.both_pass.all() and frequency>=3),
            'fees':float(fills.fees.sum()),'exposure_close_sessions':int(daily.quantity.gt(0).sum()),
            'failed_orders':int(orders.status.ne('FILLED').sum()),'buy_attempts':int(orders.side.eq('BUY').sum()),
            'closed_mean_return':float(closed.net_return.mean()),'closed_win_rate':float(closed.net_return.gt(0).mean()),
            'source_evidence':ref.to_dict()}
        summaries.append(r);all_daily[record['variant']]=daily;all_trades[record['variant']]=trades
    pd.concat(years).to_csv(EX/'others/annual_comparison.csv',index=False)
    pd.DataFrame([{k:v for k,v in r.items() if k!='source_evidence'} for r in summaries]).to_csv(EX/'others/account_comparison.csv',index=False)
    ba=annual(bench);ba.to_csv(EX/'others/buyhold_annual.csv')
    bn=np.r_[100000.,bench.equity.to_numpy(float)]
    value={'status':'COMPLETE','account_count':len(summaries),'all_targets_pass_count':sum(r['all_targets_pass'] for r in summaries),
        'annual_formula':'Closing NAV / previous year closing NAV - 1; first opening NAV=100000; year drawdown includes opening NAV',
        'frequency_formula':'60 * CLOSED trades / 1642; OPEN excluded',
        'buyhold':{'ending_equity':float(bn[-1]),'total_return':float(bn[-1]/100000-1),
                   'full_max_drawdown':float(-(bn/np.maximum.accumulate(bn)-1).min())},
        'summaries':summaries,'annual':pd.concat(years).to_dict('records'),
        'all_data_seen':True,'parameter_search':False}
    (EX/'others/comparison.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(pd.DataFrame(summaries).drop(columns='source_evidence').to_string(index=False))
    print(pd.concat(years)[['year','variant','return','max_drawdown','buyhold_return','buyhold_drawdown','return_pass','drawdown_pass']].to_string(index=False))

if __name__=='__main__':main()
