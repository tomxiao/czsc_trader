"""Independent saved-ledger audit. Run at repository root; optional NEW --output JSON."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import socket

import pandas as pd

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
FOLDER = ROOT / 'research/S014/materials/20261019_year_driver_research'
ATOMS = ['entry_mark_pnl', 'hold_mark_pnl', 'exit_mark_pnl', 'fees_pnl']
COMPS = ['hold_market_pnl', 'hold_sector_minus_market_pnl', 'hold_stock_minus_sector_pnl']
STATES = [f'{e}__STOCK_{s}' for e in ['COMMON_UP', 'COMMON_NONUP', 'DIVERGENT'] for s in ['UP', 'NONUP']] + ['UNKNOWN']
POSTURES = ['PLAN_BUY', 'PLAN_SELL', 'HOLD', 'FLAT']
COUNTS = Counter()
ERRORS = defaultdict(float)

def block(*args, **kwargs):
    raise RuntimeError('No network calls permitted')

socket.socket.connect = block
socket.create_connection = block

def check(kind, value, detail=''):
    if not value:
        raise AssertionError(kind + ': ' + detail)
    COUNTS[kind] += 1

def number(kind, actual, expected, unit='ratio'):
    if expected is None:
        check(kind, actual is None, 'null expected')
        return
    error = abs(float(actual) - expected)
    ERRORS[unit] = max(ERRORS[unit], error)
    check(kind, math.isfinite(float(actual)) and error <= (1e-6 if unit == 'currency' else 1e-10), str((actual, expected)))

def publish(ref_value):
    ref = EvidenceRef.from_dict(ref_value)
    check('S014 source', ref.experiment.strategy_id == 'S014')
    raw = ref.resolve(ROOT).read_bytes()
    check('source hash', sha256(raw).hexdigest() == ref.sha256)
    return raw

def date(x):
    return str(x)[:10]

def mean(items):
    return math.fsum(items) / len(items) if items else None

def finite(x):
    return not pd.isna(x) and math.isfinite(float(x))

def summary(rows):
    n = len(rows)
    return {'days': n, 'known_exposure_days': sum(r['known_exposure_D'] > 0 for r in rows),
            'ready_days': sum(r['D_ready'] for r in rows),
            'phases': {p: sum(r['phase'] == p for r in rows) for p in ['ENTRY', 'HOLD', 'EXIT', 'FLAT']},
            'actual_pnl': math.fsum(r['actual_pnl'] for r in rows),
            'original_annual_return_contribution': math.fsum(r['annual_return_contribution'] for r in rows),
            'buyhold_annual_return_contribution': math.fsum(r['buyhold_annual_return_contribution'] for r in rows),
            'mean_actual_daily_return': mean([r['actual_daily_return'] for r in rows]),
            'mean_buyhold_daily_return': mean([r['buyhold_daily_return'] for r in rows]),
            'mean_active_log_return': mean([r['active_log_return'] for r in rows]),
            'mean_known_exposure_D': mean([r['known_exposure_D'] for r in rows]),
            'active_log_return_sum': math.fsum(r['active_log_return'] for r in rows),
            'atoms': {a: math.fsum(r[a] for r in rows) for a in ATOMS},
            'hold_accounting_components': {c: math.fsum(r[c] for r in rows if r[c] is not None)
                                           if any(r[c] is not None for r in rows) else None for c in COMPS}}

def compare_summary(saved, expected):
    for key, value in expected.items():
        if isinstance(value, dict):
            for subkey, subvalue in value.items():
                if key == 'phases':
                    check('group phase counts', saved[key][subkey] == subvalue)
                else:
                    number('group ' + key, saved[key][subkey], subvalue, 'currency')
        elif key in ['days', 'known_exposure_days', 'ready_days']:
            check('group counts', saved[key] == value)
        else:
            number('group metrics', saved[key], value, 'currency' if key == 'actual_pnl' else 'ratio')

def run(output):
    result_path = FOLDER / 'state_driver_analysis.json'
    panel_path = FOLDER / 'state_driver_daily_panel.csv'
    check('fixed result SHA', sha256(result_path.read_bytes()).hexdigest() == 'e8005d55e95f6d4beacaf454353d29bb7392a26f13279e1b27b9818c3c4a42ac')
    check('fixed panel SHA', sha256(panel_path.read_bytes()).hexdigest() == 'd2ce4f0294a5dc5b6b8df959a15e06f3a71360ec66bdef756411fc2c2de9c4b6')
    result = json.loads(result_path.read_bytes())
    refs = result['source_references']
    raw = {name: publish(ref) for name, ref in refs.items()}
    lock = json.loads((FOLDER / 'main_lock.json').read_bytes())
    check('published source lock', publish(lock['source']) == raw['source'] == (FOLDER / 'state_driver_analysis.py').read_bytes())
    check('published design lock', publish(lock['design']) == raw['design'] == (FOLDER / 'design.json').read_bytes())
    check('pre-review design identity', json.loads((FOLDER / 'pre_review.json').read_bytes())['reviewed_design_sha256'] == sha256(raw['design']).hexdigest())
    account = json.loads(raw['original_account_and_embedded_buyhold'])
    request = account['request_identity']
    check('exact original account identity', account['result_hash'] == '423a1ccf05574d17eb4fa3d5984de02dc869c7387cbe66bf4f502b54c7510ef6'
          and request['strategy_reference'] == 'S014-C0056' and request['initial_cash'] == 100000)
    check('research representation', request['pricing'] == {'anchor_date': '2019-12-31', 'anchor_factor': 5.892, 'basis': 'HFQ_RESEARCH', 'quantity_unit': 'RESEARCH_UNIT'})
    original = account['runs'][0]
    daily = original['ledgers']['account_daily']['data']
    decisions = original['ledgers']['decisions']['data']
    buyhold = original['buyhold']['account_daily']['data']
    fills = original['ledgers']['fills']['data']
    fill_map = {date(x['fill_time']): x for x in fills}
    check('one fill per day', len(fill_map) == len(fills) == 276)
    check('same benchmark contract', original['buyhold']['benchmark'] == request['benchmark'])
    f20 = pd.read_csv(BytesIO(raw['features20']), usecols=['date', 'signal', 'ret20', 'market_ret20', 'sector_ret20'], float_precision='round_trip').to_dict('records')
    f1 = pd.read_csv(BytesIO(raw['features1']), float_precision='round_trip').to_dict('records')
    published_atoms = pd.read_csv(BytesIO(raw['daily_reconciliation']), float_precision='round_trip').to_dict('records')
    saved_panel = pd.read_csv(panel_path, float_precision='round_trip').to_dict('records')
    calendar = pd.read_csv(BytesIO(raw['calendar'])).date.tolist()
    check('1642 exact calendars', len(daily) == len(decisions) == len(buyhold) == len(f20) == len(f1) == len(saved_panel) == len(calendar) == 1642)
    for rows, key in [(daily, 'date'), (buyhold, 'date'), (decisions, 'valid_session'), (f20, 'date'), (f1, 'date'), (published_atoms, 'date')]:
        check('source calendar alignment', [date(x[key]) for x in rows] == calendar)
    dec_by_id = {x['decision_id']: x for x in decisions}
    check('unique original decision IDs', len(dec_by_id) == 1642)
    planned_ids = set()
    records = []
    opening_by_year, bh_opening_by_year = {}, {}
    for i, (d, dec, b, old, saved) in enumerate(zip(daily, decisions, buyhold, published_atoms, saved_panel, strict=True)):
        E, D = date(d['date']), date(dec['signal_date'])
        check('exact D before E', D < E and date(dec['valid_session']) == E and (i == 0 or D == calendar[i-1]))
        check('D original ledger clock', D == date(d['signal_date']))
        previous_wealth = daily[i-1]['equity'] if i else 100000.
        previous_bh = buyhold[i-1]['equity'] if i else 100000.
        previous_close = daily[i-1]['close'] if i else None
        check('known D holding exact', bool(dec['held_at_close']) == (d['quantity_before'] > 0))
        posture = 'PLAN_BUY' if dec['entry_signal'] else 'PLAN_SELL' if dec['held_at_close'] and dec['exit_pending'] else 'HOLD' if dec['held_at_close'] else 'FLAT'
        check('target matches causal posture', d['target_position'] == dec['target_position'] == float(posture in ['PLAN_BUY', 'HOLD']))
        if posture in ['PLAN_BUY', 'PLAN_SELL']:
            planned_ids.add(dec['decision_id'])
        atoms = {a: 0. for a in ATOMS}
        phase = 'FLAT'
        fill = fill_map.get(E)
        if fill:
            number('fill fee identity', fill['fees'], .001 * fill['quantity'] * fill['price'], 'currency')
            atoms['fees_pnl'] = -fill['fees']
            if fill['side'] == 'BUY':
                phase = 'ENTRY'
                atoms['entry_mark_pnl'] = fill['quantity'] * (d['close'] - fill['price'])
            else:
                phase = 'EXIT'
                atoms['exit_mark_pnl'] = fill['quantity'] * (fill['price'] - previous_close)
        elif d['quantity_before']:
            phase = 'HOLD'
            atoms['hold_mark_pnl'] = d['quantity'] * (d['close'] - previous_close)
        pnl = d['equity'] - previous_wealth
        number('daily wealth identity', d['equity'], d['cash'] + d['quantity'] * d['close'], 'currency')
        number('daily atoms identity', math.fsum(atoms.values()), pnl, 'currency')
        check('original phase', old['phase'] == phase == saved['phase'])
        for a, v in atoms.items():
            number('published atom reconciliation', old[a], v, 'currency')
        number('published actual pnl', old['actual_pnl'], pnl, 'currency')
        year = int(E[:4])
        opening_by_year.setdefault(year, previous_wealth)
        bh_opening_by_year.setdefault(year, previous_bh)
        state = 'UNKNOWN'
        prior = f20[i-1] if i else None
        if prior and all(finite(prior[k]) for k in ['ret20', 'market_ret20', 'sector_ret20']):
            m, s, stock = prior['market_ret20'], prior['sector_ret20'], prior['ret20']
            external = 'COMMON_UP' if m > 0 and s > 0 else 'COMMON_NONUP' if m <= 0 and s <= 0 else 'DIVERGENT'
            state = external + ('__STOCK_UP' if stock > 0 else '__STOCK_NONUP')
        if i >= 20:
            number('stock20 simple semantics', f20[i]['ret20'], d['close'] / daily[i-20]['close'] - 1)
            for feature, ret in [('market_ret20', 'market_return'), ('sector_ret20', 'sector_return')]:
                expected = math.fsum(math.log1p(x[ret]) for x in f1[i-19:i+1])
                number('external20 log semantics', f20[i][feature], expected)
        if i:
            number('E stock simple unit identity', f1[i]['stock_return'], d['close'] / previous_close - 1)
        exposure = d['quantity_before'] * previous_close if d['quantity_before'] else 0.
        comps = dict.fromkeys(COMPS, None)
        if phase == 'HOLD':
            comps = dict(zip(COMPS, [exposure * f1[i]['market_return'],
                                     exposure * (f1[i]['sector_return'] - f1[i]['market_return']),
                                     exposure * (f1[i]['stock_return'] - f1[i]['sector_return'])], strict=True))
            number('HOLD exact component sum', math.fsum(comps.values()), atoms['hold_mark_pnl'], 'currency')
        bh_pnl = b['equity'] - previous_bh
        record = {'date': E, 'D_signal_date': D, 'D_valid_session': E, 'year': year, 'month': E[:7],
                  'D_state': state, 'D_posture': posture, 'D_ready': bool(dec['ready']),
                  'phase': phase, **{a: old[a] for a in ATOMS}, 'actual_pnl': old['actual_pnl'],
                  'known_position_value_D': exposure, 'known_exposure_D': exposure / previous_wealth,
                  'previous_equity': previous_wealth, 'previous_ledger_close': previous_close,
                  'actual_daily_return': d['equity'] / previous_wealth - 1,
                  'buyhold_pnl': bh_pnl, 'buyhold_daily_return': b['equity'] / previous_bh - 1,
                  'active_log_return': math.log(d['equity'] / previous_wealth) - math.log(b['equity'] / previous_bh),
                  'annual_open_equity': opening_by_year[year], 'buyhold_annual_open_equity': bh_opening_by_year[year],
                  'annual_return_contribution': old['actual_pnl'] / opening_by_year[year],
                  'buyhold_annual_return_contribution': bh_pnl / bh_opening_by_year[year], **comps}
        records.append(record)
        for key, value in record.items():
            if isinstance(value, (str, bool)) or key == 'year':
                check('daily state/identity fields', date(saved[key]) == value if key in ['date', 'D_signal_date', 'D_valid_session'] else saved[key] == value)
            elif value is None:
                check('daily null retained', pd.isna(saved[key]))
            else:
                currency = key in [*ATOMS, *COMPS, 'actual_pnl', 'known_position_value_D', 'previous_equity', 'buyhold_pnl', 'annual_open_equity', 'buyhold_annual_open_equity']
                number('daily numeric fields', saved[key], value, 'currency' if currency else 'ratio')
    orders = original['ledgers']['orders']['data']
    check('exact original planned orders', {x['decision_id'] for x in orders} == planned_ids and len(orders) == len(planned_ids) == 280)
    for order in orders:
        dec = dec_by_id[order['decision_id']]
        check('order D-E-side linkage', date(order['signal_date']) == date(dec['signal_date'])
              and date(order['execution_date']) == date(dec['valid_session'])
              and order['side'] == ('BUY' if dec['entry_signal'] else 'SELL'))
    annuals = {x['year']: x for x in result['annual']}
    months = {x['month']: x for x in result['monthly']}
    by_group = {(x['year'], x['state'], x['D_posture']): x for x in result['year_state_D_posture']}
    check('all fixed group slots', len(by_group) == 7 * 7 * 4)
    for year, saved in annuals.items():
        chosen = [r for r in records if r['year'] == year]
        compare_summary(saved, summary(chosen))
        endpoint = next(d['equity'] for d in reversed(daily) if date(d['date']).startswith(str(year)))
        bh_endpoint = next(d['equity'] for d in reversed(buyhold) if date(d['date']).startswith(str(year)))
        number('annual original return', saved['return'], endpoint / opening_by_year[year] - 1)
        number('annual benchmark return', saved['buyhold_return'], bh_endpoint / bh_opening_by_year[year] - 1)
    for month, saved in months.items():
        chosen = [r for r in records if r['month'] == month]
        compare_summary(saved, summary(chosen))
        one = [d for d in daily if date(d['date']).startswith(month)]
        number('month original wealth return', saved['month_return'], one[-1]['equity'] / chosen[0]['previous_equity'] - 1)
    for (year, state, posture), saved in by_group.items():
        compare_summary(saved, summary([r for r in records if (r['year'], r['D_state'], r['D_posture']) == (year, state, posture)]))
    check('all OTHER/PAST reference slots', len(result['cross_year_observed_references']) == 7 * 7 * 4 * 2)
    for saved in result['cross_year_observed_references']:
        year, state, posture, mode = saved['target_year'], saved['state'], saved['D_posture'], saved['mode']
        target = [r for r in records if (r['year'], r['D_state'], r['D_posture']) == (year, state, posture)]
        selected = [r for r in records if r['D_state'] == state and r['D_posture'] == posture
                    and (r['year'] != year if mode == 'ALL_OTHER_YEARS' else r['year'] < year)]
        check('reference counts', saved['target_days'] == len(target) and saved['reference_days'] == len(selected))
        check('reference calendar years', saved['reference_years'] == sorted({r['year'] for r in selected}))
        check('reference support semantics', saved['support'] == ('OBSERVED_SAME_STATE_POSTURE' if selected else 'NO_SUPPORT'))
        for key, source in [('observed_reference_mean_daily_return', 'actual_daily_return'),
                            ('observed_reference_mean_active_log', 'active_log_return'),
                            ('observed_reference_mean_known_exposure', 'known_exposure_D')]:
            number('reference means/null', saved[key], mean([r[source] for r in selected]))
    report = {'status': 'PASS_INDEPENDENT_SAVED_LEDGER_AND_STATE_ARITHMETIC',
              'method': 'Direct scalar reconstruction from original account/fill/decision/benchmark records and pinned feature bytes; independent list filtering and math.fsum; original analysis module never imported or executed.',
              'source_references': refs, 'checked_output_sha256': {'analysis': sha256(result_path.read_bytes()).hexdigest(), 'panel': sha256(panel_path.read_bytes()).hexdigest()},
              'audit_source': {'path': Path(__file__).relative_to(ROOT).as_posix(), 'sha256': sha256(Path(__file__).read_bytes()).hexdigest()},
              'check_counts': dict(COUNTS), 'total_checks': sum(COUNTS.values()), 'maximum_absolute_errors': dict(ERRORS),
              'audited_scope': {'days': len(records), 'annual': len(annuals), 'months': len(months), 'state_posture_year_cells': len(by_group), 'OTHER_PAST_references': len(result['cross_year_observed_references'])},
              'interpretation_limits': ['Three HOLD components are exact contemporaneous accounting coordinates, not causal market/sector effects.',
                                       'A D-known classification is not an intervention; conditional historical returns do not equal a filtered-account improvement.',
                                       'OTHER-year references include future data relative to a target; PAST_ONLY uses strictly earlier complete calendar years and remains descriptive.',
                                       'UNKNOWN dates and empty group/reference nulls were preserved; all seven years remain in the annual identity.',
                                       'Old 2024 September and 2025 June examples are already seen, so do not claim independent confirmation.'],
              'new_fits': 0, 'new_return_labels': 0, 'new_accounts': 0, 'new_market_data_calls': 0}
    if output:
        with output.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
    print(json.dumps({'status': report['status'], 'checks': report['total_checks'], 'errors': dict(ERRORS),
                      'output': str(output) if output else None, 'sha256': sha256(output.read_bytes()).hexdigest() if output else None}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Optional new JSON path; refuse overwrite, default stdout only')
    run(parser.parse_args().output)
