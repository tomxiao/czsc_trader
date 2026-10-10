"""Descriptive one-step input/state contrasts, with no account replay or returns."""
from transition import Trace, state_dict, step


CATEGORIES = ('equal', 'input_only', 'state_only', 'either_sufficient',
              'joint_interaction', 'cancellation')
OUTCOMES = ('target', 'target_reason')
STATE_GROUPS = ('physical_equal_decision_equal', 'physical_equal_decision_different',
                'physical_different_decision_equal', 'physical_different_decision_different')


def classify(a, b, c, d):
    """A=Fc(Sc), B=Fp(Sc), C=Fc(Sp), D=Fp(Sp); exhaustive for multivalued outcomes."""
    if a == d:
        return 'equal' if b == a and c == a else 'cancellation'
    if b == d and c == d:
        return 'either_sufficient'
    if b == d:
        return 'input_only'
    if c == d:
        return 'state_only'
    return 'joint_interaction'


def _aligned(center, point, same_kind):
    if not isinstance(center, Trace) or not isinstance(point, Trace):
        raise TypeError('typed certified Trace required')
    if same_kind and center.kind != point.kind:
        raise ValueError('mixed mechanisms cannot receive one-step mixed-state predictions')
    if center.signal_dates != point.signal_dates or center.execution_dates != point.execution_dates:
        raise ValueError('complete aligned signal and execution dates required')
    for own in (center, point):
        size = len(own.features)
        if not size or any(len(values) != size for values in
                           (own.before, own.after, own.decisions, own.signal_dates, own.execution_dates)):
            raise ValueError('complete nonempty trace required')
        for i, (feature, before, after, decision) in enumerate(zip(
                own.features, own.before, own.after, own.decisions, strict=True)):
            if step(own.kind, before, feature) != decision or decision.next_state != after:
                raise ValueError('own trace transition mismatch')
            if i and own.before[i] != own.after[i - 1]:
                raise ValueError('own trace continuity mismatch')


def _runs(rows, key):
    """All contiguous segments, including unchanged runs and the final open endpoint."""
    result = []
    for row in rows:
        value = row[key]
        if not result or result[-1]['value'] != value:
            result.append({'value': value, 'first_index': row['index'], 'last_index': row['index'],
                'length': 1, 'first_signal_date': row['signal_date'], 'last_signal_date': row['signal_date'],
                'first_execution_date': row['execution_date'], 'last_execution_date': row['execution_date']})
        else:
            result[-1].update(last_index=row['index'], length=result[-1]['length'] + 1,
                last_signal_date=row['signal_date'], last_execution_date=row['execution_date'])
    assert sum(row['length'] for row in result) == len(rows)
    return result


def _first(rows, difference_key):
    first = next((row for row in rows if row[difference_key]), None)
    return None if first is None else {'index': first['index'], 'signal_date': first['signal_date'],
                                      'execution_date': first['execution_date']}


def _summary(rows, label_key=None, difference_key=None, categories=CATEGORIES):
    result = {'days': len(rows)}
    if label_key is not None:
        result['counts'] = {category: sum(row[label_key] == category for row in rows) for category in categories}
        assert sum(result['counts'].values()) == len(rows)
    if difference_key is not None:
        result['actual_difference_days'] = sum(row[difference_key] for row in rows)
        result['first_actual_divergence'] = _first(rows, difference_key)
    return result


def _partitions(rows, label_key=None, difference_key=None, categories=CATEGORIES):
    signal_years = sorted({row['signal_date'][:4] for row in rows})
    execution_years = sorted({row['execution_date'][:4] for row in rows if row['execution_date'] is not None})
    signal = {'ALL': _summary(rows, label_key, difference_key, categories)}
    execution = {'ALL': _summary(rows, label_key, difference_key, categories)}
    for year in signal_years:
        signal[year] = _summary([row for row in rows if row['signal_date'][:4] == year], label_key, difference_key, categories)
    for year in execution_years:
        execution[year] = _summary([row for row in rows if row['execution_date'] is not None
                                   and row['execution_date'][:4] == year], label_key, difference_key, categories)
    execution['NONE'] = _summary([row for row in rows if row['execution_date'] is None], label_key, difference_key, categories)
    assert sum(row['days'] for year, row in signal.items() if year != 'ALL') == len(rows)
    assert sum(row['days'] for year, row in execution.items() if year != 'ALL') == len(rows)
    if label_key is not None:
        for category in categories:
            for mapping in (signal, execution):
                assert sum(row['counts'][category] for year, row in mapping.items() if year != 'ALL') == mapping['ALL']['counts'][category]
    return {'signal_year': signal, 'execution_year': execution}


def compare_same_kind(center: Trace, point: Trace):
    """Compare all days of one mechanism's center/point; cross predictions are single-step only."""
    _aligned(center, point, same_kind=True)
    rows = []
    for i, (fc, fp, sc, sp, ac, ap) in enumerate(zip(center.features, point.features,
            center.before, point.before, center.decisions, point.decisions, strict=True)):
        a = step(center.kind, sc, fc)
        b = step(center.kind, sc, fp)
        c = step(center.kind, sp, fc)
        d = step(center.kind, sp, fp)
        assert a == ac and d == ap
        row = {'index': i, 'signal_date': center.signal_dates[i], 'execution_date': center.execution_dates[i],
            'center_state_before': state_dict(sc), 'point_state_before': state_dict(sp),
            'input_features_different': fc != fp, 'decision_state_different': sc != sp,
            'physical_state_different': sc.physical != sp.physical,
            'memory_only_state_difference': sc.physical == sp.physical and sc != sp,
            'state_group': ('physical_different_' if sc.physical != sp.physical else 'physical_equal_')
                           + ('decision_different' if sc != sp else 'decision_equal'),
            'four_decisions': {label: {'target': decision.target, 'reason': decision.reason}
                               for label, decision in zip(('A', 'B', 'C', 'D'), (a, b, c, d), strict=True)}}
        for outcome in OUTCOMES:
            values = [decision.outcome(outcome) for decision in (a, b, c, d)]
            row[outcome + '_category'] = classify(*values)
            row[outcome + '_actual_difference'] = values[0] != values[3]
        rows.append(row)
    outcome_summaries = {}
    for outcome in OUTCOMES:
        label_key, difference_key = outcome + '_category', outcome + '_actual_difference'
        outcome_summaries[outcome] = {
            'partitions': _partitions(rows, label_key, difference_key),
            'classification_runs': _runs(rows, label_key),
            'actual_difference_runs': _runs(rows, difference_key),
            'first_actual_divergence': _first(rows, difference_key)}
    return {'status': 'PASS', 'kind': center.kind.value, 'days': len(rows), 'all_days': rows,
        'outcomes': outcome_summaries,
        'state_propagation': {
            'partitions': _partitions(rows, 'state_group', 'memory_only_state_difference', STATE_GROUPS),
            'state_group_runs': _runs(rows, 'state_group'),
            'memory_only_runs': _runs(rows, 'memory_only_state_difference')},
        'tail_states': {'center': state_dict(center.tail_state), 'point': state_dict(point.tail_state)},
        'definitions': {'A': 'center features / center state', 'B': 'point features / center state',
            'C': 'center features / point state', 'D': 'point features / point state',
            'equal': 'All four outcomes identical',
            'cancellation': 'Actual A=D but at least one mixed outcome differs',
            'input_only': 'A differs from D, B=D and C differs from D',
            'state_only': 'A differs from D, C=D and B differs from D',
            'either_sufficient': 'A differs from D and B=C=D',
            'joint_interaction': 'A differs from D, neither B nor C equals D; includes multivalued residuals'},
        'limits': 'One-step logical sufficiency on certified endogenous signal states only. Combined original13 perturbations, not single-coordinate causes. B/C next states are not propagated; no new holding path, order, cash, fees, profit counterfactual or independent market sample.'}


def cross_actual(original: Trace, new: Trace):
    """Same-coordinate mechanisms' observed decisions/physical states; no cross-kind step prediction."""
    _aligned(original, new, same_kind=False)
    rows = []
    for i, (a, d, sa, sd) in enumerate(zip(original.decisions, new.decisions,
                                           original.before, new.before, strict=True)):
        rows.append({'index': i, 'signal_date': original.signal_dates[i], 'execution_date': original.execution_dates[i],
            'original': {'target': a.target, 'reason': a.reason}, 'new': {'target': d.target, 'reason': d.reason},
            'original_physical_state': list(sa.physical), 'new_physical_state': list(sd.physical),
            'target_difference': a.target != d.target,
            'target_reason_difference': a.outcome('target_reason') != d.outcome('target_reason'),
            'physical_state_difference': sa.physical != sd.physical})
    summaries = {name: {'partitions': _partitions(rows, difference_key=name),
                        'difference_runs': _runs(rows, name), 'first_actual_divergence': _first(rows, name)}
                 for name in ('target_difference', 'target_reason_difference', 'physical_state_difference')}
    return {'status': 'PASS', 'days': len(rows), 'original_kind': original.kind.value, 'new_kind': new.kind.value,
        'all_days': rows, 'summaries': summaries,
        'tail_states': {'original': state_dict(original.tail_state), 'new': state_dict(new.tail_state)},
        'limits': 'Only observed same-coordinate targets/final reasons and physical holding/route/age differ. Mechanism-specific anchor/exit memory excluded from physical equality. No mixed-kind state prediction, cash replay, profit or categorical causal inference.'}
