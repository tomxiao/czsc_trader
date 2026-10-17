"""Offline causal and public SRT input-contract checks; no strategy account runs."""
import ast
from datetime import date
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from uuid import UUID

import numpy as np
import pandas as pd
import requests
from dataflows import DataRequest, Dataset, PreparedDataRef, ProviderConfig
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef
from strategy_runtime import (ParameterSet, StrategyCandidate, StrategyInit, StrategyInputBinding,
                              StrategyRuntime, TradableWindow, implementation_sha256)
from build_candidates import ROOT, EX, OLD, PACKAGE, VARIANTS

FULL_REFERENCE = {'space_id': '9b7260bb-f12c-4eab-bc37-884d0cc58c91',
                  'preparation_id': 'dfb12e42-f327-4e1b-bf25-d15201b4e69b',
                  'manifest_sha256': 'b68cf906d81e19a16b131fe63ca1f4f901f9baa202bae75110481b5f209d8f57'}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    destination = EX / 'others/precheck.json'
    if destination.exists():
        raise RuntimeError('Preserve existing precheck evidence')
    calls = []
    def prohibited(*args, **kwargs):
        calls.append('ATTEMPTED')
        raise RuntimeError('No supplier access permitted during precheck')
    requests.sessions.Session.request = prohibited
    checks = []
    def check(name, value):
        assert bool(value), name
        checks.append(name)
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'), providers=ProviderConfig())
    prepared = PreparedDataRef(UUID(FULL_REFERENCE['space_id']), UUID(FULL_REFERENCE['preparation_id']), FULL_REFERENCE['manifest_sha256'])
    datasets = {}
    identities = {}
    for dataset, symbol, start in ((Dataset.TRADING_CALENDAR, 'SSE', '2019-12-01'),
        (Dataset.STOCK_OHLCV, '600722.SH', '2019-12-31'),
        (Dataset.STOCK_UNADJUSTED_DAILY, '600722.SH', '2019-12-31'),
        (Dataset.SECURITY_PRICE_LIMITS, '600722.SH', '2020-01-01'),
        (Dataset.SECURITY_TRADING_STATUS, '600722.SH', '2019-12-01')):
        request = DataRequest(dataset, symbol, start, '2026-10-15', '2026-10-15')
        fetched = ctx.data.fetch(request, prepared=prepared)
        check('authenticated offline input ' + dataset.value, fetched.ready)
        datasets[dataset.value] = fetched
        identities[dataset.value] = fetched.identity.content_sha256
    source = PACKAGE / 'strategies/repair.py'
    strategy = module('ex018_repair_precheck', source)
    previous = module('ex017_repair_precheck', OLD / 'src/strategy_runtime/strategies/repair_v3.py')
    old_payload = json.loads((OLD / 'protocols/payload_v3_parent_H3.json').read_text(encoding='utf-8'))
    check('old frozen closure authenticated', implementation_sha256(tuple(old_payload['runtime']['source_files']),
        source_root=OLD / 'src/strategy_runtime') == old_payload['runtime']['source_sha256'])
    samples_path = PACKAGE / 'strategies/calibration_samples.csv'
    check('calibration closure byte identical', samples_path.read_bytes() ==
          (OLD / 'src/strategy_runtime/strategies/calibration_samples.csv').read_bytes())
    samples = pd.read_csv(samples_path)
    args = [datasets[name].dataframe for name in ('stock.ohlcv', 'stock.unadjusted_daily',
                                                 'security.price_limits', 'security.trading_status')]
    sessions = pd.DatetimeIndex(pd.to_datetime(args[0].Date))
    inputs = dict(zip(('market', 'raw', 'limits', 'status'), args, strict=True))
    for name in ('tick', 'buy_limit'):
        nodes = [next(n for n in ast.parse(path.read_text(encoding='utf-8')).body
                      if isinstance(n, ast.FunctionDef) and n.name == name)
                 for path in (source, OLD / 'src/strategy_runtime/strategies/repair_v3.py')]
        check('unchanged execution helper ' + name, ast.dump(nodes[0]) == ast.dump(nodes[1]))
    baseline_map = {'parent_all_H3': 'parent_H3', 'parent_high_H3': 'high_H3'}
    records = []
    histories = {}
    window = TradableWindow(date(2020, 1, 2), date(2026, 10, 15))
    for number, variant in enumerate(VARIANTS, 13):
        payload = json.loads((EX / 'protocols' / f'payload_{variant}.json').read_text(encoding='utf-8'))
        check('fixed parameter ' + variant, payload['parameters'] == {'variant': variant})
        candidate = StrategyCandidate('S014', f'C{number:04}', payload, PACKAGE)
        description = StrategyRuntime().describe(candidate)
        instance = strategy.RepairStrategy.from_parameters(ParameterSet({'variant': variant}))
        old_instance = previous.RepairStrategy.from_parameters(ParameterSet({'variant': 'parent_H3'}))
        check('frozen fee and execution ' + variant, instance.definition.execution == old_instance.definition.execution)
        history = strategy.history(*args, samples, variant)
        visible = instance.calculate_history(inputs, sessions)
        histories[variant] = history
        entry_kind, environment, duration = variant.rsplit('_', 2)
        intended_horizon = int(duration[1:])
        check('same causal startup ' + variant, not history.ready.iloc[:186].any() and history.ready.iloc[186])
        check('all states require ready ' + variant, not history.loc[~history.ready, 'entry_signal'].any())
        check('failed buy resets and suppresses same day reentry ' + variant,
              history.loc[history.failed_buy_reset, 'target_position'].eq(0).all()
              and not history.loc[history.failed_buy_reset, 'entry_signal'].any())
        candles = args[0].Close.to_numpy() > args[0].Open.to_numpy()
        entry_condition = history.parent.to_numpy() if entry_kind == 'parent' else candles
        selected = history.entry_signal.to_numpy()
        check('entry predicate ' + variant, entry_condition[selected].all())
        check('environment condition ' + variant, environment == 'all' or history.loc[selected, 'high'].all())
        check('fixed frozen horizon ' + variant, history.loc[history.holding_horizon.gt(0), 'holding_horizon'].eq(intended_horizon).all())
        # The existing execution state machine must request sale after E+H-1 close, never on E.
        entry_index = None
        for i, row in enumerate(history.itertuples()):
            if row.sell_filled_today:
                entry_index = None
            if row.buy_filled_today:
                entry_index = i
            if row.held_at_close:
                assert entry_index is not None
                expected_target = 0. if i >= entry_index + intended_horizon - 1 else 1.
                assert row.target_position == expected_target, (variant, i, 'holding timing')
        check('actual-entry holding clock ' + variant, True)
        observed_column = 'parent' if entry_kind == 'parent' else 'up_candle'
        check('numeric finite public observation columns ' + variant,
              all(pd.api.types.is_float_dtype(visible[col]) and np.isfinite(visible[col]).all()
                  for col in ('high', observed_column)))
        if variant in baseline_map:
            old_variant = baseline_map[variant]
            old_history = previous.history(*args, samples, old_variant)
            pd.testing.assert_frame_equal(history, old_history, check_exact=True)
            old_visible = previous.RepairStrategy.from_parameters(ParameterSet({'variant': old_variant})).calculate_history(inputs, sessions)
            pd.testing.assert_frame_equal(visible, old_visible, check_exact=True)
            check('exact original all-column history and display ' + variant, True)
        for stop in (187, 500, 1000, 1500):
            cutoff = sessions[stop - 1]
            truncated = [value.loc[pd.to_datetime(value.Date).le(cutoff)].copy() for value in args]
            prefix = strategy.history(*truncated, samples, variant)
            pd.testing.assert_frame_equal(prefix, history.iloc[:stop], check_exact=True)
            check(f'causal prefix {variant}/{stop}', True)
        altered = [value.copy() for value in args]
        boundary = sessions[1000]
        for value in altered[:2]:
            value.loc[pd.to_datetime(value.Date).ge(boundary), ['Open', 'High', 'Low', 'Close']] *= 1.2
        altered[2].loc[pd.to_datetime(altered[2].Date).ge(boundary), ['DownLimit', 'UpLimit']] *= 1.2
        future_samples = samples.copy()
        future_samples.loc[pd.to_datetime(future_samples.maturity_date).ge(boundary), 'gap_autocorr'] = .999
        future = strategy.history(*altered, future_samples, variant)
        pd.testing.assert_frame_equal(future.iloc[:1000], history.iloc[:1000], check_exact=True)
        check('future price and immature calibration perturbation ' + variant, True)
        runtime = StrategyRuntime(ROOT, dataflows=ctx.data).create(StrategyInit(candidate, window,
            ROOT / '.tmp/s014-ex018-precheck' / variant))
        calendar_request = runtime.calendar_request()
        calendar = ctx.data.fetch(calendar_request, prepared=prepared)
        plan = runtime.plan_inputs(calendar)
        check('calendar is explicit public input ' + variant, 'calendar' in plan.requests)
        binding = StrategyInputBinding(plan, prepared)
        prepared_result = runtime.prepare_data(binding=binding)
        prepared_again = runtime.prepare_data(binding=binding)
        runtime_visible = runtime.inspect_signals()
        expected = visible.loc[runtime_visible.index]
        pd.testing.assert_frame_equal(runtime_visible, expected, check_names=False, check_exact=True)
        check('public prepare and window inspection exact ' + variant, len(runtime_visible) == 1642)
        records.append({'variant': variant, 'candidate': candidate.reference_id,
                        'runtime_sha256': description.runtime_sha256,
                        'implementation_sha256': payload['runtime']['source_sha256'],
                        'input_binding': binding.to_dict(), 'signal_sessions': len(runtime_visible),
                        'account_evaluation': False})
        print('PRECHECK_VARIANT_PASS', variant, flush=True)
    # Entry and high-state truth tables are outcome-independent and do not bypass startup.
    reference = histories['parent_all_H3']
    for variant, value in histories.items():
        check('all eight identical environment and readiness ' + variant,
              value[['ready', 'high', 'threshold', 'gap_autocorr']].equals(
                  reference[['ready', 'high', 'threshold', 'gap_autocorr']]))
    for value in ('parent_all_H5', 'up_candle_low_H3', '', None):
        try:
            strategy.RepairStrategy.from_parameters(ParameterSet({'variant': value}))
        except (TypeError, ValueError):
            pass
        else:
            raise AssertionError('Illegal variant accepted')
    check('invalid variants rejected', True)
    check('no external calls attempted', not calls)
    result = {'status': 'PASS', 'check_count': len(checks), 'checks': checks,
              'candidates': records, 'full_prepared_reference': FULL_REFERENCE, 'input_content_sha256': identities,
              'source_sha256': sha256(source.read_bytes()).hexdigest(),
              'calibration_sha256': sha256(samples_path.read_bytes()).hexdigest(),
              'account_runs': 0, 'supplier_calls': 0, 'registered_or_published': False,
              'execution_authorization': 'Candidate preparation only; selection of formal comparisons remains with parent task.',
              'pending': ['Formal-account daily state and full ledger audit for any subsequently authorized executed variants.']}
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('EX018_PRECHECK_PASS', len(checks))


if __name__ == '__main__':
    main()
