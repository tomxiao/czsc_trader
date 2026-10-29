"""Fixed S017-M005 factor ablation using already certified entry facts."""

import numpy as np

NEW_NAMES = ('S017-M006', 'S017-M007', 'S017-M008')
FACTOR_NAMES = ('S017-M005', *NEW_NAMES)
REQUIRED = ('close', 'previous_close', 'previous_open', 'previous_high',
            'prior_volume', 'same_slot_volume_median20', 'previous_tr1',
            'atr_before_prior')


def flags(facts):
    """Return four numbered flags; invalid required observations are rejected.

    Accept a mapping of numeric scalars or equally shaped arrays, including a
    DataFrame. Scalar inputs return bools; array inputs return boolean arrays.
    Extra fields are ignored and no future observations are consulted.
    """
    values = {}
    for name in REQUIRED:
        try:
            value = np.asarray(facts[name])
        except (KeyError, TypeError) as exc:
            raise ValueError(f'Missing required fact: {name}') from exc
        if value.dtype.kind not in 'iuf' or not np.isfinite(value).all():
            raise ValueError(f'Require finite numeric fact: {name}')
        values[name] = value
    if len({value.shape for value in values.values()}) != 1:
        raise ValueError('Required facts must have identical shapes')
    for name in ('close', 'previous_close', 'previous_open', 'previous_high',
                 'atr_before_prior'):
        if (values[name] <= 0).any():
            raise ValueError(f'Require positive fact: {name}')
    for name in ('prior_volume', 'same_slot_volume_median20', 'previous_tr1'):
        if (values[name] < 0).any():
            raise ValueError(f'Require nonnegative fact: {name}')
    base = ((values['previous_close'] < values['previous_open'])
            & (values['close'] > values['previous_high']))
    volume = values['prior_volume'] >= 1.5 * values['same_slot_volume_median20']
    narrow = values['previous_tr1'] <= values['atr_before_prior']
    result = {
        'S017-M005': base & volume & narrow,
        'S017-M006': base,
        'S017-M007': base & narrow,
        'S017-M008': base & volume,
    }
    return {name: bool(value) if value.ndim == 0 else value
            for name, value in result.items()}
