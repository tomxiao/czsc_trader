"""Focused synthetic verification before historical result calculation."""
from types import SimpleNamespace
import pandas as pd
from trading_execution_engine import MarketExecutionRules,SessionPriceLimits
from study import WORK,save,digest,sources,buy_limit,fill,label
from stats_checks import run_checks


def fixture():
    days=list(pd.date_range('2025-01-02',periods=25,freq='B'))
    daily=pd.DataFrame({'open':10.,'high':10.5,'low':9.5,'close':10.},index=pd.DatetimeIndex(days))
    intra=pd.DataFrame({'low':9.5,'high':10.5},index=pd.DatetimeIndex([d+pd.Timedelta(hours=10) for d in days]))
    rules=MarketExecutionRules('159326.SZ',tuple(SessionPriceLimits(d.date(),9,11,.001) for d in days))
    settings={'capital':{'fee_rate':.001,'mode':'signal_cash_fraction','target_scope':'entry_cycle'},
        'entry':{'limit_parameter':.01,'order_type':'LIMIT'},'exit':{'limit_ratio':.1,'order_type':'MARKET'},
        'instrument':{'lot_size':100,'maximum_order_quantity':1000000,'price_limit_ratio':.1,'price_tick':.001}}
    return days,daily,intra,rules,SimpleNamespace(policy_type='FROZEN_RULE',settings=settings)


def main():
    checks=run_checks()
    days,daily,intra,rules,policy=fixture()
    assert buy_limit(days[0],daily,daily,daily,policy)==10.1
    raw=daily.copy()
    raw['close']=1.0019
    adjusted=daily.copy()
    adjusted['close']=2.0038
    assert buy_limit(days[0],raw,adjusted,adjusted,policy)==2.022
    checks.append('public_limit_floor_before_signal_day_price_scaling')
    day=days[1]
    daily.loc[day,['open','low']]=[10.2,10.1]
    # DailyQuote reaches equality even when synthetic intraday lows do not cross it.
    equality=fill('BUY',day,daily,intra,rules,10.1)
    assert equality.filled and equality.price==10.1 and equality.time_precision.value=='SESSION'
    daily.loc[day,'low']=10.101
    assert not fill('BUY',day,daily,intra,rules,10.1).filled
    daily.loc[day,['open','low','high']]=[9.,9.,9.]
    assert not fill('SELL',day,daily,intra,rules).filled
    daily.loc[day,'high']=9.001
    assert fill('SELL',day,daily,intra,rules).price==9.001
    checks.append('daily_equality_no_touch_and_down_limit_open_plus_tick')
    days,daily,intra,rules,policy=fixture()
    value=label(0,1,days,daily,intra,rules,10.1)
    assert value['entry_at']==str(days[1].date()) and value['exit_at']==str(days[2].date())
    assert abs(value['price_net_return']-(.999/1.001-1))<1e-14
    assert label(5,20,days,daily,intra,rules,10.1)['status']=='RIGHT_CENSORED_EXIT'
    assert label(0,1,days,daily,intra,rules,9.1)['status']=='NO_ENTRY'
    altered=daily.copy()
    altered.loc[days[4]:,'close']=10.4
    assert label(0,1,days,altered,intra,rules,10.1)==value
    checks.append('T_plus_one_entry_fixed_horizon_fees_censor_and_future_path_independence')
    save(WORK/'others/checks.json',{'status':'PASS','checks':checks,
        'sources':{p.name:digest(p) for _,p in sources()},'scope':'Synthetic only; no historical opportunity returns.'})
    print('FOCUSED_CHECKS_PASS',len(checks),flush=True)


if __name__=='__main__':
    main()
