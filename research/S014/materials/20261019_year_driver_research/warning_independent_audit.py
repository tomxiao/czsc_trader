"""Independent locked warning-state audit. Default stdout; optional NEW --output."""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
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
STATES = [f'{x}__STOCK_{s}' for x in ['COMMON_UP', 'COMMON_NONUP', 'DIVERGENT'] for s in ['UP', 'NONUP']]
POSTURES = ['PLAN_BUY', 'PLAN_SELL', 'HOLD', 'FLAT']
PRIMARY = ['PLAN_BUY', 'HOLD']
METRICS = ['actual_daily_return', 'buyhold_daily_return', 'active_log_return']
NUMERIC = METRICS + ['actual_pnl', 'annual_open_equity', 'annual_return_contribution']
CHECKS = Counter()
ERRORS = {'currency': 0., 'ratio_or_percentage_points': 0.}

def block(*args, **kwargs):
    raise RuntimeError('Independent audit forbids external calls')

socket.socket.connect = block
socket.create_connection = block

def check(kind, value, detail=''):
    if not value:
        raise AssertionError(kind + ': ' + detail)
    CHECKS[kind] += 1

def source(value):
    ref = EvidenceRef.from_dict(value)
    check('S014 source', ref.experiment.strategy_id == 'S014')
    raw = ref.resolve(ROOT).read_bytes()
    check('published SHA', sha256(raw).hexdigest() == ref.sha256)
    return raw

def same(saved, expected, label='tree', key=''):
    if isinstance(expected, dict):
        check('dictionary schema', set(saved) == set(expected), label)
        for subkey, value in expected.items():
            same(saved[subkey], value, label + '/' + subkey, subkey)
    elif isinstance(expected, list):
        check('list length', len(saved) == len(expected), label)
        for index, value in enumerate(expected):
            same(saved[index], value, label + '/' + str(index), key)
    elif expected is None or isinstance(expected, (str, bool, int)):
        check('exact value/null', saved == expected, label)
    else:
        error = abs(saved - expected)
        kind = 'currency' if key == 'observed_actual_pnl_sum' else 'ratio_or_percentage_points'
        ERRORS[kind] = max(ERRORS[kind], error)
        check('numeric value', math.isfinite(saved) and error <= (1e-6 if kind == 'currency' else 1e-10), label)

def title_match(title):
    return '股票交易' in title and any(x in title for x in ['异常波动', '风险提示']) and '回复' not in title

def independent_group(frame, annual):
    n = len(frame)
    return {'n': n, 'means': {m: float(frame[m].mean()) if n else None for m in METRICS},
            'observed_actual_pnl_sum': float(frame.actual_pnl.sum()),
            'observed_annual_contribution_pp': float(frame.annual_return_contribution.sum() * 100) if annual else None,
            'annual_contribution_status': 'SAME_ORIGINAL_YEAR_DENOMINATOR' if annual else 'NOT_SUMMED_ACROSS_DIFFERENT_YEAR_OPENING_DENOMINATORS',
            'planned_buy_decisions': int(frame.D_posture.eq('PLAN_BUY').sum()),
            'original_buy_fill_days': int((frame.D_posture.eq('PLAN_BUY') & frame.phase.eq('ENTRY')).sum()),
            'original_buy_unfilled_days': int((frame.D_posture.eq('PLAN_BUY') & ~frame.phase.eq('ENTRY')).sum())}

def delta(a, b):
    return {m: b['means'][m] - a['means'][m] if a['n'] and b['n'] else None for m in METRICS}

def independent_scope(frame, name, original_weights=None):
    annual = name != 'ALL2020_2025'
    raw, cells = [], []
    weights = {} if original_weights is None else original_weights.copy()
    for posture in POSTURES:
        own = frame.loc[frame.D_posture.eq(posture)]
        a = independent_group(own.loc[own.W_state.eq('W0')], annual)
        b = independent_group(own.loc[own.W_state.eq('W1')], annual)
        raw.append({'D_posture': posture, 'primary_population': posture in PRIMARY,
                    'W0': a, 'W1': b, 'W1_minus_W0': delta(a, b)})
        for state in STATES + ['UNKNOWN']:
            selected = own.loc[own.D_state.eq(state)]
            a = independent_group(selected.loc[selected.W_state.eq('W0')], annual)
            b = independent_group(selected.loc[selected.W_state.eq('W1')], annual)
            key = posture + '|' + state
            if original_weights is None:
                weights[key] = min(a['n'], b['n']) if posture in PRIMARY and state != 'UNKNOWN' else 0
            weight = weights[key]
            status = 'ORIGINAL_COMMON_CELL_SUPPORTED' if weight and a['n'] and b['n'] else 'MISSING_ORIGINAL_REQUIRED_GROUP' if weight else 'ORIGINAL_UNSUPPORTED_OR_NOT_PRIMARY'
            cells.append({'D_posture': posture, 'D_state': state, 'original_min_count_weight': weight,
                          'support': status, 'W0': a, 'W1': b, 'W1_minus_W0': delta(a, b)})
    fixed = []
    for postures in [['PLAN_BUY'], ['HOLD'], PRIMARY]:
        required = [x for x in cells if x['D_posture'] in postures and x['original_min_count_weight'] > 0]
        missing = [x['D_posture'] + '|' + x['D_state'] for x in required if not x['W0']['n'] or not x['W1']['n']]
        total = sum(x['original_min_count_weight'] for x in required)
        supported = total > 0 and not missing
        fixed.append({'D_postures': postures, 'original_common_weight': total,
                      'original_required_cells': len(required), 'missing_original_required_cells': missing,
                      'status': 'AVAILABLE' if supported else 'MISSING_FIXED_GROUP' if missing else 'NO_COMMON_SUPPORT',
                      'W1_minus_W0': {m: float(sum(x['original_min_count_weight'] * x['W1_minus_W0'][m] for x in required) / total) if supported else None for m in METRICS}})
    return {'scope': name, 'raw_by_posture': raw, 'all_state_posture_cells': cells,
            'fixed_common_cell_contrasts': fixed}, weights

def run(output):
    result_path = FOLDER / 'warning_state_results.json'
    row_path = FOLDER / 'warning_state_rows.csv'
    check('fixed result identity', sha256(result_path.read_bytes()).hexdigest() == 'fa8570537387b7dfe792c69ff21463be1874b7dd3e22e032ccf213953692368f')
    check('fixed rows identity', sha256(row_path.read_bytes()).hexdigest() == 'c2e7a756ead771bdfe7cff7686fdacf35c699d429cb25b0b3dc18da524190301')
    result = json.loads(result_path.read_bytes())
    lock = json.loads((FOLDER / 'warning_lock.json').read_bytes())
    check('five fixed sources', set(lock) == {'source', 'design', 'panel', 'events', 'coverage'})
    raw = {key: source(ref) for key, ref in lock.items()}
    check('source lock unchanged', raw['source'] == (FOLDER / 'warning_state_analysis.py').read_bytes())
    check('design lock unchanged', raw['design'] == (FOLDER / 'design.json').read_bytes())
    check('original audited panel unchanged', raw['panel'] == (FOLDER / 'state_driver_daily_panel.csv').read_bytes())
    check('source refs recorded unchanged', result['source_references'] == lock)
    events = json.loads(raw['events'])['events']
    coverage = json.loads(raw['coverage'])
    check('30 complete issuer leaves', len(coverage['leaf_proofs']) == coverage['complete_2020_2025_leaf_count'] == 30 and coverage['scope_is_all_issuer_announcement_classes'])
    records = {}
    original_ref_count = 0
    for proof in coverage['leaf_proofs']:
        body = json.loads(source(proof['original_evidence_ref']))
        query = json.loads(source(proof['request_original_evidence_ref']))['params']
        original_ref_count += 2
        check('original query identity', query == proof['query_params'] and query['seDate'] == proof['start'] + '~' + proof['end'])
        check('all issuer classes', query['category'] == query['searchkey'] == '' and query['stock'] == '600722,gssh0600722')
        rows = body.get('announcements') or []
        check('leaf complete count/no-more', body['hasMore'] is False and len(rows) == body['totalAnnouncement'] == proof['total'] == proof['rows'] and proof['complete_within_current_source'])
        for row in rows:
            day = datetime.fromtimestamp(row['announcementTime'] / 1000, tz=timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()
            check('issuer/calendar/date/unique', row['secCode'] == '600722' and proof['start'] <= day <= proof['end'] and row['announcementId'] not in records)
            records[row['announcementId']] = {'date': day, 'title': row['announcementTitle'], 'url': 'https://static.cninfo.com.cn/' + row['adjunctUrl']}
    for year in range(2020, 2026):
        dates = set()
        for proof in coverage['leaf_proofs']:
            if proof['start'].startswith(str(year)):
                start, end = date.fromisoformat(proof['start']), date.fromisoformat(proof['end'])
                leaf_dates = {start + timedelta(days=i) for i in range((end-start).days+1)}
                check('no overlapping catalogue dates', not dates & leaf_dates)
                dates |= leaf_dates
        start, end = date(year, 1, 1), date(year+1, 1, 1)
        check('complete calendar-year catalogue dates', dates == {start + timedelta(days=i) for i in range((end-start).days)})
    matches = {key for key, value in records.items() if title_match(value['title'])}
    check('exact 14 title-matched notices', len(events) == len(matches) == 14 and {x['doc_id'] for x in events} == matches)
    for event in events:
        same(records[event['doc_id']], {'date': event['publication_date'], 'title': event['title'], 'url': event['url']}, 'event title/date/url')
    panel = pd.read_csv(BytesIO(raw['panel']), float_precision='round_trip')
    saved_rows = pd.read_csv(row_path, float_precision='round_trip', keep_default_na=False)
    sessions = panel.date.tolist()
    indices = {day: i for i, day in enumerate(sessions)}
    check('1642 pinned original sessions', len(sessions) == len(indices) == len(saved_rows) == 1642 and sessions == sorted(sessions))
    windows, active_sets = [], []
    for event in sorted(events, key=lambda x: (x['publication_date'], x['doc_id'])):
        subsequent = [day for day in sessions if day > event['publication_date']]
        available = subsequent[0]
        start = indices[available]
        active_set = set(subsequent[:10])
        check('strict-after conservative source availability', event['availability']['decision_date_15_00'] == available and event['availability']['earliest_execution_date'] == subsequent[1])
        check('0..9 exactly ten sessions', len(active_set) == 10 and max(indices[x] for x in active_set) - start == 9)
        windows.append({'doc_id': event['doc_id'], 'publication_date': event['publication_date'],
                        'available_D': available, 'earliest_execution_E': subsequent[1], 'start_D_index': start,
                        'end_D_index': start+9, 'last_active_D': subsequent[9]})
        active_sets.append(active_set)
    same(result['notice_windows'], windows, 'windows')
    # Independent connected set-union construction: only intersecting sessions join.
    episodes = []
    current = set()
    for window, active in zip(windows, active_sets, strict=True):
        if current & active:
            current |= active
            episodes[-1]['end_D_index'] = max(indices[x] for x in current)
            episodes[-1]['doc_ids'].append(window['doc_id'])
            episodes[-1]['last_active_D'] = max(current)
        else:
            current = active.copy()
            episodes.append({'episode_id': len(episodes)+1, 'start_D_index': min(indices[x] for x in active),
                             'end_D_index': max(indices[x] for x in active), 'doc_ids': [window['doc_id']],
                             'first_available_D': min(active), 'last_active_D': max(active)})
    same(result['time_only_original_episodes'], episodes, 'episodes')
    reconstructed = []
    for index, original in enumerate(panel.to_dict('records')):
        E, D = original['date'], original['D_signal_date']
        i = indices.get(D)
        check('D/E previous-session linkage', D < E and (index == 0 or D == sessions[index-1]))
        active = [window for window, active in zip(windows, active_sets, strict=True) if D in active]
        state = 'OUT_OF_DOMAIN' if original['year'] > 2025 else 'UNKNOWN' if i is None or i < 9 else 'W1' if active else 'W0'
        episode = next((e['episode_id'] for e in episodes if i is not None and e['start_D_index'] <= i <= e['end_D_index']), None)
        record = {k: original[k] for k in ['date', 'D_signal_date', 'D_state', 'D_posture', 'phase', 'year', 'month', *NUMERIC]}
        record.update(W_state=state, W_eligible=state in ['W0', 'W1'], D_session_index=i,
                      active_notice_count=len(active), active_notice_ids='|'.join(x['doc_id'] for x in active),
                      active_notice_publication_dates='|'.join(x['publication_date'] for x in active),
                      active_notice_available_dates='|'.join(x['available_D'] for x in active), original_time_episode_id=episode)
        saved = saved_rows.iloc[index]
        for key, value in record.items():
            if key in NUMERIC:
                same(float(saved[key]), float(value), 'existing economic outcome', 'observed_actual_pnl_sum' if key in ['actual_pnl', 'annual_open_equity'] else key)
            elif value is None:
                check('row null retained', saved[key] == '')
            elif isinstance(value, bool):
                check('row boolean', str(saved[key]) == str(value))
            elif key in ['year', 'D_session_index', 'active_notice_count', 'original_time_episode_id']:
                check('row count/id', int(float(saved[key])) == value)
            else:
                check('row identity/feature', saved[key] == value)
        reconstructed.append(record)
    frame = pd.DataFrame(reconstructed)
    check('initial E plus nine D unknown', frame.W_state.iloc[:10].eq('UNKNOWN').all() and frame.W_state.iloc[10] != 'UNKNOWN')
    check('all 2026 outside W domain', frame.loc[frame.year.eq(2026), 'W_state'].eq('OUT_OF_DOMAIN').all())
    eligible = frame.loc[frame.W_eligible].copy()
    scopes = ['ALL2020_2025'] + [str(y) for y in range(2020, 2026)]
    weights, recomputed = {}, {}
    for name in scopes:
        own = eligible if name == 'ALL2020_2025' else eligible.loc[eligible.year.eq(int(name))]
        expected, weights[name] = independent_scope(own, name)
        same(result['scopes'][name], expected, 'scope/' + name)
        recomputed[name] = expected
    check('all six episodes deleted', len(result['leave_one_original_time_episode_out']) == len(episodes) == 6)
    for episode, saved in zip(episodes, result['leave_one_original_time_episode_out'], strict=True):
        retained = eligible.loc[~(eligible.W_state.eq('W1') & eligible.original_time_episode_id.eq(episode['episode_id']))]
        check('whole episode deletion count', saved['episode_id'] == episode['episode_id'] and saved['deleted_original_W1_rows'] == len(eligible) - len(retained))
        for name in scopes:
            own = retained if name == 'ALL2020_2025' else retained.loc[retained.year.eq(int(name))]
            expected, after_weights = independent_scope(own, name, weights[name])
            check('frozen common-cell weights', after_weights == weights[name])
            same(saved['scopes'][name], expected, 'delete/' + str(episode['episode_id']) + '/' + name)
    counts = [{'year': y, 'D_posture': p, 'W_state': w,
               'n': int((frame.year.eq(y) & frame.D_posture.eq(p) & frame.W_state.eq(w)).sum())}
              for y in sorted(frame.year.unique().tolist()) for p in POSTURES for w in ['W0', 'W1', 'UNKNOWN', 'OUT_OF_DOMAIN']]
    same(result['status_population_counts'], counts, 'status counts')
    report = {'status': 'PASS_INDEPENDENT_DISCLOSURE_CLOCK_AND_EXISTING_LEDGER_COMPARISON',
              'method': 'Independently parsed 30 published catalogue leaves plus original queries; time-set windows/episode union; pandas group aggregation with frozen original weights, no import or invocation of primary warning analysis.',
              'source_references': lock,
              'checked_sha256': {'warning_results': sha256(result_path.read_bytes()).hexdigest(), 'warning_rows': sha256(row_path.read_bytes()).hexdigest()},
              'audit_source': {'path': Path(__file__).relative_to(ROOT).as_posix(), 'sha256': sha256(Path(__file__).read_bytes()).hexdigest()},
              'check_counts': dict(CHECKS), 'total_checks': sum(CHECKS.values()), 'maximum_absolute_errors': ERRORS,
              'audited_scope': {'original_catalogue_leaves': 30, 'catalogue_plus_query_refs': original_ref_count,
                                'issuer_records': len(records), 'matched_notices': len(events), 'time_episodes': len(episodes),
                                'daily_rows': len(frame), 'W_eligible_rows': len(eligible), 'scope_count': len(scopes),
                                'fixed_deletion_scope_comparisons': len(scopes) * len(episodes)},
              'independent_population_counts': {str(k): int(v) for k, v in frame.W_state.value_counts().items()},
              'primary_all_period_results': [x for x in recomputed['ALL2020_2025']['raw_by_posture'] if x['primary_population']],
              'interpretation_limits': ['W=1 denotes a recently disclosed trading warning under a conservative date rule, not necessarily negative business news or impending reversal.',
                                       'Only seven W1 PLAN_BUY decisions and six time episodes exist; annual/episode/common-state support and absent-group nulls are substantive limits.',
                                       'W1 PLAN_BUY and HOLD can show opposite observed behavior; do not merge them into a universal trading rejection rule.',
                                       'No cancellation/sale counterfactual or filtered-account return is calculated. Existing actual outcomes are conditional on the original policy and fills.',
                                       '2021 and 2025 business-unchanged statements do not justify a narrative that only the latter was speculation; this audit verifies clocks/titles/outcomes, not investor motives.',
                                       'All history and selected cases were already seen. Pooled common states do not balance years, holding age or floating PnL.'],
              'new_fits': 0, 'new_accounts': 0, 'new_return_labels': 0, 'new_market_data_calls': 0}
    if output:
        with output.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
    print(json.dumps({'status': report['status'], 'checks': report['total_checks'], 'errors': ERRORS,
                      'counts': report['independent_population_counts'], 'output': str(output) if output else None,
                      'sha256': sha256(output.read_bytes()).hexdigest() if output else None}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Optional new JSON; refuse overwrite, default stdout only')
    run(parser.parse_args().output)
