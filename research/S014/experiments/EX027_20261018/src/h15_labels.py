"""Locked H15 same-entry labels over all actual B-H10 entries; no account replay."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,time
import importlib.util,json,sys
import numpy as np
import pandas as pd
import requests
from trading_execution_engine import OrderSpec,DailyQuote,SessionPriceLimits,resolve_fill
ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]
def mod(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def main():
    dest=EX/'others/h15_labels.json'
    if dest.exists():raise RuntimeError('Preserve completed diagnostic')
    lockpath=EX/'others/h15_label_lock.json';lock=json.loads(lockpath.read_text(encoding='utf-8'))
    assert lock['status']=='LOCKED_BEFORE_LABEL_CALCULATION'
    recpath=EX/'others/account_results.json';assert sha256(recpath.read_bytes()).hexdigest()==lock['source_records_sha256']
    attempts=[]
    def block(*a,**kw):attempts.append(1);raise RuntimeError('No upstream')
    requests.sessions.Session.request=block
    inputpath=EX.parent/'EX017_20261017/src/audit_accounts.py';sys.path.insert(0,str(inputpath.parent));audit=mod('h15_inputs',inputpath);frames=audit.load_frames()
    market,raw,limits,status=[frames[n].set_index(pd.to_datetime(frames[n].Date)).sort_index() for n in ('stock.ohlcv','stock.unadjusted_daily','security.price_limits','security.trading_status')]
    scale=market.Close/raw.Close
    corepath=EX.parent/'EX018_20261017/src/account_diagnostics.py';core=mod('h15_cycles',corepath)
    baselinepath=EX.parent/'EX021_20261018/others/account_results.json';bindingpath=EX/'others/h15_baseline_binding.json';binding=json.loads(bindingpath.read_text(encoding='utf-8'));assert sha256(baselinepath.read_bytes()).hexdigest()==binding['baseline_account_results_sha256']
    records=json.loads(baselinepath.read_text(encoding='utf-8'))['records'];record=next(r for r in records if r['variant']=='support_entry_H10');tables=core.load(record);daily=tables['account_daily'];anchor=float(market.loc[daily.index[0],'Close']/daily.close.iloc[0])
    assert np.allclose(market.loc[daily.index,'Close']/anchor,daily.close,atol=1e-9,rtol=0)
    cycles,reconciliation=core.cycles(tables,pd.Timestamp('2026-10-15'),'support_entry_H10')
    assert len(cycles)==len(tables['fills'].query("side == 'BUY'"))
    def sell(first,end,quantity):
        for j in range(first,end+1):
            day=market.index[j];state=status.loc[day,'Status'];assert state in ('TRADING','SUSPENDED')
            if state=='SUSPENDED':continue
            b=limits.loc[day];bar=market.iloc[j]
            fill=resolve_fill(OrderSpec('SELL','MARKET',quantity),session_open=float(bar.Open),session_time=datetime.combine(day.date(),time(9,30)),intraday_touches=(),daily_quote=DailyQuote(float(bar.Low),float(bar.High)),session_limits=SessionPriceLimits(day.date(),float(b.DownLimit*scale.iloc[j]),float(b.UpLimit*scale.iloc[j]),float(.01*scale.iloc[j])))
            if fill.filled:return j,float(fill.price)/anchor
        return None,None
    checks=0;rows=[]
    for c in cycles.to_dict('records'):
        e=market.index.get_loc(pd.Timestamp(c['entry_date']));q=c['quantity'];outlay=c['entry_outlay']
        assert np.isclose(outlay,q*c['entry_price']*1.001,atol=1e-8,rtol=0)
        bi,bp=sell(e+10,len(market)-1,q)
        if c['status']=='CLOSED':
            assert bi is not None and str(market.index[bi].date())==c['exit_or_mark_date']
            assert np.isclose(bp,c['exit_or_mark_price'],atol=1e-9,rtol=0)
            assert np.isclose(q*bp*.999/outlay-1,c['position_return'],atol=1e-11,rtol=0)
        else:assert bi is None
        checks+=1
        for window,cutoff in [('ALL','2026-10-15'),('THROUGH_2025','2025-12-31')]:
            end=int(market.index.searchsorted(pd.Timestamp(cutoff),side='right'))-1
            if e>end:continue
            original_closed=bi is not None and bi<=end
            original_price=bp if original_closed else float(market.Close.iloc[end])/anchor
            original_return=q*original_price*(.999 if original_closed else 1.)/outlay-1
            j,p=sell(e+15,end,q);closed=j is not None;mark_price=p if closed else float(market.Close.iloc[end])/anchor
            ret=q*mark_price*(.999 if closed else 1.)/outlay-1
            paired=original_closed and closed
            rows.append(dict(window=window,cutoff=cutoff,cycle_id=c['cycle_id'],entry_date=c['entry_date'],entry_year=c['entry_year'],quantity=q,actual_entry_price=c['entry_price'],buy_outlay=outlay,decision_date=str(market.index[e+14].date()) if e+14<len(market) else None,H15_due_date=str(market.index[e+15].date()) if e+15<len(market) else None,original_H10_exit_date=str(market.index[bi].date()) if original_closed else None,original_closed=original_closed,H15_exit_date=str(market.index[j].date()) if closed else None,H15_closed=closed,H15_exit_delay_sessions=j-(e+15) if closed else None,paired_complete=paired,original_position_return=original_return,H15_position_return=ret,completed_increment=ret-original_return if paired else None,right_censored=not paired,original_terminal_mark_price=None if original_closed else original_price,H15_terminal_mark_price=None if closed else mark_price,mark_no_fake_exit_fee=not paired))
    df=pd.DataFrame(rows);summary=[]
    for window in ('ALL','THROUGH_2025'):
        scope=df[df.window.eq(window)]
        for name,subset in [('ALL',scope),*[(str(y),scope[scope.entry_year.eq(y)]) for y in range(2020,2027)]]:
            complete=subset[subset.paired_complete]
            summary.append(dict(window=window,entry_year=name,total_entries=len(subset),right_censored=int(subset.right_censored.sum()),increment=core.distribution(complete.completed_increment),H10_mean_completed_return=None if complete.empty else float(complete.original_position_return.mean()),H15_mean_completed_return=None if complete.empty else float(complete.H15_position_return.mean())))
    csv=EX/'others/h15_labels.csv';csv.write_text(df.to_csv(index=False,lineterminator='\n'),encoding='utf-8',newline='\n')
    sources=[Path(__file__),lockpath,recpath,baselinepath,bindingpath,corepath,inputpath,EX/'others/capacity_upper_bound.json']
    result=dict(status='PASS',new_accounts=0,new_trials=0,new_upstream_calls=0,original_B_entries=len(cycles),original_H10_fill_reproductions=checks,baseline_account_reconciliation=reconciliation,source_record=record,source_sha256={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest() for p in sources},labels_csv_sha256=sha256(csv.read_bytes()).hexdigest(),summary=summary,terminal_censored=df[df.right_censored].where(pd.notna(df),None).to_dict('records'),limits=['Same actual entry/quantity/fee labels only; overlapping positions are not simultaneous affordable accounts.','Completed label differences do not include changed next entries or capital/lot sizes. No compound/account total from label sums.','Entry-year grouping is not calendar-year NAV acceptance. THROUGH_2025 uses actual2025 cutoff and censors any2026 fill.','Future SELL outcome is a label, not an available entry/exit decision feature. All data already seen.','H18 excluded by frequency; no H18 labels computed.'])
    assert not attempts
    # Pandas nullable numeric fields require explicit JSON-compatible nulls.
    result['terminal_censored']=json.loads(df[df.right_censored].to_json(orient='records'))
    dest.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'status':'PASS','entries':len(cycles),'summary':summary},indent=2))
if __name__=='__main__':main()
