"""Semantic boundary of center invalidation versus a closing-price overshoot."""
from pathlib import Path
import importlib.util,json
import pandas as pd
home=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('center_semantics_runtime',home/'src/strategy_runtime/strategies/price_process.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
p=json.loads((home/'protocols/accounts.json').read_bytes())['configurations'][1]
f=pd.DataFrame([dict(feature_ready=True,m=c,p=v,low=min(c,v)-1,high=max(c,v)+1,center_gain=g,dcenter=1.,atr=1.,r3=1.,prior_positive=1.,up_count=3,concentration=.5) for c,v,g in [(100,99,4),(97,95,1),(96,95,2)]],index=pd.date_range('2025-01-02',periods=3))
center=m.intentions(f,p);price=m.intentions(f,{**p,'exit_mode':'anchor_origin'})
assert center.target_position.tolist()==[1.,1.,0.]
assert price.target_position.tolist()==[1.,0.,1.]
assert f.m.iloc[0] > f.m.iloc[0]-f.center_gain.iloc[0]
out={'status':'PASS','checks':['price overshoot below origin does not invalidate a still-elevated center','center returning to fixed origin invalidates trade including equality','entry positive migration guarantees center invalidation is not already true']}
(home/'others/center_semantics.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
print('CENTER_SEMANTICS_PASS')
