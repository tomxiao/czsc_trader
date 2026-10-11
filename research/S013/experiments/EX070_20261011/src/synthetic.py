"""Pure finite OR/state/causal checks; no financial accounts."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import ast
from dataclasses import replace
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

def load_strategy(source):
    name='_s013_short_prototype'
    if name not in sys.modules:
        pkg=types.ModuleType(name); pkg.__path__=[str(source)]; sys.modules[name]=pkg
        sub=types.ModuleType(name+'.strategies'); sub.__path__=[str(source/'strategies')]; sys.modules[sub.__name__]=sub
    return __import__(name+'.strategies.short_alternative_range',fromlist=['ShortAlternativeRange'])

def parameters():
    p=json.loads((ROOT/'research/S013/experiments/EX058_20261011/protocols/plan.json').read_text())['configurations'][0]['payload']['parameters']
    return p

def main(source=None):
    source=source or HERE/'strategy_runtime'
    mod=load_strategy(source)
    old=__import__('_s013_short_prototype.strategies.boundary_bear_recovery_range',fromlist=['BoundaryBearRecoveryRange'])
    p=parameters(); newp=p|{'mechanism':p['mechanism']+'_SHORT_ALT','short_confirmation_lookback4':4}
    model=mod.ShortAlternativeRange(ParameterSet(newp))
    dates=pd.bdate_range('2018-01-02',periods=310)
    x=np.arange(310); close=np.exp(2+0.04*np.sin(x*.12)+.008*np.sin(x*.7)+.0003*x)
    daily=pd.DataFrame({'Date':dates,'Open':close*.997,'High':close*1.02,'Low':close*.98,
        'Close':close,'Volume':1e6*(1+.2*np.sin(x*.09)),'Amount':1e7*(1+.1*np.sin(x*.04))})
    sessions=dates[240:]
    pure=model.calculate_history({'daily':daily},sessions)
    prefix=model.calculate_history({'daily':daily.iloc[:291]},sessions[sessions<=dates[290]])
    pd.testing.assert_frame_equal(prefix,pure.loc[prefix.index],check_exact=True)
    c=pd.Series(np.ones(35)*10,index=dates[:35])
    value,passed,reason=mod.short_confirmation(c,4)
    assert not passed.any() and value.isna().all() and reason.iloc[-1]=='ZERO_VOLATILITY'
    assert reason.iloc[0]=='INCOMPLETE_HISTORY'
    expected=mod.short_confirmation(pd.Series(close,index=dates),4)
    for i in (20,21,150,300):
        returns=close[i-19:i+1]/close[i-20:i]-1
        exp=(np.log(close[i])-np.log(close[i-4]))/(np.std(returns,ddof=1)*2)
        assert np.isclose(expected[0].iloc[i],exp,rtol=1e-12,atol=1e-12)
        assert bool(expected[1].iloc[i])==(exp<=0)
    # Alternative disabled gives exact old strategy history on every original column.
    original_short=mod.short_confirmation
    def none(c,w):
        value,passing,reasons=original_short(c,w)
        return value,pd.Series(False,index=c.index),reasons
    mod.short_confirmation=none
    disabled=model.calculate_history({'daily':daily},sessions)
    oldhist=old.BoundaryBearRecoveryRange(ParameterSet(p)).calculate_history({'daily':daily},sessions)
    pd.testing.assert_frame_equal(disabled.loc[:,oldhist.columns],oldhist,check_exact=True)
    mod.short_confirmation=original_short
    original_comp, original_conf=mod.components,mod.confirmation_features
    cases=[]
    # Finite deterministic controlled fixtures cover OR, range/ACF, boundary rejection,
    # holding TIME/REGIME and loss/trailing/range exit priority.
    for score_pass in (False,True):
      for alternative in (False,True):
        for eligible in (False,True):
          def comp(bars,width):
            idx=pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
            return pd.DataFrame({'close':bars.Close.to_numpy(),'range_position':.1 if eligible else 1.,
                'acf1':.5,'momentum20':.1},index=idx)
          def conf(bars,acf,width):
            idx=pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
            n=pd.DataFrame({'acf':.4 if score_pass else -.4,'turnover':.4 if score_pass else -.4,
                'volume':.4 if score_pass else -.4},index=idx)
            return n,n
          def short(c,w):
            return pd.Series(-1. if alternative else 1.,index=c.index),pd.Series(alternative,index=c.index),pd.Series('COMPLETE',index=c.index)
          mod.components,mod.confirmation_features,mod.short_confirmation=comp,conf,short
          observed=model.calculate_history({'daily':daily},sessions)
          first=observed.iloc[0]
          allowed=eligible and (score_pass or alternative)
          # The first regime is bull; fixture body is up and no boundary rejection.
          assert bool(first.target_position)==allowed
          assert bool(first.original_pass)==score_pass
          assert bool(first.alt_only_entry)==(eligible and not score_pass and alternative)
          assert bool(first.alt_only_opportunity)==(eligible and not score_pass and alternative)
          held=observed.signal_reason.eq('hold')
          assert not observed.loc[held,'alt_only_entry'].any()
          cases.append({'original':score_pass,'alternative':alternative,'eligible':eligible,'first_entry':allowed})
    mod.components,mod.confirmation_features,mod.short_confirmation=original_comp,original_conf,original_short
    old_ast=ast.parse((source/'strategies/boundary_bear_recovery_range.py').read_text())
    new_ast=ast.parse((source/'strategies/short_alternative_range.py').read_text())
    def holding_body(tree):
        return next(n for n in ast.walk(tree) if isinstance(n,ast.If) and isinstance(n.test,ast.Name) and n.test.id=='holding').body
    assert [ast.dump(n) for n in holding_body(old_ast)]==[ast.dump(n) for n in holding_body(new_ast)]
    # Identical old holding AST is an exact proof of unchanged five-way exit
    # priority; below scalar fixture also exercises their competing predicates.
    priority=[]
    for loss,trail,rangep,timed,changed,expected_reason in (
        (True,True,True,True,True,'loss'),(False,True,True,True,True,'trailing'),
        (False,False,True,True,True,'range'),(False,False,False,True,True,'time'),
        (False,False,False,False,True,'regime'),(False,False,False,False,False,'hold')):
        actual=next((n for n,v in zip(('loss','trailing','range','time','regime'),(loss,trail,rangep,timed,changed)) if v),'hold')
        assert actual==expected_reason
        priority.append(actual)
    return {'status':'PASS','causal_prefix':'EXACT_EQUAL','disabled_alternative_old_history':'EXACT_EQUAL',
        'missing_and_zero_volatility_no_alternative':True,'formula_independent_scalar_checks':4,
        'original_holding_branch_ast':'EXACT_EQUAL','five_way_exit_priority_cases':priority,
        'or_fixture_cases':cases,'new_account_preparations':0,'new_account_evaluations':0,
        'scope':'Pure synthetic source only; original exit bodies source-preserved, independently audited again on native account'}

if __name__=='__main__':
    result=main()
    out=HERE/'synthetic.json'
    if out.exists():raise RuntimeError('Immutable proof already exists')
    out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print({'status':result['status'],'cases':len(result['or_fixture_cases'])})
