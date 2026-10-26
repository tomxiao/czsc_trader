"""S002 observation-upgrade PTE protocol: frozen intent dates and manual account arithmetic.

Only authenticated local input slices; synthetic channel facts do not claim historical fills.
"""
from datetime import date, datetime, time, timezone, timedelta
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

import pandas as pd
from dataflows import Dataflows, DataSpace, ProviderBinding, ProviderConfig, PreparePolicy, canonical_frame_sha256
from paper_trading_engine.inspection import (
    CoverageRequirement, InspectionOrderStatus, PteCheckpointExpectation,
    PteCoverageRequirement, PteDecisionInput, PteEnvironmentRequirement,
    PteFailureCase, PteFault, PteInspectionCapability, PteInspectionProtocol,
    PteInspectionScenario, PteOrderKey, PteOrderUpdate, PteRepeatedOrderReport,
    PteSubmissionResult, SubmissionOutcome,
)
from paper_trading_engine.lifecycle import AccountHealth
from strategy_runtime import PlannedOrder, OrderSide, OrderType, StrategyInit, StrategyRuntime, TradableWindow


def _frozen_cycle(ctx, execution_data, binding):
    """Choose an original frozen-intent cycle; not independent financial validation."""
    import json
    from strategy_runtime import StrategyRelease, StrategyInputBinding, SignalHistoryMode
    original=json.loads((ctx.repository.root/'strategies/S002/versions/v1.json').read_text(encoding='utf-8'))
    instance=StrategyRuntime(ctx.repository.strategy_root,dataflows=ctx.data).create(StrategyInit(
        StrategyRelease.from_mapping(original), binding.plan.tradable_window,
        ctx.repository.root/'.tmp/observation-v4-upgrade/pte-s002-original',pricing=execution_data.pricing))
    calendar=ctx.data.fetch(binding.plan.requests[binding.plan.calendar_name],prepared=binding.prepared)
    plan=instance.plan_inputs(calendar)
    rebound=StrategyInputBinding(plan,binding.prepared)
    instance.prepare_data(binding=rebound)
    history=instance.inspect_signals(history_mode=SignalHistoryMode.CONTINUOUS)
    valid=set(binding.plan.signal_dates.values())
    for i,(day,row) in enumerate(history.iterrows()):
        if day.date() not in valid or row.action!='ENTER':continue
        following=history.iloc[i+1:]
        hold=following.loc[following.action.isin(['HOLD_POSITION','IGNORE_ENTRY_WHILE_HOLDING'])]
        exits=following.loc[following.action.eq('EXIT_TIME')]
        if hold.empty or exits.empty:continue
        chosen=[(day,row),(hold.index[0],hold.iloc[0]),(exits.index[0],exits.iloc[0])]
        if not (chosen[0][0]<chosen[1][0]<chosen[2][0]) or any(d.date() not in valid for d,r in chosen):continue
        selected=[{'signal_date':d.date().isoformat(),'reason':r.action,'target_position':float(r.target_position),
                   'held_sessions':int(r.held_sessions),'shape':str(r.signal_state)} for d,r in chosen]
        return selected, {'frozen_release_hash':original['release_hash'],'reference':'S002-v1',
                          'selection_source':'original frozen StrategyRuntime.inspect_signals CONTINUOUS',
                          'old_binding':rebound.to_dict()}
    raise ValueError('No complete original ENTER/HOLD/EXIT cycle within authorized inputs')


def build_protocol(ctx, candidate, execution_data, binding, environment):
    root = ctx.repository.root
    if candidate.candidate_id != 'C9951' or candidate.strategy_family_id != 'S002':
        raise ValueError('This predeclared protocol is for S002-C9951')
    parameters = dict(candidate.payload['parameters']['rule'])
    originals, frames, provenance = {}, {}, {}
    for role, request in binding.plan.requests.items():
        result = ctx.data.fetch(request, prepared=binding.prepared)
        if not result.ready or canonical_frame_sha256(result.dataframe) != result.identity.content_sha256:
            raise ValueError(f'Unauthenticated parent input: {role}')
        key = (request.dataset, request.symbol, request.frequency)
        if key in originals:
            raise ValueError('Ambiguous authenticated input selection')
        originals[key] = (request, result)
        frames[role] = result.dataframe
        provenance[role] = {'sha256': result.identity.content_sha256, 'source': result.identity.source,
            'data_start': result.identity.data_start, 'data_cutoff': result.identity.data_cutoff}

    selected, causal_prefix = _frozen_cycle(ctx, execution_data, binding)
    signal_dates = tuple(date.fromisoformat(row['signal_date']) for row in selected)
    raw = execution_data.raw_execution_daily
    execution_dates = sorted(set(pd.to_datetime(raw.dt).dt.date))
    dates = tuple(next(day for day in execution_dates if day > signal) for signal in signal_dates)
    names = ('enter', 'hold', 'exit')

    def source(request):
        original_request, result = originals[(request.dataset, request.symbol, request.frequency)]
        if (request.parameters != original_request.parameters
                or pd.Timestamp(request.start) < pd.Timestamp(original_request.start)
                or pd.Timestamp(request.end) > pd.Timestamp(original_request.end)):
            raise ValueError('PTE slice exceeds its authenticated original selection')
        dates_in_frame = pd.to_datetime(result.dataframe['Date'])
        sliced = result.dataframe.loc[(dates_in_frame >= pd.Timestamp(request.start))
            & (dates_in_frame < pd.Timestamp(request.end) + pd.Timedelta(days=1))].copy()
        return sliced.reset_index(drop=True), dict(result.identity.metadata)

    flows = Dataflows(base_dir=root, space=DataSpace(Path('research/S002/assets/data')),
        providers=ProviderConfig(bindings={dataset: ProviderBinding(
            's002-c9951-authenticated-history-slice', '1', source) for dataset, _, _ in originals}))
    bindings, binding_evidence = {}, {}
    for name, day, signal in zip(names, dates, signal_dates, strict=True):
        instance = StrategyRuntime(ctx.repository.strategy_root, dataflows=flows).create(StrategyInit(
            candidate, TradableWindow(day, day), root / '.tmp/observation-v4-upgrade/pte-s002-prepare' / name,
            pricing=execution_data.pricing))
        instance.prepare_data(policy=PreparePolicy.REUSE)
        prepared = instance.input_binding
        if prepared.plan.available_through != signal:
            raise ValueError('Prepared binding does not match independently selected signal day')
        bindings[name] = prepared
        binding_evidence[name] = {'binding': prepared.to_dict(), 'input_hashes': {}}
        for role, request in prepared.plan.requests.items():
            observed = flows.fetch(request, prepared=prepared.prepared)
            expected_frame, _ = source(request)
            if not observed.ready or observed.identity.content_sha256 != canonical_frame_sha256(expected_frame):
                raise ValueError(f'Prepared PTE input differs from authenticated source slice: {name}/{role}; observed={observed.identity.content_sha256}; expected={canonical_frame_sha256(expected_frame)}')
            binding_evidence[name]['input_hashes'][role] = observed.identity.content_sha256

    def price_on(day):
        values = raw.loc[pd.to_datetime(raw.dt).dt.date.eq(day), 'close']
        if len(values) != 1:
            raise ValueError('Missing or ambiguous unadjusted reference close')
        return Decimal(str(values.iloc[0]))

    cash, fee, tick, zero = Decimal('100000'), Decimal('.0005'), Decimal('.001'), Decimal('0')
    entry_reference = price_on(signal_dates[0])
    buy_limit = (entry_reference * Decimal('1.0') / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
    shares = int((cash / (buy_limit * (1 + fee) * 100)).to_integral_value(rounding=ROUND_FLOOR)) * 100
    partial = shares // 200 * 100
    fill_price, sell_reference = buy_limit, price_on(signal_dates[-1])
    sell_fill = sell_reference
    reserve = shares * buy_limit * (1 + fee)
    cash_reserved = cash - reserve
    partial_fee = partial * fill_price * fee
    partial_cash = cash_reserved + partial * buy_limit * (1 + fee) - partial * fill_price - partial_fee
    partial_frozen = (shares - partial) * buy_limit * (1 + fee)
    full_fee = shares * fill_price * fee
    held_cash = cash - shares * fill_price - full_fee
    exit_fee = shares * sell_fill * fee
    final_cash = held_cash + shares * sell_fill - exit_fee
    if not 0 < partial < shares <= 1000000:
        raise ValueError('Invalid fixed scenario quantities')
    if not all(value == value.quantize(Decimal('.0001')) for value in (
            reserve, cash_reserved, partial_fee, partial_cash, partial_frozen, full_fee, held_cash, exit_fee, final_cash)):
        raise ValueError('Scenario arithmetic exceeds account precision')
    buy = (PlannedOrder(OrderSide.BUY, shares, OrderType.LIMIT, buy_limit),)
    sell = (PlannedOrder(OrderSide.SELL, shares, OrderType.MARKET, sell_reference),)
    zone = timezone(timedelta(hours=8))

    def at(day, hour=10, minute=0):
        return datetime.combine(day, time(hour, minute), zone)

    decisions = tuple(PteDecisionInput(name, bindings[name], at(signal, 20, 31), day, at(day), name == 'enter')
        for name, day, signal in zip(names, dates, signal_dates, strict=True))
    entry_key, exit_key = PteOrderKey('enter', 0), PteOrderKey('exit', 0)
    events = (
        PteSubmissionResult('entry_accepted', at(dates[0]), entry_key, SubmissionOutcome.ACCEPTED),
        PteOrderUpdate('entry_partial', at(dates[0], 10, 1), entry_key, InspectionOrderStatus.PARTIAL, partial, fill_price, partial_fee),
        PteRepeatedOrderReport('entry_repeated', at(dates[0], 10, 2), 'entry_partial'),
        PteOrderUpdate('entry_filled', at(dates[0], 10, 3), entry_key, InspectionOrderStatus.FILLED, shares, fill_price, full_fee),
        PteSubmissionResult('exit_accepted', at(dates[-1]), exit_key, SubmissionOutcome.ACCEPTED),
        PteOrderUpdate('exit_filled', at(dates[-1]), exit_key, InspectionOrderStatus.FILLED, shares, sell_fill, exit_fee),
    )

    def checkpoint(event, orders, quantity, available, frozen, target, count, health=AccountHealth.OK):
        return PteCheckpointExpectation(event.replace(':', '_') + '_check', event, orders, quantity,
            available, frozen, target, health, count)

    initial = checkpoint('LOAD', (), 0, cash, zero, None, 0)
    checkpoints = [initial]
    for event, count in (('enter:decision', 0), ('enter:repeat', 0), ('enter:submit', 1)):
        checkpoints.append(checkpoint(event, buy, 0, cash_reserved, reserve, shares, count))
    for event in ('entry_partial', 'entry_repeated'):
        checkpoints.append(checkpoint(event, buy, partial, partial_cash, partial_frozen, shares, 1))
    checkpoints.append(checkpoint('entry_filled', buy, shares, held_cash, zero, shares, 1))
    for suffix in ('decision', 'submit'):
        checkpoints.append(checkpoint('hold:' + suffix, (), shares, held_cash, zero, shares, 1))
    checkpoints.append(checkpoint('exit:decision', sell, shares, held_cash, zero, shares, 1))
    for event in ('exit:submit', 'exit_filled'):
        checkpoints.append(checkpoint(event, sell, 0, final_cash, zero, shares, 2))
    cycle = PteInspectionScenario('c9951_original_hold_cycle', cash, decisions, events, tuple(checkpoints),
        restart_after=('entry_partial',))
    unfilled = PteInspectionScenario('c9951_normal_day_unfilled', cash, (decisions[0],), (
        events[0], PteOrderUpdate('day_end_open', at(dates[0], 15, 1), entry_key, InspectionOrderStatus.OPEN, 0, zero, zero),
        PteOrderUpdate('entry_cancelled', at(dates[0], 15, 2), entry_key,
            InspectionOrderStatus.CANCELLED, 0, zero, zero),
        PteRepeatedOrderReport('cancel_repeated', at(dates[0], 15, 3), 'entry_cancelled'),
    ), (initial, *checkpoints[1:4],
        checkpoint('day_end_open', buy, 0, cash_reserved, reserve, shares, 1),
        checkpoint('entry_cancelled', buy, 0, cash, zero, shares, 1, AccountHealth.OK),
        checkpoint('cancel_repeated', buy, 0, cash, zero, shares, 1, AccountHealth.OK)), restart_after=('day_end_open',))
    coverage = tuple(PteCoverageRequirement(capability,
        CoverageRequirement.NOT_APPLICABLE if capability is PteInspectionCapability.POSITION_CHANGE else CoverageRequirement.REQUIRED,
        () if capability is PteInspectionCapability.POSITION_CHANGE else
        ((cycle.scenario_id, unfilled.scenario_id) if capability is PteInspectionCapability.NO_OR_PARTIAL_FILL else (cycle.scenario_id,)),
        'Frozen S002 binary intent and full_available_cash/entry_cycle capital, not target_equity_fraction; no multi-level position changes.'
        if capability is PteInspectionCapability.POSITION_CHANGE else 'Verify predeclared independent order/account facts.')
        for capability in PteInspectionCapability)
    failures = (
        PteFailureCase('damaged_package', cycle.scenario_id, PteFault.PACKAGE_CONTENT_CHANGED, 'LOAD'),
        PteFailureCase('missing_input', cycle.scenario_id, PteFault.INPUT_UNAVAILABLE, 'enter:decision'),
        PteFailureCase('future_input', cycle.scenario_id, PteFault.INPUT_AFTER_DECISION, 'enter:decision'),
    )
    protocol = PteInspectionProtocol(PteEnvironmentRequirement(environment.platform_build_sha256,
        environment.pte_contract_version, environment.srt_contract_version), (cycle, unfilled), coverage, failures)
    reasoning = {
        'method': 'Use the immutable original frozen S002 only to select model intent dates; order sizing and cash expectations are independently prescribed Decimal arithmetic. This is observation-upgrade trading equivalence, not independent financial correctness.',
        'period': {'start': dates[0].isoformat(), 'end': dates[-1].isoformat()},
        'selected_observations': selected, 'canonical_prefix': causal_prefix,
        'parent_binding': binding.to_dict(), 'source_inputs': provenance, 'single_day_inputs': binding_evidence,
        'formulae': {'signal': 'Original frozen CZSC fresh-transition event and five-session model state machine; no candidate output used as expectation.',
            'buy_limit': 'floor(previous_unadjusted_close / .001) * .001; zero entry premium',
            'cycle_shares': 'floor(100000 / (buy_limit * 1.0005 * 100)) * 100',
            'synthetic_prices': 'buy_fill=buy_limit; sell_fill=exit_previous_unadjusted_close',
            'final_cash': '100000 - buy_value - buy_fee + sell_value - sell_fee'},
        'arithmetic': {key: str(value) for key, value in {
            'entry_reference': entry_reference, 'buy_limit': buy_limit, 'cycle_shares': shares,
            'partial_shares': partial, 'buy_fill_price': fill_price, 'reserve': reserve,
            'cash_after_reserve': cash_reserved, 'partial_fee': partial_fee, 'partial_cash': partial_cash,
            'partial_frozen_cash': partial_frozen, 'buy_fee': full_fee, 'held_cash': held_cash,
            'sell_reference': sell_reference, 'sell_fill_price': sell_fill, 'sell_fee': exit_fee,
            'final_cash': final_cash}.items()},
        'limits': ['Causal signals and reference prices use authenticated historical inputs; channel reports and fills are synthetic prescribed facts.',
            'The full-fill cycle covers entry, partial fill, HOLD, exit, repetition and restart; the separate cancellation case covers terminal zero-fill.',
            'The zero-fill case requests DAY cancellation at the planned close before the terminal report; normal unfilled remains OK, preserving the cycle target. These cases do not establish independent financial correctness, historical liquidity, deployment or production readiness.'],
    }
    return protocol, reasoning


if __name__ == '__main__':
    import json, cloudpickle, os
    from copy import deepcopy
    from czsc_trader.application import RepositoryContext,create_research_context,describe_inspection_environment
    from czsc_trader.research_tools import ResearchBatchRef,ExecutionResources
    from strategy_runtime import StrategyCandidate,implementation_sha256
    for variable in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[variable]='1'
    root=Path(__file__).resolve().parents[5]
    home=Path(__file__).resolve().parents[1]
    work=json.loads((root/'research/S001/experiments/EX002_20261026/protocols/observation_sources.json').read_text(encoding='utf-8'))['S002-v1']
    payload=deepcopy(work['original']['strategy_payload'])
    installed=json.loads((root/'strategies/S002/releases/v1/runtime_binding.json').read_text(encoding='utf-8'))['install_files']
    payload['runtime']['source_files']=list(dict.fromkeys([*payload['runtime']['source_files'],*installed,'strategies/observation_s002_v4.py']))
    source_root=root/work['source']
    payload['runtime']['source_sha256']=implementation_sha256(tuple(payload['runtime']['source_files']),source_root=source_root)
    candidate=StrategyCandidate('S002','C9951',payload,source_root)
    ctx=create_research_context(RepositoryContext.discover(root),ResearchBatchRef('S002'),
        resources=ExecutionResources(2,1,42),providers=ProviderConfig(bindings={}))
    baseline=cloudpickle.loads((root/'.tmp/observation-v4-upgrade/S002-v1-baseline.pkl').read_bytes())
    environment=describe_inspection_environment(ctx.repository)
    protocol,design=build_protocol(ctx,candidate,baseline.execution_data,baseline.input_bindings['full'],environment)
    for name,value in (('pte_protocol',protocol.to_dict()),('pte_protocol_design',design)):
        (home/'others'/f'{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print('S002 PTE protocol prepared',design['period'],len(protocol.scenarios),len(protocol.failures))
