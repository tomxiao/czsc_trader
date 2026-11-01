"""Outcome-blind planned-session opening features; never open return labels."""
from collections import Counter
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path

from common import WORK, account_input, digest, save


def at(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def predicates(prior_close, opening, low, close, atr):
    g0 = low > prior_close
    g1 = g0 and close > opening
    old = opening >= prior_close + atr and close > opening
    return {'G0': g0, 'G1': g1, 'OLD_M025': old, 'G0_WITHOUT_G1': g0 and not g1,
        'G1_NEW_NOT_M025': g1 and not old}


def derive(bars, sessions):
    times = [at(row['Date']) for row in bars]
    if times != sorted(times) or len(set(times)) != len(times):
        raise ValueError('Unique chronological bars required')
    by_time = {value: i for i, value in enumerate(times)}
    tr = [None]
    for j in range(1, len(bars)):
        b, p = bars[j], bars[j - 1]
        tr.append(max(b['High'] - b['Low'], abs(b['High'] - p['Close']), abs(b['Low'] - p['Close'])))
    sessions = sorted(sessions, key=lambda x: x['session_date'])
    if len({s['session_date'] for s in sessions}) != len(sessions):
        raise ValueError('Unique calendar sessions required')
    rows = []
    for j, session in enumerate(sessions):
        if not '2024-01-02' <= session['session_date'] <= '2025-12-31':
            continue
        if j == 0 or session['timezone'] != 'America/New_York':
            raise ValueError('Prior planned RTH session and NY timezone required')
        start = at(session['segments'][0]['start'])
        first_end = start + timedelta(minutes=30)
        if first_end > at(session['segments'][0]['end']) or first_end not in by_time:
            raise ValueError('First planned complete M30 bar missing')
        i = by_time[first_end]
        prior_end = at(sessions[j - 1]['segments'][-1]['end'])
        if i < 14 or at(bars[i]['BarStart']) != start or times[i - 1] != prior_end:
            raise ValueError('Observed prior bar is not the prior planned RTH close')
        b, p = bars[i], bars[i - 1]
        o, h, l, c, prior = map(float, (b['Open'], b['High'], b['Low'], b['Close'], p['Close']))
        if not all(isfinite(v) and v > 0 for v in (o, h, l, c, prior)) or not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError('Valid positive OHLC required')
        atr = sum(tr[i - 13:i]) / 13
        if atr < 0 or not isfinite(atr):
            raise ValueError('Defined nonnegative prior simple ATR required')
        rows.append({'session_date': session['session_date'], 'signal_at': b['Date'],
            'bar_index': i, 'BarStart': b['BarStart'], 'prior_session_date': sessions[j - 1]['session_date'],
            'prior_planned_close_at': prior_end.isoformat(), 'prior_observed_at': p['Date'],
            'prior_close': prior, 'open': o, 'high': h, 'low': l, 'close': c,
            'prior_atr13': atr, 'gap_fraction': o / prior - 1,
            'first_bar_progress_fraction': c / o - 1,
            **predicates(prior, o, l, c, atr)})
    if len(rows) != 502 or len({r['signal_at'] for r in rows}) != 502:
        raise ValueError('All 502 training session openings required')
    return rows


def main():
    value, account_ref, input_ref = account_input()
    bars = value['products']['bars']
    metadata = value['data']['sessions']['metadata']
    sessions = metadata['sessions']
    if len(sessions) != 543:
        raise ValueError('Approved 543-session calendar required')
    rows = derive(bars, sessions)
    groups = ('G0', 'G1', 'OLD_M025', 'G0_WITHOUT_G1', 'G1_NEW_NOT_M025')
    save(WORK / 'others/features.json', {
        'status': 'PASS_OUTCOME_BLIND_OPENING_FEATURES', 'source_sha256': digest(Path(__file__)),
        'source_account': account_ref, 'input_ref': input_ref,
        'calendar_content_sha256': value['data']['sessions']['content_sha256'],
        'calendar_publication_time_verified': metadata.get('publication_time_verified'),
        'training_openings': len(rows), 'all_first_bars_and_prior_planned_session_ends_verified': True,
        'populations': {g: {'raw': sum(r[g] for r in rows),
            'years': dict(Counter(r['session_date'][:4] for r in rows if r[g]))} for g in groups},
        'overlaps': {a + '&' + b: sum(r[a] and r[b] for r in rows) for a in groups for b in groups},
        'feature_rows': rows, 'new_future_labels_or_group_returns': 0,
        'new_account_compute': 0, 'new_data_downloads': 0, 'sealed_2026_access': False})
    print('OPENING_FEATURES_PASS', {g: sum(r[g] for r in rows) for g in groups}, flush=True)


if __name__ == '__main__':
    main()
