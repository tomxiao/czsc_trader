"""V4 capability acceptance: identical accounts, explicitly different market rules."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dataflows import BarFrequency, InstrumentId, MarketId, AssetClass
from strategy_runtime import AccountPolicy, CashAvailabilityPolicy, ResearchExecutionSpec, UsEquitySpec, CnEquitySpec
from strategy_runtime.contracts import OrderSide, OrderType
from strategy_runtime.replay_contracts import (AccountExecutionPlan, ReplayPoint, ExecutionPrecision,
                                               ReplayOrder, ReplayLeg, CycleBudget)
from strategy_runtime.entry_cycle import EntryCyclePhase
from trading_execution_engine import PortfolioHistoricalExecutor


def setup(market, *, cash_policy=CashAvailabilityPolicy.IMMEDIATE_RESEARCH, actions=None):
    zone = ZoneInfo('Asia/Shanghai' if market is MarketId.CN else 'America/New_York')
    stamp = datetime(2026, 10, 8, 9, 30, tzinfo=zone)
    spec = ResearchExecutionSpec(CnEquitySpec() if market is MarketId.CN else UsEquitySpec(),
        BarFrequency.M30, AccountPolicy('CNY' if market is MarketId.CN else 'USD', cash_policy),
        100, .01, .01, 0.)
    if actions is None:
        actions = pd.DataFrame([dict(Date=stamp, AvailableDate=stamp,EventId='none',Kind='NONE',Ratio=1.,CashPerShare=0.,PayAt=None)])
    executor = PortfolioHistoricalExecutor(specification=spec, initial_cash=10000., fee_rate=.001,
        actions=actions, price_basis='RAW')
    instrument = InstrumentId(market, AssetClass.STOCK, '600722.SH' if market is MarketId.CN else 'LITE')
    return executor, stamp, instrument


def facts(stamp, *, unlock=None, close=10., volume=10000.):
    end = stamp + timedelta(minutes=30)
    bar = dict(BarStart=stamp,Date=end,AvailableDate=end,Open=10.,High=max(10.2,close),Low=min(9.8,close),
        Close=close,Volume=volume,Amount=100000.)
    constraints = dict(Date=stamp,AvailableDate=stamp,QuantityStep=100,PriceTick=.01,Tradable=True,
        SettlementAt=end+timedelta(days=1),BuySellableAt=stamp if unlock is None else unlock,
        SellRemainderPolicy='STRICT_STEP',PriceLimitPolicy='EXPLICIT_UNBOUNDED',PriceLimitLower=None,PriceLimitUpper=None)
    return bar, constraints


def plan(executor, stamp, orders=(), *, legs=(), capital='target_equity_fraction', before=None, after=None):
    point = ReplayPoint(stamp-timedelta(minutes=30),stamp,stamp,stamp+timedelta(minutes=30),
        stamp.date().isoformat(),ExecutionPrecision.BAR_INTERVAL)
    entries = tuple(leg.order for leg in legs) if legs else orders
    target = executor.quantity+sum(o.quantity if o.side is OrderSide.BUY else -o.quantity for o in entries)
    return AccountExecutionPlan(f'{executor.revision+1:064x}', 'fixture',point,executor.revision,target,
        orders,legs,capital,before,after,evidence={'sizing':'EXPLICIT_ORDERS',
            'target':min(1.,target*10/10000),'reference_price':10.,
            'specification_hash':executor.spec.fingerprint,'fee_rate':executor.fee_rate})


def order(side, quantity, price=None):
    return ReplayOrder(side,quantity,OrderType.MARKET if price is None else OrderType.LIMIT,price)


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_scaling_and_repeated_execution_close_one_real_position(market, monkeypatch):
    import trading_execution_engine.portfolio as implementation
    original=implementation._serial
    serialized=[]
    def counted(value):
        serialized.append(value)
        return original(value)
    monkeypatch.setattr(implementation,'_serial',counted)
    executor, stamp, instrument = setup(market)
    for index, orders in enumerate(((order(OrderSide.BUY,100,10.1),),
            (order(OrderSide.BUY,100,10.1),order(OrderSide.BUY,100,10.1)),
            (order(OrderSide.SELL,100),),(order(OrderSide.SELL,200),))):
        at=stamp+timedelta(minutes=30*index)
        proposal=plan(executor,at,orders)
        bar, dated=facts(at)
        before=executor.account_snapshot(proposal.point,instrument)
        assert before.quantity==executor.quantity
        result=executor.execute_account_plan(proposal,bar,constraint=dated)
        assert executor.execute_account_plan(proposal,bar,constraint=dated)==result
    result=executor.finish()
    assert len(result.fills)==5 and len(result.trades)==1
    assert result.trades.net_pnl.iloc[0]==pytest.approx(-6.)
    assert executor.position_feedback.latest_closed.buy_fills==3
    assert executor.position_feedback.latest_closed.sell_fills==2
    assert len(serialized)==8 and all(type(value) is AccountExecutionPlan for value in serialized)


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_dated_sellability_not_market_name_controls_reentry(market):
    executor,stamp,_=setup(market)
    bar,dated=facts(stamp,unlock=stamp+timedelta(days=1))
    executor.execute_account_plan(plan(executor,stamp,(order(OrderSide.BUY,100,10.1),)),bar,constraint=dated)
    at=stamp+timedelta(minutes=30)
    bar,dated=facts(at)
    executor.execute_account_plan(plan(executor,at,(order(OrderSide.SELL,100),)),bar,constraint=dated)
    assert executor.quantity==100
    assert executor.rows['orders'][-1]['reason']=='INSUFFICIENT_SELLABLE_QUANTITY'
    at=stamp+timedelta(days=1)
    bar,dated=facts(at)
    executor.execute_account_plan(plan(executor,at,(order(OrderSide.SELL,100),)),bar,constraint=dated)
    assert executor.quantity==0


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_cumulative_volume_and_explicit_limits_reject_unfillable_orders(market):
    executor,stamp,_=setup(market)
    bar,dated=facts(stamp,volume=150.)
    dated.update(PriceLimitPolicy='DATED_LIMITS',PriceLimitLower=9.,PriceLimitUpper=11.)
    executor.execute_account_plan(plan(executor,stamp,(order(OrderSide.BUY,100,10.1),order(OrderSide.BUY,100,10.1))),bar,constraint=dated)
    assert executor.quantity==100
    assert executor.rows['orders'][-1]['reason']=='INSUFFICIENT_BAR_VOLUME'
    at=stamp+timedelta(minutes=30)
    bar,dated=facts(at)
    dated.update(PriceLimitPolicy='DATED_LIMITS',PriceLimitLower=9.,PriceLimitUpper=11.)
    executor.execute_account_plan(plan(executor,at,(order(OrderSide.BUY,100,12.),)),bar,constraint=dated)
    assert executor.rows['orders'][-1]['reason']=='ORDER_PRICE_OUTSIDE_LIMITS'


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_dependency_legs_use_real_open_and_close_and_no_price_path_invention(market):
    executor,stamp,_=setup(market)
    end=stamp+timedelta(minutes=30)
    legs=(ReplayLeg(0,order(OrderSide.BUY,100),'OPEN',stamp,end),
          ReplayLeg(1,order(OrderSide.SELL,100),'CLOSE',stamp,end,0,'FILLED'))
    bar,dated=facts(stamp,close=11.)
    executor.execute_account_plan(plan(executor,stamp,legs=legs),bar,constraint=dated)
    assert executor.quantity==0
    assert [row['price'] for row in executor.rows['fills']]==[10.,11.]
    assert [row['executed_at'] for row in executor.rows['fills']]==[stamp,end]
    assert executor.rows['trades'][0]['net_pnl']==pytest.approx(97.9)
    at=end
    leg=ReplayLeg(0,order(OrderSide.BUY,100),'11:30_CLOSE',at,at+timedelta(minutes=30))
    bar,dated=facts(at)
    with pytest.raises(ValueError,match='CHECKPOINT_DATA_UNAVAILABLE'):
        executor.execute_account_plan(plan(executor,at,legs=(leg,)),bar,constraint=dated)
    assert executor.revision==1 and len(executor.rows['fills'])==2


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_split_dividend_payment_and_sale_settlement_account_once(market):
    executor,stamp,instrument=setup(market,cash_policy=CashAvailabilityPolicy.SETTLED_ONLY)
    split=stamp+timedelta(minutes=30)
    pay=stamp+timedelta(minutes=90)
    actions=pd.DataFrame([dict(Date=split,AvailableDate=split,EventId='split',Kind='SPLIT',Ratio=2.,CashPerShare=0.,PayAt=None),
        dict(Date=split,AvailableDate=split,EventId='dividend',Kind='CASH_DIVIDEND',Ratio=1.,CashPerShare=.1,PayAt=pay)])
    executor,_,_=setup(market,cash_policy=CashAvailabilityPolicy.SETTLED_ONLY,actions=actions)
    bar,dated=facts(stamp)
    executor.execute_account_plan(plan(executor,stamp,(order(OrderSide.BUY,100,10.1),)),bar,constraint=dated)
    point=ReplayPoint(stamp,split,split,split+timedelta(minutes=30),split.date().isoformat(),ExecutionPrecision.BAR_INTERVAL)
    snapshot=executor.account_snapshot(point,instrument)
    assert snapshot.quantity==200 and snapshot.receivable==20.
    assert executor.account_snapshot(point,instrument)==snapshot
    bar,dated=facts(split)
    for key in ('Open','High','Low','Close'):
        bar[key]/=2
    executor.execute_account_plan(plan(executor,split,(order(OrderSide.SELL,200),)),bar,constraint=dated)
    assert executor.cash==pytest.approx(8999.) and executor.receivable==pytest.approx(1019.)
    at=dated['SettlementAt']
    bar,dated=facts(at)
    executor.execute_account_plan(plan(executor,at),bar,constraint=dated)
    assert executor.cash==pytest.approx(10018.) and executor.receivable==pytest.approx(0.)
    assert [row['kind'] for row in executor.rows['actions']].count('DIVIDEND_PAYMENT')==1
    assert executor.rows['trades'][0]['net_pnl']==pytest.approx(18.)


def test_later_leg_failure_keeps_confirmed_prefix_and_blocks_successful_finalization():
    executor,stamp,_=setup(MarketId.US,cash_policy=CashAvailabilityPolicy.SETTLED_ONLY)
    end=stamp+timedelta(minutes=30)
    legs=(ReplayLeg(0,order(OrderSide.BUY,100),'OPEN',stamp,end),
          ReplayLeg(1,order(OrderSide.SELL,100),'CLOSE',stamp,end,0,'FILLED'))
    bar,dated=facts(stamp)
    dated['SettlementAt']=None
    with pytest.raises(ValueError,match='settlement'):
        executor.execute_account_plan(plan(executor,stamp,legs=legs),bar,constraint=dated)
    assert executor.quantity==100 and len(executor.rows['fills'])==1
    with pytest.raises(ValueError,match='failed account'):
        executor.finish()


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_cycle_budget_is_locked_across_unfilled_retry_and_additional_entries(market):
    executor,stamp,_=setup(market)
    budget=CycleBudget('cycle',300,Decimal('.3'),Decimal('3000'),Decimal('0'),EntryCyclePhase.ACTIVE)
    proposal=plan(executor,stamp,(order(OrderSide.BUY,100,9.),),capital='signal_cash_fraction',after=budget)
    bar,dated=facts(stamp)
    executor.execute_account_plan(proposal,bar,constraint=dated)
    assert executor.quantity==0 and executor.cycle_budget==budget
    at=stamp+timedelta(minutes=30)
    revised=replace(budget,cash_budget=Decimal('4000'))
    bar,dated=facts(at)
    with pytest.raises(ValueError,match='rebuilt'):
        executor.execute_account_plan(plan(executor,at,(order(OrderSide.BUY,100,10.1),),
            capital='signal_cash_fraction',before=budget,after=revised),bar,constraint=dated)
    executor.execute_account_plan(plan(executor,at,(order(OrderSide.BUY,100,10.1),),
        capital='signal_cash_fraction',before=budget,after=budget),bar,constraint=dated)
    assert executor.cycle_budget.buy_cost_including_fees==Decimal('1001.000')
    at+=timedelta(minutes=30)
    bar,dated=facts(at)
    active=executor.cycle_budget
    executor.execute_account_plan(plan(executor,at,(order(OrderSide.BUY,200,10.1),),
        capital='signal_cash_fraction',before=active,after=active),bar,constraint=dated)
    assert executor.quantity==100 and executor.rows['orders'][-1]['reason']=='CYCLE_BUDGET_EXCEEDED'


def test_missing_sizing_is_not_guessed_from_order_shape():
    executor,stamp,_=setup(MarketId.US)
    proposal=plan(executor,stamp,(order(OrderSide.BUY,100),))
    bar,dated=facts(stamp)
    with pytest.raises(ValueError,match='sizing'):
        executor.execute_account_plan(replace(proposal,evidence={}),bar,constraint=dated)
    assert executor.quantity==0 and not executor.rows['fills']


def test_closed_budget_does_not_consume_the_next_position_budget():
    executor,stamp,_=setup(MarketId.US)
    first=CycleBudget('first',200,Decimal('.3'),Decimal('3000'),Decimal(0),EntryCyclePhase.ACTIVE)
    bar,dated=facts(stamp)
    executor.execute_account_plan(plan(executor,stamp,(order(OrderSide.BUY,200,10.1),),
        capital='signal_cash_fraction',after=first),bar,constraint=dated)
    at=stamp+timedelta(minutes=30)
    bar,dated=facts(at)
    executor.execute_account_plan(plan(executor,at,(order(OrderSide.SELL,200),),
        capital='signal_cash_fraction',before=executor.cycle_budget),bar,constraint=dated)
    assert executor.cycle_budget is None
    at+=timedelta(minutes=30)
    second=CycleBudget('second',100,Decimal('.2'),Decimal('1500'),Decimal(0),EntryCyclePhase.ACTIVE)
    bar,dated=facts(at)
    executor.execute_account_plan(plan(executor,at,(order(OrderSide.BUY,100,10.1),),
        capital='signal_cash_fraction',after=second),bar,constraint=dated)
    assert executor.quantity==100
    assert executor.cycle_budget.cycle_id=='second'
    assert executor.cycle_budget.buy_cost_including_fees==Decimal('1001.000')


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_dated_full_liquidation_rule_handles_integer_split_remainders(market):
    executor,stamp,instrument=setup(market)
    split=stamp+timedelta(minutes=30)
    actions=pd.DataFrame([dict(Date=split,AvailableDate=split,EventId='split',Kind='SPLIT',Ratio=1.5,CashPerShare=0.,PayAt=None)])
    executor,_,_=setup(market,actions=actions)
    bar,dated=facts(stamp)
    executor.execute_account_plan(plan(executor,stamp,(order(OrderSide.BUY,100,10.1),)),bar,constraint=dated)
    point=ReplayPoint(stamp,split,split,split+timedelta(minutes=30),split.date().isoformat(),ExecutionPrecision.BAR_INTERVAL)
    assert executor.account_snapshot(point,instrument).quantity==150
    bar,dated=facts(split)
    for key in ('Open','High','Low','Close'):
        bar[key]/=1.5
    with pytest.raises(ValueError,match='step'):
        executor.execute_account_plan(plan(executor,split,(order(OrderSide.SELL,150),)),bar,constraint=dated)
    dated['SellRemainderPolicy']='FULL_LIQUIDATION'
    executor.execute_account_plan(plan(executor,split,(order(OrderSide.SELL,150),)),bar,constraint=dated)
    assert executor.quantity==0 and len(executor.rows['trades'])==1


def test_unfilled_earlier_order_cannot_turn_full_exit_remainder_into_partial_odd_sale():
    executor,stamp,instrument=setup(MarketId.CN)
    split=stamp+timedelta(minutes=30)
    actions=pd.DataFrame([dict(Date=split,AvailableDate=split,EventId='split',Kind='SPLIT',Ratio=1.5,CashPerShare=0.,PayAt=None)])
    executor,_,_=setup(MarketId.CN,actions=actions)
    bar,dated=facts(stamp)
    executor.execute_account_plan(plan(executor,stamp,(order(OrderSide.BUY,100,10.1),)),bar,constraint=dated)
    point=ReplayPoint(stamp,split,split,split+timedelta(minutes=30),split.date().isoformat(),ExecutionPrecision.BAR_INTERVAL)
    executor.account_snapshot(point,instrument)
    bar,dated=facts(split)
    for key in ('Open','High','Low','Close'):
        bar[key]/=1.5
    dated['SellRemainderPolicy']='FULL_LIQUIDATION'
    proposal=plan(executor,split,(order(OrderSide.SELL,100,20.),order(OrderSide.SELL,50)))
    executor.execute_account_plan(proposal,bar,constraint=dated)
    assert executor.quantity==150
    assert executor.rows['orders'][-1]['reason']=='ODD_LOT_REQUIRES_FULL_LIQUIDATION'
    assert len(executor.rows['fills'])==1


def test_dependency_cannot_use_a_future_close_fill_to_sell_at_earlier_open():
    executor,stamp,_=setup(MarketId.US)
    end=stamp+timedelta(minutes=30)
    legs=(ReplayLeg(0,order(OrderSide.BUY,100),'CLOSE',stamp,end),
          ReplayLeg(1,order(OrderSide.SELL,100),'OPEN',stamp,end,0,'FILLED'))
    bar,dated=facts(stamp)
    with pytest.raises(ValueError,match='reverses'):
        executor.execute_account_plan(plan(executor,stamp,legs=legs),bar,constraint=dated)
    assert not executor.rows['fills'] and executor.quantity==0


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_daily_plan_uses_real_intraday_checkpoints_and_volume_per_quote_bar(market):
    executor,stamp,_=setup(market)
    close=stamp.replace(hour=15,minute=0)
    rows=[]
    for begin,opening,ending,volume in ((stamp,10.,10.1,100.),
            (stamp.replace(hour=11,minute=0),10.5,11.,100.),
            (stamp.replace(hour=14,minute=30),11.5,12.,100.)):
        rows.append(dict(BarStart=begin,Date=begin+timedelta(minutes=30),Open=opening,
            High=max(opening,ending),Low=min(opening,ending),Close=ending,Volume=volume,Amount=1000.))
    executor=PortfolioHistoricalExecutor(specification=replace(executor.spec,decision_clock=BarFrequency.DAILY),
        initial_cash=10000.,fee_rate=.001,actions=executor.actions,price_basis='RAW',execution_bars=pd.DataFrame(rows))
    point=ReplayPoint(stamp-timedelta(minutes=30),stamp,stamp,close,stamp.date().isoformat(),ExecutionPrecision.BAR_INTERVAL)
    legs=(ReplayLeg(0,order(OrderSide.BUY,100),'OPEN',stamp,close),
        ReplayLeg(1,order(OrderSide.SELL,100),'11:30_CLOSE',stamp,close,0,'FILLED'),
        ReplayLeg(2,order(OrderSide.BUY,100),'CLOSE',stamp,close,1,'FILLED'))
    proposal=AccountExecutionPlan('f'*64,'fixture',point,0,100,legs=legs,
        evidence={'sizing':'EXPLICIT_ORDERS','target':.1,'reference_price':10.,
            'specification_hash':executor.spec.fingerprint,'fee_rate':.001})
    bar,dated=facts(stamp,volume=300.)
    bar.update(Date=close,AvailableDate=close,High=12.,Close=12.)
    executor.execute_account_plan(proposal,bar,constraint=dated)
    fills=executor.rows['fills']
    assert [row['price'] for row in fills]==[10.,11.,12.]
    assert [row['executed_at'] for row in fills]==[stamp,stamp.replace(hour=11,minute=30),close]
    assert all(row['quote_source']=='EXECUTION_BARS' for row in fills)
    assert all(row['interval_end']==close for row in fills)
    assert [row['quote_interval_end'] for row in fills]==[row['Date'] for row in rows]
    assert executor.cash==pytest.approx(8896.7) and executor.quantity==100


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_two_checkpoint_legs_cannot_each_consume_the_whole_same_execution_bar(market):
    executor,stamp,_=setup(market)
    end=stamp+timedelta(minutes=30)
    bar,dated=facts(stamp,volume=150.)
    executor=PortfolioHistoricalExecutor(specification=executor.spec,initial_cash=10000.,fee_rate=.001,
        actions=executor.actions,price_basis='RAW',execution_bars=pd.DataFrame([bar]))
    legs=(ReplayLeg(0,order(OrderSide.BUY,100),'OPEN',stamp,end),
          ReplayLeg(1,order(OrderSide.SELL,100),'CLOSE',stamp,end,0,'FILLED'))
    executor.execute_account_plan(plan(executor,stamp,legs=legs),bar,constraint=dated)
    assert executor.quantity==100 and len(executor.rows['fills'])==1
    assert executor.rows['orders'][-1]['reason']=='INSUFFICIENT_BAR_VOLUME'


def test_prepared_execution_quotes_are_shared_immutable_and_pickle_without_reindexing(monkeypatch):
    import pickle
    from trading_execution_engine import PreparedExecutionQuotes
    executor,stamp,_=setup(MarketId.US)
    bar,dated=facts(stamp)
    frame=pd.DataFrame([bar])
    compile_method=PreparedExecutionQuotes.from_frame.__func__
    calls=[]
    def observed(cls,*args):
        calls.append(1)
        return compile_method(cls,*args)
    monkeypatch.setattr(PreparedExecutionQuotes,'from_frame',classmethod(observed))
    compiled=PreparedExecutionQuotes.from_frame(frame,MarketId.US)
    restored=pickle.loads(pickle.dumps(compiled))
    assert restored.identity==compiled.identity and restored.by_slot==compiled.by_slot
    assert len(calls)==1
    with pytest.raises(TypeError):
        compiled.by_start[stamp]=None
    frame.loc[:,['Open','High','Low','Close']]=999.
    accounts=[PortfolioHistoricalExecutor(specification=executor.spec,initial_cash=10000.,fee_rate=.001,
        actions=executor.actions,price_basis='RAW',execution_bars=compiled) for _ in range(2)]
    assert accounts[0]._quotes_by_start is accounts[1]._quotes_by_start
    end=stamp+timedelta(minutes=30)
    leg=ReplayLeg(0,order(OrderSide.BUY,100),'OPEN',stamp,end)
    accounts[0].execute_account_plan(plan(accounts[0],stamp,legs=(leg,)),bar,constraint=dated)
    assert accounts[0].rows['fills'][0]['price']==10.
    assert accounts[1].quantity==0 and accounts[1].rows['fills']==[]
    assert len(calls)==1


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_due_dividend_cash_is_available_before_later_real_checkpoint(market):
    executor,stamp,instrument=setup(market)
    today=stamp+timedelta(days=1)
    pay=today.replace(hour=11,minute=0)
    actions=pd.DataFrame([dict(Date=today,AvailableDate=today,EventId='dividend',Kind='CASH_DIVIDEND',
        Ratio=1.,CashPerShare=.2,PayAt=pay)])
    execution_bar,unused=facts(today.replace(hour=11,minute=0),volume=1000.)
    earlier_bar,_=facts(stamp)
    opening_bar,_=facts(today)
    closing_bar,_=facts(today.replace(hour=14,minute=30))
    executor=PortfolioHistoricalExecutor(specification=replace(executor.spec,decision_clock=BarFrequency.DAILY),
        initial_cash=10000.,fee_rate=.001,actions=actions,price_basis='RAW',
        execution_bars=pd.DataFrame([earlier_bar,opening_bar,execution_bar,closing_bar]))
    bar,dated=facts(stamp)
    executor.execute_account_plan(plan(executor,stamp,(order(OrderSide.BUY,100,10.1),)),bar,constraint=dated)
    close=today.replace(hour=15,minute=0)
    point=ReplayPoint(bar['Date'],today,today,close,today.date().isoformat(),ExecutionPrecision.BAR_INTERVAL)
    account=executor.account_snapshot(point,instrument)
    assert account.cash==8999. and account.receivable==20.
    leg=ReplayLeg(0,order(OrderSide.BUY,900),'11:30_CLOSE',today,close)
    proposal=AccountExecutionPlan('e'*64,'fixture',point,1,1000,legs=(leg,),
        evidence={'sizing':'EXPLICIT_ORDERS','target':1.,'reference_price':10.,
            'specification_hash':executor.spec.fingerprint,'fee_rate':.001})
    bar,dated=facts(today)
    bar.update(Date=close,AvailableDate=close)
    executor.execute_account_plan(proposal,bar,constraint=dated)
    assert executor.quantity==1000 and executor.cash==pytest.approx(10.)
    assert executor.receivable==pytest.approx(0.)
    payment=next(row for row in executor.rows['actions'] if row['kind']=='DIVIDEND_PAYMENT')
    assert payment['time']==pay


def test_execution_quote_prices_cannot_silently_mix_adjusted_and_raw_units():
    executor,stamp,_=setup(MarketId.US)
    main,dated=facts(stamp)
    raw=dict(main)
    for key in ('Open','High','Low','Close'):
        raw[key]*=2
    executor=PortfolioHistoricalExecutor(specification=executor.spec,initial_cash=10000.,fee_rate=.001,
        actions=executor.actions,price_basis='RAW',execution_bars=pd.DataFrame([raw]))
    end=stamp+timedelta(minutes=30)
    leg=ReplayLeg(0,order(OrderSide.BUY,100),'OPEN',stamp,end)
    with pytest.raises(ValueError,match='RAW price units'):
        executor.execute_account_plan(plan(executor,stamp,legs=(leg,)),main,constraint=dated)
    assert executor.quantity==0 and not executor.rows['fills']


def test_recognized_event_cursor_exposes_confirmed_asof_facts_not_future_source_events():
    from dataclasses import FrozenInstanceError
    executor,stamp,instrument=setup(MarketId.US)
    future=stamp+timedelta(days=1)
    actions=pd.DataFrame([dict(Date=stamp,AvailableDate=stamp,EventId='split',Kind='SPLIT',Ratio=1.5,CashPerShare=0.,PayAt=None),
        dict(Date=future,AvailableDate=stamp,EventId='future',Kind='CASH_DIVIDEND',Ratio=1.,CashPerShare=.2,PayAt=future)])
    executor,_,_=setup(MarketId.US,actions=actions)
    point=ReplayPoint(stamp-timedelta(minutes=30),stamp,stamp,stamp+timedelta(minutes=30),
        stamp.date().isoformat(),ExecutionPrecision.BAR_INTERVAL)
    assert executor.recognized_events_since(0,future)==((),0)
    executor.account_snapshot(point,instrument)
    assert executor.recognized_events_since(0,stamp-timedelta(seconds=1))==((),0)
    events,cursor=executor.recognized_events_since(0,stamp)
    assert cursor==1 and len(events)==1 and events[0].ratio==1.5
    assert events[0].quantity_before==events[0].quantity_after==0
    with pytest.raises(FrozenInstanceError):
        events[0].ratio=2.
    assert executor.recognized_events_since(cursor,future)==((),cursor)


def test_event_index_never_rescans_source_and_rolls_back_with_failed_split():
    executor,stamp,_=setup(MarketId.US)
    split=stamp+timedelta(minutes=30)
    actions=pd.DataFrame([dict(Date=split,AvailableDate=stamp,EventId='split',Kind='SPLIT',
        Ratio=1.5,CashPerShare=0.,PayAt=None)])
    executor,_,_=setup(MarketId.US,actions=actions)
    # The original source is never traversed by the V4 per-decision path.
    executor._action_events=None
    executor.quantity=1
    with pytest.raises(ValueError,match='fractional split'):
        executor.snapshot_at(stamp,split)
    assert executor.quantity==1 and executor._event_cursor==0 and not executor.applied
    executor.quantity=2
    snapshot=executor.snapshot_at(stamp,split)
    assert snapshot.quantity==3 and snapshot.reference_price_scale==1/1.5
    assert executor._event_cursor==1 and len(executor.rows['actions'])==1
    assert executor.snapshot_at(stamp,split)==snapshot
    assert len(executor.rows['actions'])==1


def test_unfilled_outer_transaction_rejection_does_not_retain_idempotency_key():
    executor,stamp,_=setup(MarketId.US)
    bar,dated=facts(stamp)
    proposal=plan(executor,stamp)
    with pytest.raises(ValueError,match='caller rejects'):
        with executor.transaction():
            executor.execute_account_plan(proposal,bar,constraint=dated)
            raise ValueError('caller rejects')
    assert not executor.completed and executor.revision==0 and not executor.rows['decisions']
    executor.execute_account_plan(proposal,bar,constraint=dated)
    assert executor.revision==1 and len(executor.rows['points'])==1
