"""C9700 financial rules on V4; signal-cycle state survives an unfilled order."""
from decimal import Decimal, ROUND_FLOOR
from dataclasses import replace
import numpy as np
from strategy_runtime import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord
from strategy_runtime.replay_contracts import CycleBudget
from strategy_runtime.entry_cycle import EntryCyclePhase


def step(ctx, state):
    p=ctx.parameters
    n=int(p['lookback'])
    raw=ctx.history.to_frame(tail=n+2)
    hfq=ctx.auxiliary_histories['hfq'].to_frame(tail=n+2)
    bars=ctx.auxiliary_histories['intraday'].to_frame(tail=(n+2)*8)
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
    active=state.account.get('active')
    target=state.account.get('repair_target')
    origin=state.account.get('invalidation_origin')
    enter=exit_=False
    permit=bool(ready and gain>0 and price<center and repair>=p['minimum_repair_space'])
    if active:
        if price>=target or center<=origin:
            active=False
            exit_=True
    elif permit:
        active=enter=True
        target,origin=center,center-gain
    before=ctx.budget
    after=before
    if enter:
        cash=Decimal(str(ctx.account.available_cash))*Decimal(str(p['allocation']))
        limit=(Decimal(str(raw.Close.iloc[-1]))*Decimal('1.01')/Decimal('.001')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.001')
        quantity=min(1000000,int(cash/(limit*Decimal('1.001'))/100)*100)
        if quantity<=0:
            raise ValueError('migration sample cannot form a minimum lot')
        after=CycleBudget('signal-'+day.isoformat(),quantity,Decimal(str(p['allocation'])),cash,Decimal(0),EntryCyclePhase.ACTIVE)
    elif exit_ and before is not None:
        after=replace(before,phase=EntryCyclePhase.EXITING)
    elif active and before is not None and ctx.account.quantity:
        # The original strategy holds its filled position; higher execution
        # fees must not create a later top-up towards an unfilled budget lot.
        after=replace(before,target_quantity=ctx.account.quantity)
    mode='signal_cash_fraction' if after is not None else 'full_available_cash'
    decision=AccountDecision.from_facts(float(active),'entry' if enter else 'exit' if exit_ else 'hold' if active else 'cash',
        facts={'signal_day':day.isoformat(),'center':center,'log_price':price,'center_gain':gain,'repair_space':repair,
               'permission':permit,'entry_signal':enter,'exit_signal':exit_,
               'repair_target':target,'invalidation_origin':origin},next_watch='next completed session',
        capital_mode=mode,cycle_before=before,cycle_after=after)
    return AccountStepResult(decision,StateRecord((('active',active),('repair_target',float(target)),('invalidation_origin',float(origin)))),StateRecord())
