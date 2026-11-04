from pathlib import Path
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from czsc_trader.research_tools.equity_replay import materialize_equity

ROOT = Path(__file__).resolve().parents[4]
W = Path(__file__).resolve().parents[1]

def materialize(ref):
    p = ROOT/'S018/assets/evidence'/ref['experiment']['experiment_id']/ref['evidence_id']
    content = p.read_bytes()
    assert sha256(content).hexdigest() == ref['sha256']
    return materialize_equity(content, lambda x: (p.parent/(x['sha256']+'.json')).read_bytes()).payload


def summary(x):
    r=x['net_return'].astype(float)
    wins=r[r>0]; losses=r[r<0]
    return {'n':len(r),'mean':float(r.mean()),'median':float(r.median()),
            'win_rate':float((r>0).mean()),'p05':float(r.quantile(.05)),
            'payoff':float(wins.mean()/-losses.mean()) if len(wins) and len(losses) else None}


def main():
    records=json.loads((W/'others/results.json').read_text())['accounts']
    rows=[]; audits={}; buy_intents={h:0 for h in [1,3,6]}; filled_counts={h:0 for h in [1,3,6]}
    for candidate, rec in records.items():
        view=materialize(rec['account_ref'])
        run=view['runs']['candidate']
        bars=pd.DataFrame(view['audit_inputs']['bars'])
        by_start={b['BarStart']:i for i,b in enumerate(view['audit_inputs']['bars'])}
        h=int(rec['config'][1])
        buy_intents[h]+=sum(o['side']=='BUY' for o in run['orders'])
        buys={f['cycle_id']:f for f in run['fills'] if f['side']=='BUY'}
        filled_counts[h]+=len(buys)
        sells={f['cycle_id']:f for f in run['fills'] if f['side']=='SELL'}
        for trade in run['trades']:
            buy=buys[trade['cycle_id']]
            assert buy['quantity']==1
            j=by_start[buy['interval_start']]; t=j-1
            row={'candidate':candidate,'horizon':h,'signal_date':bars.iloc[t]['Date'][:10],
                 'entry_date':buy['interval_start'][:10],'status':trade['status'],
                 'entry_price':buy['price'],'net_return':trade.get('net_return'),
                 'signal_close':float(bars.iloc[t]['Close'])}
            c=bars['Close']
            row.update(down=bool(c.iloc[t]<c.iloc[t-1]),up=bool(c.iloc[t]>c.iloc[t-1]),
                two_down=bool(c.iloc[t]<c.iloc[t-1]<c.iloc[t-2]),
                prior20_up=bool(c.iloc[t-2]>c.iloc[t-22]))
            if trade['status']=='CLOSED':
                sell=sells[trade['cycle_id']]
                assert by_start[sell['interval_start']]-j==h
                assert sell['quantity']==1
                row['exit_date']=sell['interval_start'][:10]
                row['exit_price']=sell['price']
            rows.append(row)
    frame=pd.DataFrame(rows)
    assert not frame.duplicated(['horizon','signal_date']).any()
    groups={}
    for h in [1,3,6]:
        part=frame[frame.horizon==h]
        closed=part[part.status=='CLOSED']
        audits[str(h)]={'buy_intents':buy_intents[h], 'filled':filled_counts[h],'closed':len(closed),
                        'open':filled_counts[h]-len(closed),'unfilled':buy_intents[h]-filled_counts[h]}
        assert buy_intents[h]==961
        masks={'all':pd.Series(True,index=closed.index),'down':closed.down,'up':closed.up,
               'two_down':closed.two_down,'not_two_down':~closed.two_down,
               'two_down_prior_up':closed.two_down & closed.prior20_up,
               'two_down_prior_down':closed.two_down & ~closed.prior20_up}
        for name, mask in masks.items():
            x=closed[mask]; group=summary(x)
            group['years']={str(y):summary(x[x.entry_date.str.startswith(str(y))]) for y in [2023,2024,2025,2026]}
            groups[f'{h}:{name}']=group
    frame.to_json(W/'others/analysis_events_enriched.json',orient='records',force_ascii=False,indent=2)
    out={'coverage':audits,'groups':groups,'checks':['one_share','unique_signal_per_horizon','all_961_intents','exit_interval_distance'],
         'limits':'重叠机会不独立，1股事件收益不是可加总账户绩效；trade.exit_at为记账时刻，实际卖价与日期取fill。'}
    (W/'others/analysis_summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'coverage':audits,'groups':{k:{a:v[a] for a in ['n','mean','win_rate','payoff']} for k,v in groups.items()}},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
