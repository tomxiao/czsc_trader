"""Offline causal, synthetic boundary and public SRT preparation checks only."""
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
from build_candidates import ROOT, EX, OLD, PACKAGE, VARIANTS, EXTENSIONS, BASELINES

FULL_REFERENCE = {'space_id': '9b7260bb-f12c-4eab-bc37-884d0cc58c91',
                  'preparation_id': 'dfb12e42-f327-4e1b-bf25-d15201b4e69b',
                  'manifest_sha256': 'b68cf906d81e19a16b131fe63ca1f4f901f9baa202bae75110481b5f209d8f57'}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def fixture(profit=True, rising=True, limit_fill=False, failed_buy=False, blocked_sell=None):
    """One eligible entry after varied red candles; actual entry E=23."""
    dates = pd.bdate_range('2020-01-01', periods=40)
    close = 10 + .02 * np.sin(np.arange(40))
    close[22] = 10.
    close[23] = 10.12 if limit_fill else 10.02
    close[25] = 10.3 if profit else 9.95
    close[24] = close[25] - .05 if rising else close[25] + .05
    raw = pd.DataFrame({'Date': dates, 'Open': close + .02, 'High': close + .12,
                        'Low': close - .1, 'Close': close, 'Volume': 100000., 'Amount': 1000000.})
    raw.loc[22, ['Open', 'High', 'Low']] = [9.9, 10.1, 9.8]
    raw.loc[23, ['Open', 'High', 'Low']] = [10.15, 10.3, 10.05] if limit_fill else [10., 10.2, 9.9]
    if failed_buy:
        raw.loc[23, ['Open', 'High', 'Low', 'Close']] = [10.25, 10.4, 10.2, 10.3]
    limits = pd.DataFrame({'Date': dates, 'DownLimit': 5., 'UpLimit': 20.})
    if blocked_sell is not None:
        raw.loc[blocked_sell, ['Open', 'High', 'Low', 'Close']] = 9.
        limits.loc[blocked_sell, 'DownLimit'] = 9.
        raw.loc[blocked_sell + 1, ['Open', 'High', 'Low', 'Close']] = [9., 9.01, 9., 9.]
        limits.loc[blocked_sell + 1, 'DownLimit'] = 9.
    status = pd.DataFrame({'Date': dates, 'Status': 'TRADING'})
    samples = pd.DataFrame({'maturity_date': pd.bdate_range('2019-01-01', periods=60),
                            'gap_autocorr': -1.})
    return [raw.copy(), raw, limits, status], samples


def main():
    destination = EX / 'others/precheck.json'
    if destination.exists():
        raise RuntimeError('Preserve existing precheck evidence')
    attempts = []
    def prohibited(*args, **kwargs):
        attempts.append('ATTEMPTED')
        raise RuntimeError('No supplier access permitted during precheck')
    requests.sessions.Session.request = prohibited
    checks = []
    def check(name, value):
        assert bool(value), name
        checks.append(name)
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'), providers=ProviderConfig())
    prepared = PreparedDataRef(UUID(FULL_REFERENCE['space_id']), UUID(FULL_REFERENCE['preparation_id']), FULL_REFERENCE['manifest_sha256'])
    datasets = {}; identities = {}
    for dataset, symbol, start in ((Dataset.TRADING_CALENDAR, 'SSE', '2019-12-01'),
        (Dataset.STOCK_OHLCV, '600722.SH', '2019-12-31'),
        (Dataset.STOCK_UNADJUSTED_DAILY, '600722.SH', '2019-12-31'),
        (Dataset.SECURITY_PRICE_LIMITS, '600722.SH', '2020-01-01'),
        (Dataset.SECURITY_TRADING_STATUS, '600722.SH', '2019-12-01')):
        request = DataRequest(dataset, symbol, start, '2026-10-15', '2026-10-15')
        fetched = ctx.data.fetch(request, prepared=prepared)
        check('authenticated offline input ' + dataset.value, fetched.ready)
        datasets[dataset.value] = fetched.dataframe
        identities[dataset.value] = fetched.identity.content_sha256
    source = PACKAGE / 'strategies/repair.py'
    strategy = module('ex019_repair_precheck', source)
    previous = module('ex018_repair_precheck', OLD / 'src/strategy_runtime/strategies/repair.py')
    sample_path = PACKAGE / 'strategies/calibration_samples.csv'
    check('calibration byte identical', sample_path.read_bytes() == (OLD / 'src/strategy_runtime/strategies/calibration_samples.csv').read_bytes())
    samples = pd.read_csv(sample_path)
    args = [datasets[name] for name in ('stock.ohlcv', 'stock.unadjusted_daily', 'security.price_limits', 'security.trading_status')]
    sessions = pd.DatetimeIndex(pd.to_datetime(args[0].Date))
    inputs = dict(zip(('market', 'raw', 'limits', 'status'), args, strict=True))
    for name in ('tick', 'buy_limit'):
        nodes = [next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef) and n.name == name)
                 for path in (source, OLD / 'src/strategy_runtime/strategies/repair.py')]
        check('unchanged execution helper ' + name, ast.dump(nodes[0]) == ast.dump(nodes[1]))
    histories = {}; records = []; baseline_records = []
    window = TradableWindow(date(2020, 1, 2), date(2026, 10, 15))
    for variant in VARIANTS:
        instance = strategy.RepairStrategy.from_parameters(ParameterSet({'variant': variant}))
        old_instance = previous.RepairStrategy.from_parameters(ParameterSet({'variant': 'parent_high_H3'}))
        check('unchanged execution and input contract ' + variant,
              instance.definition.execution == old_instance.definition.execution and instance.definition.inputs == old_instance.definition.inputs)
        history = strategy.history(*args, samples, variant)
        visible = instance.calculate_history(inputs, sessions)
        histories[variant] = history
        check('same startup ' + variant, not history.ready.iloc[:186].any() and history.ready.iloc[186])
        check('entry keeps parent high and ready ' + variant,
              history.loc[history.entry_signal, ['parent', 'high', 'ready']].all().all())
        check('failed buy clears cycle ' + variant, history.loc[history.failed_buy_reset, 'target_position'].eq(0).all()
              and not history.loc[history.failed_buy_reset, 'entry_signal'].any())
        if variant in BASELINES:
            batch, payload_name, candidate_id, old_variant = BASELINES[variant]
            folder = EX.parent / batch
            old_payload = json.loads((folder / 'protocols' / payload_name).read_text(encoding='utf-8'))
            check('original baseline source authenticated ' + variant,
                  implementation_sha256(tuple(old_payload['runtime']['source_files']), source_root=folder / 'src/strategy_runtime') == old_payload['runtime']['source_sha256'])
            old_module = module('original_' + variant, folder / 'src/strategy_runtime' / old_payload['runtime']['source_files'][0])
            pd.testing.assert_frame_equal(history, old_module.history(*args, samples, old_variant), check_exact=True)
            pd.testing.assert_frame_equal(visible, old_module.RepairStrategy.from_parameters(ParameterSet({'variant': old_variant})).calculate_history(inputs, sessions), check_exact=True)
            check('baseline exact all-column history and display ' + variant, True)
            baseline_records.append({'variant': variant, 'candidate': 'S014-' + candidate_id,
                                     'original_payload': (folder / 'protocols' / payload_name).relative_to(ROOT).as_posix(),
                                     'implementation_sha256': old_payload['runtime']['source_sha256'], 'new_candidate': False})
        else:
            observed = ('parent', 'high', 'decision_evaluated', 'extend_selected', 'float_pnl', 'close_change')
            check('finite numeric observations ' + variant, all(pd.api.types.is_float_dtype(visible[col]) and np.isfinite(visible[col]).all() for col in observed))
            entry = None; evaluated = False; planned_horizon = 3; fill_price = None
            for i, row in enumerate(history.itertuples()):
                if row.sell_filled_today:
                    entry = None; evaluated = False
                if row.buy_filled_today:
                    entry = i; evaluated = False; planned_horizon = 3; fill_price = row.entry_fill_price
                if row.decision_evaluated:
                    assert entry is not None and i == entry + 2 and not evaluated
                    evaluated = True
                    floating = float(args[0].Close.iloc[i]) / (fill_price * 1.001) - 1
                    change = float(args[0].Close.iloc[i]) / float(args[0].Close.iloc[i - 1]) - 1
                    truth = {'extend_profit': floating > 0, 'extend_rising': change > 0,
                             'extend_both': floating > 0 and change > 0, 'extend_either': floating > 0 or change > 0}[variant]
                    assert row.extend_selected == truth and row.float_pnl == floating and row.close_change == change
                    if truth: planned_horizon = 6
                if row.held_at_close:
                    assert row.holding_horizon == planned_horizon
                    assert row.target_position == (0. if i >= entry + planned_horizon - 1 else 1.)
                if row.extend_selected: assert row.decision_evaluated
            check('one-time actual-entry clock and decision truth ' + variant, True)
            number = 21 + EXTENSIONS.index(variant)
            payload = json.loads((EX / f'protocols/payload_{variant}.json').read_text(encoding='utf-8'))
            candidate = StrategyCandidate('S014', f'C{number:04}', payload, PACKAGE)
            runtime = StrategyRuntime(ROOT, dataflows=ctx.data).create(StrategyInit(candidate, window, ROOT / '.tmp/s014-ex019-precheck' / variant))
            calendar = ctx.data.fetch(runtime.calendar_request(), prepared=prepared)
            plan = runtime.plan_inputs(calendar)
            check('calendar explicit ' + variant, 'calendar' in plan.requests)
            binding = StrategyInputBinding(plan, prepared)
            runtime.prepare_data(binding=binding)
            runtime.prepare_data(binding=binding)
            actual = runtime.inspect_signals()
            pd.testing.assert_frame_equal(actual, visible.loc[actual.index], check_names=False, check_exact=True)
            check('public SRT prepare and inspection ' + variant, len(actual) == 1642)
            encoded = json.dumps(binding.to_dict(), sort_keys=True, separators=(',', ':')).encode()
            records.append({'variant': variant, 'candidate': candidate.reference_id,
                            'implementation_sha256': payload['runtime']['source_sha256'],
                            'input_binding_canonical_sha256': sha256(encoded).hexdigest(),
                            'prepared_reference': FULL_REFERENCE, 'signal_sessions': len(actual),
                            'first_signal': str(actual.index[0].date()), 'last_signal': str(actual.index[-1].date())})
        for stop in (187, 500, 1000, 1500, len(sessions)):
            cutoff = sessions[stop - 1]
            truncated = [frame.loc[pd.to_datetime(frame.Date).le(cutoff)].copy() for frame in args]
            pd.testing.assert_frame_equal(strategy.history(*truncated, samples, variant), history.iloc[:stop], check_exact=True)
            check(f'causal prefix and final session {variant}/{stop}', True)
        altered = [frame.copy() for frame in args]; boundary = sessions[1000]
        for frame in altered[:2]:frame.loc[pd.to_datetime(frame.Date).ge(boundary), ['Open', 'High', 'Low', 'Close']] *= 1.2
        altered[2].loc[pd.to_datetime(altered[2].Date).ge(boundary), ['DownLimit', 'UpLimit']] *= 1.2
        future_samples = samples.copy();future_samples.loc[pd.to_datetime(future_samples.maturity_date).ge(boundary), 'gap_autocorr'] = .999
        pd.testing.assert_frame_equal(strategy.history(*altered, future_samples, variant).iloc[:1000], history.iloc[:1000], check_exact=True)
        check('future prices and immature calibration ' + variant, True)
        print('PRECHECK_VARIANT_PASS', variant, flush=True)
    for variant, history in histories.items():
        check('unchanged environment ' + variant, history[['parent', 'ready', 'high', 'threshold', 'gap_autocorr']].equals(histories['baseline_H3'][['parent', 'ready', 'high', 'threshold', 'gap_autocorr']]))
    for variant in EXTENSIONS:
        for p in (False, True):
            for d in (False, True):
                synthetic, cal = fixture(p, d)
                h = strategy.history(*synthetic, cal, variant)
                expected = {'extend_profit': p, 'extend_rising': d, 'extend_both': p and d, 'extend_either': p or d}[variant]
                check(f'synthetic P/D truth {variant}/{p}/{d}', h.buy_filled_today.iloc[23] and h.decision_evaluated.sum() == 1
                      and h.decision_evaluated.iloc[25] and bool(h.extend_selected.iloc[25]) == expected
                      and h.sell_filled_today.iloc[29 if expected else 26])
        for profit, rise in ((0., 0.), (0., .01), (.01, 0.), (-.01, 0.)):
            entry_price = 10.;close = entry_price * 1.001 * (1 + profit);previous_close = close / (1 + rise)
            selected, floating, change = strategy.extension_decision(variant, close, previous_close, entry_price)
            truth = {'extend_profit': profit > 0, 'extend_rising': rise > 0,
                     'extend_both': profit > 0 and rise > 0, 'extend_either': profit > 0 or rise > 0}[variant]
            check(f'strict zero boundary {variant}/{profit}/{rise}', selected == truth
                  and (profit != 0 or floating == 0) and (rise != 0 or change == 0))
        for limit_fill in (False, True):
            synthetic, cal = fixture(limit_fill=limit_fill)
            h = strategy.history(*synthetic, cal, variant)
            expected_price = 10.1 if limit_fill else 10.
            check(f'actual fill price {variant}/{limit_fill}', h.entry_fill_price.iloc[23] == expected_price
                  and h.float_pnl.iloc[25] == synthetic[0].Close.iloc[25] / (expected_price * 1.001) - 1)
            # A constant HFQ normalization changes prices but cancels out of the decision.
            scaled = [frame.copy() for frame in synthetic];scaled[0][['Open', 'High', 'Low', 'Close']] *= 5.892
            hs = strategy.history(*scaled, cal, variant)
            check(f'normalization decision invariant {variant}/{limit_fill}',
                  hs[['target_position', 'decision_evaluated', 'extend_selected']].equals(h[['target_position', 'decision_evaluated', 'extend_selected']])
                  and np.isclose(hs.entry_fill_price.iloc[23], expected_price * 5.892))
            # Change only the next session after the decision; today's choice is unchanged.
            changed = [frame.copy() for frame in synthetic]
            for frame in changed[:2]:frame.loc[26:, ['Open', 'High', 'Low', 'Close']] *= 1.1
            hh = strategy.history(*changed, cal, variant)
            pd.testing.assert_frame_equal(hh.iloc[:26], h.iloc[:26], check_exact=True)
            check(f'next-day perturbation cannot change decision {variant}/{limit_fill}', True)
        synthetic, cal = fixture(failed_buy=True)
        h = strategy.history(*synthetic, cal, variant)
        check('synthetic failed buy reset ' + variant, h.failed_buy_reset.iloc[23] and h.target_position.iloc[23] == 0
              and not h.buy_filled_today.any() and not h.decision_evaluated.any())
        for selected, blocked in ((False, 26), (True, 29)):
            synthetic, cal = fixture(selected, selected, blocked_sell=blocked)
            h = strategy.history(*synthetic, cal, variant)
            check(f'blocked sell maintains exit {variant}/{selected}', h.held_at_close.iloc[blocked]
                  and h.target_position.iloc[blocked] == 0 and not h.sell_filled_today.iloc[blocked]
                  and h.sell_filled_today.iloc[blocked + 1] and h.decision_evaluated.sum() == 1)
            prefix = [frame.iloc[:26].copy() for frame in synthetic]
            pd.testing.assert_frame_equal(strategy.history(*prefix, cal, variant), h.iloc[:26], check_exact=True)
            check(f'final-day decision retained {variant}/{selected}', True)
    for illegal in ('extend_none', 'baseline_H1', '', None):
        try:strategy.RepairStrategy.from_parameters(ParameterSet({'variant': illegal}))
        except (TypeError, ValueError):pass
        else:raise AssertionError('Illegal variant accepted')
    check('invalid fixed variants rejected', True)
    check('no supplier attempts', not attempts)
    check('all source and payload files LF', all(b'\r' not in p.read_bytes() for p in
          [source, sample_path, EX / 'src/build_candidates.py', EX / 'src/precheck.py', *list((EX / 'protocols').glob('payload_*.json'))]))
    result = {'status': 'PASS', 'check_count': len(checks), 'checks': checks, 'candidates': records,
              'baselines': baseline_records, 'full_prepared_reference': FULL_REFERENCE, 'input_content_sha256': identities,
              'source_sha256': sha256(source.read_bytes()).hexdigest(), 'calibration_sha256': sha256(sample_path.read_bytes()).hexdigest(),
              'source_files_sha256': {name: sha256((EX / name).read_bytes()).hexdigest() for name in ('src/build_candidates.py', 'src/precheck.py')},
              'account_runs': 0, 'supplier_calls': 0, 'supplier_attempts': 0, 'registered_or_published': False,
              'observation_semantics': 'decision_evaluated and extend_selected are one-session events; float_pnl/close_change only meaningful on decision_evaluated sessions, otherwise zero. entry_fill_price tracks the open holding in HFQ units, otherwise zero.',
              'pending': ['Formal account daily quantity and actual fill-price reconciliation after separate locked account authorization.']}
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('EX019_PRECHECK_PASS', len(checks))


if __name__ == '__main__':
    main()
