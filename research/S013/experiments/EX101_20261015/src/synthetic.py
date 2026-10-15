"""Boundary, responsibility and causality tests on generated data only."""
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import sys
import types
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from trading_execution_engine import OrderSpec, resolve_fill
from common import SOURCE, PROTOCOLS, RUNS, read, write

def module():
    package=types.ModuleType('_s013_ex101_synthetic'); package.__path__=[str(SOURCE/'strategies')]
    sys.modules[package.__name__]=package
    spec=importlib.util.spec_from_file_location(package.__name__+'.trend_participation',SOURCE/'strategies/trend_participation.py')
    value=importlib.util.module_from_spec(spec); sys.modules[spec.name]=value; spec.loader.exec_module(value)
    return value

def main():
    m=module(); configs=read(PROTOCOLS/'configurations.json')['configurations']
    rng=np.random.default_rng(13); dates=pd.bdate_range('2018-01-01',periods=450)
    price=6*np.exp(np.cumsum(rng.normal(.0004,.02,len(dates))))
    bars=pd.DataFrame(dict(Date=dates,Open=price,High=price*1.01,Low=price*.99,Close=price,
        Volume=np.exp(rng.normal(15,.2,len(dates))),Amount=np.exp(rng.normal(18,.2,len(dates)))))
    sessions=dates[230:]; checks=[]
    for config in configs:
        implementation=m.TrendParticipation(ParameterSet(config['payload']['parameters']))
        result=implementation.calculate_history({'daily':bars},sessions)
        prefix=implementation.calculate_history({'daily':bars.loc[bars.Date<=sessions[80]]},sessions[:81])
        pd.testing.assert_frame_equal(result.iloc[:81],prefix,check_exact=True)
        future=bars.copy(); future.loc[future.Date>sessions[80],['Close','Volume','Amount']]*=1.2
        changed=implementation.calculate_history({'daily':future},sessions)
        pd.testing.assert_frame_equal(result.iloc[:81],changed.iloc[:81],check_exact=True)
        assert result.prior_owner.iloc[0]=='EMPTY'
        checks.append(config['mode']+': exact prefix/future invariance and EMPTY initialization')
    p=deepcopy(configs[1]['payload']['parameters']); p['trend']['mode']='OFF'
    off=m.TrendParticipation(ParameterSet(p)); original=m.ReentryConfirmedRange(ParameterSet(p['base']))
    pd.testing.assert_frame_equal(off.calculate_history({'daily':bars},sessions),original.calculate_history({'daily':bars},sessions),check_exact=True)
    assert off.definition.execution==original.definition.execution
    checks.append('OFF all original output fields and execution policy exactly equal')
    # A deterministic shadow sequence isolates arbitration from price features.
    idx=pd.date_range('2020-01-01',periods=8)
    base=pd.DataFrame(dict(target_position=[1.,1.,0.,1.,1.,1.,0.,0.],
        signal_reason=['entry','hold','time','entry','hold','hold','time','flat']),index=idx)
    enter=pd.Series([True,True,True,True,False,True,False,True],index=idx)
    leave=pd.Series([False,True,False,False,False,True,False,False],index=idx)
    combo=m.arbitrate(base,enter,leave,'COMBINED')
    assert combo.signal_owner.tolist()==['BASE','BASE','EMPTY','BASE','BASE','BASE','EMPTY','TREND']
    assert combo.target_position.iloc[2]==0 and combo.target_position.iloc[6]==0
    no_trend=m.arbitrate(base,pd.Series(False,index=idx),leave,'COMBINED')
    pd.testing.assert_series_equal(no_trend.target_position,base.target_position)
    blocked_base=pd.DataFrame(dict(target_position=[0.,1.,1.,1.,0.,0.],
        signal_reason=['flat','entry','hold','hold','time','flat']),index=idx[:6])
    locked=m.arbitrate(blocked_base,pd.Series([True,False,False,False,False,True],index=idx[:6]),
        pd.Series([False,True,False,False,False,False],index=idx[:6]),'COMBINED')
    assert locked.signal_owner.tolist()==['TREND','EMPTY','EMPTY','EMPTY','EMPTY','TREND']
    assert bool(locked.blocked_base_entry.iloc[1])
    checks.extend(['dual entry BASE priority and no owner stealing',
        'exit date zero without immediate reentry', 'blocked BASE entry never queued',
        'trend never triggers: combined targets equal BASE'])
    # Strict threshold and complete warmup tests through the actual implementation.
    p=deepcopy(configs[0]['payload']['parameters'])
    def prices(values):
        dates_=pd.bdate_range('2019-01-01',periods=len(values))
        return pd.DataFrame(dict(Date=dates_,Close=values)),dates_
    impl=m.TrendParticipation(ParameterSet(p))
    monotonic,axis=prices(list(range(1,42)))
    h=impl.calculate_history({'daily':monotonic},axis[20:])
    assert h.trend_entry_condition.all() and h.signal_owner.eq('TREND').all()
    assert h.signal_reason.eq('trend_entry').sum()==1 and h.target_position.iloc[-1]==1.
    equal,axis=prices([10.]*21+[11.]+[11.]*10+[10.])
    h=impl.calculate_history({'daily':equal},axis[20:])
    assert not h.trend_entry_condition.iloc[0] and h.trend_entry_condition.iloc[1]
    assert not h.trend_exit_condition.iloc[-2] and h.trend_exit_condition.iloc[-1]
    assert h.target_position.iloc[-1]==0.
    checks.extend(['strict prior 20 high/10 low; equality does not trigger',
        'continuous new highs require no false-to-true edge',
        'prewarm prices do not create prior holding; no forced tail liquidation'])
    for bad in ('short','nan','duplicate'):
        badbars=monotonic.copy(); selected=axis[:1] if bad=='short' else pd.DatetimeIndex(monotonic.Date.iloc[20:])
        if bad=='nan': badbars.loc[0,'Close']=np.nan
        if bad=='duplicate': badbars.loc[1,'Date']=badbars.Date.iloc[0]
        try: impl.calculate_history({'daily':badbars},selected)
        except ValueError: pass
        else: raise AssertionError('invalid '+bad+' history accepted')
    for key,value in [('entry_sessions',True),('entry_sessions',9),('exit_sessions',31),('exit_sessions',20),('mode','unknown')]:
        bad=deepcopy(p); bad['trend'][key]=value
        try: m.TrendParticipation(ParameterSet(bad))
        except (ValueError,TypeError): pass
        else: raise AssertionError('invalid parameter accepted')
    checks.append('insufficient/nonfinite/duplicate history and illegal parameters rejected')
    time=datetime(2020,1,2,9,30,tzinfo=timezone.utc)
    order=OrderSpec('BUY','LIMIT',100,10.1)
    rejected=resolve_fill(order,session_open=10.5,session_time=time,intraday_touches=[(time,10.2)])
    assert not rejected.filled and rejected.price is None
    repeated=resolve_fill(OrderSpec('BUY','LIMIT',100,10.6),session_open=10.4,session_time=time,intraday_touches=[])
    assert repeated.filled and repeated.price==10.4
    sold=resolve_fill(OrderSpec('SELL','MARKET',100),session_open=9.,session_time=time,intraday_touches=[])
    assert sold.filled and sold.price==9.
    checks.append('public TXE unfilled DAY buy, later newly priced order, MARKET exit at open')
    write(RUNS/'synthetic_checks.json',dict(status='PASS',checks=checks,generated_data_only=True,
        full_account_evaluations=0,provider_calls=0))
    print({'synthetic':'PASS','checks':len(checks)})
if __name__=='__main__': main()
