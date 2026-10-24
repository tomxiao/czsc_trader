"""Causal features, gate semantics and zero-hurdle economic control."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
from pathlib import Path
import importlib.util,json,sys
import pandas as pd
H=Path(__file__).resolve().parents[1];B=H.parent
def mod(p,n):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def read(p):return json.loads(p.read_bytes())
def main():
 m=mod(H/'src/strategy_runtime/strategies/price_process.py','new');prior=mod(B/'EX074_20261024/src/strategy_runtime/strategies/price_process.py','prior')
 loader=mod(B/'EX051_20261024/src/study.py','loader');old,_=loader.loader();adj,raw,bars,rules,ids=old.inputs(old.sources());checks=0
 for kind in ('mean','median'):
  for n in (1,2,3,5,10,20,30):
   f=m.causal_features(adj,raw,bars,n,kind)
   for stop in (75,76,79,85,106,120,250,509):
    part=m.causal_features(adj.iloc[:stop],raw.iloc[:stop],bars.iloc[:max(0,stop-75)*8],n,kind);pd.testing.assert_frame_equal(part,f.iloc[:len(part)]);checks+=1
   p={'center_kind':kind,'lookback':n,'allocation':1.,'minimum_repair_space':0.}
   if 2<=n<=10:
    previous=prior.intentions(prior.causal_features(adj,raw,bars,n,kind),{k:v for k,v in p.items() if k!='minimum_repair_space'});new=m.intentions(f,p);pd.testing.assert_frame_equal(new[previous.columns],previous);checks+=1
   for threshold in (0.,.002002002002001957,.012022022022021961,.02):
    p['minimum_repair_space']=threshold;out=m.intentions(f,p)
    for stop in (1,4,20,100,250,435):pd.testing.assert_frame_equal(m.intentions(f.iloc[:stop],p),out.iloc[:stop]);checks+=1
 # Admission hurdle does not become an unrequested holding/exit filter.
 p={'center_kind':'median','lookback':3,'allocation':1.,'minimum_repair_space':.01}
 fake=pd.DataFrame({'m':[2.,2.,2.,2.],'p':[1.9,1.999,2.,1.9],'center_gain':[.1]*4,'feature_ready':[True]*4,'repair_space':[.02,.001,0.,.02]},index=pd.bdate_range('2025-01-02',periods=4))
 assert m.intentions(fake,p).target_position.tolist()==[1.,1.,0.,1.]
 for value in (-.01,.051,float('nan'),True,'0.01'):
  try:m.validate_parameters(dict(p,minimum_repair_space=value))
  except ValueError:pass
  else:raise AssertionError(value)
 result={'status':'PASS','checks':checks,'zero_hurdle_signal_equivalence':True,'admission_not_holding_filter':True,'invalid_hurdle_cases':5,'inputs':ids}
 (H/'others/runtime_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(result,flush=True)
if __name__=='__main__':main()
