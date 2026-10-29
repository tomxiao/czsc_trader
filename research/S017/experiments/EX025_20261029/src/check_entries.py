"""Synthetic contract checks for the S017-M005 factor ablation."""

import numpy as np
import pandas as pd

from ablation_entries import FACTOR_NAMES, NEW_NAMES, REQUIRED, flags


def sample():
    return {'close': 102., 'previous_close': 99., 'previous_open': 100.,
            'previous_high': 101., 'prior_volume': 150.,
            'same_slot_volume_median20': 100., 'previous_tr1': 2.,
            'atr_before_prior': 2.}


def rejected(facts):
    try:
        flags(facts)
    except ValueError:
        return
    raise AssertionError('Invalid facts must be rejected')


def run():
    checks = []
    assert NEW_NAMES == ('S017-M006', 'S017-M007', 'S017-M008')
    assert FACTOR_NAMES == ('S017-M005', *NEW_NAMES)
    assert list(flags(sample())) == list(FACTOR_NAMES)
    assert all(flags(sample()).values())  # Inclusive volume/range equalities.
    for field, value in [('previous_close', 100.), ('close', 101.),
                         ('previous_close', 100.1), ('close', 100.9)]:
        facts = sample()
        facts[field] = value
        assert not any(flags(facts).values())
    checks.append('numbered_contract_strict_base_inclusive_factor_boundaries')

    rows = []
    for previous_close in (99., 100., 101.):
        for close in (100., 101., 102.):
            for volume in (149.99, 150., 150.01):
                for previous_tr in (1.99, 2., 2.01):
                    facts = sample()
                    facts.update(previous_close=previous_close, close=close,
                                 prior_volume=volume, previous_tr1=previous_tr)
                    result = flags(facts)
                    base = previous_close < 100. and close > 101.
                    volume_pass = volume >= 150.
                    narrow_pass = previous_tr <= 2.
                    assert result == {
                        'S017-M005': base and volume_pass and narrow_pass,
                        'S017-M006': base,
                        'S017-M007': base and narrow_pass,
                        'S017-M008': base and volume_pass,
                    }
                    rows.append(facts)
    result = flags(pd.DataFrame(rows))
    assert np.array_equal(result['S017-M005'], result['S017-M007'] & result['S017-M008'])
    for number in ('S017-M005', 'S017-M007', 'S017-M008'):
        assert not (result[number] & ~result['S017-M006']).any()
    checks.append('four_factor_groups_truth_table_intersection_and_nesting')

    for field in REQUIRED:
        facts = sample()
        del facts[field]
        rejected(facts)
        for invalid in (None, float('nan'), float('inf'), -float('inf'), '100', True):
            facts = sample()
            facts[field] = invalid
            rejected(facts)
        facts = sample()
        facts[field] = -1.
        rejected(facts)
    for field in ('close', 'previous_close', 'previous_open', 'previous_high',
                  'atr_before_prior'):
        facts = sample()
        facts[field] = 0.
        rejected(facts)
    for field in ('prior_volume', 'same_slot_volume_median20', 'previous_tr1'):
        facts = sample()
        facts[field] = 0.
        flags(facts)
    facts = sample()
    facts['close'] = [102., 102.]
    rejected(facts)
    checks.append('missing_nonfinite_nonnumeric_negative_and_shape_rejected')

    frame = pd.DataFrame(rows)
    expected = flags(frame.iloc[:30])
    altered = frame.copy()
    altered.loc[30:, list(REQUIRED)] = 1.
    altered['future_close'] = np.arange(len(altered)) * 1_000_000.
    altered['irrelevant'] = None
    actual = flags(altered)
    for number in FACTOR_NAMES:
        assert np.array_equal(expected[number], actual[number][:30])
    facts = sample()
    expected = flags(facts)
    facts.update(future_close=-float('inf'), irrelevant=None)
    assert flags(facts) == expected
    checks.append('future_rows_and_unrelated_fields_do_not_change_prior_flags')
    return checks


if __name__ == '__main__':
    print({'status': 'PASS', 'checks': run()}, flush=True)
