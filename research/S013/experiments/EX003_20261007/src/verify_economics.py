"""Focused independent research checks; no repository-wide regression."""
import importlib.util
import json
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from common import ROOT,BASE,cache_read,save, SRC
from economics import annual_stats,summarize

def main():
    spec=importlib.util.spec_from_file_location('s013_check',SRC/'strategy_runtime/strategies/range_reversion.py')
    author=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(author)
    sessions=pd.date_range('2020-01-01',periods=7)
    fixture=pd.DataFrame({'range_position':[.2,.3,.4,.8,.2,.4,.2],
        'acf1':[-.2,.2,.2,.2,.2,.2,.2],'close':[100,99,96,99,100,100,101],
        'momentum20':[0.]*7},index=sessions)
    author.components=lambda inputs,range_window:fixture
    expected={
        'range':(BASE,[1,1,1,0,1,1,1]),
        'time':(dict(BASE,max_hold=2),[1,1,0,0,1,1,0]),
        'loss':(dict(BASE,stop_loss=.03),[1,1,0,0,1,1,1]),
        'cooldown':(dict(BASE,stop_loss=.03,cooldown=2),[1,1,0,0,0,0,1]),
        'acf_confirmation':(dict(BASE,acf_min=0),[0,1,1,0,1,1,1]),
    }
    for parameters,target in expected.values():
        a=author.RangeReversion.from_parameters(ParameterSet(parameters))
        actual=a.calculate_history({'daily':None},sessions)
        assert actual.target_position.tolist()==list(map(float,target))
    fixture.loc[sessions[1],'close']=103
    fixture.loc[sessions[2],'close']=99
    trailing=author.RangeReversion.from_parameters(ParameterSet(dict(BASE,trailing_stop=.03)))
    assert trailing.calculate_history({'daily':None},sessions).target_position.tolist()==[1.,1.,0.,0.,1.,1.,1.]
    bound,result=cache_read(ROOT/'.tmp/s013-stage3/precheck.pkl.gz')
    run=result.runs[0]
    own=run.execution.account_daily.copy()
    values=own.equity.to_numpy(float)
    dates=pd.DatetimeIndex(pd.to_datetime(own.date))
    actual=annual_stats(own)
    for year,row in actual.items():
        locations=np.flatnonzero(dates.year==int(year))
        opening=1_000_000 if locations[0]==0 else values[locations[0]-1]
        peak=opening
        deepest=0.
        for loc in locations:
            peak=max(peak,values[loc])
            deepest=min(deepest,values[loc]/peak-1)
        assert abs(-deepest-row['max_drawdown_magnitude'])<1e-12
    # Designed cross-year boundary: first-year loss and inherited year-end capital.
    artificial=own.copy()
    artificial['equity']=1_000_000.
    artificial.loc[dates.year==2020,'equity']=900_000.
    artificial.loc[dates.year==2021,'equity']=810_000.
    synthetic=annual_stats(artificial)
    assert np.isclose(synthetic['2020']['max_drawdown_magnitude'],.10)
    assert np.isclose(synthetic['2021']['max_drawdown_magnitude'],.10)
    assert synthetic['2021']['opening_equity']==900_000
    assert synthetic['2022']['max_drawdown_magnitude']==0.
    account=run.execution.account_daily
    fills=run.execution.fills
    cash=1_000_000.
    quantity=0
    for row in account.itertuples():
        today=fills.loc[pd.to_datetime(fills.fill_time).dt.normalize()==pd.Timestamp(row.date)]
        for fill in today.itertuples():
            assert int(fill.quantity)%100==0
            assert abs(fill.fees-round(fill.price*fill.quantity*.001,2))<=.01000001
            change=fill.quantity if fill.side=='BUY' else -fill.quantity
            quantity+=int(change)
            cash-=change*fill.price+fill.fees
        assert quantity==row.quantity
        assert abs(cash-row.cash)<.02
        assert abs(cash+quantity*row.close-row.equity)<.02
    save('economic_verification.json',{'status':'PASS','state_scenarios':list(expected)+['trailing'],
        'annual_continuous_account_checks':len(actual),'synthetic_year_anchor_checks':3,
        'daily_cash_position_equity_checks':len(account),'fee_lot_checks':len(fills),
        'full_gate_summary':summarize(result)})
    print(json.dumps({'verification':'PASS','state_scenarios':6,'account_checks':len(account),'fill_checks':len(fills)}),flush=True)

if __name__=='__main__':
    main()
