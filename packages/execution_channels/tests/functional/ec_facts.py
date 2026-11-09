"""Minimal EC facts; no provider, research context, or strategy loader."""
from datetime import datetime, timedelta, timezone
from execution_channels.contracts import ExecutionPrecision, ReplayPoint
from execution_channels.instruments import AssetClass, BarFrequency, InstrumentId, MarketId
from execution_channels.policy import (AccountPolicy, CashAvailabilityPolicy, CnEquitySpec,
    ExecutionPolicy, ResearchExecutionSpec, UsEquitySpec)

def fixture(market):
    instrument = InstrumentId(market, AssetClass.STOCK, 'MU' if market is MarketId.US else '600000.SH')
    start = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc) if market is MarketId.US else datetime(2026, 1, 5, 1, 30, tzinfo=timezone.utc)
    end = start + timedelta(hours=6 if market is MarketId.US else 4)
    spec = ResearchExecutionSpec(UsEquitySpec() if market is MarketId.US else CnEquitySpec(), BarFrequency.DAILY,
        AccountPolicy(instrument.currency, CashAvailabilityPolicy.IMMEDIATE_RESEARCH),
        1 if market is MarketId.US else 100, .01, .01, 0.)
    point = ReplayPoint(start-timedelta(days=1), start, start, end, '2026-01-05', ExecutionPrecision.BAR_INTERVAL)
    row = {'BarStart': start, 'Date': end, 'Open': 10., 'High': 11., 'Low': 9., 'Close': 10.5, 'Volume': 10000.}
    constraint = {'Date': start, 'AvailableDate': start, 'QuantityStep': spec.quantity_step, 'PriceTick': .01,
        'Tradable': True, 'BuySellableAt': start, 'SettlementAt': end, 'SellRemainderPolicy': 'FULL_LIQUIDATION',
        'PriceLimitPolicy': 'EXPLICIT_UNBOUNDED' if market is MarketId.US else 'DATED_LIMITS',
        'PriceLimitLower': None if market is MarketId.US else 9., 'PriceLimitUpper': None if market is MarketId.US else 11.}
    return instrument, spec, point, row, constraint


def frozen(spec, mode='available_cash_fraction'):
    capital = {'fee_rate':.001,'mode':mode,'target_scope':'entry_cycle'}
    if mode != 'signal_cash_fraction':
        capital['allocation_fraction'] = 1.
    return ExecutionPolicy('FROZEN_RULE', {'capital':capital,
        'entry':{'limit_parameter':.01,'order_type':'LIMIT'},
        'exit':{'limit_ratio':.1,'order_type':'MARKET'},
        'instrument':{'lot_size':spec.quantity_step,'price_tick':spec.price_tick,
            'price_limit_ratio':.1,'maximum_order_quantity':100000}})
