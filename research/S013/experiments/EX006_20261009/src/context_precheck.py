"""Synthetic checks for contextual information gates and raw-volume units."""
from copy import deepcopy
import importlib.util
import sys

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from common import SOURCE, PROTOCOLS, RUNS, read, write
from score_audit import expression


def main():
    base_module = expression()
    name = '_s013_score_audit.reentry_confirmed_range'
    spec = importlib.util.spec_from_file_location(name, SOURCE / 'strategies/reentry_confirmed_range.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    dates = pd.bdate_range('2019-01-01', periods=520)
    t = np.arange(len(dates))
    close = 100 * np.exp(.0002 * t + .04 * np.sin(t / 11) + .005 * np.sin(t / 2.7))
    volume = 10000 * np.exp(.1 * np.sin(t / 7) + .03 * np.cos(t / 3))
    raw = pd.DataFrame({'Date': dates, 'Open': close * .998, 'High': close * 1.1,
                         'Low': close * .9, 'Close': close, 'Volume': volume, 'Amount': close * volume})
    adjusted = raw.copy()
    adjusted[['Open', 'High', 'Low', 'Close']] *= .2803
    adjusted['Volume'] /= .2803
    sessions = dates[200:]
    p = deepcopy(read(PROTOCOLS / 'initial_plan.json')['configurations'][2]['parameters'])
    p['confirmation'].update(enabled=True, threshold=-.2)
    old = base_module.ConfirmedRange(ParameterSet(p)).calculate_history({'daily': adjusted}, sessions)
    p['context'] = {'entry_gate': 'all', 'volume_basis': 'ADJUSTED', 'weighting': 'EQUAL_FEATURES'}
    new = module.ReentryConfirmedRange(ParameterSet(p)).calculate_history({'daily': adjusted}, sessions)
    pd.testing.assert_frame_equal(old, new.loc[:, old.columns], check_exact=True)
    for basis in ('RAW', 'ADJUSTED'):
        p['context']['volume_basis'] = basis
        p['confirmation']['lookback'] = 40
        before = module.ReentryConfirmedRange(ParameterSet(p)).calculate_history({'daily': adjusted, 'execution': raw}, sessions)
        changed_daily, changed_raw = adjusted.copy(), raw.copy()
        cutoff = dates[360]
        changed_daily.loc[changed_daily.Date > cutoff, ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']] *= 1.2
        changed_raw.loc[changed_raw.Date > cutoff, ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']] *= 1.2
        after = module.ReentryConfirmedRange(ParameterSet(p)).calculate_history(
            {'daily': changed_daily, 'execution': changed_raw}, sessions)
        pd.testing.assert_frame_equal(before.loc[:cutoff], after.loc[:cutoff], check_exact=True)
    # Zero time waiting: only the observed last exit reason activates a reentry gate.
    p['context'].update(volume_basis='ADJUSTED', entry_gate='regime_reentry')
    p['confirmation'].update(threshold=0., lookback=120)
    p['regime_window'] = 5
    for route in ('bull', 'bear'):
        p[route].update(entry=.99, exit=1., max_hold=60, acf_min=None, momentum_min=None)
    plain = deepcopy(p)
    plain['confirmation']['enabled'] = False
    baseline = module.ReentryConfirmedRange(ParameterSet(plain)).calculate_history({'daily': adjusted}, sessions)
    position = int(np.flatnonzero(baseline.signal_reason.eq('regime'))[0])
    panel = pd.DataFrame(-.1, index=dates, columns=['acf', 'turnover', 'volume'])
    panel.loc[sessions[position + 4:]] = .1
    module.confirmation_features = lambda *args: (panel, panel)
    path = module.ReentryConfirmedRange(ParameterSet(p)).calculate_history({'daily': adjusted}, sessions)
    assert path.signal_reason.iloc[0] == 'entry'
    assert path.signal_reason.iloc[position] == 'regime'
    assert path.signal_reason.iloc[position + 1:position + 4].eq('confirmation_rejected').all()
    assert path.signal_reason.iloc[position + 4] == 'entry'
    assert path.confirmation_exit_context.iloc[position + 1:position + 5].eq('regime').all()
    p['exit_on_regime_change'] = False
    for route in ('bull', 'bear'):
        p[route]['max_hold'] = 1
    panel.loc[:] = -.1
    path = module.ReentryConfirmedRange(ParameterSet(p)).calculate_history({'daily': adjusted}, sessions)
    assert list(path.signal_reason.iloc[:3]) == ['entry', 'time', 'entry']
    bad = adjusted.copy()
    bad['Volume'] *= 1.01
    p['context']['volume_basis'] = 'RAW'
    p['confirmation']['lookback'] = 40
    try:
        module.ReentryConfirmedRange(ParameterSet(p)).calculate_history({'daily': bad, 'execution': raw}, sessions)
    except ValueError:
        pass
    else:
        raise AssertionError('wrong volume conversion accepted')
    write(RUNS / 'context_synthetic_check.json', {'status': 'PASS', 'checks': [
        'all-entry context exact old history', 'RAW/ADJUSTED prefix invariance',
        'initial entry ignores state-reentry gate', 'state exit activates information gate',
        'gate persists until observed score passes', 'non-state exit cannot activate gate',
        'bad raw/HFQ conversion rejected']})
    print({'context_synthetic': 'PASS'}, flush=True)


if __name__ == '__main__':
    main()
