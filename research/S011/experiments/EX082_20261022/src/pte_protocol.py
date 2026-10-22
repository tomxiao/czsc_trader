"""Predeclare S011-C9902 PTE cases from authenticated causal inputs.

Signal arithmetic below is independent of SRT/PTE decision output. Synthetic
channel reports exercise account contracts; they do not claim historical fills.
"""
from datetime import date, datetime, time, timezone, timedelta
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

import numpy as np
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


def _independent_cycle(frames, parameters):
    """Literal rank/count arithmetic and canonical intent state, without SRT."""
    daily = frames['daily'].copy()
    daily.index = pd.to_datetime(daily.Date)
    daily = daily.loc['2024-12-26':]
    market = frames['market'].copy()
    market.index = pd.to_datetime(market.Date)
    bars = frames['bars'].copy()
    bars['day'] = pd.to_datetime(bars.Date).dt.normalize()
    bars['clock'] = pd.to_datetime(bars.Date).dt.strftime('%H:%M')
    intraday = bars.pivot(index='day', columns='clock', values='Close').loc['2024-12-26':]
    if set(intraday.columns) != {'10:00', '10:30', '11:00', '11:30', '13:30', '14:00', '14:30', '15:00'} or intraday.isna().any().any():
        raise ValueError('Incomplete independent intraday inputs')
    spx = frames['spx'].copy()
    spx.index = pd.to_datetime(spx.Date).dt.normalize()
    aligned, source_dates = [], []
    for day in daily.index:
        prior = spx.loc[spx.index < day.normalize()]
        if prior.empty or (day.normalize() - prior.index[-1]).days > 10:
            raise ValueError('Independent SPX alignment unavailable or stale')
        aligned.append(float(prior.PercentChange.iloc[-1]))
        source_dates.append(prior.index[-1].date().isoformat())
    values = pd.DataFrame({
        'tail': (intraday['15:00'] / intraday['13:30'] - 1).reindex(daily.index),
        'market': (market.Close / market.Close.shift(1) - 1).reindex(daily.index),
        'spx': aligned,
    }, index=daily.index)
    ranks = {}
    for name in values:
        ranked = []
        for offset in range(len(values)):
            window = values[name].iloc[max(0, offset + 1 - parameters['lookback']):offset + 1].to_numpy()
            valid = window[np.isfinite(window)]
            current = window[-1]
            ranked.append(float((np.count_nonzero(valid < current) + .5 * np.count_nonzero(valid == current)) / len(valid) - .5)
                          if len(valid) >= 20 and np.isfinite(current) else np.nan)
        ranks[name] = np.asarray(ranked)
    score = (-parameters['tail_weight'] * ranks['tail'] - (1 - parameters['tail_weight']) * ranks['market']
             + parameters['spx_weight'] * ranks['spx']) / (1 + parameters['spx_weight'])
    current, age, observations = 0, 0, []
    for offset, day in enumerate(daily.index):
        if day < pd.Timestamp('2025-02-05'):
            continue
        value = float(score[offset])
        if not np.isfinite(value):
            raise ValueError('Insufficient independent canonical warmup')
        reason = 'HOLD' if current else 'CASH'
        if current:
            age += 1
            if value <= parameters['exit'] or age >= parameters['max_days']:
                current = 0
                reason = 'PRESSURE_RELEASED' if value <= parameters['exit'] else 'SIGNAL_EXPIRED'
        elif value >= parameters['entry']:
            current, age, reason = 1, 0, 'PRESSURE_ENTRY'
        observations.append({'signal_date': day.date().isoformat(), 'score': value,
            'target_position': current, 'intent_age': age, 'reason': reason,
            'spx_source_date': source_dates[offset],
            'rank_tail': float(ranks['tail'][offset]), 'rank_market': float(ranks['market'][offset]),
            'rank_spx': float(ranks['spx'][offset])})
    for offset in range(len(observations) - 2):
        selected = observations[offset:offset + 3]
        if ([row['reason'] for row in selected[:2]] == ['PRESSURE_ENTRY', 'HOLD']
                and [row['target_position'] for row in selected] == [1, 1, 0]):
            return selected, observations[:offset + 3]
    raise ValueError('No canonical ENTER/HOLD/EXIT cycle in the authorized inputs')


def build_protocol(ctx, candidate, execution_data, binding, environment):
    root = ctx.repository.root
    if candidate.candidate_id != 'C9902' or candidate.strategy_family_id != 'S011':
        raise ValueError('This predeclared protocol is for S011-C9902')
    parameters = dict(candidate.payload['parameters'])
    if parameters != {'entry': .325, 'exit': .025, 'lookback': 130, 'max_days': 2,
                      'premium': .003, 'spx_weight': .05, 'tail_weight': .575}:
        raise ValueError('Unexpected repaired candidate parameters')
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

    selected, causal_prefix = _independent_cycle(frames, parameters)
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

    flows = Dataflows(base_dir=root, space=DataSpace(Path('research/S011/assets/data')),
        providers=ProviderConfig(bindings={dataset: ProviderBinding(
            's011-c9902-authenticated-history-slice', '1', source) for dataset, _, _ in originals}))
    bindings, binding_evidence = {}, {}
    for name, day, signal in zip(names, dates, signal_dates, strict=True):
        instance = StrategyRuntime(ctx.repository.strategy_root, dataflows=flows).create(StrategyInit(
            candidate, TradableWindow(day, day), root / '.tmp/s011_stage5_c9902/pte-prepare' / name,
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

    cash, fee, tick, zero = Decimal('100000'), Decimal('.001'), Decimal('.001'), Decimal('0')
    entry_reference = price_on(signal_dates[0])
    buy_limit = (entry_reference * Decimal('1.003') / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
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
    cycle = PteInspectionScenario('c9902_first_hold_cycle', cash, decisions, events, tuple(checkpoints),
        restart_after=('entry_partial',))
    unfilled = PteInspectionScenario('c9902_zero_fill_cancel', cash, (decisions[0],), (
        events[0], PteOrderUpdate('entry_cancelled', at(dates[0], 10, 1), entry_key,
            InspectionOrderStatus.CANCELLED, 0, zero, zero),
        PteRepeatedOrderReport('cancel_repeated', at(dates[0], 10, 2), 'entry_cancelled'),
    ), (initial, *checkpoints[1:4],
        checkpoint('entry_cancelled', buy, 0, cash, zero, shares, 1, AccountHealth.BLOCKED),
        checkpoint('cancel_repeated', buy, 0, cash, zero, shares, 1, AccountHealth.BLOCKED)), restart_after=('entry_cancelled',))
    coverage = tuple(PteCoverageRequirement(capability,
        CoverageRequirement.NOT_APPLICABLE if capability is PteInspectionCapability.POSITION_CHANGE else CoverageRequirement.REQUIRED,
        () if capability is PteInspectionCapability.POSITION_CHANGE else
        ((cycle.scenario_id, unfilled.scenario_id) if capability is PteInspectionCapability.NO_OR_PARTIAL_FILL else (cycle.scenario_id,)),
        'Binary intent with a fixed entry-cycle quantity; fractional equity rebalancing is not applicable.'
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
        'method': 'Independent causal rank/count arithmetic; first canonical entry with one HOLD then exit; no SRT/PTE result used as expectation.',
        'period': {'start': dates[0].isoformat(), 'end': dates[-1].isoformat()},
        'selected_observations': selected, 'canonical_prefix': causal_prefix,
        'parent_binding': binding.to_dict(), 'source_inputs': provenance, 'single_day_inputs': binding_evidence,
        'formulae': {'score': '(-.575 * rank(tail) - .425 * rank(market_return) + .05 * rank(strict_prior_spx)) / 1.05',
            'rank': '(count(window < current) + .5 * count(window == current)) / valid_count - .5; min20/max130',
            'signal': 'Canonical replay from 2025-02-05; enter score>=.325; exit score<=.025 or intent age>=2.',
            'buy_limit': 'floor(previous_unadjusted_close * 1.003 / .001) * .001',
            'cycle_shares': 'floor(100000 / (buy_limit * 1.001 * 100)) * 100',
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
            'These cases establish sandbox runtime/account behavior, not historical liquidity, live availability, deployment or production readiness.'],
    }
    return protocol, reasoning
