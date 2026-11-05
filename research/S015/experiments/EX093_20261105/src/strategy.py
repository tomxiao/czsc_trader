"""C9700 financial rules on V4; signal-cycle state survives an unfilled order."""
import numpy as np
from strategy_runtime import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord


def signal_state(p, raw, hfq, bars, state):
    n=int(p['lookback'])
    raw_dates=raw.Date.dt.tz_convert('Asia/Shanghai').dt.date
    hfq_dates=hfq.Date.dt.tz_convert('Asia/Shanghai').dt.date
    day=raw_dates.iloc[-1]
    assert raw_dates.tolist()==hfq_dates.tolist()
    centers=[]
    for d,g in bars.groupby(bars.Date.dt.tz_convert('Asia/Shanghai').dt.date,sort=True):
        if d.isoformat()<'2025-01-02' or d not in set(raw_dates):
            continue
        if len(g)!=8:
            continue
        adjusted=float(hfq.loc[hfq_dates==d,'Close'].iloc[0])
        unadjusted=float(raw.loc[raw_dates==d,'Close'].iloc[0])
        values=np.log(g.Close.to_numpy(float))
        center=float(np.median(values) if p['center_kind']=='median' else np.mean(values))
        centers.append((d,center+float(np.log(adjusted/unadjusted))))
    ready=len(centers)>=n+1 and centers[-1][0]==day
    center=centers[-1][1] if centers else 0.
    gain=center-centers[-n-1][1] if ready else 0.
    price=float(np.log(hfq.Close.iloc[-1]))
    repair=float(np.expm1(center-price)) if ready else 0.
    active=state.get('active')
    target=state.get('repair_target')
    origin=state.get('invalidation_origin')
    enter=exit_=False
    permit=bool(ready and gain>0 and price<center and repair>=p['minimum_repair_space'])
    if active:
        if price>=target or center<=origin:
            active=False
            exit_=True
    elif permit:
        active=enter=True
        target,origin=center,center-gain
    return day,center,gain,price,repair,permit,active,target,origin,enter,exit_


def step(ctx, state):
    p=ctx.parameters
    n=int(p['lookback'])
    raw=ctx.history.to_frame()
    hfq=ctx.auxiliary_histories['hfq'].to_frame()
    bars=ctx.auxiliary_histories['intraday'].to_frame()
    memory=state.account
    if not memory.get('initialized'):
        # Warm only signal intentions, never cash, holdings or execution budgets.
        days=raw.Date.dt.tz_convert('Asia/Shanghai').dt.date
        for day in days.iloc[:-1]:
            if day.isoformat()<'2024-12-31':
                continue
            r=raw.loc[days<=day].tail(n+2)
            h=hfq.loc[hfq.Date.dt.tz_convert('Asia/Shanghai').dt.date<=day].tail(n+2)
            b=bars.loc[bars.Date.dt.tz_convert('Asia/Shanghai').dt.date<=day].tail((n+2)*8)
            values=signal_state(p,r,h,b,memory)
            memory=StateRecord((('active',values[6]),('repair_target',float(values[7])),('invalidation_origin',float(values[8])),('initialized',True)))
    raw,hfq,bars=raw.tail(n+2),hfq.tail(n+2),bars.tail((n+2)*8)
    day,center,gain,price,repair,permit,active,target,origin,enter,exit_=signal_state(p,raw,hfq,bars,memory)
    # Signal intent is independent of fees; V4 plans and charges execution.
    mode='full_available_cash' if ctx.account.quantity else 'target_equity_fraction'
    requested=(1. if ctx.account.quantity else float(p['allocation'])) if active else 0.
    decision=AccountDecision.from_facts(requested,'entry' if enter else 'exit' if exit_ else 'hold' if active else 'cash',
        facts={'signal_day':day.isoformat(),'center':center,'log_price':price,'center_gain':gain,'repair_space':repair,
               'permission':permit,'entry_signal':enter,'exit_signal':exit_,
               'repair_target':target,'invalidation_origin':origin},next_watch='next completed session',
        capital_mode=mode)
    return AccountStepResult(decision,StateRecord((('active',active),('repair_target',float(target)),('invalidation_origin',float(origin)),('initialized',True))),StateRecord())
