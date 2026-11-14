# Risk ownership: E2E-05
"""Native dual-market state follows actual PTE adoption and cumulative fills."""
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path

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


def native_account(tmp_path, market, computation=StrategyComputation.STATEFUL_STEP, *, etf=False, intraday=False,
                   unfilled_morning=False):
    context, request, products, _ = native_fixture(tmp_path, market, computation, etf=etf)
    if intraday:
        context, request, products = intraday_inputs(context, request, products, unfilled_morning=unfilled_morning)
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
                qualification_snapshot='INSPECTION', selection_data_cutoff='2026-10-11', channel_id=channel_id,
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


@pytest.mark.parametrize('partially_filled', [False, True])
def test_daily_target_next_pte_plan_uses_confirmed_fill_result(tmp_path, partially_filled):
    from dataclasses import replace
    from execution_channels.daily_execution import DAILY_TARGET_TRIGGER, DailyExecutionOutcome
    from strategy_runtime import ExecutionPolicy

    context, request, products, store, permit, channel = native_account(tmp_path, MarketId.US)
    policy = ExecutionPolicy('TARGET_POSITION', {'execution_trigger': DAILY_TARGET_TRIGGER})
    request = replace(request, candidate=replace(request.candidate,
        definition=replace(request.candidate.definition, execution_policy=policy)))
    try:
        prepared = prepared_at(context, request, products)
        start, end = prepared.interval.start, prepared.interval.end
        AccountEngine(store, EquityAdviceClient(store), now=lambda: start).refresh_account('native', prepared=prepared)
        first = store.adopted_decision('native')['payload']['strategy_output']['execution_plan']
        assert first['execution_trigger'] == 'INITIAL_TARGET'
        execution = EquityExecution(store, channel, now=lambda: start)
        execution.reconcile(cash=Decimal(str(request.initial_cash)), quantity=0, account_id='native')
        order, = execution.submit_pending('native')
        filled = context.execution_spec.quantity_step if partially_filled else 0
        if partially_filled:
            execution.apply_report(EquityOrderReport(order, filled, Decimal('10'), start + timedelta(minutes=1), 'FILLED_PART'))
        execution.apply_report(EquityOrderReport(order, filled, Decimal('10') if filled else Decimal(0), end,
            'CANCELLED_PART' if partially_filled else 'CANCELLED_ALL'))

        path = store.path
        store.close()
        if not partially_filled:
            import sqlite3
            with sqlite3.connect(path) as connection:
                connection.executescript("""
                    ALTER TABLE decision_adoptions RENAME TO current_adoptions;
                    CREATE TABLE decision_adoptions (
                        account_id TEXT NOT NULL, valid_session TEXT NOT NULL, decision_id TEXT NOT NULL,
                        PRIMARY KEY(account_id,valid_session));
                    INSERT INTO decision_adoptions SELECT account_id,valid_session,decision_id FROM current_adoptions;
                    DROP TABLE current_adoptions;
                    UPDATE settings SET value='9' WHERE key='runtime_database_schema_version';
                """)
        store = PaperStore(path, inspection_permit=execution_permit(permit))
        following = prepared_at(context, request, products, 1)
        previous = store.previous_daily_execution('native', previous_session=following.available_through)
        assert previous.outcome is (DailyExecutionOutcome.PARTIAL_FILL if filled else DailyExecutionOutcome.ZERO_FILL)
        AccountEngine(store, EquityAdviceClient(store), now=lambda: following.interval.start).refresh_account(
            'native', prepared=following)
        payload = store.adopted_decision('native')['payload']
        assert payload['strategy_output']['execution_plan']['execution_trigger'] == (
            'UNCHANGED_TARGET' if filled else 'PREVIOUS_ZERO_FILL')
        assert bool(payload['orders']) == (not partially_filled)
        assert store.virtual_account('native')['quantity'] == filled
    finally:
        store.close()


def test_daily_staged_entry_budget_survives_in_research_and_pte(tmp_path):
    from dataclasses import replace
    from czsc_trader.application import EquityInspectionReplay
    from czsc_trader.application.equity_inspection import replay_account
    from execution_channels.daily_execution import DAILY_TARGET_TRIGGER
    from strategy_manager.freeze_contracts import InspectionCoordinate
    from strategy_runtime import ExecutionPolicy

    context, request, products, store, _, channel = native_account(tmp_path, MarketId.US)
    request = replace_strategy(request, """from strategy_runtime import AccountDecision, AccountStepResult, StateRecord
def step(ctx, state):
    target = .375 if ctx.account.quantity else .1875
    return AccountStepResult(AccountDecision.from_facts(target, 'stage', facts={'stage_target': target},
                                                       next_watch='next session'),
                             cycle_values=StateRecord())
""")
    policy = ExecutionPolicy('TARGET_POSITION', {'execution_trigger': DAILY_TARGET_TRIGGER,
                                                  'capital_mode': 'entry_cash_fraction'})
    request = replace(request, candidate=replace(request.candidate,
        definition=replace(request.candidate.definition, execution_policy=policy)))
    try:
        replay = EquityInspectionReplay(InspectionCoordinate('main', 'standard'), request.input_binding,
            request.requests(context.execution_spec), request.window, request.initial_cash, request.fee_rate,
            execution_reference=raw_binding(context.data, request.input_binding))
        result = replay_account(request.candidate, context.data, replay)['facts']
        assert [row['plan']['evidence']['execution_trigger'] for row in result['decisions']] == [
            'INITIAL_TARGET', 'TARGET_CHANGED', 'UNCHANGED_TARGET']
        assert [row['quantity'] for row in result['orders']] == [92, 94]
        assert {Decimal(row['plan']['evidence']['entry_cash']) for row in result['decisions']} == {Decimal('10000')}

        prepared = prepared_at(context, request, products)
        start = prepared.interval.start
        AccountEngine(store, EquityAdviceClient(store), now=lambda: start).refresh_account('native', prepared=prepared)
        execution = EquityExecution(store, channel, now=lambda: start)
        execution.reconcile(cash=Decimal(str(request.initial_cash)), quantity=0, account_id='native')
        order, = execution.submit_pending('native')
        assert store.account_order(order)['quantity'] == 185
        execution.apply_report(EquityOrderReport(order, 185, Decimal('10'), start + timedelta(minutes=1), 'FILLED_ALL'))

        following = prepared_at(context, request, products, 1)
        AccountEngine(store, EquityAdviceClient(store), now=lambda: following.interval.start).refresh_account(
            'native', prepared=following)
        payload = store.adopted_decision('native')['payload']
        evidence = payload['strategy_output']['execution_plan']
        assert evidence['execution_trigger'] == 'TARGET_CHANGED'
        assert Decimal(evidence['entry_cash']) == Decimal('10000')
        assert payload['orders'][0]['quantity'] == 187
    finally:
        store.close()


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


def intraday_inputs(context, request, products, *, unfilled_morning=False):
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
    if unfilled_morning:
        morning_end = sessions[0].segments[0].end
        bars.loc[bars.Date.eq(morning_end), ['Open', 'High', 'Low', 'Close']] = 10.2
    constraints = products[EquityProduct.TRADING_FACTS].iloc[[0]*len(grid)].copy().reset_index(drop=True)
    constraints['Date'] = [b.start for b in grid]
    constraints['AvailableDate'] = [session.segments[0].start
        for session in sessions for _ in session.bars(BarFrequency.M30)]
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
        frame = products[query.parameters.query.product]
        p = query.parameters
        if p.query.completed_through is not None:
            frame = frame.loc[frame.Date <= p.query.completed_through]
        if p.query.end != sessions[-1].session_date:
            days = frame.Date.dt.tz_convert(p.instrument.timezone).dt.date
            frame = frame.loc[(days >= p.query.start) & (days <= p.query.end)]
        metadata['sessions'] = [session_record(session) for session in sessions
                                if p.query.start <= session.session_date <= p.query.end]
        frame = frame.copy(deep=True)
        if p.query.product is EquityProduct.BARS and p.instrument != request.candidate.instrument:
            frame.loc[:, ['Open', 'High', 'Low', 'Close']] *= 20
        return frame, metadata
    source = request.sources.bars
    providers = ProviderConfig(bindings={}, equity_bindings={ProviderKey(product,request.candidate.instrument.market,source):
        ProviderBinding(source.provider,source.revision,fetch) for product in EquityProduct})
    spec = replace(context.execution_spec, decision_clock=BarFrequency.M30)
    context = create_research_context(context.repository,context.batch,providers=providers,execution_spec=spec)
    candidate = replace(request.candidate, definition=replace(request.candidate.definition,
        execution_spec=spec))
    request = replace(request,candidate=candidate,window=TimeInterval(grid[1].start,grid[-1].end),prepared=None,
        input_binding=None,audit_inputs_sha256=None,benchmark=EvaluationBenchmark(EquityBuyHold(spec)))
    request = replace_strategy(request, "from strategy_runtime import AccountDecision,AccountStepResult,StateRecord\n"
        "def step(ctx,state):\n"
        "    return AccountStepResult(AccountDecision.from_facts(0 if ctx.portfolio.quantity else 1,'alternate',facts={'quantity':ctx.portfolio.quantity},next_watch='next bar'),cycle_values=StateRecord())\n")
    with ResearchExecutionSession(context,experiment=request.experiment) as execution:
        request = context.evaluation.prepare(request,execution=execution).request
    return context,request,products


def test_us_m30_opening_decision_reads_only_completed_step_bars(tmp_path, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    from dataflows import AssetClass, Dataset, InstrumentId
    from execution_channels.daily_execution import INTERVAL_TARGET_TRIGGER
    from execution_channels.instruments import TimeInterval as ChannelInterval
    from paper_trading_engine.equity_runtime import EquityRuntimeAdviceClient, EquityAccountInputs, EquityScheduleProvider
    from paper_trading_engine.data_space import AccountDataflows
    from dataflows import DataSpace, ProviderConfig
    from strategy_runtime import ExecutionPolicy, ObservationAvailability, StepDataInput

    context, request, _, store, permit, _ = native_account(tmp_path, MarketId.US, intraday=True)
    try:
        request = replace_strategy(request, """from zoneinfo import ZoneInfo
from strategy_runtime import AccountDecision, AccountStepResult, StateRecord, StepDataWindow
def step(ctx, state):
    day = ctx.point.observed_through.astimezone(ZoneInfo('America/New_York')).date()
    soxx, = ctx.dfls.fetch(StepDataWindow('soxx_open', day, day)).itertuples()
    assert soxx.Date == ctx.point.observed_through and soxx.Close == 200.
    return AccountStepResult(AccountDecision.from_facts(.5, 'opening', facts={'soxx': soxx.Close},
        next_watch='next bar'), cycle_values=StateRecord())
""")
        soxx = InstrumentId(MarketId.US, AssetClass.ETF, 'SOXX')
        step_input = StepDataInput('soxx_open', Dataset.EQUITY_BARS, soxx.symbol, '30m', 1,
            ObservationAvailability(soxx.timezone, '00:00'), instrument=soxx, source=request.sources.bars)
        candidate = replace(request.candidate, definition=replace(request.candidate.definition,
            step_data_inputs=(step_input,),
            execution_policy=ExecutionPolicy('TARGET_POSITION', {'execution_trigger': INTERVAL_TARGET_TRIGGER})))
        release = SimpleNamespace(release_hash=permit.release_sha256)
        account_dataflows = AccountDataflows(tmp_path, DataSpace(Path('account-dfls')),
            ProviderConfig(equity_bindings=context.data._equity_providers))
        client = EquityRuntimeAdviceClient(repo_root=permit.isolated_repository, store=store, dataflows=context.data,
                                      data_dir=permit.workspace / 'runtime-data', account_dataflows=account_dataflows)
        monkeypatch.setattr(client, '_account_release',
                            lambda account_id: (store.virtual_account(account_id), release, candidate))
        client.register_recipe('native', EquityAccountInputs(release.release_hash, request.input_binding,
            request.fee_rate, raw_binding(context.data, request.input_binding)))
        scheduler = EquityScheduleProvider(client, AccountEngine(store, client))
        opening_decision = request.window.start.astimezone(ZoneInfo('America/New_York'))
        assert (opening_decision.hour, opening_decision.minute) == (10, 0)
        task = scheduler.due_decision(store.virtual_account('native'), opening_decision)
        assert task.interval == TimeInterval(opening_decision, opening_decision + timedelta(minutes=30))
        scheduler.run_scheduled('native', task, opening_decision)
        adopted = store.adopted_execution_decision('native', ChannelInterval(task.interval.start, task.interval.end))
        assert adopted['payload']['strategy_output']['execution_plan']['target'] == .5
        order, = adopted['payload']['orders']
        assert order['side'] == 'BUY'

        pinned = EquityAccountInputs.from_dict(json.loads(client._interval_path(
            'native', release.release_hash, task.interval).read_bytes()))
        requests = dict(pinned.binding.request_bindings)
        assert requests['bars'].query.completed_through == opening_decision
        assert set(requests) == {'bars', 'sessions'}
        read, = adopted['payload']['strategy_output']['data_reads']
        assert read['window']['name'] == 'soxx_open'
        assert read['window']['start'] == read['window']['end'] == str(opening_decision.date())
        assert read['rows'] == 1
    finally:
        store.close()



@pytest.mark.parametrize("filled", [False, True])
def test_m30_lunch_decision_uses_same_interval_and_confirmed_outcome(tmp_path, monkeypatch, filled):
    from dataclasses import replace
    from datetime import datetime
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    from czsc_trader.application import EquityInspectionReplay
    from czsc_trader.application.equity_inspection import replay_account
    from execution_channels.daily_execution import INTERVAL_TARGET_TRIGGER
    from execution_channels.instruments import TimeInterval as ChannelInterval
    from paper_trading_engine.equity_runtime import EquityRuntimeAdviceClient, EquityAccountInputs, EquityScheduleProvider
    from strategy_manager.freeze_contracts import InspectionCoordinate
    from strategy_runtime import ExecutionPolicy

    context, request, products, store, permit, channel = native_account(
        tmp_path, MarketId.CN, intraday=True, unfilled_morning=not filled)
    request = replace_strategy(request, """from strategy_runtime import AccountDecision, AccountStepResult, StateRecord
def step(ctx, state):
    return AccountStepResult(AccountDecision.from_facts(.5, 'target', facts={'weight': .5},
        next_watch='next bar'), cycle_values=StateRecord())
""")
    request = replace(request, candidate=replace(request.candidate,
        definition=replace(request.candidate.definition, execution_policy=ExecutionPolicy(
            'TARGET_POSITION', {'execution_trigger': INTERVAL_TARGET_TRIGGER}))))
    zone = ZoneInfo('Asia/Shanghai')
    morning = next(TimeInterval(row.BarStart.to_pydatetime(), row.Date.to_pydatetime())
        for row in products[EquityProduct.BARS].itertuples()
        if row.BarStart >= request.window.start and row.Date.tz_convert(zone).hour == 11
        and row.Date.tz_convert(zone).minute == 30)
    afternoon = TimeInterval(morning.end + timedelta(minutes=90), morning.end + timedelta(minutes=120))
    raw = raw_binding(context.data, request.input_binding)
    candidate = request.candidate
    release = SimpleNamespace(release_hash='a'*64)

    def provider_for(current_store):
        client = EquityRuntimeAdviceClient(repo_root=permit.isolated_repository, store=current_store, dataflows=context.data,
                                      data_dir=permit.workspace / 'runtime-data')
        monkeypatch.setattr(client, '_account_release',
                            lambda account_id: (current_store.virtual_account(account_id), release, candidate))
        return client, EquityScheduleProvider(client, AccountEngine(current_store, client))

    try:
        client, provider = provider_for(store)
        client.register_recipe('native', EquityAccountInputs(release.release_hash, request.input_binding, request.fee_rate, raw))
        morning_task = provider.due_decision(store.virtual_account('native'), morning.start)
        assert morning_task.interval == morning
        provider.run_scheduled('native', morning_task, morning.start)
        first = store.adopted_execution_decision('native', ChannelInterval(morning.start, morning.end))
        assert first['payload']['strategy_output']['execution_plan']['execution_trigger'] == 'INITIAL_TARGET'
        execution = EquityExecution(store, channel, now=lambda: morning.start)
        execution.reconcile(cash=Decimal(str(request.initial_cash)), quantity=0, account_id='native')
        order, = execution.submit_pending('native')

        during_lunch = morning.end + timedelta(minutes=5)
        task = provider.due_decision(store.virtual_account('native'), during_lunch)
        assert task.interval == afternoon and task.execution_interval.start == morning.end
        assert task.execution_interval.previous_window == ChannelInterval(morning.start, morning.end)
        assert task.cycle_record()['validity']['start'] == morning.end.isoformat()
        with pytest.raises(RuntimeError, match='not adopted|pending|等待对账'):
            provider.run_scheduled('native', task, during_lunch)

        quantity = store.account_order(order)['quantity']
        execution.apply_report(EquityOrderReport(order, quantity if filled else 0,
            Decimal('10') if filled else Decimal(0),
            morning.end - timedelta(minutes=1) if filled else morning.end,
            'FILLED_ALL' if filled else 'CANCELLED_ALL'))
        path = store.path
        store.close()
        store = PaperStore(path, inspection_permit=execution_permit(permit))
        client, provider = provider_for(store)
        provider.run_scheduled('native', task, during_lunch)
        second = store.adopted_execution_decision('native', ChannelInterval(afternoon.start, afternoon.end))
        assert second['valid_session'] == first['valid_session'] and second['decision_id'] != first['decision_id']
        plan = second['payload']['strategy_output']['execution_plan']
        assert plan['execution_trigger'] == ('UNCHANGED_TARGET' if filled else 'PREVIOUS_ZERO_FILL')
        assert datetime.fromisoformat(plan['decision_at']) == during_lunch
        assert bool(second['payload']['orders']) is (not filled)
        assert second['payload']['decision_cycle'] == task.cycle_record()
        assert len(store.account_orders('native')) == 1
        provider.run_scheduled('native', task, during_lunch)
        assert len(store.account_decisions('native')) == 2
        assert client._forward_requests(client.recipe('native'), afternoon, candidate, cutoff=during_lunch)[0][0].parameters.query.completed_through == morning.end

        next_open = next(row.BarStart.to_pydatetime() for row in products[EquityProduct.BARS].itertuples()
                         if row.BarStart.tz_convert(zone).date() > morning.start.astimezone(zone).date())
        next_task = provider.due_decision(store.virtual_account('native'), next_open)
        assert type(next_task.decision_at) is datetime and next_task.decision_at == next_open

        replay = EquityInspectionReplay(InspectionCoordinate('main', 'standard'), request.input_binding,
            request.requests(context.execution_spec), TimeInterval(morning.start, afternoon.end),
            request.initial_cash, request.fee_rate, execution_reference=raw)
        facts = replay_account(candidate, context.data, replay)['facts']
        decisions = facts['decisions']
        assert len(decisions) == 2
        assert datetime.fromisoformat(decisions[1]['decision_at']) == morning.end
        assert decisions[1]['plan']['evidence']['execution_interval'] == plan['execution_interval']
        assert decisions[1]['plan']['evidence']['execution_trigger'] == plan['execution_trigger']
        assert decisions[1]['target'] == plan['target'] == .5
        planned = [quantity, *(order['quantity'] for order in second['payload']['orders'])]
        assert [order['quantity'] for order in facts['orders']] == planned
        if filled:
            assert store.virtual_account('native')['quantity'] == facts['account_points'][-1]['quantity']
    finally:
        store.close()
