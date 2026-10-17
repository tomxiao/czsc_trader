"""Offline ledger and actual-cost audit of four one-time extension accounts."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import traceback

import numpy as np
import pandas as pd
import requests
from czsc_trader.research_tools import EvidenceRef
from strategy_runtime import implementation_sha256

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OLD = ROOT / 'research/S014/experiments/EX017_20261017'
PREVIOUS = ROOT / 'research/S014/experiments/EX018_20261017'
EXPECTED = {
    'extend_profit': 'S014-C0021',
    'extend_rising': 'S014-C0022',
    'extend_both': 'S014-C0023',
    'extend_either': 'S014-C0024',
}
REUSED = {'baseline_H3': ('EX017_20261017', 'high_H3', 'S014-C0011'),
          'baseline_H6': ('EX018_20261017', 'parent_high_H6', 'S014-C0016')}
SUMMARY = EX / 'others/account_audit.json'
FULL = ROOT / 'research/S014/assets/runs/EX019_20261017/account_audit_full.json'



def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def write_result(result):
    if SUMMARY.exists() or FULL.exists():
        raise RuntimeError('Preserve previous EX019 account audit evidence')
    FULL.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    FULL.write_bytes(content)
    summary = {k: v for k, v in result.items() if k != 'checks'}
    summary['accounts'] = [{k: v for k, v in account.items() if k != 'extension_decision_records'}
                           for account in result['accounts']]
    summary['full_audit'] = {'path': FULL.relative_to(ROOT).as_posix(),
                           'sha256': sha256(content).hexdigest(), 'bytes': len(content)}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                       encoding='utf-8', newline='\n')


def audit_extension(variant, tables, shadow, anchor, prior, require):
    """Rebuild each decision from actual fill cost/quantity, without strategy predicates."""
    daily = prior.by_date(tables['account_daily'], 'date').sort_values('date').reset_index(drop=True)
    fills = prior.by_date(tables['fills'], 'fill_time')
    episode = None
    entries = evaluations = extensions = exits = 0
    decision_records = []
    for i, row in enumerate(daily.itertuples()):
        day = row.date
        label = f'{variant} {day.date()} independent extension'
        today = shadow.loc[day]
        same = fills.loc[fills.fill_time.eq(day)]
        buys, sells = same.loc[same.side.eq('BUY')], same.loc[same.side.eq('SELL')]
        require(label + ' no same-session round trip', not (len(buys) and len(sells)))
        if episode is not None:
            # Decision at E+2 affects the next execution, never the current close.
            require(label + ' actual daily target follows frozen entry clock',
                    float(row.target_position) == float(i < episode['entry_index'] + episode['horizon']))
        if len(sells):
            require(label + ' exit follows one decision and fixed E+3 or E+6',
                    episode is not None and episode['evaluated']
                    and i >= episode['entry_index'] + episode['horizon']
                    and int(sells.quantity.sum()) == episode['quantity'])
            exits += 1
            episode = None
        if len(buys):
            require(label + ' actual entry creates one new cycle', episode is None)
            qty = int(buys.quantity.sum())
            notional = float((buys.quantity * buys.price).sum())
            fees = float(buys.fees.sum())
            require(label + ' finite positive actual cost basis',
                    qty > 0 and np.isfinite([notional, fees]).all() and notional > 0 and fees > 0)
            episode = {'entry_index': i, 'entry_date': str(day.date()), 'quantity': qty,
                       'entry_notional': notional, 'buy_fees': fees, 'entry_price': notional / qty,
                       'evaluated': False, 'horizon': 3}
            entries += 1
        expected_event = episode is not None and i == episode['entry_index'] + 2
        require(label + ' evaluation event only on actual E+2', bool(today.decision_evaluated) == expected_event)
        if expected_event:
            require(label + ' one evaluation per holding episode', not episode['evaluated'])
            floating = episode['quantity'] * float(row.close) / (episode['entry_notional'] + episode['buy_fees']) - 1
            change = float(row.close) / float(daily.close.iloc[i - 1]) - 1
            p, d = floating > 0, change > 0
            selected = {'extend_profit': p, 'extend_rising': d,
                        'extend_both': p and d, 'extend_either': p or d}[variant]
            require(label + ' P reconstructed from actual quantity notional and buy fees',
                    np.isfinite(float(today.float_pnl)) and abs(float(today.float_pnl) - floating) < 1e-12)
            require(label + ' D uses current and previous normalized daily close',
                    np.isfinite(float(today.close_change)) and abs(float(today.close_change) - change) < 1e-12)
            require(label + ' strict P/D predicate independently agrees', bool(today.extend_selected) == selected)
            episode['evaluated'] = True
            episode['horizon'] = 6 if selected else 3
            evaluations += 1
            extensions += int(selected)
            due = episode['entry_index'] + episode['horizon']
            decision_records.append({**episode, 'decision_date': str(day.date()), 'close': float(row.close),
                                     'previous_close': float(daily.close.iloc[i - 1]), 'float_pnl': floating,
                                     'close_change': change, 'P': bool(p), 'D': bool(d), 'extended': bool(selected),
                                     'scheduled_exit': str(daily.date.iloc[due].date()) if due < len(daily) else None})
        else:
            require(label + ' nondecision observations have zero event payload',
                    not bool(today.extend_selected) and float(today.float_pnl) == 0. and float(today.close_change) == 0.)
        if episode is None:
            require(label + ' flat has no remaining fill basis',
                    int(row.quantity) == 0 and float(today.entry_fill_price) == 0.)
        else:
            require(label + ' normalized shadow price equals actual weighted buy price',
                    abs(float(today.entry_fill_price) / anchor - episode['entry_price']) < 1e-9)
            require(label + ' full actual quantity stays fixed until exit', int(row.quantity) == episode['quantity'])
            require(label + ' horizon stays frozen after one decision', int(today.holding_horizon) == episode['horizon'])
            require(label + ' next-day exit intent persists after scheduled date',
                    float(today.target_position) == float(i < episode['entry_index'] + episode['horizon'] - 1))
    pending = int(episode is not None and not episode['evaluated'])
    require(variant + ' every mature actual entry evaluated exactly once', evaluations + pending == entries)
    require(variant + ' only final actual entry can remain open', entries - exits == int(episode is not None))
    return {'actual_entry_cycles': entries, 'extension_decisions': evaluations, 'selected_extensions': extensions,
            'censored_before_decision': pending, 'extension_decision_records': decision_records,
            'observation_scope': 'Authenticated runtime history independently reconciled to actual fills and daily close; cutoff-close state has no execution beyond cutoff.'}


def main():
    if SUMMARY.exists() or FULL.exists():
        raise RuntimeError('Preserve previous EX019 account audit evidence')
    checks, accounts, refs = [], [], []
    external_attempts = []

    def require(name, condition):
        if not bool(condition):
            raise AssertionError(name)
        checks.append(name)

    def prohibited(*args, **kwargs):
        external_attempts.append('blocked')
        raise RuntimeError('No external call permitted during EX019 account audit')

    def verified_record(record):
        require(record['variant'] + ' succeeded', record['status'] == 'SUCCEEDED')
        ref = EvidenceRef.from_dict(record['evidence'])
        content = ref.resolve(ROOT).read_bytes()
        require(record['variant'] + ' formal evidence bytes', sha256(content).hexdigest() == ref.sha256)
        payload = json.loads(content)
        require(record['variant'] + ' formal result hash and single run',
                payload['result_hash'] == record['result_hash'] and len(payload['runs']) == 1)
        run = payload['runs'][0]
        require(record['variant'] + ' candidate and full baseline coordinate',
                record['candidate'] == 'S014-' + run['candidate_id']
                and (run['window_id'], run['scenario_id']) == ('full', 'baseline'))
        refs.append(ref.to_dict())
        return run

    original_request = requests.sessions.Session.request
    requests.sessions.Session.request = prohibited
    original_path = list(sys.path)
    try:
        # Reuse the authenticated EX017 prepared input and independent ledger checks.
        sys.path.insert(0, str(OLD / 'src'))
        prior_audit_path = OLD / 'src/audit_accounts.py'
        prior = module('s014_ex019_predecessor_account_audit', prior_audit_path)
        data = prior.load_frames()
        records = read(EX / 'others/account_results.json')['records']
        comparison = read(EX / 'others/comparison_accounts.json')['records']
        previous = read(OLD / 'others/account_results.json')['records']
        require('exactly four unique authorized new accounts',
                len(records) == len(EXPECTED) and {r['variant'] for r in records} == set(EXPECTED))
        require('comparison contains four new rules and two exact baselines',
                len(comparison) == 6 and {r['variant'] for r in comparison} == set(EXPECTED) | set(REUSED))
        combined = {r['variant']: r for r in comparison}
        previous = {r['variant']: r for r in previous}
        ex018 = {r['variant']: r for r in read(PREVIOUS / 'others/account_results.json')['records']}
        source_path = EX / 'src/strategy_runtime/strategies/repair.py'
        sample_path = source_path.with_name('calibration_samples.csv')
        source_hash = sha256(source_path.read_bytes()).hexdigest()
        sample_hash = sha256(sample_path.read_bytes()).hexdigest()
        precheck = read(EX / 'others/precheck.json')
        require('causal precheck binds actual source and calibration',
                precheck['status'] == 'PASS' and precheck['source_sha256'] == source_hash
                and precheck['calibration_sha256'] == sample_hash)
        require('calibration identical to original fixed baseline',
                sample_path.read_bytes() == (OLD / 'src/strategy_runtime/strategies/calibration_samples.csv').read_bytes())
        require('predecessor account audit passed', read(OLD / 'others/account_audit.json')['status'] == 'PASS')
        require('EX018 predecessor account audit passed', read(PREVIOUS / 'others/account_audit_v2.json')['status'] == 'PASS')
        strategy = module('s014_ex019_account_audit_repair', source_path)
        market, raw, limits, status = [data[k] for k in (
            'stock.ohlcv', 'stock.unadjusted_daily', 'security.price_limits', 'security.trading_status')]
        samples = pd.read_csv(sample_path)
        indexed = [x.set_index(pd.to_datetime(x.Date)).sort_index() for x in (market, raw, limits)]
        old_high = verified_record(previous['high_H3'])
        require('original high H3 has complete buyhold execution',
                old_high['buyhold'] is not None and old_high['buyhold']['execution'] is not None)
        benchmark = json.dumps(old_high['buyhold'], sort_keys=True, separators=(',', ':'))
        for variant, (batch, old_name, candidate) in REUSED.items():
            left = combined[variant]
            right = (previous if batch == OLD.name else ex018)[old_name]
            require(variant + ' fixed baseline candidate', left['candidate'] == candidate)
            require(variant + ' reuses exact original candidate result and evidence',
                    all(left[k] == right[k] for k in ('candidate', 'result_hash', 'evidence', 'status')))
            reused_run = verified_record(left)
            require(variant + ' unchanged complete buyhold evidence',
                    json.dumps(reused_run['buyhold'], sort_keys=True, separators=(',', ':')) == benchmark)
        for record in records:
            variant = record['variant']
            require(variant + ' authorized candidate identity', record['candidate'] == EXPECTED[variant])
            require(variant + ' comparison references same new result',
                    all(combined[variant][k] == record[k] for k in ('candidate', 'result_hash', 'evidence', 'status')))
            payload = read(EX / f'protocols/payload_{variant}.json')
            runtime = payload['runtime']
            require(variant + ' fixed parameter and authenticated runtime closure',
                    payload['parameters'] == {'variant': variant}
                    and implementation_sha256(tuple(runtime['source_files']),
                        source_root=EX / 'src/strategy_runtime') == runtime['source_sha256'])
            run = verified_record(record)
            ledgers = {name: prior.frame(table) for name, table in run['ledgers'].items()}
            shadow = strategy.history(market, raw, limits, status, samples, variant)
            instance = strategy.RepairStrategy.from_parameters(strategy.ParameterSet({'variant': variant}))
            visible = instance.calculate_history({'market': market, 'raw': raw, 'limits': limits,
                                                   'status': status}, shadow.index)
            observed = ['parent', 'high', 'decision_evaluated', 'extend_selected']
            require(variant + ' numeric observation casts preserve state',
                    visible[observed].dtypes.eq(float).all()
                    and np.array_equal(visible[observed].to_numpy(), shadow[observed].to_numpy()))
            pd.testing.assert_frame_equal(visible.drop(columns=observed), shadow.drop(columns=observed))
            require(variant + ' public history preserves all economic values', True)
            report = prior.audit_ledger(variant, ledgers, *indexed, strategy, require, shadow)
            conditional = audit_extension(variant, ledgers, shadow, report['normalization_anchor'], prior, require)
            accounts.append({'variant': variant, 'candidate': record['candidate'], **report, **conditional})
            require(variant + ' full buyhold exactly equals original high H3 benchmark',
                    run['buyhold'] is not None
                    and json.dumps(run['buyhold'], sort_keys=True, separators=(',', ':')) == benchmark)
        bh_tables = {name: prior.frame(table) for name, table in old_high['buyhold']['execution'].items()}
        bh_report = prior.audit_ledger('buyhold', bh_tables, *indexed, strategy, require)
        bh_fills = bh_tables['fills']
        require('buyhold first purchase original first session and never sold',
                len(bh_fills) == 1 and bh_fills.side.eq('BUY').all()
                and pd.Timestamp(bh_fills.fill_time.iloc[0]).date().isoformat() == '2020-01-02')
        accounts.append({'variant': 'buyhold', **bh_report})
        require('no attempted external calls', not external_attempts)
        result = {'status': 'PASS', 'check_count': len(checks), 'checks': checks,
                  'accounts': accounts, 'new_accounts_audited': len(EXPECTED), 'reused_accounts': REUSED,
                  'formal_evidence': refs, 'source_sha256': source_hash, 'calibration_sha256': sample_hash,
                  'predecessor_audit_source_sha256': sha256(prior_audit_path.read_bytes()).hexdigest(),
                  'audit_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
                  'method_review_sha256': sha256((EX / 'others/method_review.json').read_bytes()).hexdigest(),
                  'full_input_reference': prior.FULL_INPUT_REFERENCE,
                  'external_calls': 0, 'external_attempts': len(external_attempts), 'new_account_runs': 0}
    except Exception as exc:
        result = {'status': 'FAIL', 'check_count': len(checks), 'checks': checks,
                  'accounts': accounts, 'formal_evidence': refs,
                  'error': type(exc).__name__ + ': ' + str(exc), 'traceback': traceback.format_exc(),
                  'external_calls': 0, 'external_attempts': len(external_attempts), 'new_account_runs': 0}
        write_result(result)
        raise
    finally:
        requests.sessions.Session.request = original_request
        sys.path[:] = original_path
    write_result(result)
    print('EX019_ACCOUNT_AUDIT_PASS', len(checks))


if __name__ == '__main__':
    main()
