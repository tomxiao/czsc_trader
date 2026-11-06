"""Native V4 S003 core inventory and confirmed dependent intraday rotation."""
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_FLOOR
from zoneinfo import ZoneInfo
import pandas as pd
from strategy_runtime import AccountDecision, AccountStepResult, StateRecord, ReplayOrder, ReplayLeg
from strategy_runtime.contracts import OrderSide, OrderType
from .signals import _seed_history, _incremental_history, _decision_history


def signal_history(inputs, feature, signal_date):
    seed = inputs['constituent_moneyflow_seed']
    history = _seed_history(seed)
    if signal_date > pd.Timestamp('2026-09-08'):
        weights = inputs['incremental_constituent_weights']
        flows = inputs['incremental_constituent_moneyflow']
        flows = flows.loc[pd.to_datetime(flows.Date).dt.normalize().le(signal_date)]
        extra = _incremental_history(seed, weights, flows, float(feature['minimum_observed_weight_ratio']))
        history = pd.concat([history, extra]).sort_index()
        history = history.loc[~history.index.duplicated(keep='last')]
    return _decision_history(history.loc[:signal_date], feature)


def plan_overlay(ctx, *, active, core_quantity, execution):
    cash = Decimal(str(ctx.account.available_cash))
    lot = int(execution['lot_size'])
    fee = Decimal(str(ctx.planning.fee_rate))
    # Preserve the original float multiplication followed by Decimal tick rounding.
    raw = float(ctx.history.last()['Close'])
    rounded = (Decimal(str(raw * 1.10)) / Decimal('.001')).to_integral_value(rounding=ROUND_FLOOR) * Decimal('.001')
    limit = Decimal(str(float(rounded) * ctx.portfolio.reference_price_scale))
    def affordable(value):
        return int(value / (limit * (1 + fee))) // lot * lot
    local_day = ctx.point.execution_interval.start.astimezone(ZoneInfo('Asia/Shanghai')).date()
    def stamp(hour, minute):
        return datetime.combine(local_day, time(hour, minute), ZoneInfo('Asia/Shanghai'))
    # Legacy submission endpoints are inclusive. V4 is half-open, so preserve
    # the exact microsecond datetime domain by advancing the upper endpoint.
    def leg(sequence, order, checkpoint, start, end, dependency=None):
        return ReplayLeg(sequence, order, checkpoint, stamp(*start),
            stamp(*end) + timedelta(microseconds=1), dependency,
            'FILLED_ALL' if dependency is not None else None)
    actual = ctx.account.quantity
    legs = ()
    mode = 'NONE'
    if core_quantity == 0:
        if actual:
            raise ValueError('S003 core identity is missing')
        core_quantity = affordable(cash * Decimal(str(execution['core_fraction'])))
        if core_quantity <= 0:
            raise ValueError('S003 cannot afford one core lot')
        legs = (leg(0, ReplayOrder(OrderSide.BUY, core_quantity, OrderType.LIMIT, float(limit)),
                    'OPEN', (9,30), (9,35)),)
        mode = 'CORE_SETUP'
    else:
        if actual != core_quantity:
            raise ValueError('S003 account differs from core quantity')
        if active:
            quantity = min(core_quantity, affordable(cash))
            if quantity <= 0:
                raise ValueError('S003 cannot afford one event lot')
            if quantity > ctx.account.sellable_quantity:
                raise ValueError('S003 rotation requires confirmed sellable core inventory')
            legs = (leg(0, ReplayOrder(OrderSide.BUY, quantity, OrderType.LIMIT, float(limit)),
                        'OPEN', (9,30), (9,35)),
                    leg(1, ReplayOrder(OrderSide.SELL, quantity, OrderType.MARKET),
                        '11:30_CLOSE', (11,29), (11,30), 0))
            mode = 'CORE_EVENT_INTRADAY_ROTATION'
    decision = AccountDecision.from_facts(1., mode,
        facts={'signal_active':active,'core_quantity':core_quantity,'buy_limit':str(limit)},
        next_watch='next completed moneyflow session', legs=legs, capital_mode='full_available_cash')
    return decision, core_quantity


def step(ctx, state):
    day = pd.Timestamp(ctx.history.last()['Date']).tz_convert('Asia/Shanghai').tz_localize(None).normalize()
    inputs = {name:view.to_frame() for name,view in ctx.observations.items()}
    history = signal_history(inputs, ctx.parameters['rule']['feature'], day)
    if day not in history.index:
        raise ValueError('S003 signal session is missing')
    decision, core = plan_overlay(ctx, active=bool(history.loc[day,'signal_active']),
        core_quantity=state.account.get('core_quantity'), execution=ctx.parameters['rule']['execution'])
    return AccountStepResult(decision, StateRecord((('core_quantity',core),)), StateRecord())
