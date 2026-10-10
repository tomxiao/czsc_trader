"""Pure EX039 direction/method/oracle checks; do not read retained accounts."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
import direction_diagnosis as diagnosis


def strategy_module(source, name):
    package = ModuleType(name)
    package.__path__ = [str(source / 'strategies')]
    sys.modules[name] = package
    spec = importlib.util.spec_from_file_location(name + '.acf_range', source / 'strategies/acf_range.py')
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def main():
    counts = {'direction_partitions': 0, 'invalid_prices': 0, 'group_total_checks': 0,
              'date_contract_rejections': 0, 'extra_native_synthetic_rows': 0,
              'strict_JSON_rejections': 0, 'method_guard_checks': 0, 'frozen_auditors_loaded': 0}
    auditors = diagnosis.load_original_oracle()
    assert len(auditors) == 4 and all(callable(auditor) for auditor in auditors)
    counts['frozen_auditors_loaded'] = 4
    rows, dates = [], []
    for year in range(2019, 2027):
        for i, (close_delta, body_delta) in enumerate(((-1., -1.), (0., 0.), (1., 1.),
                                                       (1., -1.), (-1., 1.))):
            dates.append(pd.Timestamp(year, 1, i + 2))
            close = 10.
            direction = diagnosis.direction_fields([close], [close - body_delta], [close - close_delta])
            row = {name: value[0] for name, value in direction.items()}
            row.update(raw_route='bull' if i % 2 == 0 else 'bear', opportunity=i != 3,
                       entry=i in (0, 2), score_pass=i != 1)
            rows.append(row)
    values = pd.DataFrame(rows, index=pd.DatetimeIndex(dates))
    diagnosis.validate_days(values, dates)
    counts['direction_partitions'] = len(values) * 2
    statistics = diagnosis.direction_statistics(values)
    assert len(statistics) == 9 * 2 * 2
    assert {row['year'] for row in statistics} == {'ALL', *(str(year) for year in range(2019, 2027))}
    for selected in ('opportunity', 'entry'):
        assert sum(row['count'] for row in statistics if row['year'] == 'ALL' and row['set'] == selected) == int(values[selected].sum())
        assert sum(row['count'] for row in statistics if row['year'] != 'ALL' and row['set'] == selected) == int(values[selected].sum())
        counts['group_total_checks'] += 2
    # All groups, including empty bear entries, stay explicit and zero-counted.
    assert all(row['count'] == 0 for row in statistics if row['route'] == 'bear' and row['set'] == 'entry')
    for column in range(3):
        for invalid in (0., -1., np.nan, np.inf, -np.inf):
            prices = [[10.], [10.], [10.]]
            prices[column] = [invalid]
            try:
                diagnosis.direction_fields(*prices)
            except ValueError:
                counts['invalid_prices'] += 1
            else:
                raise AssertionError('Invalid signal direction accepted')
    for bad in (values.iloc[::-1], values.iloc[1:], pd.concat([values.iloc[:1], values])):
        try:
            diagnosis.validate_days(bad, dates)
        except ValueError:
            counts['date_contract_rejections'] += 1
        else:
            raise AssertionError('Reordered/selected/duplicated native dates accepted')
    for invalid in (np.nan, np.inf, -np.inf):
        try:
            diagnosis.json_standard({'rows': [{'price': invalid}]})
        except ValueError:
            counts['strict_JSON_rejections'] += 1
        else:
            raise AssertionError('nonfinite output accepted')
    assert diagnosis.json_standard({'route_before': None}) == {'route_before': None}
    # No method declaration: fail before context/cache/data access.
    with patch.object(Path, 'is_file', return_value=False), patch.object(diagnosis, 'context', side_effect=RuntimeError('forbidden')), patch.object(diagnosis, 'cache_read', side_effect=RuntimeError('forbidden')):
        try:
            diagnosis.main()
        except AssertionError as error:
            assert 'Declare EX039' in str(error)
            counts['method_guard_checks'] += 1
        else:
            raise AssertionError('Undeclared method proceeded')

    # Generate native strategy signal histories on fake bars; never an account.
    rng = np.random.default_rng(13)
    bar_dates = pd.bdate_range('2018-01-01', periods=2000)
    close = 10 * np.exp(np.cumsum(rng.normal(.0004, .02, len(bar_dates))))
    bars = pd.DataFrame({'Date': bar_dates, 'Open': close * .999, 'High': close * 1.02,
                         'Low': close * .98, 'Close': close,
                         'Volume': np.exp(rng.normal(15, .2, len(bar_dates))),
                         'Amount': np.exp(rng.normal(18, .2, len(bar_dates)))})
    sessions = bar_dates[364:]
    fake_ctx = SimpleNamespace(data=SimpleNamespace(fetch=lambda *args, **kwargs:
        SimpleNamespace(ready=True, dataframe=bars)))
    binding = SimpleNamespace(plan=SimpleNamespace(requests={'daily': object()}), prepared=object())
    fake_bound = SimpleNamespace(input_bindings={'test': binding})
    for experiment, is_body in (('EX028_20261011', False), ('EX029_20261011', True)):
        source = diagnosis.ROOT / 'research/S013/experiments' / experiment / 'src/strategy_runtime'
        cfg = next(row for row in json.loads((source.parent.parent / 'protocols/plan.json').read_text(encoding='utf-8'))['configurations'] if row['label'] == 'N1')
        parameters = deepcopy(cfg['payload']['parameters'])
        implementation = strategy_module(source, '_ex039_pure_' + experiment)
        native = implementation.AcfRange(ParameterSet(parameters)).calculate_history({'daily': bars}, sessions)
        native = native.assign(signal_date=sessions, valid_session=sessions + pd.Timedelta(days=1))
        rebuilt = diagnosis.reconstruct_extra(fake_ctx, fake_bound, native, parameters, is_body)
        diagnosis.validate_days(rebuilt, sessions)
        assert np.array_equal(rebuilt.target, native.target_position)
        assert np.array_equal(rebuilt.entry, native.signal_reason.eq('entry'))
        assert all(value is None for value in rebuilt.loc[~rebuilt.holding_before, 'route_before'])
        diagnosis.direction_statistics(rebuilt)
        json.dumps(diagnosis.json_standard(rebuilt.to_dict('records')), allow_nan=False)
        counts['extra_native_synthetic_rows'] += len(rebuilt)
    assert not diagnosis.SOURCE_CALLS
    result = {'status': 'PURE_PASS', 'new_account_evaluations': 0, 'retained_account_reads': 0,
              'cases': counts, 'source_sha256': hashlib.sha256(Path(diagnosis.__file__).read_bytes()).hexdigest()}
    target = diagnosis.ROOT / '.tmp/ex039-diagnosis/focused.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
