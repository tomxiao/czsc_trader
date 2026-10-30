"""V4 market-neutral batch/stateful planning on the common replay lifecycle."""
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from time import perf_counter
import math

from dataflows import BarFrequency, TimeInterval
from .contracts import OrderSide, OrderType
from .equity import DecisionPoint, ResearchExecutionSpec, equity_hash
from .equity_replay import (PreparedReplay, CycleState, StateRecord, ReplayOutcome,
    ReplayStatistics, ReplayFailure, _Visibility, _FeatureEvaluator)
from .replay_contracts import (AccountExecutionPlan, ReplayOrder, ReplayPoint,
    ExecutionPrecision, StrategyComputation, AccountSnapshot)
from .replay_kernel import run_account_replay
from .account_strategy import (AccountStepContext, AccountStepResult, AccountDecision,
    BatchObservation, BatchAccountContext, SellRemainderPolicy, AccountStrategyState)


def plan_account_decision(decision, point, account, reference, spec, *, owner, implementation, fee_rate, sell_remainder_policy):
    """Resolve a desired fraction using confirmed cash, legal units and price tick."""
    if type(decision) is not AccountDecision:
        raise TypeError('account planning requires AccountDecision')
    if type(point) is not ReplayPoint or type(account) is not AccountSnapshot or type(spec) is not ResearchExecutionSpec:
        raise TypeError('account planning requires typed point, account and execution contract')
    spec.require_instrument(account.instrument)
    if account.currency!=spec.account.currency:
        raise ValueError('account currency differs from execution contract')
    if type(reference) not in (float,int) or not math.isfinite(reference) or reference<=0:
        raise ValueError('planning reference must be finite positive price')
    if type(fee_rate) not in (float,int) or not math.isfinite(fee_rate) or not 0<=fee_rate<1:
        raise ValueError('planning fee must be finite in [0,1)')

    if type(sell_remainder_policy) is not SellRemainderPolicy:
        raise TypeError('automatic planning requires declared sell remainder policy')
    step = spec.quantity_step
    orders, legs = decision.orders, decision.legs
    mode = 'DEPENDENCY_LEGS' if legs else 'EXPLICIT_ORDERS' if orders else 'TARGET_FRACTION'
    desired = None
    if not orders and not legs:
        if decision.capital_mode == 'full_available_cash' and decision.target not in (0,1):
            raise ValueError('full_available_cash supports flat/long only')
        equity = Decimal(str(account.cash)) + Decimal(str(account.receivable)) + Decimal(account.quantity) * Decimal(str(reference))
        desired = int(equity * Decimal(str(decision.target)) / Decimal(str(reference)) / step) * step
        if decision.capital_mode == 'full_available_cash' and account.quantity and decision.target:
            desired = account.quantity
        if decision.capital_mode == 'signal_cash_fraction':
            budget = decision.cycle_after or decision.cycle_before
            if budget is None:
                raise ValueError('cycle allocation requires explicit budget facts')
            desired = budget.target_quantity if decision.target else 0
        if desired > account.quantity:
            tick = Decimal(str(spec.price_tick))
            price = ((Decimal(str(reference)) * (1+Decimal(str(spec.buy_premium))) / tick).to_integral_value(rounding=ROUND_FLOOR) * tick)
            available = Decimal(str(account.available_cash))
            if decision.capital_mode == 'signal_cash_fraction':
                available = min(available, budget.cash_budget-budget.buy_cost_including_fees)
            affordable = max(0, int(available / (price * (1+Decimal(str(fee_rate)))) / step) * step)
            amount = min(desired-account.quantity, affordable) // step * step
            if amount:
                orders = (ReplayOrder(OrderSide.BUY, amount, OrderType.LIMIT, float(price)),)
        elif desired < account.quantity:
            amount = min(account.quantity-desired, account.sellable_quantity)
            # Partial reductions use the declared unit. Full liquidation may
            # legally dispose of an integer split remainder under an explicit rule.
            if amount < account.quantity or sell_remainder_policy is SellRemainderPolicy.STRICT_STEP:
                amount = amount // step * step
            if amount:
                orders = (ReplayOrder(OrderSide.SELL, amount, OrderType.MARKET),)
    instructions = orders if orders else tuple(leg.order for leg in legs)
    target = account.quantity + sum(order.quantity * (1 if order.side is OrderSide.BUY else -1) for order in instructions)
    if target < 0:
        raise ValueError('orders exceed confirmed holdings')
    evidence = {'planning_mode': mode, 'sizing': 'TARGET_FRACTION' if mode == 'TARGET_FRACTION' else 'EXPLICIT_ORDERS',
                'desired_quantity': desired, 'target': float(decision.target), 'explanation': decision.explanation.to_dict(),
                'reference_price': reference, 'implementation': implementation, 'fee_rate': fee_rate,
                'specification_hash': spec.fingerprint}
    identity = equity_hash({'owner': owner, 'point': {'observed_through': point.observed_through,
        'decision_at': point.decision_at, 'start': point.execution_start, 'end': point.execution_end},
        'revision': account.revision, 'target': target, 'orders': [(x.side.value,x.quantity,x.order_type.value,x.limit_price) for x in orders],
        'legs': [(x.sequence,x.checkpoint,x.submit_after,x.submit_before,x.order.side.value,x.order.quantity,
                  x.order.order_type.value,x.order.limit_price,x.dependency_sequence,x.dependency_required_status) for x in legs],
        'capital_mode': decision.capital_mode,
        'cycle_before': None if decision.cycle_before is None else repr(decision.cycle_before),
        'cycle_after': None if decision.cycle_after is None else repr(decision.cycle_after), 'evidence':evidence})
    return AccountExecutionPlan(identity, owner, point, account.revision, target, orders, legs,
        decision.capital_mode, decision.cycle_before, decision.cycle_after, evidence)


def run_account_v4(prepared, candidate, executor, *, start, end, fee_rate, initial_state=None, owner=None):
    started = perf_counter()
    if type(prepared) is not PreparedReplay:
        raise TypeError('account replay requires PreparedReplay')
    definition, spec = candidate.definition, candidate.definition.execution_spec
    if definition.contract_version != 4 or spec.decision_clock not in (BarFrequency.DAILY, BarFrequency.M30):
        raise ValueError('account replay requires explicit V4 clock contract')
    if prepared.frequency is not spec.decision_clock:
        raise ValueError('prepared decision clock differs from strategy')
    if definition.feature_graph != prepared.graph or spec.data_latency_seconds != prepared._data.latency_seconds:
        raise ValueError('prepared feature/visibility contract differs')
    if not prepared._sessions or not prepared._calendar_intervals:
        raise ValueError('V4 replay requires explicit certified session evidence')
    if any(type(value) is not datetime or value.tzinfo is None for value in (start,end)) or start>=end:
        raise ValueError('account replay requires an aware positive window')
    if type(fee_rate) not in (float,int) or not math.isfinite(fee_rate) or not 0<=fee_rate<1:
        raise ValueError('account fee must be finite in [0,1)')
    if executor.spec.fingerprint != spec.fingerprint or executor.fee_rate != fee_rate:
        raise ValueError('executor contract differs from replay')
    owner = candidate.candidate_id if owner is None else owner
    if type(owner) is not str or not owner:
        raise TypeError('account replay requires owner identity')
    state = AccountStrategyState(account=definition.initial_account if definition.initial_account is not None else StateRecord()) if initial_state is None else initial_state
    if type(state) is not AccountStrategyState:
        raise TypeError('V4 account replay requires AccountStrategyState')
    binding = equity_hash({'owner':owner,'implementation':candidate.implementation_hash,'prepared':prepared.identity,
                          'specification':spec.fingerprint,'fee_rate':fee_rate})
    if state.binding not in (None,binding) or (state.revision>0 and state.binding is None):
        raise ValueError('strategy state belongs to another account')
    schema = definition.state_schema
    schema.validate_record(state.account,scope='account')
    if state.cycle is not None:
        schema.validate_record(state.cycle.values,scope='cycle')
    data = prepared._data
    intervals = dict(prepared._calendar_intervals)
    ticks = tuple((i,a,b) for i,(a,b) in enumerate(zip(data.starts,data.ends)) if a>=start and b<=end)
    if not ticks or ticks[0][1] != start or ticks[-1][2] != end:
        raise ValueError('account window must align with its complete execution grid')
    if any((a,b) not in intervals for _,a,b in ticks):
        raise ValueError('execution interval absent from declared calendar')
    expected_grid=[]
    for session,_ in prepared._sessions:
        if session.timezone != candidate.instrument.timezone:
            raise ValueError('prepared session timezone differs from instrument')
        periods = (TimeInterval(session.segments[0].start, session.segments[-1].end),) if spec.decision_clock is BarFrequency.DAILY else session.bars(spec.decision_clock)
        expected_grid.extend((period.start,period.end) for period in periods if period.start>=start and period.end<=end)
    if tuple((a,b) for _,a,b in ticks)!=tuple(expected_grid):
        raise ValueError('execution rows do not cover the declared clock grid')

    feature_start = perf_counter()
    visibility = _Visibility(data)
    evaluator = _FeatureEvaluator(data,prepared.graph,visibility)
    auxiliary = {name:(_Visibility(item),item) for name,item in prepared._auxiliary}
    feature_seconds = perf_counter()-feature_start
    decisions=rows=0

    def observation(tick):
        nonlocal feature_seconds
        _,a,b=tick
        visibility.advance(a)
        if visibility.count<definition.warmup_bars:
            raise ValueError('WARMUP_INSUFFICIENT: visible observed history')
        current=visibility.row(0)
        point=DecisionPoint(data.ends[current],a, TimeInterval(a,b))
        views={}
        for declaration in definition.auxiliary_inputs:
            if declaration.name not in auxiliary:
                raise ValueError('AUXILIARY_INPUT_UNAVAILABLE: '+declaration.name)
            indexer,item=auxiliary[declaration.name]
            indexer.advance(a)
            if indexer.count<declaration.warmup_bars:
                raise ValueError('AUXILIARY_WARMUP_INSUFFICIENT: '+declaration.name)
            latest=indexer.row(0)
            if not item.observed[indexer.latest_completed] or float(item.rows[latest]['Volume'])<=0:
                raise ValueError('AUXILIARY_INPUT_UNAVAILABLE: '+declaration.name)
            if (a-item.ends[latest]).total_seconds()>declaration.max_age_seconds:
                raise ValueError('AUXILIARY_INPUT_STALE: '+declaration.name)
            views[declaration.name]=indexer.history_view(a)
        session,available=prepared._sessions[intervals[(a,b)]]
        if available>a:
            raise ValueError('session calendar is not yet available')
        before=perf_counter()
        features=evaluator.at(a)
        history=visibility.history_view(a)
        feature_seconds+=perf_counter()-before
        return point,features,history,views,session,available,not data.observed[visibility.latest_completed]

    batch={}
    batch_inputs={}
    if definition.computation is StrategyComputation.BATCH_HISTORY:
        observations=[]
        batch_ticks=[]
        for tick in ticks:
            current = observation(tick)
            batch_inputs[tick[1]] = current
            point,features,history,views,session,available,suppressed = current
            if not suppressed:
                observations.append(BatchObservation(point,features,history,views,session if definition.session_context else None,available if definition.session_context else None))
                batch_ticks.append(tick[1])
        outputs=candidate.calculate_account_batch(BatchAccountContext(tuple(observations),definition.parameters))
        batch=dict(zip(batch_ticks,outputs,strict=True))

    class Driver:
        def transaction(self,tick):
            self.prior=state
            return executor.transaction()
        def snapshot(self,tick):
            nonlocal state
            self.observation=batch_inputs[tick[1]] if definition.computation is StrategyComputation.BATCH_HISTORY else observation(tick)
            point,_,_,_,session,_,_=self.observation
            self.constraint=data.constraints[tick[0]]
            if self.constraint is None or self.constraint['AvailableDate']>tick[1]:
                raise ValueError('trading constraint unavailable at decision')
            self.sell_policy=SellRemainderPolicy(self.constraint['SellRemainderPolicy'])
            self.point=ReplayPoint(point.observed_through,point.decision_at,tick[1],tick[2],
                                  session.session_date.isoformat(),ExecutionPrecision.BAR_INTERVAL)
            self.portfolio=executor.snapshot_at(point.observed_through,point.decision_at)
            self.account=executor.account_snapshot(self.point,candidate.instrument)
            self.events=()
            self.next_event_cursor=state.event_cursor
            if definition.computation is StrategyComputation.STATEFUL_STEP and not self.observation[-1]:
                self.events,self.next_event_cursor=executor.recognized_events_since(state.event_cursor,self.point.decision_at)

            if self.portfolio.revision!=state.revision or bool(self.portfolio.quantity)!=(state.cycle is not None):
                raise ValueError('strategy state differs from confirmed execution')
            if state.cycle is not None and (state.cycle.entry_at!=self.portfolio.cycle_entry or state.cycle.cycle_id!=executor.cycle):
                raise ValueError('strategy cycle differs from confirmed fills')
            return self.portfolio
        def decide(self,tick,portfolio):
            nonlocal decisions
            point,features,history,views,session,available,suppressed=self.observation
            if suppressed:
                proposal=AccountStepResult(AccountDecision.from_facts(float(portfolio.quantity>0),'unobserved input',
                    facts={'suppressed':True},next_watch='next observed bar'),state.account,
                    state.cycle.values if state.cycle else None)
                identity=equity_hash({'owner':owner,'point':repr(self.point),'revision':portfolio.revision,'suppressed':True})
                self.proposal=proposal
                return AccountExecutionPlan(identity,owner,self.point,portfolio.revision,portfolio.quantity,
                    evidence={'signal_status':'SUPPRESSED_UNOBSERVED_BAR','target':float(portfolio.quantity>0),
                              'sizing':'EXPLICIT_ORDERS', 'planning_mode':'EXPLICIT_ORDERS',
                              'reference_price':float(history.last()['Close'])*portfolio.reference_price_scale,
                              'specification_hash':spec.fingerprint, 'fee_rate':fee_rate})
            if definition.computation is StrategyComputation.BATCH_HISTORY:
                proposal=AccountStepResult(batch[tick[1]],state.account,StateRecord())
            else:
                ctx=AccountStepContext(point,portfolio,self.account,executor.position_feedback,
                    definition.parameters,features,history,budget=executor.cycle_budget,events=self.events,auxiliary_histories=views,session=session if definition.session_context else None,session_available_at=available if definition.session_context else None)
                proposal=candidate.account_step(ctx,state)
            if (portfolio.quantity or proposal.decision.target or any(order.side is OrderSide.BUY for order in proposal.decision.orders)
                    or any(leg.order.side is OrderSide.BUY for leg in proposal.decision.legs)) and proposal.cycle_values is None:
                raise ValueError('holding/entry requires typed cycle state')
            self.proposal=proposal
            reference=float(history.last()['Close'])*portfolio.reference_price_scale
            decisions+=1
            return plan_account_decision(proposal.decision,self.point,self.account,reference,spec,
                owner=owner,implementation=candidate.implementation_hash,fee_rate=fee_rate,
                sell_remainder_policy=self.sell_policy)
        def execute(self,tick,plan):
            constraint=data.constraints[tick[0]]
            if constraint is None or constraint['AvailableDate']>tick[1]:
                raise ValueError('trading constraint unavailable at decision')
            return executor.execute_account_plan(plan,data.rows[tick[0]],constraint=constraint)
        def commit(self,tick,before,plan,after):
            nonlocal state,rows
            if after.revision!=before.revision+1:
                raise ValueError('account transition must advance revision once')
            cycle=None
            if after.quantity:
                values=self.proposal.cycle_values
                if values is None:
                    raise ValueError('holding requires explicit cycle state')
                schema.validate_record(values,scope='cycle')
                cycle=CycleState(executor.cycle,after.cycle_entry,values)
            state=AccountStrategyState(after.revision,self.proposal.account,cycle,binding,self.next_event_cursor)
            rows+=1
        def failure(self,tick,error):
            nonlocal state
            state=self.prior
            return ReplayFailure(state,tick[1],error)
        def finish(self):
            return executor.finish()
    result=run_account_replay(ticks,Driver())
    return ReplayOutcome(result,state,ReplayStatistics(feature_seconds,perf_counter()-started,rows,decisions))
