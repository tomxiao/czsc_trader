"""Native strategy decisions exercised against the real V4 planning contract."""
from types import SimpleNamespace
from dataclasses import replace
from plan_context import *
from strategy import step
from strategy_runtime.replay_contracts import AccountSnapshot,ReplayPoint,ExecutionPrecision
from strategy_runtime.account_replay import plan_account_decision
from strategy_runtime.account_strategy import SellRemainderPolicy

def main():
    params=read(OUT/'jobs.json')[0]['parameters']
    raw=pd.read_parquet(INPUT/'raw_complete.parquet');hfq=pd.read_parquet(INPUT/'hfq_complete.parquet');bars=pd.read_parquet(INPUT/'intraday_complete.parquet')
    frames=[]
    for frame,minute in [(raw,False),(hfq,False),(bars,True)]:
        frame=frame.copy();frame['Date']=pd.to_datetime(frame.Date).dt.tz_localize(ZONE)
        if not minute:frame['Date']+=pd.Timedelta(hours=15)
        frame=frame.loc[frame.Date<=at(date(2025,1,9),15)]
        frames.append(frame)
    class View:
        def __init__(self,frame):self.frame=frame
        def to_frame(self):return self.frame.copy()
    instrument=InstrumentId(MarketId.CN,AssetClass.ETF,'159326.SZ')
    spec=ResearchExecutionSpec(CnEquitySpec(),BarFrequency.DAILY,AccountPolicy('CNY',CashAvailabilityPolicy.IMMEDIATE_RESEARCH),100,.001,.01,0.)
    point=ReplayPoint(at(date(2025,1,9),15),at(date(2025,1,9),17),at(date(2025,1,10),9,30),at(date(2025,1,10),15),'2025-01-10',ExecutionPrecision.BAR_INTERVAL)
    state=SimpleNamespace(account=StateRecord((('active',True),('repair_target',100.),('invalidation_origin',-100.),('initialized',True))))
    def decide(cash,qty):
        account=AccountSnapshot(instrument,'CNY',point.decision_at,0,cash,cash,0.,qty,qty)
        ctx=SimpleNamespace(parameters=params,account=account,history=View(frames[0]),auxiliary_histories={'hfq':View(frames[1]),'intraday':View(frames[2])})
        return account,step(ctx,state).decision
    def plan(cash,qty,fee,reference=1.055):
        account,decision=decide(cash,qty)
        return plan_account_decision(decision,point,account,reference,spec,owner='S015-C9820',implementation='native-v4-check',fee_rate=fee,sell_remainder_policy=SellRemainderPolicy.FULL_LIQUIDATION)
    standard=plan(100000.,0,.001);pressure=plan(100000.,0,.002)
    assert standard.orders[0].quantity==93800 and pressure.orders[0].quantity==93700
    assert not plan(10.,0,.001).orders
    assert not plan(10000.,90000,.001).orders and not plan(10000.,90000,.002).orders
    retry=plan(100000.,0,.002,1.05)
    assert retry.orders and retry.orders[0].quantity!=pressure.orders[0].quantity
    assert standard.cycle_after is None and pressure.cycle_after is None
    save(OUT/'focused_checks.json',{'status':'PASS','standard_quantity':standard.orders[0].quantity,'stress_quantity':pressure.orders[0].quantity,'insufficient_lot':'WAIT_NO_ORDER','held_position':'NO_TOPUP','unfilled_retry':'REPLANS_WITH_CURRENT_REFERENCE','strategy_fee_input':False,'cycle_budget':False})
    print('FOCUSED_CHECKS_PASS')
if __name__=='__main__':main()
