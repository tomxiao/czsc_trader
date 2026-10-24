"""Event-origin decisions must not retain a hidden observation/holding-day parameter."""
from pathlib import Path
import importlib.util,json
import pandas as pd
HOME=Path(__file__).resolve().parents[1];BASE=HOME.parent
def mod(p,n):
 spec=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
study=mod(BASE/'EX051_20261024/src/study.py','event_loader72');old,_=study.loader();adj,raw,bars,_,ids=old.inputs(old.sources())
m=mod(HOME/'src/strategy_runtime/strategies/price_process.py','event_runtime72')
configs=json.loads((HOME/'protocols/accounts.json').read_bytes())['configurations'];cols=['target_position','entry_allocation_fraction','intent_age','permission','exit_signal','entry_signal']
checks=0
for p in configs:
 if p['mode']!='leg_below':continue
 baseline=m.intentions(m.causal_features(adj,raw,bars,p['lookback'],p['center_kind']),p)[cols]
 for n in (2,5,10):
  changed={**p,'lookback':n,'hold':17,'max_hold':30,'concentration':.5,'confirmation':5,'failure_buffer':3.}
  actual=m.intentions(m.causal_features(adj,raw,bars,n,p['center_kind']),changed)[cols]
  pd.testing.assert_frame_equal(actual,baseline);checks+=1
out={'status':'PASS','inactive_parameter_invariance_checks':checks,'input_ids':ids,'meaning':'Leg origin is established by completed-price turns; lookback and holding horizon cannot alter its decisions.'}
(HOME/'others/event_invariance.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
print('EVENT_INVARIANCE_PASS',checks)
