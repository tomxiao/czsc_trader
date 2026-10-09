"""Independent synthetic checks of directional exits, confirmations and cooldowns."""
from copy import deepcopy
import importlib.util
import sys
import types

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from common import SOURCE, PROTOCOLS, RUNS, read, write


def main():
    package = types.ModuleType('_s013_mechanism_boundary')
    package.__path__ = [str(SOURCE / 'strategies')]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location(
        package.__name__ + '.stable_range', SOURCE / 'strategies/stable_range.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    dates = pd.bdate_range('2019-01-01', periods=520)
    x = np.arange(len(dates))
    close = 100 * np.exp(.0002 * x + .04 * np.sin(x / 11) + .005 * np.sin(x / 2.7))
    bars = pd.DataFrame({'Date': dates, 'Open': close * .998, 'High': close * 1.1,
                         'Low': close * .9, 'Close': close, 'Volume': 10000., 'Amount': close * 10000})
    source = read(PROTOCOLS / 'initial_plan.json')['configurations'][0]['parameters']
    cases = []
    for direction in ('both', 'bull_to_bear', 'bear_to_bull'):
        for confirmation, cooldown in ((1, 0), (2, 2), (3, 5)):
            p = deepcopy(source)
            for key in ('bull', 'bear'):
                p[key].update(entry=.98, exit=.999, max_hold=60, acf_min=None)
            p.update(regime_window=10, exit_direction=direction,
                     exit_confirmation=confirmation, regime_cooldown=cooldown)
            frame = module.StableRange(ParameterSet(p)).calculate_history({'daily': bars}, dates[200:])
            active, count, exits = None, 0, 0
            for i, row in enumerate(frame.itertuples()):
                if row.signal_reason == 'entry':
                    active, count = row.regime, 0
                    continue
                if active is not None:
                    count = count + 1 if row.regime != active else 0
                allowed = active is not None and (direction == 'both' or direction == active + '_to_' + row.regime)
                if row.signal_reason == 'regime':
                    exits += 1
                    assert allowed and count >= confirmation
                    for offset in range(1, cooldown + 1):
                        if i + offset < len(frame):
                            assert frame.signal_reason.iloc[i + offset] == 'cooldown'
                            assert frame.target_position.iloc[i + offset] == 0.
                    active, count = None, 0
                elif row.signal_reason in ('range', 'time', 'loss', 'trailing'):
                    active, count = None, 0
                elif row.signal_reason == 'hold':
                    assert not (allowed and count >= confirmation)
            assert exits > 0
            cases.append({'direction': direction, 'confirmation': confirmation,
                          'cooldown': cooldown, 'regime_exits': exits})
    write(RUNS / 'mechanism_boundary_check.json', {'status': 'PASS', 'cases': cases,
        'checks': ['actual exit direction', 'consecutive contrary-state confirmation',
                   'exact signal-day cooldown after regime exits']})
    print({'status': 'PASS', 'cases': len(cases)})


if __name__ == '__main__':
    main()
