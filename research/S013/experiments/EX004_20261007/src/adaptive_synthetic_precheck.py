"""Independent synthetic checks; no market data, evaluation, or publication."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys
import types

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet


SRC = Path(__file__).resolve().parent
SOURCE = SRC / 'adaptive_range/strategy_runtime/strategies'
PACKAGE = '_s013_adaptive_synthetic'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(SOURCE)]
sys.modules[PACKAGE] = package
spec = importlib.util.spec_from_file_location(
    PACKAGE + '.adaptive_range', SOURCE / 'adaptive_range.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
AdaptiveRange = module.AdaptiveRange
RangeReversion = module.RangeReversion


def make_parameters(route=None, **changes):
    if route is None:
        route = {'range_window': 60, 'entry': .675, 'exit': .9,
                 'max_hold': 8, 'acf_min': None, 'stop_loss': None,
                 'trailing_stop': None, 'cooldown': 0, 'momentum_min': None,
                 'limit_premium': .01}
    result = {'bull': deepcopy(route), 'bear': deepcopy(route),
              'regime_window': 10, 'regime_threshold': 0.0,
              'exit_on_regime_change': False}
    result.update(changes)
    return result


def calculate(parameters, bars, sessions):
    return AdaptiveRange(ParameterSet(parameters)).calculate_history(
        {'daily': bars}, sessions)


def main():
    original = SRC / 'extended_window/strategy_runtime/strategies/range_reversion.py'
    assert hashlib.sha256(original.read_bytes()).digest() == hashlib.sha256(
        (SOURCE / 'range_reversion.py').read_bytes()).digest()
    dates = pd.bdate_range('2019-01-01', periods=420)
    x = np.arange(len(dates), dtype=float)
    close = 100 * np.exp(.0002 * x + .04 * np.sin(x / 11) + .005 * np.sin(x / 2.7))
    bars = pd.DataFrame({'Date': dates, 'Open': close * .998,
                         'High': close * 1.1, 'Low': close * .9,
                         'Close': close, 'Volume': 10000.0, 'Amount': close * 10000})
    sessions = dates[100:]
    for window, cooldown, stop, trail, acf, momentum in (
            (60, 0, None, None, None, None),
            (21, 2, .02, .03, -.4, -.05),
            (90, 5, .03, None, None, .01)):
        parameters = make_parameters()
        for key in ('bull', 'bear'):
            parameters[key].update(range_window=window, cooldown=cooldown,
                                   stop_loss=stop, trailing_stop=trail,
                                   acf_min=acf, momentum_min=momentum)
        adaptive = calculate(parameters, bars, sessions)
        fixed = RangeReversion(ParameterSet(parameters['bull'])).calculate_history(
            {'daily': bars}, sessions)
        pd.testing.assert_series_equal(adaptive.target_position, fixed.target_position)
        pd.testing.assert_series_equal(adaptive.signal_reason, fixed.signal_reason)
        pd.testing.assert_series_equal(adaptive.range_position, fixed.range_position)

    parameters = make_parameters(exit_on_regime_change=True)
    parameters['bull'].update(entry=.98, exit=.999, max_hold=60)
    parameters['bear'].update(entry=.98, exit=.999, max_hold=30, cooldown=3)
    before = calculate(parameters, bars, sessions)
    assert set(before.regime) == {'bull', 'bear'}
    assert (before.signal_reason == 'regime').any()
    for i in np.flatnonzero(before.signal_reason.to_numpy() == 'regime'):
        assert i > 0 and before.target_position.iloc[i - 1] == 1.0
        assert before.target_position.iloc[i] == 0.0
        assert before.regime.iloc[i] != before.regime.iloc[i - 1]
    no_switch = deepcopy(parameters)
    no_switch['exit_on_regime_change'] = False
    locked = calculate(no_switch, bars, sessions)
    assert not (locked.signal_reason == 'regime').any()
    assert (locked.target_position != before.target_position).any()

    # Revise every future OHLC bar while preserving dates and historical prefix.
    boundary = dates[280]
    changed = bars.copy()
    changed.loc[changed.Date > boundary, ['Open', 'High', 'Low', 'Close']] *= 1.7
    after = calculate(parameters, changed, sessions)
    pd.testing.assert_frame_equal(before.loc[:boundary], after.loc[:boundary])

    malformed = []
    for key, value in (
            ('regime_window', True), ('regime_window', 4), ('regime_window', 61),
            ('regime_threshold', 0), ('regime_threshold', float('nan')),
            ('regime_threshold', float('inf')), ('regime_threshold', -.201),
            ('regime_threshold', .201), ('exit_on_regime_change', 1), ('bull', [])):
        case = make_parameters()
        case[key] = value
        malformed.append(case)
    case = make_parameters()
    case['unexpected'] = 1
    malformed.append(case)
    case = make_parameters()
    del case['bear']['stop_loss']
    malformed.append(case)
    case = make_parameters()
    case['bear']['range_window'] = 361
    malformed.append(case)
    case = make_parameters()
    case['bear']['limit_premium'] = .02
    malformed.append(case)
    for case in malformed:
        try:
            AdaptiveRange(ParameterSet(case))
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError('malformed adaptive parameters accepted')
    definition = AdaptiveRange(ParameterSet(parameters)).definition
    assert definition.parameters == ParameterSet(parameters)
    daily = next(item for item in definition.inputs.requirements if item.name == 'daily')
    assert daily.lookback_sessions == 60
    assert definition.execution == RangeReversion(ParameterSet(parameters['bull'])).definition.execution
    print('PASS')


if __name__ == '__main__':
    main()
