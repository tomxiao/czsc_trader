"""V4 capability acceptance: identical accounts, explicitly different market rules."""
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from execution_channels.instruments import BarFrequency
from execution_channels.instruments import InstrumentId
from execution_channels.instruments import MarketId
from execution_channels.instruments import AssetClass
from execution_channels.policy import AccountPolicy
from execution_channels.policy import CashAvailabilityPolicy
from execution_channels.policy import ResearchExecutionSpec
from execution_channels.policy import UsEquitySpec
from execution_channels.policy import CnEquitySpec
from execution_channels.session_contracts import OrderSide
from execution_channels.session_contracts import OrderType
from execution_channels.contracts import AccountExecutionPlan
from execution_channels.contracts import ReplayPoint
from execution_channels.contracts import ExecutionPrecision
from execution_channels.contracts import ReplayOrder
from execution_channels.contracts import ReplayLeg
from execution_channels.historical import PortfolioHistoricalExecutor


def setup(market, *, cash_policy=CashAvailabilityPolicy.IMMEDIATE_RESEARCH):
    zone = ZoneInfo('Asia/Shanghai' if market is MarketId.CN else 'America/New_York')
    stamp = datetime(2026, 10, 8, 9, 30, tzinfo=zone)
    spec = ResearchExecutionSpec(CnEquitySpec() if market is MarketId.CN else UsEquitySpec(),
        BarFrequency.M30, AccountPolicy('CNY' if market is MarketId.CN else 'USD', cash_policy),
        100, .01, .01, 0.)
    executor = PortfolioHistoricalExecutor(specification=spec, initial_cash=10000., fee_rate=.001,
        price_basis='HFQ')
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


# Independent risk: EC11; responsibility-level assertions.
def test_later_leg_failure_keeps_confirmed_prefix_and_blocks_successful_finalization():
    executor,stamp,_=setup(MarketId.US,cash_policy=CashAvailabilityPolicy.SETTLED_ONLY)
    end=stamp+timedelta(minutes=30)
    legs=(ReplayLeg(0,order(OrderSide.BUY,100),'OPEN',stamp,end),
          ReplayLeg(1,order(OrderSide.SELL,100),'CLOSE',stamp,end,0,'FILLED_ALL'))
    bar,dated=facts(stamp)
    # A valid input clock can still precede a later leg's actual fill. Missing
    # clocks are now rejected before any leg, while this preserves prefix coverage.
    dated['SettlementAt']=stamp
    with pytest.raises(ValueError,match='settlement'):
        executor.execute_account_plan(plan(executor,stamp,legs=legs),bar,constraint=dated)
    assert executor.quantity==100 and len(executor.rows['fills'])==1
    with pytest.raises(ValueError,match='failed account'):
        executor.finish()


# Independent risk: EC06; responsibility-level assertions.
@pytest.mark.parametrize('quantity', [150,50], ids=['EC06-C03','EC06-C04'])
def test_full_liquidation_remainder_cannot_be_used_for_partial_sale(quantity):
    executor,stamp,_ = setup(MarketId.CN)
    bar,rule = facts(stamp)
    executor.execute_account_plan(plan(executor,stamp,(order(OrderSide.BUY,100),)),bar,constraint=rule)
    executor.quantity = 150
    later = stamp+timedelta(minutes=30)
    bar,rule = facts(later)
    rule['SellRemainderPolicy'] = 'FULL_LIQUIDATION'
    proposal = plan(executor,later,(order(OrderSide.SELL,quantity),))
    if quantity == 50:
        with pytest.raises(ValueError,match='instrument step'):
            executor.execute_account_plan(proposal,bar,constraint=rule)
        assert executor.quantity == 150
        assert len(executor.rows['fills']) == 1
    else:
        executor.execute_account_plan(proposal,bar,constraint=rule)
        assert executor.quantity == 0 and len(executor.rows['fills']) == 2


# Independent risk: EC06; responsibility-level assertions.
def test_dependency_cannot_use_a_future_close_fill_to_sell_at_earlier_open():
    executor,stamp,_=setup(MarketId.US)
    end=stamp+timedelta(minutes=30)
    legs=(ReplayLeg(0,order(OrderSide.BUY,100),'CLOSE',stamp,end),
          ReplayLeg(1,order(OrderSide.SELL,100),'OPEN',stamp,end,0,'FILLED_ALL'))
    bar,dated=facts(stamp)
    with pytest.raises(ValueError,match='reverses'):
        executor.execute_account_plan(plan(executor,stamp,legs=legs),bar,constraint=dated)
    assert not executor.rows['fills'] and executor.quantity==0


# Independent risk: EC28; responsibility-level assertions.
def test_daily_plan_uses_real_intraday_checkpoints_and_volume_per_quote_bar():
    market = MarketId.US
    executor,stamp,_=setup(market)
    close=stamp.replace(hour=15,minute=0)
    rows=[]
    for begin,opening,ending,volume in ((stamp,10.,10.1,100.),
            (stamp.replace(hour=11,minute=0),10.5,11.,100.),
            (stamp.replace(hour=14,minute=30),11.5,12.,100.)):
        rows.append(dict(BarStart=begin,Date=begin+timedelta(minutes=30),Open=opening,
            High=max(opening,ending),Low=min(opening,ending),Close=ending,Volume=volume,Amount=1000.))
    executor=PortfolioHistoricalExecutor(specification=replace(executor.spec,decision_clock=BarFrequency.DAILY),
        initial_cash=10000.,fee_rate=.001,price_basis='HFQ',execution_bars=pd.DataFrame(rows))
    point=ReplayPoint(stamp-timedelta(minutes=30),stamp,stamp,close,stamp.date().isoformat(),ExecutionPrecision.BAR_INTERVAL)
    legs=(ReplayLeg(0,order(OrderSide.BUY,100),'OPEN',stamp,close),
        ReplayLeg(1,order(OrderSide.SELL,100),'11:30_CLOSE',stamp,close,0,'FILLED_ALL'),
        ReplayLeg(2,order(OrderSide.BUY,100),'CLOSE',stamp,close,1,'FILLED_ALL'))
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


# Independent risk: EC12; responsibility-level assertions.
def test_EC12_C04_two_legs_share_one_bar_capacity():
    market = MarketId.US
    executor,stamp,_=setup(market)
    end=stamp+timedelta(minutes=30)
    bar,dated=facts(stamp,volume=150.)
    executor=PortfolioHistoricalExecutor(specification=executor.spec,initial_cash=10000.,fee_rate=.001,
        price_basis='HFQ',execution_bars=pd.DataFrame([bar]))
    legs=(ReplayLeg(0,order(OrderSide.BUY,100),'OPEN',stamp,end),
          ReplayLeg(1,order(OrderSide.SELL,100),'CLOSE',stamp,end,0,'FILLED_ALL'))
    executor.execute_account_plan(plan(executor,stamp,legs=legs),bar,constraint=dated)
    assert executor.quantity==100 and len(executor.rows['fills'])==1
    assert executor.rows['orders'][-1]['reason']=='INSUFFICIENT_BAR_VOLUME'


# Independent risk: EC08; responsibility-level assertions.
def test_execution_quote_prices_cannot_silently_mix_adjusted_and_raw_units():
    executor,stamp,_=setup(MarketId.US)
    main,dated=facts(stamp)
    raw=dict(main)
    for key in ('Open','High','Low','Close'):
        raw[key]*=2
    executor=PortfolioHistoricalExecutor(specification=executor.spec,initial_cash=10000.,fee_rate=.001,
        price_basis='HFQ',execution_bars=pd.DataFrame([raw]))
    end=stamp+timedelta(minutes=30)
    leg=ReplayLeg(0,order(OrderSide.BUY,100),'OPEN',stamp,end)
    with pytest.raises(ValueError,match='HFQ price units'):
        executor.execute_account_plan(plan(executor,stamp,legs=(leg,)),main,constraint=dated)
    assert executor.quantity==0 and not executor.rows['fills']


# Independent risk: EC10; responsibility-level assertions.
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
