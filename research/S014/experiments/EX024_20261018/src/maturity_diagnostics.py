"""Post-H10 labels for C56: diagnostic hypothetical exits, never account returns."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,time
import importlib.util
import json
import sys
import pandas as pd
import requests
from trading_execution_engine import OrderSpec,DailyQuote,SessionPriceLimits,resolve_fill
ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]
OLD=EX.parent/'EX023_20261018'

def mod(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def main():
    dest=EX/'others/maturity_diagnostics.json'
    if dest.exists():raise RuntimeError('Preserve completed diagnostic')
    requests.sessions.Session.request=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Offline diagnostic'))
    sys.path.insert(0,str(EX.parent/'EX017_20261017/src'))
    audit=mod('maturity_input',EX.parent/'EX017_20261017/src/audit_accounts.py');frames=audit.load_frames()
    args=[frames[n] for n in ('stock.ohlcv','stock.unadjusted_daily','security.price_limits','security.trading_status')]
    runtime=mod('maturity_original',OLD/'src/strategy_runtime/strategies/repair.py')
    h=runtime.history(*args,'support_exit_reserve_H10')
    market,raw,limits,status=[f.set_index(pd.to_datetime(f.Date)).sort_index() for f in args]
    scale=market.Close/raw.Close
    records=json.loads((OLD/'others/account_results.json').read_text())['records'];record=records[0]
    core=mod('maturity_cycles',EX.parent/'EX018_20261017/src/account_diagnostics.py')
    tables=core.load(record);daily=tables['account_daily'];anchor=market.loc[daily.index[0],'Close']/daily.close.iloc[0]
    cycles,reconciliation=core.cycles(tables,pd.Timestamp('2026-10-15'),'support_exit_reserve_H10')
    def sale(first):
        for j in range(first,len(market)):
            day=market.index[j]
            if status.loc[day,'Status']=='SUSPENDED':continue
            assert status.loc[day,'Status']=='TRADING'
            b=limits.loc[day];bar=market.iloc[j]
            fill=resolve_fill(OrderSpec('SELL','MARKET',100),session_open=float(bar.Open),session_time=datetime.combine(day.date(),time(9,30)),intraday_touches=(),daily_quote=DailyQuote(float(bar.Low),float(bar.High)),session_limits=SessionPriceLimits(day.date(),float(b.DownLimit*scale.iloc[j]),float(b.UpLimit*scale.iloc[j]),float(.01*scale.iloc[j])))
            if fill.filled:return j,float(fill.price)
        return None,None
    rows=[]
    for c in cycles.to_dict('records'):
        e=h.index.get_loc(pd.Timestamp(c['entry_date']));deadline=e+9
        if deadline>=len(h):continue
        before=h.iloc[e:deadline]
        if before.exit_pending.any():continue
        if not h.iloc[deadline].held_at_close:continue
        p=float(market.Close.iloc[deadline]/(c['entry_price']*anchor*1.001)-1)
        for mode in ('fixed_H20','support_until_H20','support_uncapped'):
            first=None
            if mode=='fixed_H20':first=e+20
            else:
                ceiling=e+19 if mode=='support_until_H20' else len(h)
                for j in range(deadline,len(h)):
                    if h.support_break.iloc[j] or j>=ceiling:first=j+1;break
            j,price=sale(first) if first is not None and first<len(h) else (None,None)
            censored=j is None
            end=len(h)-1 if censored else j
            exit_price=float(market.Close.iloc[-1]) if censored else price
            ret=float(exit_price*(1. if censored else .999)/(c['entry_price']*anchor*1.001)-1)
            actual=float(c['position_return'])
            rows.append(dict(entry_date=c['entry_date'],entry_year=int(c['entry_year']),decision_date=str(h.index[deadline].date()),decision_year=int(h.index[deadline].year),decision_support_ok=bool(h.support_ok.iloc[deadline]),positive_mark=p>0,known_buy_fee_mark_return=p,mode=mode,hypothetical_exit_date=str(h.index[end].date()),right_censored=censored,actual_H10_exit_date=c['exit_or_mark_date'],actual_H10_position_return=actual,hypothetical_position_return=ret,increment=ret-actual))
    df=pd.DataFrame(rows);summary=[]
    for window,cutoff in [('ALL',2026),('DECISION_BEFORE2026',2025)]:
        for mode in df['mode'].unique():
            for pos in ('ALL',True,False):
                g=df[(df.decision_year<=cutoff)&df['mode'].eq(mode)&df.decision_support_ok&~df.right_censored]
                if pos!='ALL':g=g[g.positive_mark.eq(pos)]
                v=g.increment
                summary.append(dict(window=window,mode=mode,positive_mark=pos,n=len(g),mean_increment=None if g.empty else float(v.mean()),median_increment=None if g.empty else float(v.median()),positive=int(v.gt(0).sum()),negative=int(v.lt(0).sum()),mean_remove_top3=None if len(g)<=3 else float(v.sort_values().iloc[:-3].mean()),mean_remove_top5=None if len(g)<=5 else float(v.sort_values().iloc[:-5].mean())))
    sources=[Path(__file__),OLD/'src/strategy_runtime/strategies/repair.py',OLD/'others/account_results.json']
    result=dict(status='PASS',new_accounts=0,new_upstream_calls=0,source_record=record,reconciliation=reconciliation,summary=summary,episodes=rows,
        source_sha256={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest() for p in sources},
        labels='Original C56 cycles reaching E+9 without earlier SELL intent; report support-ok subset separately. Hypothetical H20 at E+19close, or first support break with H20 cap/no cap, execute following session via same SELL rule with failures latched. Same original actual entry and buy fee; exit fee only when hypothetically filled. Future labels never used as decision features.',
        limitations=['These overlapping hypothetical per-position exit labels are not full accounts; they ignore changed participation, quantities and capital.','DECISION_BEFORE2026 is a decision cohort, not cutoff NAV; labels can mature in2026 and are not claimed as independent data.','All outcomes seen; P positive uses actual buy price and only buy fee at decision close.','H20 is a single doubled horizon diagnostic; uncapped checks whether H20 may truncate a mechanism, not a selected optimum.'])
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    df.to_csv(EX/'others/maturity_labels.csv',index=False,lineterminator='\n')
    print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':main()
