"""Fixed temporal diagnostics and prior-only selection of six-bar event labels.

These are event statistics, never a synthesized account. A signal is retained
before its result is inspected. Return availability is evaluated separately at
each window end; training never uses an exit on or after the next test date.
"""

from collections import Counter, defaultdict
from datetime import date, datetime
from math import isfinite
from statistics import mean, median
from zoneinfo import ZoneInfo


HORIZON = 6
TRAIN_SESSIONS = 252
TEST_SESSIONS = 63
NEW_YORK = ZoneInfo('America/New_York')


def _exit_day(row):
    value = row['exit_at']
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('exit_at must be a timezone-aware ISO timestamp or None')
    instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('exit_at must carry a timezone')
    return instant.astimezone(NEW_YORK).date().isoformat()


def _validate(rows, days, names):
    if (not isinstance(days, list) or not days
            or any(not isinstance(day, str) for day in days)
            or days != sorted(set(days))):
        raise ValueError('days must be unique chronological ISO session dates')
    for day in days:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError('days must use canonical ISO dates')
    if (not names or len(names) != len(set(names))
            or any(not isinstance(name, str) or not name for name in names)):
        raise ValueError('mechanism names must be unique nonempty strings')
    if not isinstance(rows, list):
        raise ValueError('rows must be a list of label records')
    primary, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('each label must be a dictionary')
        if type(row['i']) is not int or row['i'] < 0 or type(row['n']) is not int or row['n'] <= 0:
            raise ValueError('i and n require nonnegative/positive integers')
        key = row['i'], row['n']
        if key in seen:
            raise ValueError('duplicate event/horizon label')
        seen.add(key)
        if row['n'] != HORIZON:
            continue
        index = row['day_index']
        if (type(index) is not int or not 0 <= index < len(days)
                or row['date'] != days[index] or row['month'] != row['date'][:7]):
            raise ValueError('label session identity differs from days')
        if (not isinstance(row['stratum'], str) or not row['stratum']
                or not isinstance(row['regime'], str) or not row['regime']):
            raise ValueError('stratum and regime require explicit nonempty labels')
        signals = row['signals']
        if (not isinstance(signals, list) or len(signals) != len(set(signals))
                or any(not isinstance(signal, str) for signal in signals)):
            raise ValueError('signals must contain unique mechanism identities')
        if not isinstance(row['status'], str) or not row['status']:
            raise ValueError('label status must be explicit')
        value, exit_day = row['price_net_return'], _exit_day(row)
        if row['status'] == 'COMPLETE':
            if (type(value) not in (int, float) or not isfinite(value)
                    or value < -1 or exit_day is None):
                raise ValueError('COMPLETE requires a finite net return and exit')
        elif value is not None:
            raise ValueError('incomplete label cannot carry a realized return')
        if exit_day is not None and exit_day < row['date']:
            raise ValueError('exit precedes event entry session')
        primary.append(dict(row, _exit_day=exit_day))
    primary.sort(key=lambda item: item['i'])
    if not primary:
        raise ValueError('six-bar primary labels are required')
    if any(a['day_index'] > b['day_index'] for a, b in zip(primary, primary[1:])):
        raise ValueError('event indices and session dates are not chronological')
    return primary


def _sparse(rows, last=None):
    selected = []
    for row in rows:
        if last is None or row['i'] > last + HORIZON + 1:
            selected.append(row)
            last = row['i']
    return selected, last


def _mature(row, cutoff):
    return row['status'] == 'COMPLETE' and row['_exit_day'] <= cutoff


def _stats(values):
    if not values:
        return {'count': 0, 'mean': None, 'median': None, 'win_rate': None,
                'minimum': None, 'maximum': None}
    return {'count': len(values), 'mean': mean(values), 'median': median(values),
            'win_rate': sum(value > 0 for value in values) / len(values),
            'minimum': min(values), 'maximum': max(values)}


def _comparison(control, targets, name, cutoff):
    # Same-month/time-slot controls exclude this mechanism, not other mechanisms.
    controls = [row for row in control if name not in row['signals'] and _mature(row, cutoff)]
    groups = defaultdict(list)
    for row in controls:
        groups[row['stratum']].append(row['price_net_return'])
    means = {key: mean(values) for key, values in groups.items()}
    complete = [row for row in targets if _mature(row, cutoff)]
    supported = [row for row in complete if row['stratum'] in means]
    unique_cells = sorted({row['stratum'] for row in supported})
    later = [row for row in targets if row['status'] == 'COMPLETE' and not _mature(row, cutoff)]
    return {
        'trigger_count': len(targets),
        'trigger_days': len({row['date'] for row in targets}),
        'status_counts': dict(sorted(Counter(row['status'] for row in targets).items())),
        'mature_complete_count': len(complete),
        'complete_after_cutoff_count': len(later),
        'incomplete_count': len(targets) - len(complete) - len(later),
        'net_return': _stats([row['price_net_return'] for row in complete]),
        'matched': {
            'supported_target_count': len(supported),
            'unsupported_target_count': len(complete) - len(supported),
            'support_fraction': len(supported) / len(complete) if complete else None,
            'mature_control_count': len(controls),
            'supported_cell_count': len(unique_cells),
            'control_counts_by_supported_cell': {key: len(groups[key]) for key in unique_cells},
            'supported_target_net_return': _stats([row['price_net_return'] for row in supported]),
            'target_weighted_control_mean': mean([means[row['stratum']] for row in supported]) if supported else None,
            'increment': _stats([row['price_net_return'] - means[row['stratum']] for row in supported]),
        },
    }


def _mechanism_summary(control, name, cutoff):
    targets = [row for row in control if name in row['signals']]
    reduced, _ = _sparse(targets)
    return {'raw': _comparison(control, targets, name, cutoff),
            'nonoverlap': _comparison(control, reduced, name, cutoff)}


def _window(primary, days, names, start, stop):
    population = [row for row in primary if start <= row['day_index'] < stop]
    return {'start_day_index': start, 'stop_day_index_exclusive': stop,
            'start': days[start], 'end': days[stop - 1], 'sessions': stop - start,
            'cutoff_exit_date_inclusive': days[stop - 1],
            'mechanisms': {name: _mechanism_summary(population, name, days[stop - 1]) for name in names}}


def _sequential(primary, days, names, selection_names):
    folds, pooled, pooled_controls, last = [], [], [], None
    for test_start in range(TRAIN_SESSIONS, len(days), TEST_SESSIONS):
        test_stop = min(test_start + TEST_SESSIONS, len(days))
        train_start = test_start - TRAIN_SESSIONS
        train = [row for row in primary if train_start <= row['day_index'] < test_start]
        test = [row for row in primary if test_start <= row['day_index'] < test_stop]
        training = {name: _mechanism_summary(train, name, days[test_start - 1]) for name in names}
        eligible = []
        for name in selection_names:
            item = training[name]['nonoverlap']
            own, delta = item['net_return']['mean'], item['matched']['increment']['mean']
            if own is not None and delta is not None and own > 0 and delta > 0:
                eligible.append((name, delta))
        choice = min(eligible, key=lambda item: (-item[1], item[0]))[0] if eligible else None
        prior_last = last
        chosen, last = _sparse([row for row in test if choice in row['signals']], last) if choice else ([], last)
        comparison = _comparison(test, chosen, choice, days[test_stop - 1]) if choice else None
        # Matured test events only are pooled; censored and failed events remain
        # visible in each fold. Selection never considers the future test labels.
        fold_events = []
        for row in chosen:
            record = {'i': row['i'], 'date': row['date'], 'exit_at': row['exit_at'],
                      'mechanism': choice, 'status': row['status'],
                      'mature_at_fold_end': _mature(row, days[test_stop - 1]),
                      'net_return': row['price_net_return'] if _mature(row, days[test_stop - 1]) else None}
            pooled.append(record)
            fold_events.append(record)
        if comparison:
            pooled_controls.append(comparison)
        folds.append({
            'train_start': days[train_start], 'train_end': days[test_start - 1],
            'test_start': days[test_start], 'test_end': days[test_stop - 1],
            'test_sessions': test_stop - test_start, 'full_test_fold': test_stop - test_start == TEST_SESSIONS,
            'training_exit_must_precede': days[test_start], 'training': training,
            'choice': choice, 'eligible_training_scores': {name: score for name, score in eligible},
            'previous_test_selected_i': prior_last, 'last_test_selected_i': last,
            'test_summary': comparison, 'test_events': fold_events,
        })
    values = [record['net_return'] for record in pooled if record['net_return'] is not None]
    matched_count = sum(item['matched']['supported_target_count'] for item in pooled_controls)
    weighted_delta = sum(item['matched']['supported_target_count'] * item['matched']['increment']['mean']
                         for item in pooled_controls if item['matched']['supported_target_count'])
    return {
        'training_sessions': TRAIN_SESSIONS, 'test_sessions': TEST_SESSIONS,
        'selection_mechanisms': list(selection_names),
        'selection': 'positive training nonoverlap net mean and supported matched increment; highest increment; mechanism id tie',
        'training_zero_or_no_support': 'no eligible choice, no test events',
        'test_maturity': 'exit local date no later than its own fold end; later exits censored',
        'cross_fold_nonoverlap': 'i > last selected i + 6 + 1; last never resets on mechanism changes or missing choices',
        'folds': folds,
        'pooled': {'selected_events': len(pooled), 'mature_events': len(values),
                   'not_mature_or_incomplete_events': len(pooled) - len(values),
                   'net_return': _stats(values), 'matched_supported_events': matched_count,
                   'matched_increment_mean': weighted_delta / matched_count if matched_count else None,
                   'events': pooled},
        'interpretation': 'prior-only event selection within repeatedly seen development data; not an account or independent validation',
    }


def analyze_temporal(rows, days, names, selection_names=None):
    """Return JSON-compatible six-bar rolling, regime and sequential evidence."""
    names = tuple(names)
    primary = _validate(rows, days, names)
    selection_names = names if selection_names is None else tuple(selection_names)
    if (not selection_names or len(selection_names) != len(set(selection_names))
            or not set(selection_names) <= set(names)):
        raise ValueError('selection_names must be a nonempty unique subset of names')
    if len(days) <= TRAIN_SESSIONS:
        raise ValueError('more than 252 sessions are required for prior-only test folds')
    rolling = [_window(primary, days, names, start, start + TRAIN_SESSIONS)
               for start in range(0, len(days) - TRAIN_SESSIONS + 1, TEST_SESSIONS)]
    annual, regime_years = {}, {}
    regimes = sorted({row['regime'] for row in primary})
    for year in sorted({day[:4] for day in days}):
        indices = [index for index, day in enumerate(days) if day.startswith(year)]
        annual[year] = _window(primary, days, names, indices[0], indices[-1] + 1)
        population = [row for row in primary if row['date'].startswith(year)]
        cutoff = days[indices[-1]]
        regime_years[year] = {
            regime: {name: _mechanism_summary([row for row in population if row['regime'] == regime], name, cutoff)
                     for name in names}
            for regime in regimes
        }
    split = len(days) - TRAIN_SESSIONS
    return {
        'schema': 's017-temporal-events/v1', 'primary_horizon': HORIZON,
        'rolling_window_sessions': TRAIN_SESSIONS, 'rolling_step_sessions': TEST_SESSIONS,
        'maturity': 'completed exits converted to America/New_York dates and cut off at each local window end',
        'matching': 'same supplied month/local-slot stratum, exclude target mechanism; regime slices also fix regime',
        'nonoverlap': 'preselect trigger indices before inspecting results; next i strictly > previous i + 6 + 1',
        'rolling': rolling, 'years': annual,
        'last252_vs_earlier': {'earlier': _window(primary, days, names, 0, split),
                               'last252': _window(primary, days, names, split, len(days))},
        'regimes': {regime: {name: _mechanism_summary([row for row in primary if row['regime'] == regime], name, days[-1])
                            for name in names} for regime in regimes},
        'regime_years': regime_years, 'sequential': _sequential(primary, days, names, selection_names),
        'limitations': ['Overlapping windows are not independent repetitions.',
                       'Same-regime differences describe associations, not causal regime or decay attribution.',
                       'Signal selection and repeated development use do not restore independent validation.',
                       'Event selection is not an executable continuous account and cannot establish account frequency or goals.'],
    }
