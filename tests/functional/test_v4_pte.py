"""Native dual-market state follows actual PTE adoption and cumulative fills."""
from datetime import timedelta
from decimal import Decimal
import json

import pytest
from dataflows import MarketId, EquityProduct, TimeInterval
from strategy_runtime import StrategyComputation
from strategy_runtime.inspection import InspectionRuntimePermit
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.store import PaperStore
from paper_trading_engine.equity_contracts import EquityAccountRules, EquityOrderReport, equity_channel_id
from paper_trading_engine.equity_advice import EquityAdviceClient, prepare_equity_decision
from paper_trading_engine.equity_execution import EquityExecution
from test_equity_pte import RecordedChannel
from test_v4_inspection_roundtrip import native_fixture


def native_account(tmp_path, market, computation=StrategyComputation.STATEFUL_STEP, *, etf=False, intraday=False):
    context, request, products, _ = native_fixture(tmp_path, market, computation)
    if etf:
        from dataclasses import replace
        from dataflows import InstrumentId, AssetClass
        from czsc_trader.research_tools import ResearchExecutionSession
        instrument = InstrumentId(market, AssetClass.ETF, '510500.SH' if market is MarketId.CN else 'SOXX')
        candidate = replace(request.candidate, definition=replace(request.candidate.definition,
            instrument=instrument, auxiliary_inputs=()))
        request = replace(request, candidate=candidate, prepared=None, input_binding=None, audit_inputs_sha256=None)
        with ResearchExecutionSession(context, experiment=request.experiment) as execution:
            request = context.evaluation.prepare(request, execution=execution).request
    if intraday:
        context, request, products = intraday_inputs(context, request, products)
    workspace = tmp_path / '.tmp/strategy-inspection/native-pte'
    isolated = workspace / 'repository'
    isolated.mkdir(parents=True)
    permit = InspectionRuntimePermit('native-pte', 'S999-v1', 'a'*64, 'b'*64, 'c'*64, isolated, workspace)
    store = PaperStore(workspace / 'paper.db', inspection_permit=permit)
    channel_id = equity_channel_id(request.candidate.instrument)
    store.create_virtual_account('native', 'native', 'v1', 'a'*64, request.initial_cash,
        symbol=request.candidate.instrument.symbol, asset_type=request.candidate.instrument.asset_class.value.lower(),
        strategy_id='S999', strategy_name_snapshot='native', strategy_version='v1', release_hash='a'*64,
        qualification_snapshot='INSPECTION', selection_data_cutoff='2026-10-12', channel_id=channel_id,
        equity_rules=EquityAccountRules(request.candidate.instrument, context.execution_spec))
    store.set_virtual_paused('native', False)
    channel = RecordedChannel()
    channel.channel_id = channel_id
    return context, request, products, store, permit, channel


def test_native_cn_etf_uses_declared_lots_and_account_rules(tmp_path):
    context, request, products, store, _, channel = native_account(tmp_path, MarketId.CN, etf=True)
    rules = store.equity_account_rules('native')
    assert EquityAccountRules.from_dict(rules.to_dict()) == rules
    assert rules.instrument.asset_class.value == 'ETF'
    prepared = prepared_at(context, request, products)
    AccountEngine(store, EquityAdviceClient(store), now=lambda: prepared.interval.start).refresh_account('native', prepared=prepared)
    execution = EquityExecution(store, channel, now=lambda: prepared.interval.start)
    execution.reconcile(cash=Decimal(str(request.initial_cash)), quantity=0, account_id='native')
    order, = execution.submit_pending('native')
    assert store.account_order(order)['quantity'] == 900
    execution.apply_report(EquityOrderReport(order, 900, Decimal('10'), prepared.interval.start+timedelta(minutes=1), 'FILLED_ALL'))
    assert store.virtual_account('native')['quantity'] == 900
    store.close()


def prepared_at(context, request, products, index=0):
    rows = products[EquityProduct.BARS].loc[lambda frame: frame.BarStart >= request.window.start]
    row = rows.iloc[index]
    interval = TimeInterval(row.BarStart.to_pydatetime(), row.Date.to_pydatetime())
    return prepare_equity_decision(context.data, request.candidate, request.input_binding,
        request.requests(context.execution_spec), interval, fee_rate=request.fee_rate)


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
@pytest.mark.parametrize('computation', [StrategyComputation.STATEFUL_STEP, StrategyComputation.BATCH_HISTORY])
def test_native_state_fills_duplicate_restart_and_next_decision(tmp_path, market, computation):
    context, request, products, store, permit, channel = native_account(tmp_path, market, computation)
    prepared = prepared_at(context, request, products)
    engine = AccountEngine(store, EquityAdviceClient(store), now=lambda: prepared.interval.start)
    engine.refresh_account('native', prepared=prepared)
    state = json.loads(store.virtual_account('native')['account_v4_json'])
    assert state['active'] is None and state['pending_cycle'] is not None
    execution = EquityExecution(store, channel, now=lambda: prepared.interval.start)
    execution.reconcile(cash=Decimal(str(request.initial_cash)), quantity=0, account_id='native')
    order, = execution.submit_pending('native')
    quantity = store.account_order(order)['quantity']
    partial = EquityOrderReport(order, context.execution_spec.quantity_step, Decimal('10'),
                               prepared.interval.start+timedelta(minutes=1), 'FILLED_PART')
    execution.apply_report(partial)
    state = store.virtual_account('native')['account_v4_json']
    execution.apply_report(partial)
    assert store.virtual_account('native')['account_v4_json'] == state
    path = store.path
    store.close()
    store = PaperStore(path, inspection_permit=permit)
    assert store.virtual_account('native')['account_v4_json'] == state
    execution = EquityExecution(store, channel, now=lambda: prepared.interval.start)
    execution.apply_report(EquityOrderReport(order, quantity, Decimal('10'),
        prepared.interval.start+timedelta(minutes=2), 'FILLED_ALL'))
    state = json.loads(store.virtual_account('native')['account_v4_json'])
    assert state['active']['quantity'] == quantity and state['active']['buy_fills'] == 2
    assert state['state']['revision'] == 1  # Fill callbacks are not strategy clock steps.
    assert state['active']['buy_cost'] == pytest.approx(quantity*10*(1+request.fee_rate))
    assert len(store.account_fills('native')) == 2
    prepared = prepared_at(context, request, products, 1)
    AccountEngine(store, EquityAdviceClient(store), now=lambda: prepared.interval.start).refresh_account('native', prepared=prepared)
    assert len(store.account_decisions('native')) == 2
    stable = store.virtual_account('native')['account_v4_json']
    AccountEngine(store, EquityAdviceClient(store), now=lambda: prepared.interval.start).refresh_account('native', prepared=prepared)
    assert store.virtual_account('native')['account_v4_json'] == stable
    assert len(store.account_decisions('native')) == 2
    assert not store.account_invariant_violations()
    store.close()


def replace_strategy(request, code):
    from dataclasses import replace
    from strategy_runtime import equity_source_hash
    root = request.candidate.source_root
    (root / 'strategy.py').write_text(code, encoding='utf-8')
    candidate = replace(request.candidate, definition=replace(request.candidate.definition,
        source_sha256=equity_source_hash(root, ('strategy.py',))))
    return replace(request, candidate=candidate)


BUDGET_STRATEGY = '''from decimal import Decimal
from dataclasses import replace
from strategy_runtime import AccountDecision, AccountStepResult, StateRecord, CycleBudget, EntryCyclePhase
def step(ctx,state):
    budget=ctx.budget or CycleBudget('fixture-cycle',100,Decimal('.2'),Decimal('2000'),Decimal('0'),EntryCyclePhase.ACTIVE)
    target=1 if ctx.portfolio.revision<2 else 0
    after=budget if target else None
    return AccountStepResult(AccountDecision.from_facts(target,'budget',facts={'revision':ctx.portfolio.revision,'events':len(ctx.events)},
        next_watch='next session',capital_mode='signal_cash_fraction',cycle_before=ctx.budget,cycle_after=after),cycle_values=StateRecord())
'''


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_native_budget_split_events_payment_and_flat_exit(tmp_path, market):
    from paper_trading_engine.equity_account_state import recognized_events
    context, request, products, store, _, channel = native_account(tmp_path, market)
    request = replace_strategy(request, BUDGET_STRATEGY)
    prepared = prepared_at(context, request, products)
    execution = EquityExecution(store, channel, now=lambda: prepared.interval.start)

    def decide_and_submit():
        AccountEngine(store, EquityAdviceClient(store), now=lambda: prepared.interval.start).refresh_account('native', prepared=prepared)
        account = store.virtual_account('native')
        execution.reconcile(cash=Decimal(account['cash'])+Decimal(account['frozen_cash']), quantity=account['quantity'], account_id='native')
        return execution.submit_pending('native')

    buy, = decide_and_submit()
    execution.apply_report(EquityOrderReport(buy, 100, Decimal('10'), prepared.interval.start+timedelta(minutes=1), 'FILLED_ALL'))
    effective = prepared.interval.end
    store.apply_equity_event('native', event_id='split', kind='SPLIT', effective_at=effective,
        available_at=effective, source_sha256='d'*64, ratio=Decimal('2'))
    store.apply_equity_event('native', event_id='dividend', kind='CASH_DIVIDEND', effective_at=effective,
        available_at=effective, source_sha256='e'*64, cash_per_share=Decimal('.1'), pay_at=effective+timedelta(hours=1))
    assert store.settle_equity_receivables('native', at=effective+timedelta(hours=1)) == 1
    assert store.settle_equity_receivables('native', at=effective+timedelta(hours=1)) == 0
    state = json.loads(store.virtual_account('native')['account_v4_json'])
    assert state['state']['revision'] == 1
    assert state['active']['quantity'] == state['budget']['target_quantity'] == 200
    assert Decimal(state['budget']['buy_cost_including_fees']) == Decimal('1001')
    events, cursor = recognized_events(store, 'native', state['state']['event_cursor'], effective+timedelta(hours=2))
    assert [event.kind.value for event in events] == ['SPLIT', 'CASH_DIVIDEND', 'DIVIDEND_PAYMENT']
    assert [event.receivable_delta for event in events] == [0., 20., -20.]
    assert recognized_events(store, 'native', cursor, effective+timedelta(hours=2))[0] == ()
    prepared = prepared_at(context, request, products, 1)
    assert decide_and_submit() == ()
    assert json.loads(store.virtual_account('native')['account_v4_json'])['state']['event_cursor'] == cursor
    prepared = prepared_at(context, request, products, 2)
    sell, = decide_and_submit()
    # Submitted exit does not erase the owning budget before the actual fill.
    assert json.loads(store.virtual_account('native')['account_v4_json'])['budget'] is not None
    execution.apply_report(EquityOrderReport(sell, 200, Decimal('5'), prepared.interval.start+timedelta(minutes=1), 'FILLED_ALL'))
    state = json.loads(store.virtual_account('native')['account_v4_json'])
    assert state['active'] is state['budget'] is state['state']['cycle'] is None
    assert state['latest_closed']['quantity'] == 0
    assert state['latest_closed']['sell_income'] == pytest.approx(1019.)
    assert not store.account_invariant_violations()
    store.close()


@pytest.mark.parametrize('kind', ['tick', 'mixed', 'market_buy', 'price_limit'])
def test_native_invalid_orders_do_not_mutate_account_or_state(tmp_path, kind):
    context, request, products, store, _, _ = native_account(tmp_path, MarketId.CN)
    orders = {
        'tick': "(ReplayOrder(OrderSide.BUY,100,OrderType.LIMIT,10.001),)",
        'mixed': "(ReplayOrder(OrderSide.BUY,100,OrderType.LIMIT,10.),ReplayOrder(OrderSide.SELL,100,OrderType.MARKET))",
        'market_buy': "(ReplayOrder(OrderSide.BUY,100,OrderType.MARKET),)",
        'price_limit': "(ReplayOrder(OrderSide.BUY,100,OrderType.LIMIT,12.),)",
    }[kind]
    request = replace_strategy(request, "from strategy_runtime import AccountStepResult,AccountDecision,ReplayOrder,StateRecord\n"
        "from strategy_runtime.contracts import OrderSide,OrderType\n"
        "def step(ctx,state):\n"
        f"    return AccountStepResult(AccountDecision.from_facts(1,'bad order',facts={{'fixture':1}},next_watch='next',orders={orders}),cycle_values=StateRecord())\n")
    before = store.virtual_account('native')
    prepared = prepared_at(context, request, products)
    expected = {'tick':'declared tick','mixed':'mixed-side','market_buy':'limit buy','price_limit':'dated price limits'}[kind]
    with pytest.raises(ValueError, match=expected):
        AccountEngine(store, EquityAdviceClient(store), now=lambda: prepared.interval.start).refresh_account('native', prepared=prepared)
    assert store.virtual_account('native') == before
    assert not store.account_decisions('native') and not store.account_intents('native')
    store.close()


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
@pytest.mark.parametrize('terminal', ['FILLED_ALL', 'CANCELLED_PART'])
def test_cumulative_reservation_and_fee_rounding_survive_partial_reports(tmp_path, market, terminal):
    from dataclasses import replace
    context, request, products, store, _, channel = native_account(tmp_path, market)
    quantity, partial, price, rate = ((300, 100, Decimal('10.03'), Decimal('.00017')) if market is MarketId.CN
                                      else (125, 1, Decimal('57.49'), Decimal('.001')))
    request = replace(request, fee_rate=float(rate))
    request = replace_strategy(request, "from strategy_runtime import AccountStepResult,AccountDecision,ReplayOrder,StateRecord\n"
        "from strategy_runtime.contracts import OrderSide,OrderType\n"
        "def step(ctx,state):\n"
        f"    return AccountStepResult(AccountDecision.from_facts(1,'rounding',facts={{'fixture':1}},next_watch='next',orders=(ReplayOrder(OrderSide.BUY,{quantity},OrderType.LIMIT,{price}),)),cycle_values=StateRecord())\n")
    prepared = prepared_at(context, request, products)
    AccountEngine(store, EquityAdviceClient(store), now=lambda: prepared.interval.start).refresh_account('native', prepared=prepared)
    execution = EquityExecution(store, channel, now=lambda: prepared.interval.start)
    execution.reconcile(cash=Decimal(str(request.initial_cash)), quantity=0, account_id='native')
    order, = execution.submit_pending('native')
    execution.apply_report(EquityOrderReport(order, partial, price, prepared.interval.start+timedelta(minutes=1), 'FILLED_PART'))
    total = quantity if terminal == 'FILLED_ALL' else partial
    last = EquityOrderReport(order, total, price, prepared.interval.start+timedelta(minutes=2), terminal)
    execution.apply_report(last)
    execution.apply_report(last)
    account = store.virtual_account('native')
    assert Decimal(account['frozen_cash']) == 0
    fee = (price*total*rate).quantize(Decimal('.0001'))
    assert Decimal(account['cash']) == Decimal(str(request.initial_cash))-price*total-fee
    assert sum(Decimal(fill['fee']) for fill in store.account_fills('native')) == fee
    assert not store.account_invariant_violations()
    store.close()


def intraday_inputs(context, request, products):
    from dataclasses import replace
    from zoneinfo import ZoneInfo
    from dataflows import BarFrequency, ProviderBinding, ProviderConfig, ProviderKey, TradingSession
    from dataflows.equity_data import equity_metadata
    from czsc_trader.application.research_governance_service import create_research_context
    from czsc_trader.research_tools import ResearchExecutionSession, EvaluationBenchmark, EquityBuyHold
    cn = request.candidate.instrument.market is MarketId.CN
    sessions = []
    for row in products[EquityProduct.BARS].itertuples():
        zone = ZoneInfo(request.candidate.instrument.timezone)
        start, end = row.BarStart.to_pydatetime().astimezone(zone), row.Date.to_pydatetime().astimezone(zone)
        segments = ((TimeInterval(start, start.replace(hour=11, minute=30)),
                     TimeInterval(start.replace(hour=13, minute=0), end)) if cn else (TimeInterval(start,end),))
        sessions.append(TradingSession(start.date(), str(start.tzinfo), segments))
    grid = [bar for session in sessions for bar in session.bars(BarFrequency.M30)]
    bars = products[EquityProduct.BARS].iloc[[0]*len(grid)].copy().reset_index(drop=True)
    bars['BarStart'], bars['Date'], bars['AvailableDate'] = [b.start for b in grid], [b.end for b in grid], [b.end for b in grid]
    constraints = products[EquityProduct.CONSTRAINTS].iloc[[0]*len(grid)].copy().reset_index(drop=True)
    constraints['Date'], constraints['AvailableDate'] = [b.start for b in grid], [b.start for b in grid]
    constraints['BuySellableAt'] = [b.start.astimezone(ZoneInfo(request.candidate.instrument.timezone)).replace(hour=9,minute=30)+timedelta(days=1) if cn else b.start for b in grid]
    constraints['SettlementAt'] = [b.end for b in grid]
    products = {**products, EquityProduct.BARS:bars, EquityProduct.CONSTRAINTS:constraints}
    def fetch(query):
        metadata = equity_metadata(query, tuple(sessions), availability_basis='FIXTURE_BAR_CLOSE')
        metadata['no_actions_verified'] = True
        return products[query.parameters.query.product].copy(deep=True), metadata
    source = request.sources.bars
    providers = ProviderConfig(bindings={}, equity_bindings={ProviderKey(product,request.candidate.instrument.market,source):
        ProviderBinding(source.provider,source.revision,fetch) for product in EquityProduct})
    spec = replace(context.execution_spec, decision_clock=BarFrequency.M30)
    context = create_research_context(context.repository,context.batch,providers=providers,execution_spec=spec)
    candidate = replace(request.candidate, definition=replace(request.candidate.definition, execution_spec=spec, auxiliary_inputs=()))
    request = replace(request,candidate=candidate,window=TimeInterval(grid[1].start,grid[-1].end),prepared=None,
        input_binding=None,audit_inputs_sha256=None,benchmark=EvaluationBenchmark(EquityBuyHold(spec)))
    request = replace_strategy(request, "from strategy_runtime import AccountDecision,AccountStepResult,StateRecord\n"
        "def step(ctx,state):\n"
        "    return AccountStepResult(AccountDecision.from_facts(0 if ctx.portfolio.quantity else 1,'alternate',facts={'quantity':ctx.portfolio.quantity},next_watch='next bar'),cycle_values=StateRecord())\n")
    with ResearchExecutionSession(context,experiment=request.experiment) as execution:
        request = context.evaluation.prepare(request,execution=execution).request
    return context,request,products


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
@pytest.mark.parametrize('explicit', [False,True])
def test_native_m30_obeys_declared_buy_sellability(tmp_path,market,explicit):
    context,request,products,store,_,channel = native_account(tmp_path,market,intraday=True)
    if explicit:
        request=replace_strategy(request, "from strategy_runtime import AccountDecision,AccountStepResult,StateRecord,ReplayOrder\n"
            "from strategy_runtime.contracts import OrderSide,OrderType\n"
            "def step(ctx,state):\n"
            "    orders=(ReplayOrder(OrderSide.SELL,ctx.portfolio.quantity,OrderType.MARKET),) if ctx.portfolio.quantity else ()\n"
            "    return AccountStepResult(AccountDecision.from_facts(0 if ctx.portfolio.quantity else 1,'alternate',facts={'quantity':ctx.portfolio.quantity},next_watch='next bar',orders=orders),cycle_values=StateRecord())\n")
    prepared = prepared_at(context,request,products)
    execution = EquityExecution(store,channel,now=lambda:prepared.interval.start)
    def decide():
        AccountEngine(store,EquityAdviceClient(store),now=lambda:prepared.interval.start).refresh_account('native',prepared=prepared)
        account=store.virtual_account('native')
        execution.reconcile(cash=Decimal(account['cash'])+Decimal(account['frozen_cash']),quantity=account['quantity'],account_id='native')
        return execution.submit_pending('native')
    buy,=decide()
    qty=store.account_order(buy)['quantity']
    execution.apply_report(EquityOrderReport(buy,qty,Decimal('10'),prepared.interval.start+timedelta(minutes=1),'FILLED_ALL'))
    prepared=prepared_at(context,request,products,1)
    if market is MarketId.CN:
        before=store.virtual_account('native')['account_v4_json']
        if explicit:
            with pytest.raises(ValueError,match='sellable'):
                decide()
            assert store.virtual_account('native')['account_v4_json']==before
        else:
            assert decide()==()
        assert store.virtual_account('native')['quantity']==qty
        # The next actual session, including the lunch break, unlocks all lots.
        rows=products[EquityProduct.BARS].loc[lambda frame:frame.BarStart>=request.window.start]
        index=next(i for i,row in enumerate(rows.itertuples()) if row.BarStart.date()>request.window.start.date())
        prepared=prepared_at(context,request,products,index)
    sell,=decide()
    execution.apply_report(EquityOrderReport(sell,qty,Decimal('10'),prepared.interval.start+timedelta(minutes=1),'FILLED_ALL'))
    assert store.virtual_account('native')['quantity']==0
    assert not store.account_invariant_violations()
    store.close()


def test_legacy_v2_prepared_hash_uses_unchanged_input_contract(tmp_path):
    from strategy_runtime import canonical_sha256
    from test_equity_pte import equity_account
    context,request,store,_=equity_account(tmp_path,auxiliary=True)
    interval=TimeInterval(request.window.start,request.window.start+timedelta(minutes=30))
    prepared=prepare_equity_decision(context.data,request.candidate,request.input_binding,
        request.requests(context.execution_spec),interval,fee_rate=request.fee_rate)
    expected=canonical_sha256({
        'auxiliary':{key:frame.to_json(date_format='iso',date_unit='us') for key,frame in prepared.auxiliary_histories.items()},
        'sessions':None if prepared.sessions is None else prepared.sessions.to_json(date_format='iso',date_unit='us'),
        'calendar':[{'session_date':x.session_date.isoformat(),'timezone':x.timezone,
            'segments':[(s.start.isoformat(),s.end.isoformat()) for s in x.segments]} for x in prepared.trading_sessions]})
    assert prepared.decision_inputs_sha256==expected
    store.close()


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_rejected_flat_entry_releases_pending_budget_without_creating_cycle(tmp_path,market):
    from paper_trading_engine.broker import BrokerOrderRejectedError
    context,request,products,store,_,channel=native_account(tmp_path,market)
    request=replace_strategy(request,BUDGET_STRATEGY)
    prepared=prepared_at(context,request,products)
    AccountEngine(store,EquityAdviceClient(store),now=lambda:prepared.interval.start).refresh_account('native',prepared=prepared)
    before=json.loads(store.virtual_account('native')['account_v4_json'])
    assert before['budget'] is not None and before['active'] is None
    execution=EquityExecution(store,channel,now=lambda:prepared.interval.start)
    execution.reconcile(cash=Decimal(str(request.initial_cash)),quantity=0,account_id='native')
    def reject(intent):
        raise BrokerOrderRejectedError('explicit recorded rejection')
    channel.place_order=reject
    with pytest.raises(BrokerOrderRejectedError,match='recorded rejection'):
        execution.submit_pending('native')
    after=json.loads(store.virtual_account('native')['account_v4_json'])
    assert after['state']['revision']==1 and after['state']['cycle'] is None
    assert after['pending_cycle'] is after['budget'] is after['active'] is None
    assert Decimal(store.virtual_account('native')['frozen_cash'])==0
    assert not store.account_invariant_violations()
    store.close()


def test_dependency_leg_plan_is_explicitly_rejected_without_adoption(tmp_path):
    context,request,products,store,_,_=native_account(tmp_path,MarketId.US)
    request=replace_strategy(request,"from strategy_runtime import AccountDecision,AccountStepResult,StateRecord,ReplayOrder,ReplayLeg\n"
        "from strategy_runtime.contracts import OrderSide,OrderType\n"
        "from datetime import timedelta\n"
        "def step(ctx,state):\n"
        "    start=ctx.point.decision_at\n"
        "    legs=(ReplayLeg(0,ReplayOrder(OrderSide.BUY,1,OrderType.LIMIT,10.),'entry',start,start+timedelta(minutes=10)),ReplayLeg(1,ReplayOrder(OrderSide.SELL,1,OrderType.MARKET),'exit',start+timedelta(minutes=10),start+timedelta(minutes=20),0,'FILLED_ALL'))\n"
        "    return AccountStepResult(AccountDecision.from_facts(0,'legs',facts={'fixture':1},next_watch='next',legs=legs),cycle_values=StateRecord())\n")
    prepared=prepared_at(context,request,products)
    before=store.virtual_account('native')
    with pytest.raises(ValueError,match='dependency legs are not supported'):
        AccountEngine(store,EquityAdviceClient(store),now=lambda:prepared.interval.start).refresh_account('native',prepared=prepared)
    assert store.virtual_account('native')==before
    assert not store.account_decisions('native')
    store.close()
