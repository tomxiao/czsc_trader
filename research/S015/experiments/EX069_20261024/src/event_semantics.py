from pathlib import Path
import importlib.util,json,sys
import pandas as pd
home=Path('research/S015/experiments')/sys.argv[1]
p=json.loads((home/'protocols/accounts.json').read_bytes())['configurations'][0]
spec=importlib.util.spec_from_file_location('event_semantics',home/'src/strategy_runtime/strategies/price_process.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
rows=[]
for center,price,low,gain in [(100,99,98,4),(97,98,97,1),(98,97,96,2),(101,101,99,4)]:
 rows.append(dict(feature_ready=True,m=center,p=price,low=low,high=max(center,price)+1,center_gain=gain,dcenter=1.,atr=1.,r3=1.,prior_positive=1.,up_count=3,concentration=.5))
f=pd.DataFrame(rows,index=pd.date_range('2025-01-02',periods=4));f.index.name='date'
base={**p,'mode':'center_below','rearm_mode':'immediate'}
anchor=m.intentions(f,{**base,'exit_mode':'anchor_repair'})
dynamic=m.intentions(f,{**base,'exit_mode':'repair'})
floor=m.intentions(f,{**base,'exit_mode':'anchor_repair_floor'})
assert anchor.target_position.tolist()==[1.,1.,1.,0.]
assert dynamic.exit_signal.tolist()==[0.,1.,0.,1.]
assert floor.target_position.tolist()==[1.,1.,0.,0.]
checks=['moving center fall is not anchored price repair','equal entry low does not breach strict floor','floor close breach exits next decision','fixed anchor repair has no intent-age exit']
if any(c['mode']=='inside_advance' for c in json.loads((home/'protocols/accounts.json').read_bytes())['configurations']):
 z=f.copy();z.iloc[0,z.columns.get_loc('p')]=95
 assert m.intentions(z,{**base,'mode':'inside_advance','exit_mode':'anchor_origin'}).entry_signal.iloc[0]==0
 assert m.intentions(z,{**base,'mode':'center_below','exit_mode':'anchor_origin'}).entry_signal.iloc[0]==1
 z=f.copy();z.iloc[1,z.columns.get_loc('p')]=96
 assert m.intentions(z,{**base,'mode':'inside_advance','exit_mode':'anchor_origin'}).exit_signal.iloc[1]==1
 checks+=['inside-advance excludes already-broken entry structure','origin boundary equality invalidates opportunity']
(home/'others/event_semantics.json').write_text(json.dumps({'status':'PASS','checks':checks},indent=2)+'\n',encoding='utf-8')
print('EVENT_SEMANTICS_PASS',home.name,len(checks))
