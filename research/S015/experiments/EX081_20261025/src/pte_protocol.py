"""C9304 historical PTE scenarios with independently derived expectations.

Signals are reconstructed from price mathematics, never from SRT/PTE output.
Only existing authenticated S015 inputs are exposed to the local slice provider.
"""
from datetime import date, datetime, time, timezone, timedelta
from decimal import Decimal, ROUND_FLOOR
import math
from pathlib import Path
from statistics import median

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

CONTENT = 'abf26e331cac4cd030c30aa5f84269e0471d3a4c31b36f5e9f8a0dbf687beda1'
PARAMETERS = {'center_kind': 'median', 'lookback': 3, 'allocation': 1.0,
              'minimum_repair_space': 0.0017298986606429072}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def build_protocol(research, candidate, execution_data, input_binding, environment):
    root = research.repository.root
    require(candidate.candidate_id == 'C9304' and candidate.strategy_family_id == 'S015', 'Wrong candidate')
    require(dict(candidate.payload['parameters']) == PARAMETERS, 'Candidate parameters changed')
    require(StrategyRuntime().identify(candidate, dependencies=()).content_sha256 == CONTENT,
            'Candidate implementation or payload changed')
    originals, frames, provenance = {}, {}, {}
    for role, request in input_binding.plan.requests.items():
        result = research.data.fetch(request, prepared=input_binding.prepared)
        require(result.ready and canonical_frame_sha256(result.dataframe) == result.identity.content_sha256,
                f'Unauthenticated original input: {role}')
        require(request.dataset not in originals, 'Ambiguous original dataset slice')
        originals[request.dataset] = (request, result)
        frames[role] = result.dataframe
        provenance[role] = {'sha256': result.identity.content_sha256, 'source': result.identity.source,
                            'data_start': result.identity.data_start, 'data_cutoff': result.identity.data_cutoff}

    # Independent transcription of the immutable financial rule. In particular,
    # an active opportunity keeps its opening target and origin; no holding timer.
    adjusted = {pd.Timestamp(r.Date).date(): float(r.Close) for r in frames['market'].itertuples()}
    unadjusted = {pd.Timestamp(r.Date).date(): float(r.Close) for r in frames['execution'].itertuples()}
    bars = frames['intraday'].copy()
    bars['session'] = pd.to_datetime(bars.Date).dt.date
    history, cycles = [], []
    active, opening = False, None
    repair_target = invalidation_origin = 0.
    clocks = ('10:00', '10:30', '11:00', '11:30', '13:30', '14:00', '14:30', '15:00')
    for day, group in bars.groupby('session', sort=True):
        require(tuple(pd.to_datetime(group.Date).dt.strftime('%H:%M')) == clocks, 'Unexpected intraday grid')
        center = median(math.log(float(x)) for x in group.Close) + math.log(adjusted[day] / unadjusted[day])
        closing = math.log(adjusted[day])
        gain = center - history[-3]['center_log'] if len(history) >= 3 else None
        space = math.expm1(center - closing)
        permit = gain is not None and gain > 0 and closing < center and space >= PARAMETERS['minimum_repair_space']
        event = 'hold' if active else 'flat'
        if active:
            if closing >= repair_target or center <= invalidation_origin:
                active, event = False, 'exit'
                cycles.append((opening, len(history)))
        elif permit:
            active, event, opening = True, 'enter', len(history)
            repair_target, invalidation_origin = center, center - gain
        history.append({'signal_date': day.isoformat(), 'center_log': center, 'close_log': closing,
                        'center_gain': gain, 'repair_space': space, 'permit': permit, 'event': event,
                        'active': active, 'repair_target_log': repair_target,
                        'invalidation_origin_log': invalidation_origin})
    # Select by required event shape only, never by profit. Two hold decisions
    # permit an independent partial-cancel/replenishment scenario plus a true hold.
    eligible = [(start, end) for start, end in cycles if end - start >= 3]
    require(bool(eligible), 'No historical enter/two-hold/exit sequence available')
    start, end = eligible[0]
    observations = history[start:end + 1]
    require([x['event'] for x in observations] == ['enter', 'hold', 'hold', 'exit'],
            'First selected cycle shape changed; review protocol before extending it')
    signal_dates = tuple(date.fromisoformat(x['signal_date']) for x in observations)
    require(signal_dates == (date(2025, 2, 18), date(2025, 2, 19), date(2025, 2, 20), date(2025, 2, 21)),
            'Authenticated first qualifying cycle changed')
    execution_frame = execution_data.raw_execution_daily
    trading_sessions = tuple(pd.to_datetime(execution_frame.dt).dt.date)
    dates = tuple(next(day for day in trading_sessions if day > signal) for signal in signal_dates)
    require(dates == (date(2025, 2, 19), date(2025, 2, 20), date(2025, 2, 21), date(2025, 2, 24)),
            'Unexpected execution calendar')
    names = ('enter', 'hold_one', 'hold_two', 'exit')

    def source(request):
        original_request, result = originals[request.dataset]
        require(request.symbol == original_request.symbol and request.frequency == original_request.frequency
                and request.parameters == original_request.parameters
                and pd.Timestamp(request.start) >= pd.Timestamp(original_request.start)
                and pd.Timestamp(request.end) <= pd.Timestamp(original_request.end),
                'PTE slice exceeds authenticated original input')
        frame = result.dataframe
        # Requests are inclusive session dates; retain all eight end-day bars
        # while keeping the original timestamp column and observation clocks.
        sessions = pd.to_datetime(frame.Date).dt.normalize()
        mask = sessions.between(pd.Timestamp(request.start).normalize(), pd.Timestamp(request.end).normalize())
        return frame.loc[mask].copy(), dict(result.identity.metadata)

    flows = Dataflows(base_dir=root, space=DataSpace(Path('research/S015/assets/data')),
        providers=ProviderConfig(bindings={dataset: ProviderBinding(
            's015-c9304-authenticated-history-slice', '1', source) for dataset in originals}))
    bindings, binding_evidence = {}, {}
    for name, day, signal in zip(names, dates, signal_dates, strict=True):
        instance = StrategyRuntime(research.repository.strategy_root, dataflows=flows).create(StrategyInit(
            candidate, TradableWindow(day, day), root / '.tmp/s015-ex081/pte-prepare' / name,
            pricing=execution_data.pricing))
        instance.prepare_data(policy=PreparePolicy.REUSE)
        binding = instance.input_binding
        require(binding.plan.available_through == signal, 'PTE binding changes signal date')
        bindings[name] = binding
        evidence = {'binding': binding.to_dict(), 'input_hashes': {}}
        for role, request in binding.plan.requests.items():
            observed = flows.fetch(request, prepared=binding.prepared)
            expected, _ = source(request)
            require(observed.ready and observed.identity.content_sha256 == canonical_frame_sha256(expected),
                    'Prepared PTE input differs from independent original slice')
            evidence['input_hashes'][role] = observed.identity.content_sha256
        binding_evidence[name] = evidence

    def price(day, column):
        values = execution_frame.loc[pd.to_datetime(execution_frame.dt).dt.date.eq(day), column]
        require(len(values) == 1, 'Execution price must be unique')
        return Decimal(str(values.iloc[0]))

    cash, fee, tick, zero = Decimal('100000'), Decimal('.001'), Decimal('.001'), Decimal('0')

    def limit(reference):
        # 1% buy limit is below the 10% exchange upper guard for these inputs.
        requested = (reference * Decimal('1.01') / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
        guard = (reference * Decimal('1.10') / tick).to_integral_value(rounding=ROUND_FLOOR) * tick - tick
        return min(requested, guard)

    entry_reference, retry_reference = price(signal_dates[0], 'close'), price(signal_dates[1], 'close')
    buy_limit, retry_limit = limit(entry_reference), limit(retry_reference)
    shares = int((cash / (buy_limit * (1 + fee) * 100)).to_integral_value(rounding=ROUND_FLOOR)) * 100
    partial = shares // 200 * 100
    remaining = shares - partial
    fill_price, retry_price, sell_price = price(dates[0], 'open'), price(dates[1], 'open'), price(dates[-1], 'open')
    sell_reference = price(signal_dates[-1], 'close')
    require((buy_limit, shares, partial, retry_limit) == (Decimal('1.096'), 91100, 45500, Decimal('1.104')),
            'Independent order arithmetic changed')
    require(fill_price <= buy_limit and retry_price <= retry_limit, 'Prescribed fills exceed their limits')
    for day, value in ((dates[0], fill_price), (dates[1], retry_price), (dates[-1], sell_price)):
        require(price(day, 'low') <= value <= price(day, 'high'), 'Fill price outside historical daily range')
    reserve = shares * buy_limit * (1 + fee)
    partial_fee = partial * fill_price * fee
    partial_cost = partial * fill_price + partial_fee
    partial_frozen = remaining * buy_limit * (1 + fee)
    partial_available = cash - partial_cost - partial_frozen
    full_fee = shares * fill_price * fee
    full_cost = shares * fill_price + full_fee
    retry_reserve = remaining * retry_limit * (1 + fee)
    retry_fee = remaining * retry_price * fee
    retry_cost = remaining * retry_price + retry_fee
    require(retry_reserve <= cash - partial_cost, 'Remaining locked budget cannot fund the prescribed retry')
    exit_fee = shares * sell_price * fee
    sell_net = shares * sell_price - exit_fee
    buy = (PlannedOrder(OrderSide.BUY, shares, OrderType.LIMIT, buy_limit),)
    refill = (PlannedOrder(OrderSide.BUY, remaining, OrderType.LIMIT, retry_limit),)
    sell = (PlannedOrder(OrderSide.SELL, shares, OrderType.MARKET, sell_reference),)
    zone = timezone(timedelta(hours=8))

    def at(day, hour=10, minute=0):
        return datetime.combine(day, time(hour, minute), zone)

    scenarios, expected_cycles, arithmetic = [], {}, {}
    for retry in (False, True):
        sid = 'c9304_partial_cancel_retry' if retry else 'c9304_partial_full_cycle'
        steps = ('enter', 'retry' if retry else 'hold_one', 'hold_two', 'exit')
        decisions = tuple(PteDecisionInput(step, bindings[name], at(signal, 20, 31), day, at(day),
                                          step in ('enter', 'exit'))
            for step, name, signal, day in zip(steps, names, signal_dates, dates, strict=True))
        entry_key, exit_key = PteOrderKey('enter', 0), PteOrderKey('exit', 0)
        events = [
            PteSubmissionResult('entry_accepted', at(dates[0]), entry_key, SubmissionOutcome.ACCEPTED),
            PteOrderUpdate('entry_open', at(dates[0], 10, 1), entry_key, InspectionOrderStatus.OPEN, 0, zero, zero),
            PteOrderUpdate('entry_partial', at(dates[0], 10, 2), entry_key, InspectionOrderStatus.PARTIAL,
                           partial, fill_price, partial_fee),
            PteRepeatedOrderReport('entry_repeated', at(dates[0], 10, 3), 'entry_partial'),
            PteOrderUpdate('entry_cancelled' if retry else 'entry_filled', at(dates[0], 10, 4), entry_key,
                           InspectionOrderStatus.CANCELLED if retry else InspectionOrderStatus.FILLED,
                           partial if retry else shares, fill_price, partial_fee if retry else full_fee),
        ]
        if retry:
            retry_key = PteOrderKey('retry', 0)
            events.extend((
                PteSubmissionResult('retry_accepted', at(dates[1]), retry_key, SubmissionOutcome.ACCEPTED),
                PteOrderUpdate('retry_filled', at(dates[1], 10, 1), retry_key, InspectionOrderStatus.FILLED,
                               remaining, retry_price, retry_fee),
            ))
        events.extend((
            PteSubmissionResult('exit_accepted', at(dates[-1]), exit_key, SubmissionOutcome.ACCEPTED),
            PteOrderUpdate('exit_filled', at(dates[-1]), exit_key, InspectionOrderStatus.FILLED,
                           shares, sell_price, exit_fee),
            PteRepeatedOrderReport('exit_repeated', at(dates[-1], 10, 1), 'exit_filled'),
        ))
        checkpoints, cycle_states = [], {}

        def check(event, orders, quantity, available, frozen, target, count, spent=zero, phase='ACTIVE'):
            for value in (available, frozen, spent):
                require(value == value.quantize(Decimal('.0001')), 'Expected cash has unsupported precision')
            checkpoints.append(PteCheckpointExpectation(event.replace(':', '_') + '_check', event,
                orders, quantity, available, frozen, target, AccountHealth.OK, count))
            cycle_states[event] = None if target is None else {
                'allocation_fraction': '1.0', 'cash_budget': str(cash), 'target_quantity': shares,
                'buy_cost_including_fees': str(spent), 'remaining_budget': str(cash - spent), 'phase': phase}

        check('LOAD', (), 0, cash, zero, None, 0)
        for event, count in (('enter:decision', 0), ('enter:repeat', 0), ('enter:submit', 1),
                             ('entry_accepted', 1), ('entry_open', 1)):
            check(event, buy, 0, cash - reserve, reserve, shares, count)
        for event in ('entry_partial', 'entry_repeated'):
            check(event, buy, partial, partial_available, partial_frozen, shares, 1, partial_cost)
        spent = partial_cost + retry_cost if retry else full_cost
        held_cash = cash - spent
        if retry:
            check('entry_cancelled', buy, partial, cash - partial_cost, zero, shares, 1, partial_cost)
            for event, count in (('retry:decision', 1), ('retry:submit', 2), ('retry_accepted', 2)):
                check(event, refill, partial, cash - partial_cost - retry_reserve, retry_reserve,
                      shares, count, partial_cost)
            check('retry_filled', refill, shares, held_cash, zero, shares, 2, spent)
        else:
            check('entry_filled', buy, shares, held_cash, zero, shares, 1, spent)
            for event in ('hold_one:decision', 'hold_one:submit'):
                check(event, (), shares, held_cash, zero, shares, 1, spent)
        order_count = 2 if retry else 1
        for event in ('hold_two:decision', 'hold_two:submit'):
            check(event, (), shares, held_cash, zero, shares, order_count, spent)
        for event in ('exit:decision', 'exit:repeat'):
            check(event, sell, shares, held_cash, zero, shares, order_count, spent, 'EXITING')
        final_cash = held_cash + sell_net
        for event in ('exit_accepted', 'exit:submit', 'exit_filled', 'exit_repeated'):
            check(event, sell, 0, final_cash, zero, None, order_count + 1)
        scenario = PteInspectionScenario(sid, cash, decisions, tuple(events), tuple(checkpoints),
            restart_after=('entry_cancelled',) if retry else ('entry_partial',))
        scenarios.append(scenario)
        expected_cycles[sid] = cycle_states
        arithmetic[sid] = {key: str(value) for key, value in {
            'entry_reference': entry_reference, 'buy_limit': buy_limit, 'target_quantity': shares,
            'partial_quantity': partial, 'entry_fill_price': fill_price, 'initial_reserve': reserve,
            'partial_cost_including_fees': partial_cost, 'partial_frozen_cash': partial_frozen,
            'partial_available_cash': partial_available, 'retry_reference': retry_reference,
            'retry_limit': retry_limit, 'retry_quantity': remaining if retry else 0,
            'retry_fill_price': retry_price, 'retry_reserve': retry_reserve if retry else zero,
            'total_buy_cost_including_fees': spent, 'held_cash': held_cash,
            'sell_reference': sell_reference, 'sell_fill_price': sell_price, 'sell_fee': exit_fee,
            'final_cash': final_cash}.items()}

    scenario_ids = tuple(x.scenario_id for x in scenarios)
    coverage = tuple(PteCoverageRequirement(capability,
        CoverageRequirement.NOT_APPLICABLE if capability is PteInspectionCapability.POSITION_CHANGE else CoverageRequirement.REQUIRED,
        () if capability is PteInspectionCapability.POSITION_CHANGE else scenario_ids,
        'Binary opportunity with locked entry-cycle budget/quantity; it does not rebalance to a changing equity weight.'
        if capability is PteInspectionCapability.POSITION_CHANGE
        else 'Authenticated historical signal sequence and independently prescribed cash/order/position facts.')
        for capability in PteInspectionCapability)
    failures = tuple(PteFailureCase('c9304_' + fault.value.lower(), scenario_ids[0], fault,
        'LOAD' if fault is PteFault.PACKAGE_CONTENT_CHANGED else 'enter:decision') for fault in PteFault)
    protocol = PteInspectionProtocol(PteEnvironmentRequirement(environment.platform_build_sha256,
        environment.pte_contract_version, environment.srt_contract_version), tuple(scenarios), coverage, failures)
    reasoning = {
        'method': 'Independent price mathematics and Decimal cash arithmetic before any SRT/PTE outcome; no strategy decision output used as an oracle.',
        'candidate': candidate.reference_id, 'content_sha256': CONTENT, 'parameters': PARAMETERS,
        'selection_rule': 'First completed opportunity with at least two intermediate hold signals; not selected by profit.',
        'signal_dates': [x.isoformat() for x in signal_dates], 'execution_dates': [x.isoformat() for x in dates],
        'observations': observations, 'earlier_completed_cycle_count': sum(e < start for _, e in cycles),
        'source_inputs': provenance, 'parent_binding': input_binding.to_dict(), 'single_day_inputs': binding_evidence,
        'arithmetic': arithmetic, 'expected_entry_cycle_states': expected_cycles,
        'entry_cycle_assertion': 'Compare numeric Decimal fields and phase at every named checkpoint; remaining_budget is derived. cycle_id and opening_signal_identity are runtime identities, required constant within each scenario, not hardcoded.',
        'formulae': {
            'center': 'median(log(eight unadjusted 30m closes)) + log(adjusted daily close / unadjusted daily close)',
            'entry': 'center > center three sessions ago; adjusted close below center; exp(center-log(close))-1 >= fixed gap',
            'exit': 'adjusted close reaches opening fixed center OR current center falls to opening center minus opening center_gain',
            'budget': 'entry cash * signal allocation = 100000; lock until terminal exit, never reset on refill or hold',
            'quantity': 'floor(budget / (tick-rounded 1% limit * 1.001 * 100)) * 100',
            'refill': 'min(locked target - actual shares, affordable lots from min(cash, budget-actual cumulative buy cost))',
            'cash': 'initial cash - actual filled buy value - actual buy fees - outstanding buy reserves + realized sell proceeds - sell fees',
        },
        'limits': [
            'Historical authenticated inputs only. The strategy declares LAST=2026-10-21; this does not establish future-date deployability.',
            'Each isolated technical account starts with100000; it is not a new economic backtest or independent validation sample.',
            'Channel events are synthetic prescribed reports at historical in-range prices, not proof of actual liquidity or fills.',
            'Recorded market-order inspection contract requires synchronous complete fills; partial SELL is not simulated.',
            'All three public fault kinds are exercised on the first scenario. No production data/account/service is accessed.',
        ],
    }
    require(PteInspectionProtocol.from_dict(protocol.to_dict()) == protocol, 'Protocol serialization changed')
    return protocol, reasoning
