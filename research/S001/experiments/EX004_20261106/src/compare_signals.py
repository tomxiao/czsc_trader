"""Point-in-time S001 tail-week correction; immutable inputs and unchanged math."""
from pathlib import Path
from importlib import import_module
from collections import Counter
from types import SimpleNamespace
from hashlib import sha256
import ast
import json
import sys
import time
import numpy as np
import pandas as pd

ROOT=Path.cwd();sys.path.insert(0,str(ROOT))
HOME=ROOT/'.tmp/s001-v4-correction';INPUT=HOME/'inputs';OUT=HOME/'signals';OUT.mkdir(parents=True,exist_ok=True)
m=import_module('research.S001.runtime_upgrade_v4.signal_math')
native=import_module('research.S001.runtime_upgrade_v4.strategy')
build=import_module('research.S001.runtime_upgrade_v4.build').build_candidate
names=('_factor_frame','_score','_regimes','_positions','_calculate_s001_scores','calculate_s001_history')
def functions(path):
    return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef)}
original=functions(ROOT/'strategies/S001/releases/v1/src/strategy_runtime/strategies/s001_common.py')
copied=functions(ROOT/'research/S001/runtime_upgrade_v4/signal_math.py')
assert all(original[n]==copied[n] for n in names)
frames={n:pd.read_parquet(INPUT/(n+'.parquet')) for n in ('daily','m30','weekly','raw_daily','calendar')}
for name,frame in frames.items(): frame['Date']=pd.to_datetime(frame.Date)
d,i,w,calendar=[frames[k] for k in ('daily','m30','weekly','calendar')]
assert d.Date.iloc[0]==pd.Timestamp('2020-11-16')
open_days=calendar.loc[calendar.IsOpen.eq(1),'Date']
week_ends=open_days.groupby(open_days.dt.to_period('W-SUN')).max()
assert calendar.Date.max() >= pd.Timestamp('2026-11-08')
def completed(day):
    expected=w.Date.dt.to_period('W-SUN').map(week_ends)
    return w.loc[(w.Date.eq(expected)) & (expected<=day)].copy()
complete=completed(d.Date.max())
assert pd.Timestamp('2026-09-30') in set(complete.Date)
assert pd.Timestamp('2026-11-05') not in set(complete.Date)
assert complete.Date.max()==pd.Timestamp('2026-10-30')

# Raw signal generation is causal; check exact prefix outputs before reusing it.
real_signals=m._signals
full={tag:real_signals(m._ohlcv(frame,'588080.SH'),freq,configs,init,tag)
      for tag,frame,freq,configs,init in (('30m',i,'30分钟',m._INTRADAY_CONFIG,500),('daily',d,'日线',m._DAILY_CONFIG,30))}
prefix_checks=[]
for day in pd.to_datetime(['2026-09-02','2026-09-30','2026-11-05']):
    for tag,frame,freq,configs,init in (('30m',i,'30分钟',m._INTRADAY_CONFIG,500),('daily',d,'日线',m._DAILY_CONFIG,30)):
        prefix=frame.loc[frame.Date.dt.normalize()<=day]
        actual=real_signals(m._ohlcv(prefix,'588080.SH'),freq,configs,init,tag)
        pd.testing.assert_frame_equal(actual,full[tag].loc[:prefix.Date.max()])
        prefix_checks.append({'signal_day':str(day.date()),'frequency':tag,'rows':len(actual),'status':'PASS'})
print('CAUSAL_FACTOR_CACHE_VERIFIED',flush=True)
week_cache={}
def signals(frame,freq,configs,init,tag):
    if tag in full:
        assert frame.dt.iloc[0]==m._ohlcv(frames['m30' if tag=='30m' else 'daily'],'588080.SH').dt.iloc[0]
        return full[tag].loc[:frame.dt.max()].copy()
    key=sha256(pd.util.hash_pandas_object(frame,index=True).values.tobytes()).hexdigest()
    if key not in week_cache: week_cache[key]=real_signals(frame,freq,configs,init,tag)
    return week_cache[key].copy()
m._signals=signals
candidates={v:build(v) for v in ('v1','v2')}
rules={v:json.loads(c.definition.parameters_json)['rule'] for v,c in candidates.items()}
for c in candidates.values():c.verify()
baseline={v:m.calculate_s001_history(i,d,complete,rule,'588080.SH') for v,rule in rules.items()}
starts={}
for v,history in baseline.items():
    transitions=history.loc[history.target_position.ne(history.target_position.shift())]
    starts[v]={'candidate':candidates[v].candidate_id,'content_sha256':candidates[v].content_identity.content_sha256,
        'september_2':history.loc['2026-09-02'].to_dict(),'september_3':history.loc['2026-09-03'].to_dict(),
        'august_transitions':[{'date':str(day.date()),**row.to_dict()} for day,row in transitions.loc['2026-08-01':'2026-09-03'].iterrows()]}
(OUT/'startup_targets.json').write_text(json.dumps(starts,ensure_ascii=False,indent=2),encoding='utf-8')
print('STARTUP',json.dumps(starts,ensure_ascii=False),flush=True)

rows=[];adapter=[]
for day in d.loc[d.Date.between('2026-09-02','2026-11-05'),'Date']:
    dp=d.loc[d.Date<=day];ip=i.loc[i.Date.dt.normalize()<=day];cw=completed(day)
    # Older days retain already-completed weekly bars; only the current unclosed
    # week gets a new tail bar stamped with this signal day.
    week_end=week_ends[day.to_period('W-SUN')]
    old_week=cw.copy()
    if day<week_end:
        tail=dp.loc[dp.Date.dt.to_period('W-SUN').eq(day.to_period('W-SUN'))]
        bar={'Date':day,'Open':tail.Open.iloc[0],'High':tail.High.max(),'Low':tail.Low.min(),
             'Close':tail.Close.iloc[-1],'Volume':tail.Volume.sum(),'Amount':tail.Amount.sum()}
        old_week=pd.concat([cw,pd.DataFrame([bar])],ignore_index=True)
    old_weekly_signal=signals(m._ohlcv(old_week,'588080.SH'),'周线',m._WEEKLY_CONFIG,10,'weekly')
    new_weekly_signal=signals(m._ohlcv(cw,'588080.SH'),'周线',m._WEEKLY_CONFIG,10,'weekly')
    next_day=open_days.loc[open_days>day].iloc[0]
    now=day.tz_localize('Asia/Shanghai')+pd.Timedelta(hours=20,minutes=30)
    for version,rule in rules.items():
        old=m.calculate_s001_history(ip,dp,old_week,rule,'588080.SH')
        new=m.calculate_s001_history(ip,dp,cw,rule,'588080.SH')
        pd.testing.assert_frame_equal(new,baseline[version].loc[:day])
        observations={name:SimpleNamespace(to_frame=lambda frame=frame:frame.copy()) for name,frame in
            (('adjusted_daily',dp),('adjusted_30m',ip),('adjusted_weekly',cw))}
        candidate=candidates[version]
        raw=frames['raw_daily'].loc[frames['raw_daily'].Date.eq(day)].iloc[0]
        ctx=SimpleNamespace(parameters={'rule':rule},observations=observations,
            history=SimpleNamespace(last=lambda:{'Date':now.replace(hour=15,minute=0),'Close':float(raw.Close)}),
            account=SimpleNamespace(quantity=0,sellable_quantity=0,available_cash=100000.),
            portfolio=SimpleNamespace(reference_price_scale=1.),budget=None,point=SimpleNamespace(decision_at=now),
            planning=SimpleNamespace(fee_rate=.0005))
        result=native.step(ctx,SimpleNamespace(account=candidate.definition.initial_account))
        candidate.definition.state_schema.validate_record(result.account,scope='account')
        # Native planner's signal target is carried in its explanation facts;
        # with sufficient empty-account cash the explicit order target is equal.
        facts={item.key:item.text for item in result.decision.explanation.basis}
        assert result.decision.target==float(new.iloc[-1].target_position)
        assert float(facts['factor_score'])==float(new.iloc[-1].factor_score)
        assert facts['regime']==str(new.iloc[-1].regime)
        assert int(facts['signal_target'])==int(new.iloc[-1].target_position)
        adapter.append({'version':version,'signal_day':str(day.date()),'native_target':result.decision.target,
            'native_score':float(facts['factor_score']),'native_regime':facts['regime'],'status':'PASS'})
        a,b=old.iloc[-1],new.iloc[-1]
        rows.append({'version':version,'signal_day':str(day.date()),'execution_day':str(next_day.date()),
            'settled_execution_window':bool(next_day<=pd.Timestamp('2026-11-05')),
            'current_week_complete':bool(day==week_end),'new_last_week_date':str(cw.Date.iloc[-1].date()),
            'old_last_week_date':str(old_week.Date.iloc[-1].date()),
            'old_weekly_factor':m._signal_score(old_weekly_signal.iloc[-1,0],Counter()),
            'new_weekly_factor':m._signal_score(new_weekly_signal.iloc[-1,0],Counter()),
            'old_score':float(a.factor_score),'new_score':float(b.factor_score),
            'score_difference':float(b.factor_score-a.factor_score),'old_regime':str(a.regime),'new_regime':str(b.regime),
            'old_target':float(a.target_position),'new_target':float(b.target_position),
            'target_changed':bool(a.target_position!=b.target_position)})
    print('DAY',day.date(),flush=True)
frame=pd.DataFrame(rows)
frame.to_csv(OUT/'daily_signal_comparison.csv',index=False,encoding='utf-8-sig')
(OUT/'daily_signal_comparison.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
summary={'limits':['This is a controlled reconstruction from the 2026-11-05 retained canonical dataset, not a replay of every archived daily provider snapshot.','Partial tail bars are aggregated from available adjusted daily OHLCV; publication revisions and vendor per-day snapshots require separate production-decision reconciliation.','Native step checks use an empty account with sufficient cash to isolate signal agreement; root owns full account execution and production comparison.'],
    'method':'Each signal date independently recomputes canonical history scores and _positions; no stitched daily-tail scores.',
    'math_source_sha256':{str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in (ROOT/'research/S001/runtime_upgrade_v4/signal_math.py',ROOT/'strategies/S001/releases/v1/src/strategy_runtime/strategies/s001_common.py')},
    'source_math_ast_equal':list(names),'prefix_factor_cache_checks':prefix_checks,'native_step_checks':adapter,
    'input_identity':json.loads((INPUT/'input_identity.json').read_text(encoding='utf-8')),
    'files_sha256':{p.name:sha256(p.read_bytes()).hexdigest() for p in INPUT.iterdir() if p.is_file()},
    'candidates':{v:{'candidate':c.candidate_id,'content_sha256':c.content_identity.content_sha256} for v,c in candidates.items()},
    'results':{}}
for v in rules:
    group=frame.loc[frame.version.eq(v)];settled=group.loc[group.settled_execution_window]
    for name,prefix in [('complete','new'),('partial','old')]:
        export=group.loc[:,['signal_day',prefix+'_score',prefix+'_regime',prefix+'_target']].copy()
        export.columns=['Date','factor_score','regime','target_position']
        export.to_csv(OUT/(v+'-'+name+'.csv'),index=False,encoding='utf-8')
    summary['results'][v]={'signals':len(group),'settled_signals':len(settled),
        'score_differences':int(group.score_difference.abs().gt(1e-14).sum()),
        'target_differences':int(group.target_changed.sum()),'settled_target_differences':int(settled.target_changed.sum()),
        'target_changes':group.loc[group.target_changed].to_dict('records'),
        'unsettled':group.loc[~group.settled_execution_window].to_dict('records')}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print('SUMMARY',json.dumps(summary['results'],ensure_ascii=False),flush=True)
