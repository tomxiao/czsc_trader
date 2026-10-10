"""Predeclared fixed-center120 strict-past ACF baseline, one step only."""
from dataclasses import replace
import numpy as np
from transition import step, state_dict


def covariance(items):
    centered = items - items.mean()
    variance = np.mean(centered ** 2)
    return np.nan if np.isclose(variance, 0) else float(
        np.dot(centered[1:], centered[:-1]) / 19 / variance)


def fixed_values(bars, dates, certified_raw):
    full_acf = bars.Close.astype(float).pct_change(fill_method=None).rolling(20).apply(covariance, raw=True)
    raw = full_acf.reindex(dates)
    np.testing.assert_array_equal(raw.to_numpy(), certified_raw)
    baseline = full_acf.where(np.isfinite(full_acf.to_numpy())).shift(1).rolling(120, min_periods=120).mean().reindex(dates)
    values = raw - baseline
    assert np.isfinite(values.to_numpy()).all(), 'No baseline fill or shorter warmup'
    return tuple(float(value) for value in values)


def diagnose_probe(own, values):
    assert len(values) == len(own.features)
    rows = []
    for i, (feature, before, actual, value) in enumerate(zip(own.features, own.before, own.decisions, values, strict=True)):
        altered = step(own.kind, before, replace(feature, bear_acf_value=value))
        rows.append({'index': i, 'signal_date': own.signal_dates[i], 'execution_date': own.execution_dates[i],
            'native_bear_acf': feature.bear_acf_value, 'fixed120_bear_acf': value,
            'target_different': actual.target != altered.target,
            'target_reason_different': actual.outcome('target_reason') != altered.outcome('target_reason'),
            'next_state_different': actual.next_state != altered.next_state,
            'actual': {'target': actual.target, 'reason': actual.reason, 'next_state': state_dict(actual.next_state)},
            'probe': {'target': altered.target, 'reason': altered.reason, 'next_state': state_dict(altered.next_state)}})
    def summary(selected):
        return {'days': len(selected), **{key: sum(row[key] for row in selected) for key in
            ('target_different', 'target_reason_different', 'next_state_different')}}
    partitions = {'signal_year': {'ALL': summary(rows)}, 'execution_year': {'ALL': summary(rows)}}
    for year in sorted({row['signal_date'][:4] for row in rows}):
        partitions['signal_year'][year] = summary([row for row in rows if row['signal_date'][:4] == year])
    for year in sorted({row['execution_date'][:4] for row in rows if row['execution_date'] is not None}):
        partitions['execution_year'][year] = summary([row for row in rows if row['execution_date'] is not None and row['execution_date'][:4] == year])
    partitions['execution_year']['NONE'] = summary([row for row in rows if row['execution_date'] is None])
    for mapping in partitions.values():
        for key in mapping['ALL']:
            assert sum(row[key] for label, row in mapping.items() if label != 'ALL') == mapping['ALL'][key]
    return {'status': 'PASS', 'all_days': rows, 'partitions': partitions,
        'all_next_states_identical': not any(row['next_state_different'] for row in rows),
        'limits': 'Fixed120 comes from original center L. Actual confirmation L remains active for all score components; no coordinate removed. Only one current-step bear ACF changes on each own observed state. No alternate path/cash/equity/return replay. Identical every-step next state implies identical target/state path by induction only within these exact finite inputs. Final-reason path additionally requires zero target_reason_different; changed steps do not predict profit.'}
