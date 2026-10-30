"""Capability-v4 raw-price account execution for explicitly dated market rules.

Orders are full-fill or unfilled. The shared replay kernel owns iteration;
this model consumes one immutable plan and one observed execution interval.
"""
from dataclasses import fields, is_dataclass, dataclass
from datetime import datetime
from decimal import Decimal
import math
from collections.abc import Mapping
from contextlib import contextmanager
from bisect import bisect_left, bisect_right
from types import MappingProxyType

import pandas as pd
from dataflows import InstrumentId, TimeInterval, MarketId
from strategy_runtime.contracts import OrderSide, OrderType
from strategy_runtime.equity import CashAvailabilityPolicy, EquityPortfolio, equity_hash
from strategy_runtime.replay_contracts import AccountExecutionPlan, AccountSnapshot, ReplayPoint

from .accounting import _post_confirmed_fill
from .equity import (_EquityAccount, _timestamp, _bar_identity_value, _SESSION_ZONES,
                     _TransitionCheckpoint, _ACCOUNT_STATE)
from .fills import OrderSpec, resolve_fill
from .market import SessionPriceLimits


def _serial(value):
    def facts(item):
        if is_dataclass(item):
            return {field.name: facts(getattr(item, field.name)) for field in fields(item)}
        if isinstance(item, Mapping):
            return {str(key): facts(value) for key, value in item.items()}
        if isinstance(item, (tuple, list)):
            return [facts(value) for value in item]
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, Decimal):
            return str(item)
        return item
    import json
    return json.loads(json.dumps(facts(value), allow_nan=False))


@dataclass(frozen=True, slots=True)
class _CheckpointQuote:
    stamp: datetime
    price: float | None
    start: datetime
    end: datetime
    volume: float
    status: str
    blocked: bool
    source: str
    low: float | None
    high: float | None


@dataclass(frozen=True, slots=True, init=False)
class PreparedExecutionQuotes:
    """Immutable executor-only quotes, prepared once and safely shared by accounts."""
    market: MarketId
    by_start: Mapping
    by_end: Mapping
    by_slot: Mapping
    identity: str

    def __init__(self):
        raise TypeError('prepare execution quotes with from_frame')

    @classmethod
    def from_frame(cls, execution_bars, market):
        if type(market) is not MarketId or market not in _SESSION_ZONES:
            raise TypeError('execution quote preparation requires a supported market')
        by_start, by_end, by_slot = {}, {}, {}
        if not isinstance(execution_bars, pd.DataFrame) or execution_bars.empty:
            raise TypeError('execution bars require a nonempty authenticated dataframe')
        zone = _SESSION_ZONES[market]
        previous = None
        for item in execution_bars.itertuples(index=False):
            start, end = _timestamp(item.BarStart), _timestamp(item.Date)
            if (pd.isna(start) or pd.isna(end) or start.tzinfo is None or end.tzinfo is None
                    or start >= end or (previous is not None and start < previous)):
                raise ValueError('execution bars must have ordered nonoverlapping aware intervals')
            previous = end
            status = getattr(item, 'BarStatus', 'OBSERVED')
            blocked = getattr(item, 'ExecutionBlocked', False)
            if type(blocked) is not bool and type(blocked).__name__ != 'bool_':
                raise TypeError('execution bar block flag requires bool')
            if status == 'MISSING':
                if not all(pd.isna(getattr(item, key)) for key in ('Open','High','Low','Close','Volume','Amount')):
                    raise ValueError('missing execution bar contains fabricated quotes')
                values = (None,None,None,None,0.)
            else:
                values = tuple(float(getattr(item,key)) for key in ('Open','High','Low','Close','Volume'))
                opening, high, low, close, volume = values
                if (status not in {'OBSERVED','ZERO_VOLUME'} or not all(math.isfinite(v) for v in values)
                        or min(values[:4]) <= 0 or volume < 0 or low > min(opening,close)
                        or high < max(opening,close)):
                    raise ValueError('invalid execution bar quotes')
                if hasattr(item,'BarStatus') and (status=='ZERO_VOLUME') != (volume==0):
                    raise ValueError('execution bar status differs from volume')
            row = (start,end,values,status,bool(blocked))
            if start in by_start or end in by_end:
                raise ValueError('duplicate execution quote interval')
            by_start[start] = row
            by_end[end] = row
            for side, stamp in (('OPEN',start),('CLOSE',end)):
                local = stamp.astimezone(zone)
                key = (local.date().isoformat(),local.strftime('%H:%M')+'_'+side)
                if key in by_slot:
                    raise ValueError('ambiguous local execution quote checkpoint')
                by_slot[key] = row
        identity = equity_hash({'market':market.value,'rows':tuple(by_start.values())})
        return _restore_execution_quotes(market,by_start,by_end,by_slot,identity)

    def __reduce__(self):
        # Private process transport only; numeric/source validation occurred in
        # from_frame. Restoring does not repeat timestamp or checkpoint indexing.
        return (_restore_execution_quotes,(self.market,dict(self.by_start),dict(self.by_end),dict(self.by_slot),self.identity))


def _restore_execution_quotes(market, by_start, by_end, by_slot, identity):
    value = object.__new__(PreparedExecutionQuotes)
    for name, item in (('market',market),('by_start',MappingProxyType(by_start)),
            ('by_end',MappingProxyType(by_end)),('by_slot',MappingProxyType(by_slot)),('identity',identity)):
        object.__setattr__(value,name,item)
    return value


class PortfolioHistoricalExecutor(_EquityAccount):
    """One long-only raw-price account with sizes, dependencies and dated rules."""

    def __init__(self, *, specification, initial_cash, fee_rate, actions, price_basis, execution_bars=None):
        if price_basis != 'RAW':
            raise ValueError('v4 economic execution requires RAW prices and explicit actions')
        if not isinstance(actions, pd.DataFrame) or not {'Date','AvailableDate','EventId','Kind'}.issubset(actions.columns):
            raise TypeError('economic events require explicit dated facts')
        if actions.EventId.duplicated().any():
            raise ValueError('economic event identities must be unique')
        for event in actions.itertuples(index=False):
            at, available = _timestamp(event.Date), _timestamp(event.AvailableDate)
            if (pd.isna(at) or pd.isna(available) or at.tzinfo is None or available.tzinfo is None
                    or available > at or type(event.EventId) is not str or not event.EventId
                    or event.Kind not in {'NONE','SPLIT','CASH_DIVIDEND'}):
                raise ValueError('invalid economic event facts or causal time')
            if event.Kind == 'SPLIT':
                if not math.isfinite(float(event.Ratio)) or float(event.Ratio) <= 0:
                    raise ValueError('invalid split ratio')
            elif event.Kind == 'CASH_DIVIDEND':
                pay = _timestamp(event.PayAt)
                if (not math.isfinite(float(event.CashPerShare)) or float(event.CashPerShare) < 0
                        or pd.isna(pay) or pay.tzinfo is None or pay < at):
                    raise ValueError('invalid dividend entitlement or payment')
        super().__init__(specification=specification, initial_cash=initial_cash, fee_rate=fee_rate, actions=actions)
        self._buy_locks = []
        self._position_last_interval = None
        self._position_fees = 0.
        self._position_buys = self._position_sells = 0
        self._latest_position = None
        self._cycle_budget = None
        self._cycle_applied = set()
        self._cycle_spent = Decimal(0)
        self._broken = False
        self._instrument = None
        self._economic_events = tuple(event for event in self._action_events if event.Kind != "NONE")
        self._event_times = tuple(_timestamp(event.Date) for event in self._economic_events)
        self._event_cursor = 0
        self._split_events = tuple(event for event in self._economic_events if event.Kind == 'SPLIT')
        self._split_times = tuple(_timestamp(event.Date) for event in self._split_events)
        self._split_ratios = {event.EventId: float(event.Ratio) for event in self._economic_events if event.Kind == "SPLIT"}
        self._quotes_by_start, self._quotes_by_end, self._quotes_by_slot = {}, {}, {}
        if execution_bars is not None:
            quotes = (execution_bars if type(execution_bars) is PreparedExecutionQuotes
                else PreparedExecutionQuotes.from_frame(execution_bars,self.spec.market_id))
            if quotes.market is not self.spec.market_id:
                raise ValueError('execution quotes belong to another market timezone')
            self._quotes_by_start, self._quotes_by_end, self._quotes_by_slot = quotes.by_start, quotes.by_end, quotes.by_slot
        self._uses_execution_bars = execution_bars is not None

    @contextmanager
    def transaction(self):
        # A confirmed earlier execution leg is a fact, not a reversible plan.
        extra = ('_position_last_interval', '_position_fees', '_position_buys',
                 '_position_sells', '_latest_position', '_cycle_budget', '_cycle_spent', '_event_cursor')
        state = {name: getattr(self, name) for name in (*_ACCOUNT_STATE, *extra)}
        state['_buy_locks'] = list(self._buy_locks)
        checkpoint = _TransitionCheckpoint(state, list(self.pending),
            {name: len(rows) for name, rows in self.rows.items()}, [], [])
        self._transactions.append(checkpoint)
        try:
            yield self
        except BaseException:
            if len(self.rows['fills']) > checkpoint.lengths['fills']:
                self._broken = True
            else:
                self.__dict__.update(state)
                self.pending = checkpoint.pending
                for key in checkpoint.completed_added:
                    self.completed.pop(key, None)
                for key in checkpoint.applied_added:
                    self.applied.discard(key)
                for name, length in checkpoint.lengths.items():
                    del self.rows[name][length:]
            raise
        finally:
            self._transactions.pop()

    def finish(self):
        if self._broken:
            raise ValueError('failed account cannot produce successful results')
        return super().finish()

    def _events(self, through, **kwargs):
        end = (bisect_right if kwargs.get('include_actions', True) else bisect_left)(self._event_times, through)
        ready = end > self._event_cursor
        due = any(stamp <= through for stamp, *_ in self.pending)
        if not ready and not due:
            return kwargs["plan_quantity"], kwargs["limit_price"]
        with self.transaction():
            before = len(self.rows['actions'])
            result = self._apply_events(self._economic_events[self._event_cursor:end], through, **kwargs)
            for row in self.rows['actions'][before:]:
                if row['kind'] == 'SPLIT':
                    ratio = self._split_ratios[row['event_id']]
                    locks = [(stamp, quantity * ratio) for stamp, quantity in self._buy_locks]
                    if any(not float(quantity).is_integer() for _, quantity in locks):
                        raise ValueError('fractional split sellability entitlement is unsupported')
                    self._buy_locks = [(stamp, int(quantity)) for stamp, quantity in locks]
                    if self._cycle_budget is not None:
                        from dataclasses import replace
                        target = self._cycle_budget.target_quantity * ratio
                        if not float(target).is_integer():
                            raise ValueError('fractional split budget entitlement is unsupported')
                        self._cycle_budget = replace(self._cycle_budget, target_quantity=int(target))
            self._event_cursor = max(self._event_cursor, end)
            return result

    def snapshot_at(self, observed_through, decision_at):
        scale = 1.
        first, end = bisect_left(self._split_times, observed_through), bisect_right(self._split_times, decision_at)
        for event in self._split_events[first:end]:
            scale /= float(event.Ratio)
        with self.transaction():
            self._events(decision_at, after=decision_at, plan_quantity=0, limit_price=None)
            return EquityPortfolio(self.cash, self.quantity, self.receivable, self.revision,
                self.cycle_entry, self.cycle_cost, reference_price_scale=scale,
                closed_cycle_feedback=self._closed_cycle_feedback)

    @property
    def cycle_budget(self):
        return self._cycle_budget

    def _sellable(self, stamp):
        return self.quantity - sum(quantity for unlock, quantity in self._buy_locks if unlock > stamp)

    def account_snapshot(self, point, instrument):
        if type(point) is not ReplayPoint or type(instrument) is not InstrumentId:
            raise TypeError('account snapshot requires typed point and instrument')
        self.spec.require_instrument(instrument)
        if self._instrument is not None and self._instrument != instrument:
            raise ValueError("account snapshot instrument changed")
        self._instrument = instrument
        self.snapshot_at(point.observed_through, point.decision_at)
        return AccountSnapshot(instrument, self.spec.account.currency, point.decision_at,
            self.revision, self.cash, self.cash, self.receivable, self.quantity,
            max(0, self._sellable(point.decision_at)))

    def recognized_events_since(self, cursor, through):
        """Return only recognized journal facts visible at the supplied clock.

        The cursor never advances past a not-yet-visible journal row. No future
        corporate-action source rows are inspected or exposed to the strategy.
        """
        from strategy_runtime.account_strategy import RecognizedAccountEvent, RecognizedEventKind
        rows = self.rows['actions']
        if type(cursor) is not int or not 0 <= cursor <= len(rows):
            raise ValueError('recognized event cursor is outside this account journal')
        through = _timestamp(through)
        if pd.isna(through) or through.tzinfo is None:
            raise TypeError('recognized event clock requires an aware timestamp')
        output = []
        while cursor < len(rows):
            row = rows[cursor]
            at = _timestamp(row['time'])
            if at > through:
                break
            effective = at.to_pydatetime() if hasattr(at,'to_pydatetime') else at
            output.append(RecognizedAccountEvent(row['event_id'],RecognizedEventKind(row['kind']),
                effective,int(row['quantity_before']),int(row['quantity_after']),
                float(row['cash_delta']),float(row['receivable_delta']),
                self._split_ratios[row['event_id']] if row['kind']=='SPLIT' else None))
            cursor += 1
        return tuple(output), cursor

    @property
    def position_feedback(self):
        from strategy_runtime.account_strategy import PositionCycle, PositionFeedback
        active = None
        if self.cycle is not None:
            active = PositionCycle(self.cycle, self._cycle_entry_interval,
                self._position_last_interval, self.quantity, self.cycle_cost,
                self.cycle_income, self._position_fees, self._position_buys, self._position_sells)
        return PositionFeedback(active, self._latest_position)

    def _constraints(self, plan, bar, constraint):
        if not isinstance(bar, Mapping) and not isinstance(bar, pd.Series):
            raise TypeError('execution requires a typed mapping or row')
        point = plan.point
        start, end = point.execution_start, point.execution_end
        if point.session_id != start.astimezone(_SESSION_ZONES[self.spec.market_id]).date().isoformat():
            raise ValueError("execution point belongs to another trading session")
        if _timestamp(bar['BarStart']) != start or _timestamp(bar['Date']) != end:
            raise ValueError('execution interval differs from observed bar')
        if (_timestamp(constraint['Date']) != start
                or _timestamp(constraint['AvailableDate']) > point.decision_at):
            raise ValueError('CAUSAL_TIME_VIOLATION: dated execution constraints')
        if (int(constraint['QuantityStep']), float(constraint['PriceTick'])) != (self.spec.quantity_step, self.spec.price_tick):
            raise ValueError('dated execution quantity/price units differ')
        unlock = _timestamp(constraint['BuySellableAt'])
        if pd.isna(unlock) or unlock.tzinfo is None or unlock < start:
            raise ValueError('buy sellability requires an explicit valid dated unlock')
        if type(constraint["Tradable"]) is not bool and type(constraint["Tradable"]).__name__ != "bool_":
            raise TypeError("dated tradability requires bool")
        if constraint.get('SellRemainderPolicy') not in {'STRICT_STEP', 'FULL_LIQUIDATION'}:
            raise ValueError('explicit dated sell remainder policy is required')
        policy = constraint['PriceLimitPolicy']
        bounds = (constraint.get('PriceLimitLower'), constraint.get('PriceLimitUpper'))
        if policy == 'DATED_LIMITS':
            local_start = start.astimezone(_SESSION_ZONES[self.spec.market_id])
            limits = SessionPriceLimits(local_start.date(), float(bounds[0]), float(bounds[1]), self.spec.price_tick)
        elif policy == 'EXPLICIT_UNBOUNDED' and all(pd.isna(value) for value in bounds):
            limits = None
        else:
            raise ValueError('explicit dated price-limit policy is missing or inconsistent')
        status = bar.get('BarStatus', 'OBSERVED')
        if status not in {'OBSERVED', 'MISSING', 'ZERO_VOLUME'}:
            raise ValueError('invalid bar status')
        blocked = bar.get('ExecutionBlocked', False)
        if type(blocked) is not bool and type(blocked).__name__ != 'bool_':
            raise TypeError('execution block flag requires bool')
        if status == 'MISSING':
            if not all(pd.isna(bar[name]) for name in ('Open', 'High', 'Low', 'Close', 'Volume', 'Amount')):
                raise ValueError('missing bar contains invented execution prices')
            quote = None
        else:
            quote = tuple(float(bar[name]) for name in ('Open', 'High', 'Low', 'Close', 'Volume'))
            opening, high, low, close, volume = quote
            if (not all(math.isfinite(value) for value in quote) or min(quote[:4]) <= 0
                    or volume < 0 or low > min(opening, close) or high < max(opening, close)):
                raise ValueError('invalid execution OHLCV')
            if 'BarStatus' in bar and (status == 'ZERO_VOLUME') != (volume == 0):
                raise ValueError('bar status differs from volume')
            if limits is not None and not all(limits.contains(value) for value in quote[:4]):
                raise ValueError('execution prices exceed declared dated limits')
        if self._uses_execution_bars:
            first, last = self._quotes_by_start.get(start), self._quotes_by_end.get(end)
            if first is None or last is None:
                raise ValueError('execution quotes do not cover decision interval boundaries')
            if quote is not None:
                for actual, expected in ((first[2][0], quote[0]),(last[2][3], quote[3])):
                    if actual is not None and not math.isclose(actual,expected,rel_tol=1e-10,abs_tol=0.):
                        raise ValueError('execution and decision quotes use inconsistent RAW price units')
        if bisect_right(self._event_times, start) < bisect_left(self._event_times, end):
            raise ValueError('CORPORATE_ACTION_UNSUPPORTED: event inside execution interval')
        return quote, limits, unlock, status, bool(blocked)

    def _checkpoint(self, leg, point, quote, status='OBSERVED', blocked=False):
        zone = _SESSION_ZONES[self.spec.market_id]
        is_open = leg.checkpoint == 'OPEN' or leg.checkpoint.endswith('_OPEN')
        if self._uses_execution_bars:
            if leg.checkpoint == 'OPEN':
                row = self._quotes_by_start.get(point.execution_start)
            elif leg.checkpoint == 'CLOSE':
                row = self._quotes_by_end.get(point.execution_end)
            else:
                row = self._quotes_by_slot.get((point.session_id,leg.checkpoint))
            if row is None:
                raise ValueError('CHECKPOINT_DATA_UNAVAILABLE: exact execution quote is absent')
            start,end,values,status,blocked = row
            if not point.execution_start <= start < end <= point.execution_end:
                raise ValueError('execution quote interval exceeds plan interval')
            stamp,price = (start,values[0]) if is_open else (end,values[3])
            source,volume,low,high = 'EXECUTION_BARS',values[4],values[2],values[1]
        else:
            if leg.checkpoint == 'OPEN' or leg.checkpoint == point.execution_start.astimezone(zone).strftime('%H:%M') + '_OPEN':
                stamp, price = point.execution_start, None if quote is None else quote[0]
            elif leg.checkpoint == 'CLOSE' or leg.checkpoint == point.execution_end.astimezone(zone).strftime('%H:%M') + '_CLOSE':
                stamp, price = point.execution_end, None if quote is None else quote[3]
            else:
                raise ValueError('CHECKPOINT_DATA_UNAVAILABLE: no exact observed boundary quote')
            start,end = point.execution_start,point.execution_end
            source,volume = 'DECISION_BAR',0. if quote is None else quote[4]
            low,high = (None,None) if quote is None else (quote[2],quote[1])
        if not leg.submit_after <= stamp <= leg.submit_before:
            raise ValueError('checkpoint is outside the declared submission interval')
        return _CheckpointQuote(stamp,price,start,end,volume,status,blocked,source,low,high)

    def execute_account_plan(self, plan, bar, *, constraint):
        if self._transactions:
            return self._execute_account_plan(plan, bar, constraint=constraint)
        with self.transaction():
            return self._execute_account_plan(plan, bar, constraint=constraint)

    def _execute_account_plan(self, plan, bar, *, constraint):
        if self._broken:
            raise ValueError("failed account requires a new independent replay")
        if type(plan) is not AccountExecutionPlan:
            raise TypeError('v4 execution requires AccountExecutionPlan')
        evidence = plan.evidence
        if evidence.get('sizing') not in {'TARGET_FRACTION', 'EXPLICIT_ORDERS'}:
            raise ValueError('execution requires explicit sizing evidence')
        if evidence.get('specification_hash') != self.spec.fingerprint or evidence.get('fee_rate') != self.fee_rate:
            raise ValueError('MARKET_CONTRACT_MISMATCH: neutral plan execution specification')
        for name in ('target', 'reference_price'):
            value = evidence.get(name)
            if type(value) not in (float, int) or not math.isfinite(value):
                raise ValueError('execution requires finite target and reference evidence')
        if not 0 <= evidence['target'] <= 1 or evidence['reference_price'] <= 0:
            raise ValueError('invalid target/reference evidence')
        signal_status = evidence.get('signal_status', 'EVALUATED')
        if signal_status not in {'EVALUATED', 'SUPPRESSED_UNOBSERVED_BAR'}:
            raise ValueError('invalid signal status')
        if signal_status == 'SUPPRESSED_UNOBSERVED_BAR' and (plan.orders or plan.legs or plan.target_quantity != self.quantity):
            raise ValueError('suppressed input cannot submit orders or change target')
        if self._neutral_owner is not None and self._neutral_owner != plan.owner:
            raise ValueError('account owner differs from execution plan')
        plan_facts = _serial(plan)
        content = equity_hash({'plan': plan_facts, 'bar': {k: _bar_identity_value(v) for k, v in bar.items()},
                              'constraints': {k: _bar_identity_value(v) for k, v in constraint.items()}})
        if plan.plan_identity in self.completed:
            if self.completed[plan.plan_identity] != content:
                raise ValueError('same plan was resubmitted with different execution facts')
            return self.snapshot()
        if plan.expected_revision != self.revision or (self.last_end is not None and plan.point.execution_start < self.last_end):
            raise ValueError('stale revision or unordered execution interval')
        left = bisect_right(self._split_times, plan.point.decision_at)
        right = bisect_right(self._split_times, plan.point.execution_start)
        for event in self._split_events[left:right]:
            if event.EventId not in self.applied:
                raise ValueError('CORPORATE_ACTION_UNSUPPORTED: submitted plan spans quantity units')
        quote, limits, unlock, status, blocked = self._constraints(plan, bar, constraint)
        self._events(plan.point.execution_start, after=plan.point.decision_at, plan_quantity=0, limit_price=None)
        if plan.capital_mode not in {'target_equity_fraction', 'full_available_cash', 'signal_cash_fraction'}:
            raise ValueError('unsupported account capital mode')
        if plan.capital_mode == 'signal_cash_fraction':
            if plan.cycle_before != self._cycle_budget:
                raise ValueError('cycle budget before differs from confirmed account state')
            if plan.cycle_after is None and plan.target_quantity:
                raise ValueError('cycle allocation requires a declared budget')
            if plan.cycle_before is not None and plan.cycle_after is not None:
                if any(getattr(plan.cycle_before, name) != getattr(plan.cycle_after, name) for name in (
                        'cycle_id', 'target_quantity', 'allocation_fraction', 'cash_budget', 'buy_cost_including_fees')):
                    raise ValueError('cycle budget cannot be rebuilt while active')
            if plan.cycle_after is not None and plan.target_quantity > plan.cycle_after.target_quantity:
                raise ValueError('plan quantity exceeds declared cycle target')
        sequence = tuple((leg.sequence, leg.order, leg) for leg in plan.legs) if plan.legs else tuple(
            (index, order, None) for index, order in enumerate(plan.orders))
        if plan.orders and len({order.side for order in plan.orders}) > 1:
            raise ValueError("mixed-side execution requires observed checkpoint dependency legs")
        projected = self.quantity
        previous_checkpoint = None
        leg_quotes = {}
        for _, order, leg in sequence:
            if order.quantity % self.spec.quantity_step:
                full_exit = (order.side is OrderSide.SELL and order.quantity == projected
                    and constraint['SellRemainderPolicy'] == 'FULL_LIQUIDATION')
                if not full_exit:
                    raise ValueError('order quantity violates declared instrument step')
            if order.order_type is OrderType.LIMIT:
                tick = Decimal(str(self.spec.price_tick))
                if Decimal(str(order.limit_price)) % tick:
                    raise ValueError('limit price violates declared tick')
            projected += order.quantity if order.side is OrderSide.BUY else -order.quantity
            if projected < 0:
                raise ValueError('plan requests a short position')
            if leg is not None:
                if leg.dependency_required_status not in (None, "FILLED", "EXPIRED"):
                    raise ValueError("unsupported execution dependency status")
                checkpoint_quote = self._checkpoint(leg,plan.point,quote,status,blocked)
                checkpoint_stamp = checkpoint_quote.stamp
                if quote is not None and checkpoint_quote.low is not None:
                    tolerance=max(abs(quote[1]),abs(quote[2]))*1e-10
                    if checkpoint_quote.low < quote[2]-tolerance or checkpoint_quote.high > quote[1]+tolerance:
                        raise ValueError('execution source quote exceeds decision bar price range')
                if limits is not None and checkpoint_quote.low is not None:
                    if not limits.contains(checkpoint_quote.low) or not limits.contains(checkpoint_quote.high):
                        raise ValueError('execution source quotes exceed declared price limits')
                if previous_checkpoint is not None and checkpoint_stamp < previous_checkpoint:
                    raise ValueError("execution dependency reverses observed checkpoint time")
                previous_checkpoint = checkpoint_stamp
                leg_quotes[leg.sequence] = checkpoint_quote
        if projected != plan.target_quantity:
            raise ValueError('plan target differs from declared order quantities')
        if plan.capital_mode == "signal_cash_fraction" and self._cycle_budget is None and plan.cycle_after is not None:
            if plan.cycle_after.cash_budget > Decimal(str(self.cash)) * plan.cycle_after.allocation_fraction:
                raise ValueError("cycle budget exceeds declared available cash allocation")
        # Validate all structural facts before recognizing events or any fill.
        point = plan.point
        self._buy_locks = [(stamp, quantity) for stamp, quantity in self._buy_locks if stamp > point.execution_start]
        self._neutral_owner = plan.owner
        if plan.capital_mode == "signal_cash_fraction":
            if plan.cycle_after is not None:
                self._cycle_budget = plan.cycle_after
        decision = {'decision_id': plan.plan_identity, 'observed_through': point.observed_through,
            'decision_at': point.decision_at, 'execution_start': point.execution_start,
            'execution_end': point.execution_end, 'target': getattr(plan, 'target_fraction', None),
            'target_quantity': plan.target_quantity, 'portfolio_revision': plan.expected_revision,
            'signal_status': signal_status, 'plan': plan_facts}
        decision["explanation"] = plan_facts['evidence'].get("explanation")
        decision["target"] = plan_facts['evidence']['target']
        instructions = tuple(order for _, order, _ in sequence)
        sides = {order.side.value for order in instructions}
        decision['reference_price'] = float(evidence['reference_price'])
        decision['quantity'] = sum(order.quantity for order in instructions)
        decision['side'] = next(iter(sides)) if len(sides) == 1 else 'MIXED' if sides else 'HOLD'
        decision['limit_price'] = (float(instructions[0].limit_price)
            if len(instructions) == 1 and instructions[0].order_type is OrderType.LIMIT else None)
        self.rows['decisions'].append(decision)
        consumed, outcomes = {}, {}
        for number, order, leg in sequence:
            identity = f'{plan.plan_identity}:{number}'
            reason, price, precision = 'NOT_TRADABLE', None, None
            fill_interval = TimeInterval(point.execution_start, point.execution_end)
            source = leg_quotes[number] if leg is not None else _CheckpointQuote(point.execution_start,
                None if quote is None else quote[0],point.execution_start,point.execution_end,
                0. if quote is None else quote[4],status,blocked,'DECISION_BAR',
                None if quote is None else quote[2],None if quote is None else quote[1])
            volume_key = (source.start,source.end)
            if leg is not None:
                self._pay(source.stamp, inclusive=True)
            if source.status == 'MISSING':
                reason = 'MISSING_EXECUTION_BAR' if source.source == 'EXECUTION_BARS' else 'MISSING_BAR'
            elif source.status == 'ZERO_VOLUME':
                reason = 'ZERO_VOLUME'
            elif source.blocked:
                reason = 'KNOWN_INTERRUPTION'
            elif leg is not None and leg.dependency_sequence is not None and outcomes.get(leg.dependency_sequence) != leg.dependency_required_status:
                reason = 'DEPENDENCY_NOT_FILLED'
            elif not bool(constraint['Tradable']):
                reason = 'NOT_TRADABLE'
            elif consumed.get(volume_key,0) + order.quantity > source.volume:
                reason = 'INSUFFICIENT_BAR_VOLUME'
            elif order.quantity % self.spec.quantity_step and (order.side is not OrderSide.SELL
                    or constraint['SellRemainderPolicy'] != 'FULL_LIQUIDATION' or order.quantity != self.quantity):
                reason = 'ODD_LOT_REQUIRES_FULL_LIQUIDATION'
            elif order.side is OrderSide.SELL and order.quantity > self._sellable(point.execution_start if leg is None else source.stamp):
                reason = 'INSUFFICIENT_SELLABLE_QUANTITY'
            else:
                if leg is None:
                    open_price = quote[0]
                    at = point.execution_start
                    touch_at = point.execution_end
                    touch = quote[2] if order.side is OrderSide.BUY else quote[1]
                    touches = ((touch_at, touch),)
                else:
                    at, open_price = source.stamp, source.price
                    touch_at, touches = at, ()
                local_at = at.astimezone(_SESSION_ZONES[self.spec.market_id])
                local_touches = tuple((stamp.astimezone(local_at.tzinfo), value) for stamp, value in touches)
                fill = resolve_fill(OrderSpec(order.side.value, order.order_type.value, order.quantity,
                    None if order.limit_price is None else float(order.limit_price)), session_open=open_price,
                    session_time=local_at, intraday_touches=local_touches, slippage_bp=self.spec.slippage_bp,
                    inclusive_touch=self.spec.inclusive_touch, session_limits=limits)
                reason = fill.reason or 'FILLED'
                if fill.filled:
                    actual_price = float(fill.price)
                    if order.side is OrderSide.BUY and order.order_type is OrderType.LIMIT and actual_price > float(order.limit_price):
                        reason = 'SLIPPAGE_EXCEEDS_LIMIT'
                    elif order.side is OrderSide.BUY and order.quantity * actual_price * (1 + self.fee_rate) > self.cash + 1e-9:
                        reason = 'INSUFFICIENT_CASH'
                    elif order.side is OrderSide.BUY and not self._budget_allows(plan, order.quantity, actual_price):
                        reason = 'CYCLE_BUDGET_EXCEEDED'
                    else:
                        price = actual_price
                        precision = 'MODEL_CHECKPOINT' if leg is not None else 'BAR_INTERVAL' if fill.trigger == 'INTRADAY_LIMIT' else 'MODEL_BAR_OPEN'
                        if leg is not None:
                            # Interval remains the original actual execution observation;
                            # exact checkpoint time is retained separately on the fill.
                            touch_at = at
            row = {'order_id': identity, 'decision_id': plan.plan_identity, 'sequence': number,
                'side': order.side.value, 'order_type': order.order_type.value, 'quantity': order.quantity,
                'limit_price': None if order.limit_price is None else float(order.limit_price),
                'valid_start': point.execution_start, 'valid_end': point.execution_end,
                'status': 'FILLED' if price is not None else 'EXPIRED', 'reason': reason,
                'quote_interval_start':source.start,'quote_interval_end':source.end,'quote_source':source.source,
                'checkpoint': None if leg is None else leg.checkpoint,
                'dependency_sequence': None if leg is None else leg.dependency_sequence,
                'dependency_required_status': None if leg is None else leg.dependency_required_status}
            self.rows['orders'].append(row)
            outcomes[number] = row['status']
            if price is not None:
                self._post_position_fill(plan, order, identity, price, fill_interval, unlock, constraint,
                    precision, (touch_at if leg is not None else point.execution_start if precision == 'MODEL_BAR_OPEN' else point.execution_end), source)
                consumed[volume_key] = consumed.get(volume_key,0) + order.quantity
        self._events(point.execution_end, after=point.execution_start, plan_quantity=0, limit_price=None, include_actions=False)
        stale = status != 'OBSERVED'
        if not stale:
            self.last_mark_price, self.last_mark_time = quote[3], point.execution_end
        if self.last_mark_price is None:
            self.last_mark_price = float(evidence['reference_price'])
            self.last_mark_time = point.observed_through
        self.rows['points'].append({'time': point.execution_end, 'account_revision': self.revision,
            'session': point.session_id, 'cash': self.cash, 'quantity': self.quantity,
            'receivable': self.receivable, 'close': self.last_mark_price,
            'equity': self.cash + self.receivable + self.quantity * self.last_mark_price,
            'bar_status': status, 'valuation_stale': stale, 'valuation_price_at': self.last_mark_time,
            'execution_blocked': blocked, 'cycle_id': self.cycle, 'decision_id': plan.plan_identity})
        if self.quantity == 0 and plan.target_quantity == 0:
            self._cycle_budget = None
            self._cycle_spent = Decimal(0)
        self.revision += 1
        self.last_end = point.execution_end
        for checkpoint in self._transactions:
            checkpoint.completed_added.append(plan.plan_identity)
        self.completed[plan.plan_identity] = content
        return self.snapshot()

    def _budget_allows(self, plan, quantity, price):
        if plan.capital_mode != 'signal_cash_fraction':
            return True
        budget = plan.cycle_after
        spent = self._cycle_spent
        return spent + Decimal(quantity) * Decimal(str(price)) * (1 + Decimal(str(self.fee_rate))) <= budget.cash_budget

    def _post_position_fill(self, plan, order, identity, price, interval, unlock, constraint, precision, stamp, quote):
        if order.side is OrderSide.BUY and self.cycle is None:
            self.cycle = identity
            self.cycle_entry = interval.start
            self.cycle_cost = self.cycle_income = self._position_fees = 0.
            self._position_buys = self._position_sells = 0
            self._cycle_entry_interval = interval
            self._cycle_spent = Decimal(0)
        deferred = order.side is OrderSide.SELL and self.spec.account.cash_availability is CashAvailabilityPolicy.SETTLED_ONLY
        if deferred:
            settle = _timestamp(constraint['SettlementAt'])
            if pd.isna(settle) or settle.tzinfo is None or settle < (stamp if precision == 'MODEL_CHECKPOINT' else interval.end):
                raise ValueError('missing or invalid settlement time')
        self.cash, self.quantity, self.receivable, gross, fees, proceeds = _post_confirmed_fill(
            self.cash, self.quantity, self.receivable, order.side is OrderSide.BUY, order.quantity,
            price, self.fee_rate, deferred)
        if order.side is OrderSide.BUY:
            self.cycle_cost += gross + fees
            self._cycle_spent += Decimal(order.quantity) * Decimal(str(price)) * (1 + Decimal(str(self.fee_rate)))
            self._position_buys += 1
            self._buy_locks.append((unlock, order.quantity))
        else:
            self.cycle_income += proceeds
            self._position_sells += 1
            if deferred:
                self.pending.append((settle, proceeds, identity, 'SALE_SETTLEMENT'))
        self._position_fees += fees
        self._position_last_interval = interval
        self._closed_cycle_feedback = None
        self.rows['fills'].append({'fill_id': identity, 'order_id': identity,
            'account_revision': self.revision, 'cycle_id': self.cycle, 'side': order.side.value,
            'quantity': order.quantity, 'price': price, 'fees': fees,
            'interval_start': interval.start, 'interval_end': interval.end,
            'executed_at': stamp, 'time_precision': precision,
            'quote_interval_start':quote.start,'quote_interval_end':quote.end,'quote_source':quote.source})
        if plan.capital_mode == 'signal_cash_fraction':
            from dataclasses import replace
            if self._cycle_budget is not None:
                self._cycle_budget = replace(self._cycle_budget, buy_cost_including_fees=self._cycle_spent)
        if self.quantity == 0 and self.cycle is not None:
            self.rows['trades'].append({'cycle_id': self.cycle, 'entry_at': self.cycle_entry,
                'exit_at': interval.end, 'cost': self.cycle_cost, 'income': self.cycle_income,
                'net_pnl': self.cycle_income - self.cycle_cost, 'net_return': self.cycle_income / self.cycle_cost - 1,
                'status': 'CLOSED'})
            from strategy_runtime.account_strategy import PositionCycle
            self._latest_position = PositionCycle(self.cycle, self._cycle_entry_interval, interval,
                0, self.cycle_cost, self.cycle_income, self._position_fees, self._position_buys, self._position_sells)
            self.cycle = None
            self._cycle_budget = None
            self._cycle_spent = Decimal(0)
