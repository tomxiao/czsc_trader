"""Causal support-recovery landmarks and executable labels; no account simulation."""
from datetime import datetime, time
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import requests
from trading_execution_engine import DailyQuote, OrderSpec, SessionPriceLimits, resolve_fill

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]
HORIZONS=(1,3,10)
WINDOWS={'ALL':'2026-10-15','THROUGH_2025':'2025-12-31'}

def read(p): return json.loads(p.read_text(encoding='utf-8'))
def write(p,obj): p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
def module(name,p):
    s=importlib.util.spec_from_file_location(name,p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def features(close,dates):
    c=np.asarray(close,dtype=float); dates=pd.DatetimeIndex(dates)
    eligible=dates>=pd.Timestamp('2020-01-02'); counts=eligible.cumsum()
    floor=pd.Series(np.where(eligible,c,np.nan)).shift().rolling(5,min_periods=5).min().to_numpy()
    local=None; persistent=None; unresolved=False; previous_broken=False; seen_recovery=False
    episode=0; persistent_id=0; start=None; rows=[]
    for i in range(len(c)):
        ready=bool(counts[i]>=60 and np.isfinite(floor[i])); broken=bool(ready and c[i]<floor[i])
        first=False
        if broken and not previous_broken:
            local=float(floor[i]); start=i; episode+=1; seen_recovery=False
        if broken and not unresolved:
            persistent=float(floor[i]); persistent_id+=1; unresolved=True
        qualified=bool(ready and not broken)
        if qualified and local is not None and not seen_recovery:
            first=True; seen_recovery=True
        state=lambda a:'unanchored' if a is None else ('true_reclaim' if c[i]>=a else 'apparent_recovery')
        rows.append(dict(i=i,date=str(dates[i].date()),year=int(dates[i].year),ready=ready,broken=broken,qualified=qualified,
            floor=None if not np.isfinite(floor[i]) else float(floor[i]),close=float(c[i]),local_anchor=local,persistent_anchor=persistent,
            episode=episode,persistent_episode=persistent_id,break_start=start,break_age=None if start is None else i-start,
            local_state=state(local) if qualified else 'ineligible',persistent_state=state(persistent) if qualified else 'ineligible',
            first_recovery=first,local_distance=None if local is None else float(c[i]/local-1)))
        if unresolved and c[i]>=persistent: unresolved=False
        previous_broken=broken
    frame=pd.DataFrame(rows)
    for col in ('floor','local_anchor','persistent_anchor','break_start','break_age','local_distance'):
        frame[col]=pd.to_numeric(frame[col]).astype(float)
    return frame

def tick(v,mode=ROUND_FLOOR):
    return float((Decimal(str(v))/Decimal('.01')).to_integral_value(rounding=mode)*Decimal('.01'))

def limit_price(c,scale):
    return min(tick(c*1.01),tick(tick(c*1.1)-.01,ROUND_HALF_UP))*scale

def precheck():
    d=pd.bdate_range('2020-01-02',periods=66); c=[10.]*60+[9.5,9.4,9.45,9.2,9.6,10.1]
    f=features(c,d); checks=0
    assert not f.ready.iloc[58] and f.ready.iloc[59]; checks+=1
    assert f.local_anchor.iloc[61]==10 and f.first_recovery.iloc[62]; checks+=1
    assert f.local_state.iloc[62]=='apparent_recovery'; checks+=1
    assert f.local_state.iloc[64]=='true_reclaim' and f.persistent_state.iloc[64]=='apparent_recovery'; checks+=1
    assert f.persistent_state.iloc[65]=='true_reclaim'; checks+=1
    equal=c.copy(); equal[65]=10.; assert features(equal,d).persistent_state.iloc[65]=='true_reclaim'; checks+=1
    for k in range(59,66):
        pd.testing.assert_frame_equal(features(c[:k+1],d[:k+1]),f.iloc[:k+1].reset_index(drop=True)); checks+=1
    # Exact execution boundary probes, including limitdown SELL latch and better open.
    def fill(side,open_,low,high,price=None):
        return resolve_fill(OrderSpec(side,'LIMIT' if side=='BUY' else 'MARKET',100,price) if side=='BUY' else OrderSpec(side,'MARKET',100),
            session_open=open_,session_time=datetime(2020,1,2,9,30),intraday_touches=(),daily_quote=DailyQuote(low,high),
            session_limits=SessionPriceLimits(datetime(2020,1,2).date(),9.,11.,.01))
    assert fill('BUY',10.,9.8,10.2,10.1).price==10.; checks+=1
    assert not fill('BUY',10.2,10.11,10.3,10.1).filled; checks+=1
    assert not fill('SELL',9.,9.,9.).filled; checks+=1
    assert np.isclose(fill('SELL',9.,9.,9.01).price,9.01); checks+=1
    return dict(status='PASS',checks=checks,new_accounts=0)

def distribution(values):
    v=np.asarray(values,dtype=float); n=len(v)
    if not n:return dict(n=0,mean=None,median=None,q10=None,positive_contribution=None,negative_contribution=None,positive_n=0,negative_n=0,without_top3=None,without_top5=None)
    return dict(n=n,mean=float(v.mean()),median=float(np.median(v)),q10=float(np.quantile(v,.1)),
        positive_contribution=float(np.maximum(v,0).mean()),negative_contribution=float(np.minimum(v,0).mean()),
        positive_n=int((v>0).sum()),negative_n=int((v<0).sum()),
        without_top3=float(np.sort(v)[:-3].mean()) if n>3 else None,without_top5=float(np.sort(v)[:-5].mean()) if n>5 else None)

def state_blind_spacing(indices,h):
    selected=[]; last=-10000
    for i in indices:
        if i-last>=h+1:selected.append(i);last=i
    return selected

def joint_block_ci(frame,state_column,end):
    nblocks=(end-1)//20+1; sums=np.zeros((nblocks,2)); nums=np.zeros((nblocks,2))
    for r in frame.to_dict('records'):
        assert r['i']>=1
        g=0 if r[state_column]=='true_reclaim' else 1; b=(int(r['i'])-1)//20
        sums[b,g]+=r['net_return'];nums[b,g]+=1
    rng=np.random.default_rng(17); ix=rng.integers(0,nblocks,size=(2000,nblocks))
    ss=sums[ix].sum(axis=1);nn=nums[ix].sum(axis=1); valid=(nn>0).all(axis=1)
    delta=ss[valid,0]/nn[valid,0]-ss[valid,1]/nn[valid,1]
    return dict(valid_replicates=int(valid.sum()),replicates=2000,low=None if not len(delta) else float(np.quantile(delta,.025)),high=None if not len(delta) else float(np.quantile(delta,.975)))

def known_distribution(values):
    v=np.asarray(pd.Series(values).dropna(),dtype=float)
    return dict(n=len(v),mean=None if not len(v) else float(v.mean()),median=None if not len(v) else float(np.median(v)),
        q10=None if not len(v) else float(np.quantile(v,.1)),q90=None if not len(v) else float(np.quantile(v,.9)))

def persistence_summary(g,h):
    result={}
    for name,value,applicable in [('rolling_break','rolling_break_after',None),('local_loss','old_level_loss_after','old_loss_applicable'),('local_reclaim','old_level_reclaim_after','reclaim_applicable')]:
        x=g if applicable is None else g[g[applicable]]
        event=x[value].notna()
        result[name]=dict(at_risk=len(x),inapplicable=len(g)-len(x),observed=int(event.sum()),
            horizon_censored=int((~event & x.observed_future_sessions.eq(h)).sum()),cutoff_censored=int((~event & x.observed_future_sessions.lt(h)).sum()),
            event_time=known_distribution(x.loc[event,value]))
    return result

def summary(labels,features_frame):
    rows=[];contrasts=[]
    for window,cutoff in WINDOWS.items():
        end=int(features_frame[features_frame.date.le(cutoff)].i.max())
        for population in ('first_recovery','all_qualified'):
            for h in HORIZONS:
                d=labels[(labels.window==window)&(labels.horizon==h)].copy()
                if population=='first_recovery':d=d[d.first_recovery]
                scheduled=set(state_blind_spacing(d.i.tolist(),h))
                whole=d[(d.outcome=='CLOSED') & d.i.isin(scheduled)].sort_values('entry_i')
                whole_overlaps=int(sum(whole.entry_i.to_numpy()[1:]<=whole.exit_i.to_numpy()[:-1])) if len(whole)>1 else 0
                for anchor in ('local','persistent'):
                    col=anchor+'_state'
                    episode_col='episode' if anchor=='local' else 'persistent_episode'
                    for year in ('ALL',*range(2020,2027)):
                        y=d if year=='ALL' else d[d.year==year]
                        for state in ('true_reclaim','apparent_recovery','unanchored'):
                            g=y[y[col]==state];done=g[g.outcome=='CLOSED'];spaced=done[done.i.isin(scheduled)]
                            ordered=spaced.sort_values('entry_i'); overlaps=int(sum(ordered.entry_i.to_numpy()[1:]<=ordered.exit_i.to_numpy()[:-1])) if len(ordered)>1 else 0
                            rows.append(dict(window=window,population=population,horizon=h,anchor=anchor,year=year,state=state,
                                attempts=len(g),filled=int(g.outcome.isin(['CLOSED','OPEN']).sum()),closed=len(done),open=int((g.outcome=='OPEN').sum()),
                                buy_unfilled=int((g.outcome=='BUY_UNFILLED').sum()),no_next_session=int((g.outcome=='NO_NEXT_SESSION').sum()),
                                returns=distribution(done.net_return),scheduled_spaced=distribution(spaced.net_return),scheduled_actual_overlap_pairs=overlaps,
                                scheduled_whole_population_overlap_pairs=whole_overlaps,
                                episode_count=int(done[episode_col].nunique()),episode_equal_mean=None if done.empty else float(done.groupby(episode_col).net_return.mean().mean()),
                                break_age=known_distribution(g.break_age),local_distance=known_distribution(g.local_distance),persistence=persistence_summary(g,h)))
                    done=d[(d.outcome=='CLOSED')&d[col].isin(['true_reclaim','apparent_recovery'])].copy()
                    a=done[done[col]=='true_reclaim'];b=done[done[col]=='apparent_recovery']
                    done['age_bin']=pd.cut(done.break_age,[0,1,5,np.inf],labels=['1','2-5','6plus'],include_lowest=True)
                    weight=0;weighted=0.;covered=0;cells=[]
                    for (year,age),g in done.groupby(['year','age_bin'],observed=True):
                        x=g[g[col]=='true_reclaim'].net_return;y=g[g[col]=='apparent_recovery'].net_return
                        if len(x) and len(y):
                            w=min(len(x),len(y));delta=float(x.mean()-y.mean());weight+=w;weighted+=w*delta;covered+=len(x)+len(y)
                            cells.append(dict(year=int(year),age=str(age),true_n=len(x),apparent_n=len(y),difference=delta,weight=w))
                    contrasts.append(dict(window=window,population=population,horizon=h,anchor=anchor,true_n=len(a),apparent_n=len(b),
                        raw_difference=None if a.empty or b.empty else float(a.net_return.mean()-b.net_return.mean()),
                        block_ci=joint_block_ci(done,col,end),stratified_difference=None if not weight else weighted/weight,
                        stratified_covered=covered,stratified_total=len(done),stratified_cells=cells))
    return rows,contrasts

def main():
    if '--precheck' in sys.argv:
        result=precheck(); write(EX/'others/precheck.json',result); print(result);return
    if (EX/'others/analysis.json').exists():raise RuntimeError('Preserve completed diagnostic')
    locked=read(EX/'protocols/published_design.json')
    for item in locked['files']:
        assert sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256']
    attempts=[]
    def block(*args,**kwargs):attempts.append(1);raise RuntimeError('No upstream request authorized')
    requests.sessions.Session.request=block
    source=EX.parent/'EX017_20261017/src/audit_accounts.py';sys.path.insert(0,str(source.parent));a=module('ex030_pinned',source)
    frames=a.load_frames();m,raw,bounds,status=[frames[k].set_index(pd.to_datetime(frames[k].Date)).sort_index() for k in ('stock.ohlcv','stock.unadjusted_daily','security.price_limits','security.trading_status')]
    assert len(m)==1643 and len(m.loc['2020-01-02':])==1642 and (status.loc[m.index[1:],'Status']=='TRADING').all()
    dates=m.index; scale=m.Close/raw.Close; f=features(m.Close,dates);fs=f[f.ready].copy()
    sells={};buys={}
    for i in range(1,len(m)):
        day=dates[i]
        if status.loc[day,'Status']=='SUSPENDED': buys[i]=None;sells[i]=None;continue
        assert status.loc[day,'Status']=='TRADING'
        bar=m.iloc[i];bd=bounds.loc[day];rule=SessionPriceLimits(day.date(),float(bd.DownLimit*scale.iloc[i]),float(bd.UpLimit*scale.iloc[i]),float(.01*scale.iloc[i]))
        common=dict(session_open=float(bar.Open),session_time=datetime.combine(day.date(),time(9,30)),intraday_touches=(),daily_quote=DailyQuote(float(bar.Low),float(bar.High)),session_limits=rule)
        buy=resolve_fill(OrderSpec('BUY','LIMIT',100,limit_price(float(raw.Close.iloc[i-1]),float(scale.iloc[i-1]))),**common)
        sell=resolve_fill(OrderSpec('SELL','MARKET',100),**common)
        buys[i]=float(buy.price) if buy.filled else None;sells[i]=float(sell.price) if sell.filled else None
    labels=[]
    for window,cutoff in WINDOWS.items():
        end=int(dates.searchsorted(pd.Timestamp(cutoff),side='right'))-1
        for row in fs[fs.qualified & fs.i.le(end)].to_dict('records'):
            t=row['i'];e=t+1
            for h in HORIZONS:
                z=dict(row,window=window,horizon=h,entry_i=e if e<=end else None,entry_date=str(dates[e].date()) if e<=end else None,
                    entry_price=None,exit_i=None,exit_date=None,exit_price=None,net_return=None,mark_return=None,sell_delay=None)
                if e>end:z['outcome']='NO_NEXT_SESSION'
                elif buys[e] is None:z['outcome']='BUY_UNFILLED'
                else:
                    z['entry_price']=buys[e];j=next((j for j in range(e+h,end+1) if sells[j] is not None),None)
                    if j is None:z.update(outcome='OPEN',mark_return=float(m.Close.iloc[end]/(buys[e]*1.001)-1))
                    else:z.update(outcome='CLOSED',exit_i=j,exit_date=str(dates[j].date()),exit_price=sells[j],net_return=sells[j]*.999/(buys[e]*1.001)-1,sell_delay=j-(e+h))
                last=min(t+h,end);future=range(t+1,last+1)
                rolling=next((j-t for j in future if bool(f.broken.iloc[j])),None)
                anchor=row['local_anchor'];loss_applicable=anchor is not None and row['close']>=anchor;reclaim_applicable=anchor is not None and row['close']<anchor
                oldloss=next((j-t for j in future if m.Close.iloc[j]<anchor),None) if loss_applicable else None
                reclaim=next((j-t for j in future if m.Close.iloc[j]>=anchor),None) if reclaim_applicable else None
                z.update(observed_future_sessions=last-t,rolling_break_after=rolling,old_level_loss_after=oldloss,old_level_reclaim_after=reclaim,
                    old_loss_applicable=loss_applicable,reclaim_applicable=reclaim_applicable,
                    rolling_break_censored=rolling is None,old_loss_censored=loss_applicable and oldloss is None,reclaim_censored=reclaim_applicable and reclaim is None)
                labels.append(z)
    df=pd.DataFrame(labels)
    summaries,contrasts=summary(df,f)
    oldpath=EX.parent/'EX023_20261018/others/loss_state_diagnostics.json';old=read(oldpath)
    oldrows=[r for r in old['episodes'] if r['window']=='ALL' and r['entry_below_previous_broken_floor'] is True]
    assert len(oldrows)==69 and sum(r['R_cycle_log']>0 for r in oldrows)==31
    assert np.isclose(sum(r['R_cycle_log'] for r in oldrows),1.1745165549823025,atol=1e-12)
    bridge=[]
    for r in oldrows:
        e=int(dates.get_loc(pd.Timestamp(r['entry_date'])));state=f.iloc[e-1].to_dict()
        bridge.append(dict(original=r,signal_state=state))
    cross=[]
    for population in ('first_recovery','all_qualified'):
        q=fs[fs.first_recovery] if population=='first_recovery' else fs[fs.qualified]
        for (local,persistent),g in q.groupby(['local_state','persistent_state']):
            cross.append(dict(population=population,local_state=local,persistent_state=persistent,n=len(g)))
    for name,frame in [('features',f),('labels',df)]:
        (EX/f'others/{name}.csv').write_text(frame.to_csv(index=False,lineterminator='\n'),encoding='utf-8',newline='\n')
    result=dict(status='COMPLETE',prepared_reference=a.FULL_INPUT_REFERENCE,evaluation_sessions=1642,ready_sessions=len(fs),
        local_break_episodes=int(f.episode.max()),first_recoveries=int(f.first_recovery.sum()),never_anchored_qualified=int((fs.local_state=='unanchored').sum()),
        terminal_unrecovered_local_episode=bool(f.broken.iloc[-1]),new_accounts=0,new_candidates=0,new_upstream_calls=0,
        summaries=summaries,contrasts=contrasts,anchor_cross_table=cross,counterexample_bridge=bridge,
        source_sha256={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),EX/'protocols/design.json',source,oldpath,source.parent/'pinned_inputs.py']},
        output_sha256={name:sha256((EX/f'others/{name}.csv').read_bytes()).hexdigest() for name in ('features','labels')},
        limits=['Price-label association only, no simulated account or annual NAV acceptance.','Known-at-close features; forward outcomes never enter state. All data previously seen; intervals are not selection-adjusted.','Local and persistent anchors answer different questions; neither selected after observing returns.','Fixed100-share labels have no capital affordability or competing-entry effects; no frequency claim.','Actual frozen inputs contain no whole-day suspension; suspension handling is unobserved in real labels.'])
    assert not attempts
    write(EX/'others/analysis.json',result)
    print(json.dumps({k:result[k] for k in ['status','ready_sessions','local_break_episodes','first_recoveries','anchor_cross_table']},ensure_ascii=False))
    print(json.dumps([r for r in contrasts if r['population']=='first_recovery' and r['horizon']==10],ensure_ascii=False))

if __name__=='__main__':main()
