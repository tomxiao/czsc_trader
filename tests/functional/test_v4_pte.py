# Risk ownership: E2E-05
"""Native dual-market state follows actual PTE adoption and cumulative fills."""
from datetime import timedelta
from decimal import Decimal
import json

import pytest
from dataflows import MarketId, EquityProduct, TimeInterval
from strategy_runtime import StrategyComputation
from strategy_runtime.inspection import InspectionRuntimePermit
from paper_trading_engine.account_engine import AccountEngine
from execution_channels.futu.store import PaperStore
from paper_trading_engine.ec_boundary import execution_rules, execution_permit
from execution_channels.futu.equity_contracts import EquityOrderReport, equity_channel_id
from paper_trading_engine.equity_advice import EquityAdviceClient, prepare_equity_decision
from execution_channels.futu.equity_execution import EquityExecution
from czsc_trader.application.ec_boundary import execution_instrument
from equity_pte_support import RecordedChannel
from test_v4_inspection_roundtrip import native_fixture
from test_formal_v4_runtime import raw_binding
from paper_store_support import new_paper_store


_NATIVE_ACCOUNT_SEEDS = {}


def native_account(tmp_path, market, computation=StrategyComputation.STATEFUL_STEP, *, etf=False, intraday=False):
    context, request, products, _ = native_fixture(tmp_path, market, computation, etf=etf)
    if intraday:
        context, request, products = intraday_inputs(context, request, products)
    workspace = tmp_path / '.tmp/strategy-inspection/native-pte'
    isolated = workspace / 'repository'
    isolated.mkdir(parents=True)
    permit = InspectionRuntimePermit('native-pte', 'S999-v1', 'a'*64, 'b'*64, 'c'*64, isolated, workspace)
    channel_id = equity_channel_id(execution_instrument(request.candidate.instrument))
    rules = execution_rules(request.candidate.instrument, context.execution_spec)
    key = (market, computation, etf, intraday, request.initial_cash,
           json.dumps(rules.to_dict(), sort_keys=True))
    path = workspace / 'paper.db'
    if key not in _NATIVE_ACCOUNT_SEEDS:
        # Build a real empty-position account once per exact input contract.
        # Checkpoint before retaining immutable bytes; consumers never share a
        # live connection, WAL, account rows or broker state.
        initial = new_paper_store(path, inspection_permit=execution_permit(permit))
        try:
            initial.create_virtual_account('native', 'native', 'v1', 'a'*64, request.initial_cash,
                symbol=request.candidate.instrument.symbol,
                asset_type=request.candidate.instrument.asset_class.value.lower(),
                strategy_id='S999', strategy_name_snapshot='native', strategy_version='v1', release_hash='a'*64,
                qualification_snapshot='INSPECTION', selection_data_cutoff='2026-10-12', channel_id=channel_id,
                equity_rules=rules)
            initial.set_virtual_paused('native', False)
            assert initial._connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] == 0
        finally:
            initial.close()
        _NATIVE_ACCOUNT_SEEDS[key] = path.read_bytes()
    else:
        path.write_bytes(_NATIVE_ACCOUNT_SEEDS[key])
    # Normal reopening validates this consumer's path/permit and stored identity.
    store = PaperStore(path, inspection_permit=execution_permit(permit))
    channel = RecordedChannel()
    channel.channel_id = channel_id
    return context, request, products, store, permit, channel


def prepared_at(context, request, products, index=0):
    rows = products[EquityProduct.BARS].loc[lambda frame: frame.BarStart >= request.window.start]
    row = rows.iloc[index]
    interval = TimeInterval(row.BarStart.to_pydatetime(), row.Date.to_pydatetime())
    return prepare_equity_decision(context.data, request.candidate, request.input_binding,
        request.requests(context.execution_spec), interval, fee_rate=request.fee_rate,
        execution_reference=raw_binding(context.data, request.input_binding).fetch(context.data, interval,
            latency_seconds=context.execution_spec.data_latency_seconds))


@pytest.mark.parametrize('market,computation', [
    (MarketId.CN, StrategyComputation.STATEFUL_STEP),
])
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
    store = PaperStore(path, inspection_permit=execution_permit(permit))
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


BUDGET_STRATEGY = """from strategy_runtime import AccountDecision, AccountStepResult, StateRecord
def step(ctx,state):
    target=.2 if ctx.portfolio.revision<2 else 0
    return AccountStepResult(AccountDecision.from_facts(target,'budget',facts={'revision':ctx.portfolio.revision},
        next_watch='next session'),cycle_values=StateRecord())
"""


def budget_request(request):
    from dataclasses import replace
    from strategy_runtime import ExecutionPolicy
    spec = request.candidate.definition.execution_spec
    policy = ExecutionPolicy('FROZEN_RULE', {
        'capital':{'fee_rate':request.fee_rate,'mode':'signal_cash_fraction','target_scope':'entry_cycle'},
        'entry':{'limit_parameter':.01,'order_type':'LIMIT'},
        'exit':{'limit_ratio':.1,'order_type':'MARKET'},
        'instrument':{'lot_size':spec.quantity_step,'price_tick':spec.price_tick,
                      'price_limit_ratio':.1,'maximum_order_quantity':100000}})
    request = replace_strategy(request, BUDGET_STRATEGY)
    return replace(request, candidate=replace(request.candidate,
        definition=replace(request.candidate.definition, execution_policy=policy)))


def intraday_inputs(context, request, products):
    from dataclasses import replace
    from zoneinfo import ZoneInfo
    from dataflows import BarFrequency, ProviderBinding, ProviderConfig, ProviderKey, TradingSession
    from dataflows.equity_data import equity_metadata, session_record
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
    constraints = products[EquityProduct.TRADING_FACTS].iloc[[0]*len(grid)].copy().reset_index(drop=True)
    constraints['Date'], constraints['AvailableDate'] = [b.start for b in grid], [b.start for b in grid]
    products = {**products, EquityProduct.BARS:bars, EquityProduct.TRADING_FACTS:constraints}
    def fetch(query):
        metadata = equity_metadata(query, tuple(sessions), availability_basis='FIXTURE_BAR_CLOSE')
        if cn and query.parameters.query.product in (EquityProduct.TRADING_FACTS, EquityProduct.SESSIONS):
            delta = timedelta(days=3 if sessions[-1].session_date.weekday() == 4 else 1)
            following = TradingSession(sessions[-1].session_date + delta, sessions[-1].timezone,
                tuple(TimeInterval(part.start + delta, part.end + delta) for part in sessions[-1].segments))
            metadata['following_session'] = session_record(following)
        if query.parameters.query.product is EquityProduct.BARS:
            metadata['acquisition_method'] = ('PROVIDER_ADJUSTED'
                if query.parameters.query.adjustment.value == 'hfq' else 'PROVIDER_RAW')
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
