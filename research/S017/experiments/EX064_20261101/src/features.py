"""Full prior-session range and same-session first events; no future labels."""
from collections import Counter
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path

from common import WORK, account_input, digest, save

GROUPS = ('UP_CROSS', 'UP_ACCEPT', 'LOW_REJECT')


def at(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def predicates(previous_close, low, close, upper, lower, prior_close_below_upper):
    return {'UP_CROSS': previous_close <= upper < close,
        'UP_ACCEPT': low > upper and prior_close_below_upper,
        'LOW_REJECT': previous_close >= lower and low < lower < close}


def derive(bars, sessions):
    times = [at(b['Date']) for b in bars]
    if times != sorted(times) or len(times) != len(set(times)):
        raise ValueError('Unique chronological completed bars required')
    positions = {value: i for i, value in enumerate(times)}
    sessions = sorted(sessions, key=lambda s: s['session_date'])
    if len(sessions) != 543 or len({s['session_date'] for s in sessions}) != len(sessions):
        raise ValueError('Approved complete unique session calendar required')
    daily = []
    all_indices = []
    for session in sessions:
        if session['timezone'] != 'America/New_York':
            raise ValueError('Declared NY RTH timezone required')
        indices = []
        for segment in session['segments']:
            start, end = at(segment['start']), at(segment['end'])
            t = start
            while t < end:
                finish = t + timedelta(minutes=30)
                if finish > end or finish not in positions:
                    raise ValueError('Incomplete planned M30 grid,including intermediate bars')
                i = positions[finish]
                if at(bars[i]['BarStart']) != t or at(bars[i]['AvailableDate']) > finish:
                    raise ValueError('Interval or declared availability mismatch')
                b = bars[i]
                if not all(isfinite(float(b[k])) and b[k] > 0 for k in ('Open', 'High', 'Low', 'Close')) or not b['Low'] <= min(b['Open'], b['Close']) <= max(b['Open'], b['Close']) <= b['High']:
                    raise ValueError('Valid positive OHLC required')
                indices.append(i)
                t = finish
        all_indices.extend(indices)
        high = max(bars[i]['High'] for i in indices)
        low = min(bars[i]['Low'] for i in indices)
        if high <= low:
            raise ValueError('Nondegenerate observed session range required')
        daily.append({'session': session, 'indices': indices, 'high': high, 'low': low})
    if all_indices != list(range(len(bars))):
        raise ValueError('Unexpected or missing source bars outside approved grid')
    rows = []
    train_days = 0
    for j, day in enumerate(daily):
        s = day['session']
        if not '2024-01-02' <= s['session_date'] <= '2025-12-31':
            continue
        if not j:
            raise ValueError('Prior complete reference session required')
        prior = daily[j - 1]
        upper, lower = prior['high'], prior['low']
        seen = {g: False for g in GROUPS}
        indices = day['indices']
        train_days += 1
        # First completed candle lacks a same-session prior; final has no same-session next execution.
        for offset in range(1, len(indices) - 1):
            i, p = indices[offset], indices[offset - 1]
            if i != p + 1:
                raise ValueError('Previous observation must be the current session predecessor')
            current = bars[i]
            earlier_below = any(bars[k]['Close'] <= upper for k in indices[:offset])
            raw = predicates(float(bars[p]['Close']), float(current['Low']), float(current['Close']), upper, lower, earlier_below)
            selected = {g: bool(raw[g] and not seen[g]) for g in GROUPS}
            for g in GROUPS:
                seen[g] = seen[g] or selected[g]
            rows.append({'signal_at': current['Date'], 'bar_index': i, 'BarStart': current['BarStart'],
                'session_date': s['session_date'], 'prior_session_date': prior['session']['session_date'],
                'prior_session_high': upper, 'prior_session_low': lower,
                'previous_close': float(bars[p]['Close']), 'low': float(current['Low']), 'close': float(current['Close']),
                'prior_same_day_close_le_upper': earlier_below,
                'completed_bar_ordinal': offset + 1, 'total_session_bars': len(indices),
                'same_session_next_start': bars[indices[offset + 1]]['BarStart'],
                **selected, **{'raw_' + g: bool(raw[g]) for g in GROUPS}})
    if train_days != 502 or len(rows) != 5486:
        raise ValueError('All502 sessions and5486 eligible observations required')
    return rows


def main():
    value, account_ref, input_ref = account_input()
    metadata = value['data']['sessions']['metadata']
    rows = derive(value['products']['bars'], metadata['sessions'])
    out = {'status': 'PASS_OUTCOME_BLIND_SESSION_RANGE_FEATURES', 'source_sha256': digest(Path(__file__)),
        'source_account': account_ref, 'input_ref': input_ref,
        'calendar_content_sha256': value['data']['sessions']['content_sha256'],
        'complete543_session_grid_verified': True, 'eligible_observations': len(rows), 'training_sessions': 502,
        'populations': {g: {'raw_daily_first': sum(r[g] for r in rows),
            'all_predicate_matches': sum(r['raw_' + g] for r in rows),
            'years': dict(Counter(r['session_date'][:4] for r in rows if r[g]))} for g in GROUPS},
        'overlaps': {a + '&' + b: sum(r[a] and r[b] for r in rows) for a in GROUPS for b in GROUPS},
        'feature_rows': rows, 'new_future_labels_or_group_returns': 0,
        'new_account_compute': 0, 'new_data_downloads': 0, 'sealed_2026_access': False}
    save(WORK / 'others/features.json', out)
    print('SESSION_RANGE_FEATURES_PASS', out['populations'], flush=True)


if __name__ == '__main__':
    main()
