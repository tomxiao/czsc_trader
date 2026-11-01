"""Outcome-blind terminated consecutive negative-body run context at original E0 times."""
from collections import Counter
from datetime import date,datetime
from math import fsum,isfinite
from pathlib import Path
from zoneinfo import ZoneInfo
import json
from dataflows import TradingSession,TimeInterval,BarFrequency
from czsc_trader.research_tools import EvidenceRef
from common import ROOT,WORK,INPUT_SHA,account_input,checked_bytes,digest,read,save

GROUPS=('ALL','SINGLE','MULTI_FULL','MULTI_PARTIAL','FULL')
ALPHA=.3435458360048906
ZONE=ZoneInfo('America/New_York')


def at(value):return datetime.fromisoformat(value.replace('Z','+00:00'))


def run_context(bars,i):
    j=i-1
    while j>=0 and float(bars[j]['Close'])<float(bars[j]['Open']):j-=1
    length=i-1-j
    if j<0:return {'run_defined':False,'left_censored':True,'run_length':length,'run_high':None,'run_start_at':bars[0]['Date'] if length else None,'terminator_at':None,'run_cross_session':None,'previous_high_is_run_high':None,'run_net_close_change':None}
    if not length:return {'run_defined':False,'left_censored':False,'run_length':0,'run_high':None,'run_start_at':None,'terminator_at':bars[j]['Date'],'run_cross_session':False,'previous_high_is_run_high':None,'run_net_close_change':None}
    high=max(float(bars[k]['High']) for k in range(j+1,i))
    days={at(bars[k]['BarStart']).astimezone(ZONE).date() for k in range(j+1,i)}
    return {'run_defined':True,'left_censored':False,'run_length':length,'run_high':high,'run_start_at':bars[j+1]['Date'],'terminator_at':bars[j]['Date'],'run_cross_session':len(days)>1,'previous_high_is_run_high':float(bars[i-1]['High'])==high,'run_net_close_change':float(bars[i-1]['Close'])-float(bars[j]['Close'])}


def predicates(e0,close,run):
    single=bool(e0 and run['run_defined'] and run['run_length']==1)
    multi=bool(e0 and run['run_defined'] and run['run_length']>=2)
    full=bool(multi and close>run['run_high'])
    partial=bool(multi and close<=run['run_high'])
    return {'ALL':bool(e0),'SINGLE':single,'MULTI_FULL':full,'MULTI_PARTIAL':partial,'FULL':bool(single or full)}


def original_clock():
    record=read(ROOT/'research/S017/experiments/EX056_20261031/others/accounts.json')['C0222']
    ref=EvidenceRef.from_dict(record['evidence']);envelope=json.loads(checked_bytes(ref))
    if envelope['input_ref']!={'kind':'equity_input','sha256':INPUT_SHA}:raise ValueError('Exact current input required')
    dep=envelope['candidate_ref'];path=ref.resolve(ROOT).parent/(dep['sha256']+'.json')
    if digest(path)!=dep['sha256']:raise ValueError('Original candidate artifact changed')
    # Only the original decision clock and raw-entry boolean are consumed, not returns.
    decisions=json.loads(path.read_bytes())['run']['decisions']
    rows=[]
    for d in decisions:
        f={x['key']:x['text'] for x in d['explanation']['basis']}
        rows.append(dict(signal_at=d['observed_through'],decision_at=d['decision_at'],planned_entry_start=d['execution_start'],planned_entry_end=d['execution_end'],e0=f['entry_signal']=='True'))
    if len(rows)!=6490 or sum(x['e0'] for x in rows)!=209:raise ValueError('Original C222 market clock changed')
    return rows,record['evidence'],dep


def derive(bars,sessions,clock):
    if len(bars)!=7017 or len(sessions)!=543:raise ValueError('Approved7017/543 input required')
    times=[at(b['Date']) for b in bars]
    if times!=sorted(times) or len(set(times))!=len(times):raise ValueError('Unique chronological completed bars required')
    index={t:i for i,t in enumerate(times)};planned=[];firsts={}
    for s in sessions:
        session=TradingSession(date.fromisoformat(s['session_date']),s['timezone'],tuple(TimeInterval(at(x['start']),at(x['end'])) for x in s['segments']))
        if s['timezone']!=str(ZONE):raise ValueError('NY RTH required')
        slots=session.bars(BarFrequency.M30)
        for p in slots:
            if p.end not in index:raise ValueError('Missing planned complete RTH bar')
            i=index[p.end];b=bars[i]
            if at(b['BarStart'])!=p.start or at(b['AvailableDate'])>p.end:raise ValueError('Invalid interval/visibility')
            if not all(isfinite(float(b[k])) and float(b[k])>0 for k in ('Open','High','Low','Close')) or not b['Low']<=min(b['Open'],b['Close'])<=max(b['Open'],b['Close'])<=b['High']:raise ValueError('Valid OHLC required')
            planned.append(i)
        firsts[session.session_date]=index[slots[0].end]
    if planned!=list(range(len(bars))):raise ValueError('Complete planned grid differs')
    tr=[max(float(b['High'])-float(b['Low']),abs(float(b['High'])-float(bars[i-1]['Close'])),abs(float(b['Low'])-float(bars[i-1]['Close']))) if i else float(b['High'])-float(b['Low']) for i,b in enumerate(bars)]
    rows=[];warm=[]
    for d in clock:
        stamp=at(d['signal_at']);i=index[stamp];b=bars[i];prev=bars[i-1]
        observed=at(b['BarStart']).astimezone(ZONE).date();fi=firsts[observed];first=bars[fi]
        if fi>i or at(first['Date'])>stamp:raise ValueError('First low is not yet complete')
        atr=fsum(tr[i-14:i-1])/13
        e0=float(prev['Close'])<float(prev['Open']) and float(b['Close'])-float(prev['High'])>ALPHA*atr
        run=run_context(bars,i) if e0 else dict(run_defined=False,left_censored=False,run_length=0,run_high=None,run_start_at=None,terminator_at=None,run_cross_session=False,previous_high_is_run_high=None,run_net_close_change=None)
        flags=predicates(e0,float(b['Close']),run)
        margin=run['run_high']-float(prev['High']) if run['run_defined'] else None
        delta=float(b['Close'])-float(prev['High'])
        if not '2024-01-02'<=observed.isoformat()<='2025-12-31':
            if d['e0']:raise ValueError('Warmup observation cannot be an entry')
            warm.append(d);continue
        if e0!=d['e0']:raise ValueError('Independent lag2 E0 differs from original frozen decision')
        entry=at(d['planned_entry_start']).astimezone(ZONE)
        rows.append(dict(signal_at=d['signal_at'],decision_at=d['decision_at'],bar_index=i,observed_session_date=observed.isoformat(),first_bar_end=first['Date'],first_bar_start=first['BarStart'],previous_high=float(prev['High']),delta=delta,atr_lag2=atr,reclaim_margin_atr=delta/atr if atr>0 else None,run_margin_above_previous_high=margin,run_margin_atr=margin/atr if margin is not None and atr>0 else None,**run,close=float(b['Close']),first_bar=fi==i,planned_entry_start=d['planned_entry_start'],planned_entry_end=d['planned_entry_end'],planned_entry_ny_slot=entry.strftime('%H:%M'),execution_observed_day_differs=entry.date()!=observed,**flags))
    if len(rows)!=6489 or len(warm)!=1:raise ValueError('Exact original6489/6490 boundary required')
    return rows,warm


def main():
    value,source,input_ref=account_input();clock,actor,dep=original_clock()
    rows,warm=derive(value['products']['bars'],value['data']['sessions']['metadata']['sessions'],clock)
    if sum(r['ALL'] for r in rows)!=209:raise ValueError('Exact209 original E0 population required')
    out=dict(status='PASS_OUTCOME_BLIND_E0_NEGATIVE_RUN_FEATURES',source_sha256=digest(Path(__file__)),input_ref=input_ref,source_account=source,original_c222_account=actor,original_candidate_artifact=dep,actual_c222_clock=6490,eligible_observations=len(rows),excluded_warmup_observations=warm,complete543_session_grid_verified=True,feature_rows=rows,populations={g:dict(raw=sum(r[g] for r in rows),years=dict(Counter(r['observed_session_date'][:4] for r in rows if r[g])),first_bar=sum(r[g] and r['first_bar'] for r in rows),cross_execution_day=sum(r[g] and r['execution_observed_day_differs'] for r in rows)) for g in GROUPS},left_censored_e0=[r['signal_at'] for r in rows if r['ALL'] and r['left_censored']],maximum_actual_run_length=max(r['run_length'] for r in rows if r['ALL']),multi_previous_high_already_max=sum(r['ALL'] and r['run_length']>=2 and r['previous_high_is_run_high'] for r in rows),run_length_counts=dict(Counter(r['run_length'] for r in rows if r['ALL'])),margin_by_group={g:[{'signal_at':r['signal_at'],'run_length':r['run_length'],'delta':r['delta'],'margin':r['run_margin_above_previous_high'],'ny_slot':r['planned_entry_ny_slot']} for r in rows if r[g]] for g in GROUPS},new_future_labels_or_group_returns=0,new_account_compute=0,sealed_2026_access=False)
    save(WORK/'others/features.json',out)
    print('OUTCOME_BLIND_NEGATIVE_RUN_FEATURES',out['populations'],flush=True)


if __name__=='__main__':main()
