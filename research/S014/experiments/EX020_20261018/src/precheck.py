"""Causal renewal deadlines and public preparation; never evaluate an account."""
import ast
from datetime import date
from hashlib import sha256
import importlib.util
import json
from uuid import UUID

import numpy as np
import pandas as pd
import requests
from dataflows import DataRequest, Dataset, PreparedDataRef, ProviderConfig
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef
from strategy_runtime import (ParameterSet, StrategyCandidate, StrategyInit, StrategyInputBinding,
                              StrategyRuntime, TradableWindow, implementation_sha256)
from build_candidates import ROOT, EX, OLD, PACKAGE, VARIANTS, EXTENSIONS, BASELINES, GRID

FULL_REFERENCE = {'space_id': '9b7260bb-f12c-4eab-bc37-884d0cc58c91',
                  'preparation_id': 'dfb12e42-f327-4e1b-bf25-d15201b4e69b',
                  'manifest_sha256': 'b68cf906d81e19a16b131fe63ca1f4f901f9baa202bae75110481b5f209d8f57'}
OBSERVED = ('parent', 'high', 'held_at_close', 'buy_filled_today', 'sell_filled_today',
            'exit_pending', 'renewal_signal', 'renewal_applied', 'deadline_index', 'cap_hit')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def fixture(renewals=(), blocked_sell=None, failed_buy=False, low_after_entry=False):
    """Only signal 22 initiates a position; E=23. Additional signals are explicit."""
    dates = pd.bdate_range('2020-12-01' if low_after_entry else '2020-01-01', periods=55)
    close = 10 + .02 * np.sin(np.arange(len(dates)))
    close[22] = 10.
    raw = pd.DataFrame({'Date': dates, 'Open': close + .03, 'High': close + .2,
                        'Low': close - .2, 'Close': close, 'Volume': 100000., 'Amount': 1000000.})
    for i in (22, *renewals):
        raw.loc[i, 'Open'] = min(close[i], close[i - 1]) - .1
    raw.loc[23, ['High', 'Low']] = [10.2, 9.8]
    if failed_buy:
        raw.loc[23, ['Open', 'High', 'Low', 'Close']] = [10.3, 10.4, 10.2, 10.35]
    limits = pd.DataFrame({'Date': dates, 'DownLimit': 5., 'UpLimit': 20.})
    status = pd.DataFrame({'Date': dates, 'Status': 'TRADING'})
    if blocked_sell is not None:
        raw.loc[blocked_sell, ['Open', 'High', 'Low', 'Close']] = 9.
        limits.loc[blocked_sell, 'DownLimit'] = 9.
        # Next session has an eligible green candle but is suspended: pending SELL cannot be withdrawn.
        raw.loc[blocked_sell + 1, ['Open', 'High', 'Low', 'Close']] = [8.9, 9.2, 8.8, 9.1]
        status.loc[blocked_sell + 1, 'Status'] = 'SUSPENDED'
        raw.loc[blocked_sell + 2, ['Open', 'High', 'Low', 'Close']] = [9., 9.01, 9., 9.]
        limits.loc[blocked_sell + 2, 'DownLimit'] = 9.
    samples = pd.DataFrame({'maturity_date': pd.bdate_range('2019-01-01', periods=60), 'gap_autocorr': -1.})
    if low_after_entry:
        # Synthetic annual threshold changes only after the original Dec31 signal has been accepted.
        samples = pd.concat([samples, pd.DataFrame({'maturity_date': [pd.Timestamp('2020-12-31')] * 61,
                                                    'gap_autocorr': 1.})], ignore_index=True)
    return [raw.copy(), raw, limits, status], samples


def audit_deadlines(history, variant):
    """Rebuild planned exit from observed fills and original signal states."""
    _, kind, horizon, cap = variant.split('_'); h = int(horizon[1:]); cap = int(cap[3:])
    entry = None; deadline = None; pending = False
    for i, row in enumerate(history.itertuples()):
        if row.sell_filled_today:
            entry = None; deadline = None; pending = False
        if row.buy_filled_today:
            entry = i; deadline = i + h - 1; pending = False
        expected_signal = False; expected_apply = False; expected_cap = False
        if row.held_at_close:
            assert entry is not None
            expected_signal = bool(row.parent and row.ready and (kind == 'parent' or row.high))
            if expected_signal and not pending:
                new_deadline = max(deadline, i + h)
                if cap:
                    expected_cap = new_deadline > entry + cap - 1
                    new_deadline = min(new_deadline, entry + cap - 1)
                expected_apply = new_deadline > deadline
                deadline = new_deadline
            pending = pending or i >= deadline
            assert row.target_position == (0. if pending else 1.)
            assert row.holding_horizon == h
        assert row.renewal_signal == expected_signal and row.renewal_applied == expected_apply
        assert row.cap_hit == expected_cap and row.exit_pending == pending
        assert row.deadline_index == (deadline if deadline is not None else -1)


def main():
    destination = EX / 'others/precheck.json'
    if destination.exists():raise RuntimeError('Preserve existing precheck evidence')
    attempts = []
    def prohibited(*args, **kwargs):
        attempts.append('ATTEMPTED');raise RuntimeError('No supplier access permitted')
    requests.sessions.Session.request = prohibited
    checks = []
    def check(name, value):
        assert bool(value), name
        checks.append(name)
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'), providers=ProviderConfig())
    prepared = PreparedDataRef(UUID(FULL_REFERENCE['space_id']), UUID(FULL_REFERENCE['preparation_id']), FULL_REFERENCE['manifest_sha256'])
    datasets = {}; identities = {}
    for dataset, symbol, start in ((Dataset.TRADING_CALENDAR, 'SSE', '2019-12-01'),
        (Dataset.STOCK_OHLCV, '600722.SH', '2019-12-31'), (Dataset.STOCK_UNADJUSTED_DAILY, '600722.SH', '2019-12-31'),
        (Dataset.SECURITY_PRICE_LIMITS, '600722.SH', '2020-01-01'), (Dataset.SECURITY_TRADING_STATUS, '600722.SH', '2019-12-01')):
        result = ctx.data.fetch(DataRequest(dataset, symbol, start, '2026-10-15', '2026-10-15'), prepared=prepared)
        check('authenticated offline input ' + dataset.value, result.ready)
        datasets[dataset.value] = result.dataframe;identities[dataset.value] = result.identity.content_sha256
    source = PACKAGE / 'strategies/repair.py';strategy = module('ex020_repair_precheck', source)
    previous = module('ex018_repair_precheck', OLD / 'src/strategy_runtime/strategies/repair.py')
    sample_path = PACKAGE / 'strategies/calibration_samples.csv'
    check('calibration byte identical', sample_path.read_bytes() == (OLD / 'src/strategy_runtime/strategies/calibration_samples.csv').read_bytes())
    samples = pd.read_csv(sample_path)
    args = [datasets[name] for name in ('stock.ohlcv', 'stock.unadjusted_daily', 'security.price_limits', 'security.trading_status')]
    sessions = pd.DatetimeIndex(pd.to_datetime(args[0].Date));inputs = dict(zip(('market', 'raw', 'limits', 'status'), args, strict=True))
    for name in ('tick', 'buy_limit'):
        nodes = [next(n for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef) and n.name == name)
                 for p in (source, OLD / 'src/strategy_runtime/strategies/repair.py')]
        check('unchanged execution helper ' + name, ast.dump(nodes[0]) == ast.dump(nodes[1]))
    check('fixed grid order and no extra cell', tuple(strategy.RENEWALS) == tuple(EXTENSIONS) and len(set(EXTENSIONS)) == 8)
    histories = {};records = [];baselines = []
    for variant in VARIANTS:
        instance = strategy.RepairStrategy.from_parameters(ParameterSet({'variant': variant}))
        original = previous.RepairStrategy.from_parameters(ParameterSet({'variant': 'parent_high_H3'}))
        check('unchanged execution and input contract ' + variant, instance.definition.execution == original.definition.execution and instance.definition.inputs == original.definition.inputs)
        history = strategy.history(*args, samples, variant);visible = instance.calculate_history(inputs, sessions);histories[variant] = history
        check('same readiness startup ' + variant, not history.ready.iloc[:186].any() and history.ready.iloc[186])
        check('initial entries require parent high ready ' + variant, history.loc[history.entry_signal, ['parent', 'high', 'ready']].all().all())
        check('failed buy resets cycle ' + variant, history.loc[history.failed_buy_reset, 'target_position'].eq(0).all() and not history.loc[history.failed_buy_reset, 'entry_signal'].any())
        if variant in BASELINES:
            batch, payload_name, candidate_id, original_variant = BASELINES[variant];folder = EX.parent / batch
            payload = json.loads((folder / 'protocols' / payload_name).read_text(encoding='utf-8'))
            check('original closure authenticated ' + variant, implementation_sha256(tuple(payload['runtime']['source_files']), source_root=folder / 'src/strategy_runtime') == payload['runtime']['source_sha256'])
            old_module = module('original_' + variant, folder / 'src/strategy_runtime' / payload['runtime']['source_files'][0])
            pd.testing.assert_frame_equal(history, old_module.history(*args, samples, original_variant), check_exact=True)
            pd.testing.assert_frame_equal(visible, old_module.RepairStrategy.from_parameters(ParameterSet({'variant': original_variant})).calculate_history(inputs, sessions), check_exact=True)
            check('baseline all-column history and public display exact ' + variant, True)
            baselines.append({'variant': variant, 'candidate': 'S014-' + candidate_id,
                              'original_payload': (folder / 'protocols' / payload_name).relative_to(ROOT).as_posix(),
                              'implementation_sha256': payload['runtime']['source_sha256'], 'new_candidate': False})
        else:
            check('finite public observations ' + variant, all(pd.api.types.is_float_dtype(visible[c]) and np.isfinite(visible[c]).all() for c in OBSERVED))
            audit_deadlines(history, variant);check('independent deadline and exit-latch reconstruction ' + variant, True)
            number = 25 + EXTENSIONS.index(variant);payload = json.loads((EX / f'protocols/payload_{variant}.json').read_text(encoding='utf-8'))
            candidate = StrategyCandidate('S014', f'C{number:04}', payload, PACKAGE)
            runtime = StrategyRuntime(ROOT, dataflows=ctx.data).create(StrategyInit(candidate, TradableWindow(date(2020, 1, 2), date(2026, 10, 15)), ROOT / '.tmp/s014-ex020-precheck' / variant))
            calendar = ctx.data.fetch(runtime.calendar_request(), prepared=prepared);plan = runtime.plan_inputs(calendar)
            check('calendar public input ' + variant, 'calendar' in plan.requests)
            binding = StrategyInputBinding(plan, prepared);runtime.prepare_data(binding=binding);runtime.prepare_data(binding=binding)
            actual = runtime.inspect_signals();pd.testing.assert_frame_equal(actual, visible.loc[actual.index], check_names=False, check_exact=True)
            check('public preparation and inspection ' + variant, len(actual) == 1642)
            records.append({'variant': variant, 'candidate': candidate.reference_id, 'implementation_sha256': payload['runtime']['source_sha256'],
                            'prepared_reference': FULL_REFERENCE, 'input_binding_canonical_sha256': sha256(json.dumps(binding.to_dict(), sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                            'signal_sessions': len(actual), 'first_signal': str(actual.index[0].date()), 'last_signal': str(actual.index[-1].date())})
        for stop in (187, 500, 1000, 1500, len(sessions)):
            subset = [frame.loc[pd.to_datetime(frame.Date).le(sessions[stop - 1])].copy() for frame in args]
            pd.testing.assert_frame_equal(strategy.history(*subset, samples, variant), history.iloc[:stop], check_exact=True)
            check(f'prefix and final session {variant}/{stop}', True)
        changed = [frame.copy() for frame in args];boundary = sessions[1000]
        for frame in changed[:2]:frame.loc[pd.to_datetime(frame.Date).ge(boundary), ['Open', 'High', 'Low', 'Close']] *= 1.2
        changed[2].loc[pd.to_datetime(changed[2].Date).ge(boundary), ['DownLimit', 'UpLimit']] *= 1.2
        future_samples = samples.copy();future_samples.loc[pd.to_datetime(future_samples.maturity_date).ge(boundary), 'gap_autocorr'] = .999
        pd.testing.assert_frame_equal(strategy.history(*changed, future_samples, variant).iloc[:1000], history.iloc[:1000], check_exact=True)
        check('future price and immature calibration perturbation ' + variant, True)
        print('PRECHECK_VARIANT_PASS', variant, flush=True)
    for variant, history in histories.items():
        check('unchanged original environment ' + variant, history[['parent', 'ready', 'high', 'threshold', 'gap_autocorr']].equals(histories['baseline_H3'][['parent', 'ready', 'high', 'threshold', 'gap_autocorr']]))
    for variant in EXTENSIONS:
        _, kind, horizon, cap = variant.split('_');h = int(horizon[1:]);cap = int(cap[3:]);due = 23 + h - 1
        synthetic, cal = fixture();history = strategy.history(*synthetic, cal, variant)
        check('no-renewal original exit clock ' + variant, history.buy_filled_today.iloc[23] and history.exit_pending.iloc[due] and history.sell_filled_today.iloc[due + 1] and not history.renewal_applied.any())
        synthetic, cal = fixture(renewals=(due,));history = strategy.history(*synthetic, cal, variant)
        check('due-evening renewal before SELL intent ' + variant, history.renewal_applied.iloc[due] and not history.exit_pending.iloc[due]
              and history.deadline_index.iloc[due] == due + h and history.sell_filled_today.iloc[due + h + 1])
        altered = [frame.copy() for frame in synthetic]
        for frame in altered[:2]:frame.loc[due + 1, ['Open', 'High', 'Low', 'Close']] *= 1.1
        pd.testing.assert_frame_equal(strategy.history(*altered, cal, variant).iloc[:due + 1], history.iloc[:due + 1], check_exact=True)
        check('renewal never requires hypothetical next buy fill ' + variant, True)
        synthetic, cal = fixture(renewals=tuple(range(23, 55)));history = strategy.history(*synthetic, cal, variant)
        check('entry-evening renewal uses next-entry clock ' + variant, history.renewal_applied.iloc[23] and history.deadline_index.iloc[23] == 23 + h)
        if cap:
            check('cap absolute from actual entry ' + variant, history.deadline_index.iloc[34] == 34 and history.exit_pending.iloc[34]
                  and history.sell_filled_today.iloc[35] and history.cap_hit.iloc[34] and not history.renewal_applied.iloc[34])
        else:
            check('uncapped renewal continues through final day ' + variant, not history.sell_filled_today.any() and history.held_at_close.iloc[-1]
                  and history.deadline_index.iloc[-1] == 54 + h and not history.cap_hit.any())
        audit_deadlines(history, variant);check('synthetic repeated renewal reconstruction ' + variant, True)
        prefix = [frame.iloc[:35].copy() for frame in synthetic]
        pd.testing.assert_frame_equal(strategy.history(*prefix, cal, variant), history.iloc[:35], check_exact=True)
        check('final cap-day decision retained ' + variant, True)
        synthetic, cal = fixture(blocked_sell=due + 1);history = strategy.history(*synthetic, cal, variant)
        check('failed sell and later signal cannot withdraw exit ' + variant,
              history.exit_pending.iloc[due:due + 3].all() and history.target_position.iloc[due:due + 3].eq(0).all()
              and history.renewal_signal.iloc[due + 2] and not history.renewal_applied.iloc[due + 2] and not history.cap_hit.iloc[due + 2]
              and history.deadline_index.iloc[due:due + 3].eq(due).all() and history.sell_filled_today.iloc[due + 3])
        synthetic, cal = fixture(failed_buy=True);history = strategy.history(*synthetic, cal, variant)
        check('synthetic failed buy reset ' + variant, history.failed_buy_reset.iloc[23] and history.target_position.iloc[23] == 0
              and not history.buy_filled_today.any() and history.deadline_index.eq(-1).all())
        synthetic, cal = fixture(renewals=(due,), low_after_entry=True);history = strategy.history(*synthetic, cal, variant)
        check('initial entry high but renewal environment explicit ' + variant,
              history.entry_signal.iloc[22] and history.high.iloc[22] and not history.high.iloc[due]
              and bool(history.renewal_applied.iloc[due]) == (kind == 'parent'))
        check('low environment never permits fresh entry ' + variant, not history.loc[~history.high, 'entry_signal'].any())
    for illegal in ('renewal_parent_H3_cap6', 'renewal_qualified_H5_cap0', 'baseline_H1', '', None):
        try:strategy.RepairStrategy.from_parameters(ParameterSet({'variant': illegal}))
        except (TypeError, ValueError):pass
        else:raise AssertionError('Illegal variant accepted')
    check('invalid fixed cells rejected', True);check('no supplier attempts', not attempts)
    source_paths = [source, sample_path, EX / 'src/build_candidates.py', EX / 'src/precheck.py', *list((EX / 'protocols').glob('payload_*.json'))]
    check('all source and payload LF', all(b'\r' not in p.read_bytes() for p in source_paths))
    result = {'status': 'PASS', 'check_count': len(checks), 'checks': checks, 'grid': GRID, 'candidates': records, 'baselines': baselines,
              'full_prepared_reference': FULL_REFERENCE, 'input_content_sha256': identities,
              'source_sha256': sha256(source.read_bytes()).hexdigest(), 'calibration_sha256': sha256(sample_path.read_bytes()).hexdigest(),
              'source_files_sha256': {name: sha256((EX / name).read_bytes()).hexdigest() for name in ('src/build_candidates.py', 'src/precheck.py')},
              'account_runs': 0, 'supplier_calls': 0, 'supplier_attempts': 0, 'registered_or_published': False,
              'observation_semantics': {'deadline_index': 'Zero-based index of SELL decision close from full input first session 2019-12-31; -1 when flat.',
                  'exit_pending': 'Latched from first SELL decision through failed executions; cleared only after SELL fill.',
                  'renewal_signal': 'Current held parent+ready condition, plus high for qualified; can remain true during exit latch.',
                  'renewal_applied': 'One-session event: deadline strictly increased; false during exit latch.',
                  'cap_hit': 'One-session event: eligible non-latched proposed deadline exceeded entry+cap-1 and was clipped; can be true without applied renewal.',
                  'holding_horizon': 'Original base h per renewal, not total maximum elapsed holding.'},
              'pending': ['Formal-account actual entry, daily holdings, fees and exit-latch reconciliation after account authorization.']}
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('EX020_PRECHECK_PASS', len(checks))


if __name__ == '__main__':main()
