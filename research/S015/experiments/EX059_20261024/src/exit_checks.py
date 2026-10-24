"""Synthetic state-transition boundaries for phase-three exit hypotheses."""
import importlib.util
import json
from pathlib import Path

import pandas as pd

HOME = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tested_process', HOME/'src/strategy_runtime/strategies/price_process.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
p = json.loads((HOME/'protocols/accounts.json').read_bytes())['configurations'][0]


def frame():
    return pd.DataFrame({
        'feature_ready': True, 'm': 1.0, 'p': .99, 'dcenter': .01,
        'center_gain': .03, 'concentration': .5, 'up_count': 3.,
        'atr': .1, 'r3': .01, 'prior_positive': 1.,
    }, index=pd.date_range('2025-01-02', periods=8))


f = frame()
f.loc[f.index[1:3], 'dcenter'] = -.01
a = m.intentions(f, dict(p, exit_mode='confirmed_guard', hold=5, confirmation=1))
b = m.intentions(f, dict(p, exit_mode='confirmed_guard', hold=5, confirmation=2))
assert a.exit_signal.iloc[1] == 1 and b.exit_signal.iloc[1] == 0 and b.exit_signal.iloc[2] == 1
f = frame()
f.loc[f.index[1], ['m', 'p']] = [.97, .96]
f.loc[f.index[2], ['m', 'p']] = [.94, .93]
a = m.intentions(f, dict(p, exit_mode='anchored_guard', hold=5, failure_buffer=.5))
assert a.exit_signal.iloc[1] == 0 and a.exit_signal.iloc[2] == 1
f = frame()
a = m.intentions(f, dict(p, exit_mode='extend_repair', hold=3, max_hold=5, confirmation=2))
assert a.exit_signal.iloc[3] == 0 and a.exit_signal.iloc[4] == 0 and a.exit_signal.iloc[5] == 1
f.loc[f.index[3], 'center_gain'] = -.01
a = m.intentions(f, dict(p, exit_mode='extend_repair', hold=3, max_hold=5, confirmation=2))
assert a.exit_signal.iloc[3] == 1
f = frame()
f.loc[f.index[1], 'p'] = 1.01
a = m.intentions(f, dict(p, exit_mode='repair_cap', hold=3))
assert a.exit_signal.iloc[1] == 1 and a.entry_signal.iloc[1] == 0
a = m.intentions(frame(), dict(p, exit_mode='repair_cap', hold=3))
assert a.exit_signal.iloc[3] == 1
invalid = [dict(p, confirmation=0), dict(p, confirmation=True), dict(p, failure_buffer=-.1),
           dict(p, max_hold=2), dict(p, max_hold=True)]
for bad in invalid:
    try:
        m.validate_parameters(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid parameters accepted')
result={'status':'PASS','state_transition_checks':6,'invalid_parameters_rejected':len(invalid),
        'scope':'Synthetic causal exit timing, no same-day re-entry; not an economic evaluation.'}
(HOME/'others/exit_checks.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(result)
