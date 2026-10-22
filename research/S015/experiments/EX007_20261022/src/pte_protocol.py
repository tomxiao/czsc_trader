"""C0031: predeclared first-cycle PTE scenario with independent expectations.

Only authenticated EX006 input frames are sliced through the public DFLS API.
This builder does not execute SRT decisions or observe any PTE results.
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


def build_protocol(research, candidate, execution_data, input_binding, environment):
    """Return the protocol and the independent derivation, before inspection."""
    root = research.repository.root
    zone = timezone(timedelta(hours=8))
    dates = (date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 6), date(2025, 1, 7))
    names = ('enter', 'hold_one', 'hold_two', 'exit')
    assert candidate.candidate_id == 'C0031' and candidate.strategy_family_id == 'S015'
    assert dict(candidate.payload['parameters']) == {'entry': 0, 'exit': .005, 'max_days': 3, 'range_cap': 0}
    originals = {}
    provenance = {}
    for role, request in input_binding.plan.requests.items():
        result = research.data.fetch(request, prepared=input_binding.prepared)
        if not result.ready or canonical_frame_sha256(result.dataframe) != result.identity.content_sha256:
            raise ValueError(f'Unauthenticated original input: {role}')
        originals[request.dataset] = (request, result)
        provenance[role] = {'sha256': result.identity.content_sha256, 'source': result.identity.source,
                            'data_start': result.identity.data_start, 'data_cutoff': result.identity.data_cutoff}

    def source(request):
        original_request, result = originals[request.dataset]
        if (request.symbol != original_request.symbol or request.frequency != original_request.frequency
                or request.parameters != original_request.parameters
                or pd.Timestamp(request.start) < pd.Timestamp(original_request.start)
                or pd.Timestamp(request.end) > pd.Timestamp(original_request.end)):
            raise ValueError('PTE slice exceeds its authenticated original selection')
        frame = result.dataframe
        dates_in_frame = pd.to_datetime(frame['Date'])
        sliced = frame.loc[dates_in_frame.between(pd.Timestamp(request.start), pd.Timestamp(request.end))].copy()
        return sliced, dict(result.identity.metadata)

    # Same registered research data space, new immutable prepared references.
    # Every provider is the closed, authenticated local slice above: no network.
    flows = Dataflows(base_dir=root, space=DataSpace(Path('research/S015/assets/data')),
                      providers=ProviderConfig(bindings={dataset: ProviderBinding(
                          's015-c0031-authenticated-history-slice', '1', source) for dataset in originals}))
    bindings = {}
    binding_evidence = {}
    for name, day in zip(names, dates, strict=True):
        instance = StrategyRuntime(research.repository.strategy_root, dataflows=flows).create(StrategyInit(
            candidate, TradableWindow(day, day), root / '.tmp/s015_stage5_v2/pte-prepare' / name,
            pricing=execution_data.pricing))
        instance.prepare_data(policy=PreparePolicy.REUSE)
        binding = instance.input_binding
        bindings[name] = binding
        binding_evidence[name] = {'binding': binding.to_dict(), 'input_hashes': {}}
        for role, request in binding.plan.requests.items():
            observed = flows.fetch(request, prepared=binding.prepared)
            expected_frame, _ = source(request)
            if not observed.ready or observed.identity.content_sha256 != canonical_frame_sha256(expected_frame):
                raise ValueError('Prepared PTE input differs from independent source slice')
            binding_evidence[name]['input_hashes'][role] = observed.identity.content_sha256

    market = research.data.fetch(input_binding.plan.requests['market'], prepared=input_binding.prepared).dataframe
    rows = market.loc[pd.to_datetime(market.Date).between('2024-12-31', '2025-01-06')].copy()
    pressure = rows.Close / (rows.Amount / rows.Volume) - 1
    age = 0
    observations = []
    for day, value in zip(rows.Date, pressure, strict=True):
        if age:
            age = 0 if age >= 3 or value >= .005 else age + 1
        elif value <= 0:
            age = 1
        observations.append({'signal_date': pd.Timestamp(day).date().isoformat(),
                             'pressure': float(value), 'intent_age': age, 'target_position': int(age > 0)})
    assert [row['intent_age'] for row in observations] == [1, 2, 3, 0]
    assert [bindings[name].plan.available_through.isoformat() for name in names] == [row['signal_date'] for row in observations]

    def price_on(day, column):
        frame = execution_data.raw_execution_daily
        selected = frame.loc[pd.to_datetime(frame.dt).dt.date.eq(day), column]
        if len(selected) != 1:
            raise ValueError('Original execution input must contain one price per requested day')
        return Decimal(str(selected.iloc[0]))

    cash = Decimal('100000')
    fee = Decimal('.001')
    entry_reference = price_on(date(2024, 12, 31), 'close')
    tick = Decimal('.001')
    buy_limit = (entry_reference * Decimal('1.01') / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
    shares = int((cash / (buy_limit * (1 + fee) * 100)).to_integral_value(rounding=ROUND_FLOOR)) * 100
    partial = shares // 200 * 100
    fill_price = price_on(dates[0], 'open')
    sell_reference = price_on(date(2025, 1, 6), 'close')
    sell_fill = price_on(dates[-1], 'open')
    assert (entry_reference, buy_limit, shares, fill_price, sell_reference, sell_fill) == (
        Decimal('1.118'), Decimal('1.129'), 88400, Decimal('1.112'), Decimal('1.048'), Decimal('1.049'))
    assert price_on(dates[0], 'low') <= fill_price <= min(buy_limit, price_on(dates[0], 'high'))
    assert price_on(dates[-1], 'low') <= sell_fill <= price_on(dates[-1], 'high')
    reserve = shares * buy_limit * (1 + fee)
    cash_reserved = cash - reserve
    partial_fee = partial * fill_price * fee
    partial_cash = cash_reserved + partial * buy_limit * (1 + fee) - partial * fill_price - partial_fee
    partial_frozen = (shares - partial) * buy_limit * (1 + fee)
    full_fee = shares * fill_price * fee
    held_cash = cash - shares * fill_price - full_fee
    exit_fee = shares * sell_fill * fee
    final_cash = held_cash + shares * sell_fill - exit_fee
    assert all(value == value.quantize(Decimal('.0001')) for value in (
        reserve, cash_reserved, partial_fee, partial_cash, partial_frozen, full_fee, held_cash, exit_fee, final_cash))
    buy = (PlannedOrder(OrderSide.BUY, shares, OrderType.LIMIT, buy_limit),)
    sell = (PlannedOrder(OrderSide.SELL, shares, OrderType.MARKET, sell_reference),)

    def at(day, hour=10, minute=0):
        return datetime.combine(day, time(hour, minute), zone)

    decisions = tuple(PteDecisionInput(name, bindings[name],
        at(bindings[name].plan.available_through, 20, 31), day, at(day), name == 'enter')
        for name, day in zip(names, dates, strict=True))
    entry_key, exit_key = PteOrderKey('enter', 0), PteOrderKey('exit', 0)
    events = (
        PteSubmissionResult('entry_accepted', at(dates[0]), entry_key, SubmissionOutcome.ACCEPTED),
        PteOrderUpdate('entry_partial', at(dates[0], 10, 1), entry_key, InspectionOrderStatus.PARTIAL,
                       partial, fill_price, partial_fee),
        PteRepeatedOrderReport('entry_repeated', at(dates[0], 10, 2), 'entry_partial'),
        PteOrderUpdate('entry_filled', at(dates[0], 10, 3), entry_key, InspectionOrderStatus.FILLED,
                       shares, fill_price, full_fee),
        PteSubmissionResult('exit_accepted', at(dates[-1]), exit_key, SubmissionOutcome.ACCEPTED),
        PteOrderUpdate('exit_filled', at(dates[-1]), exit_key, InspectionOrderStatus.FILLED,
                       shares, sell_fill, exit_fee),
    )

    def checkpoint(event, orders, quantity, available, frozen, target, count):
        return PteCheckpointExpectation(event.replace(':', '_') + '_check', event, orders, quantity,
            available, frozen, target, AccountHealth.OK, count)

    zero = Decimal('0')
    checkpoints = [checkpoint('LOAD', (), 0, cash, zero, None, 0)]
    for event, count in (('enter:decision', 0), ('enter:repeat', 0), ('enter:submit', 1)):
        checkpoints.append(checkpoint(event, buy, 0, cash_reserved, reserve, shares, count))
    for event in ('entry_partial', 'entry_repeated'):
        checkpoints.append(checkpoint(event, buy, partial, partial_cash, partial_frozen, shares, 1))
    checkpoints.append(checkpoint('entry_filled', buy, shares, held_cash, zero, shares, 1))
    for name in ('hold_one', 'hold_two'):
        for suffix in ('decision', 'submit'):
            checkpoints.append(checkpoint(name + ':' + suffix, (), shares, held_cash, zero, shares, 1))
    checkpoints.append(checkpoint('exit:decision', sell, shares, held_cash, zero, shares, 1))
    for event in ('exit:submit', 'exit_filled'):
        checkpoints.append(checkpoint(event, sell, 0, final_cash, zero, shares, 2))
    scenario = PteInspectionScenario('c0031_first_cycle', cash, decisions, events,
                                    tuple(checkpoints), restart_after=('entry_partial',))
    coverage = tuple(PteCoverageRequirement(capability,
        CoverageRequirement.NOT_APPLICABLE if capability is PteInspectionCapability.POSITION_CHANGE else CoverageRequirement.REQUIRED,
        () if capability is PteInspectionCapability.POSITION_CHANGE else (scenario.scenario_id,),
        'C0031 has binary intent and a fixed entry-cycle quantity; fractional equity rebalancing is not applicable.'
        if capability is PteInspectionCapability.POSITION_CHANGE else 'Verify independently declared first-cycle order and account facts.')
        for capability in PteInspectionCapability)
    failures = (
        PteFailureCase('damaged_package', scenario.scenario_id, PteFault.PACKAGE_CONTENT_CHANGED, 'LOAD'),
        PteFailureCase('missing_input', scenario.scenario_id, PteFault.INPUT_UNAVAILABLE, 'enter:decision'),
        PteFailureCase('future_input', scenario.scenario_id, PteFault.INPUT_AFTER_DECISION, 'enter:decision'),
    )
    protocol = PteInspectionProtocol(PteEnvironmentRequirement(environment.platform_build_sha256,
        environment.pte_contract_version, environment.srt_contract_version), (scenario,), coverage, failures)
    reasoning = {
        'method': 'Independent C0031 source-rule arithmetic and authenticated historical input slicing; no SRT/PTE output used as expectations.',
        'period': {'start': dates[0].isoformat(), 'end': dates[-1].isoformat()},
        'observations': observations, 'parent_binding': input_binding.to_dict(),
        'source_inputs': provenance, 'single_day_inputs': binding_evidence,
        'formulae': {'pressure': 'Close / (Amount / Volume) - 1',
            'signal': 'Enter if pressure <= 0; exit at age >= 3 or pressure >= .005; otherwise increase age.',
            'buy_limit': 'floor(previous_unadjusted_close * 1.01 / .001) * .001',
            'cycle_shares': 'floor(100000 / (buy_limit * 1.001 * 100)) * 100',
            'partial_cash': '100000 - full_reserve + filled_reserve - filled_value - filled_fee',
            'final_cash': '100000 - buy_value - buy_fee + sell_value - sell_fee'},
        'arithmetic': {key: str(value) for key, value in {
            'entry_reference': entry_reference, 'buy_limit': buy_limit, 'cycle_shares': shares,
            'partial_shares': partial, 'buy_fill_price': fill_price, 'reserve': reserve,
            'cash_after_reserve': cash_reserved, 'partial_fee': partial_fee, 'partial_cash': partial_cash,
            'partial_frozen_cash': partial_frozen, 'buy_fee': full_fee, 'held_cash': held_cash,
            'sell_reference': sell_reference, 'sell_fill_price': sell_fill, 'sell_fee': exit_fee,
            'final_cash': final_cash}.items()},
        'limits': ['Historical prices and causal signals are original bound inputs; execution reports are synthetic prescribed events.',
            'A fixed cycle quantity survives fills and both hold days, so no additional buy is expected.',
            'Price and quantity expectations do not establish real liquidity, latency, or historical live availability.'],
    }
    return protocol, reasoning
