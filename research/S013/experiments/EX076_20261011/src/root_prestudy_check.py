from pathlib import Path
from hashlib import sha256
import json,sys
import numpy as np
import pandas as pd
from czsc_trader.research_tools.evidence import EvidenceRef
root=Path.cwd();w=root/'.tmp/s013-cross-day-curvature';a=w/'actual_v2'
def read(p):return json.loads(p.read_text('utf-8-sig'))
def digest(p):return sha256(p.read_bytes()).hexdigest()
def public(v):
 p=EvidenceRef.from_dict(v).resolve(root);assert digest(p)==v['sha256'];return p
def frame(p):
 d=pd.read_csv(p,index_col='signal_date',float_precision='round_trip');d.index=pd.to_datetime(d.index).as_unit('ns');return d
method=read(public(read(w/'method_reference_v2.json')));proof=read(a/'authentication.json')
assert proof['status']=='PASS' and proof['flat_eligible_n']==147
assert method['source_freeze_sha256']=='5123faa7d0473d56a59243e871276595d480779abab4d61563cff6039c466332'
for n,h in method['source_files'].items():assert digest(w/n)==h
for n,h in proof['output_sha256'].items():assert digest(a/n)==h
for manifest in ('method_references.json','technical_references_v2.json','authentication_references.json'):
 for v in read(w/manifest).values():public(v)
f,l=frame(a/'features.csv'),frame(a/'labels.csv');warm=frame(public(method['input_references']['warm69_prices']));prices=frame(public(method['input_references']['original_prices']))
cl=warm.Close.to_numpy();ret=cl[1:]/cl[:-1]-1;logs=np.log(cl);priceindex=prices.index
checked=0
for i,t in enumerate(f.index):
 p=warm.index.get_loc(t);sigma=np.std(ret[p-20:p],ddof=1);expected=(logs[p]-2*logs[p-2]+logs[p-4])/(2*sigma)
 np.testing.assert_allclose(f.curvature4.iloc[i],expected,rtol=1e-12,atol=1e-12)
 k=priceindex.get_loc(t)
 if k+5<len(prices):
  entry=prices.open.iloc[k+1];exitprice=prices.open.iloc[k+5]
  np.testing.assert_allclose(l.return4_net.iloc[i],.999*exitprice/(1.001*entry)-1,rtol=0,atol=5e-15)
  floor=min(prices.open.iloc[k+1:k+5].min(),prices.close.iloc[k+1:k+5].min(),exitprice)
  np.testing.assert_allclose(l.downside4_oc.iloc[i],max(0,1-floor/entry),rtol=0,atol=5e-15)
  assert pd.Timestamp(l.label_end4.iloc[i])==priceindex[k+5]
 else:assert pd.isna(l.return4_net.iloc[i]) and pd.isna(l.downside4_oc.iloc[i]) and pd.isna(l.label_end4.iloc[i])
 checked+=1
sys.path.insert(0,str(root/method['native_cache']['common_path']).rsplit('\\',1)[0]);import common
_,r=common.cache_read(root/method['native_cache']['path']);d=r.runs[0].execution.decisions
idx=pd.DatetimeIndex(d.signal_date).as_unit('ns');actual=pd.Series(d.entry_eligible.to_numpy() & (np.r_[0,d.target_position.to_numpy()[:-1]]==0),index=idx).reindex(f.index)
np.testing.assert_array_equal(actual,frame(a/'flat_eligible.csv').iloc[:,0]);assert not common.SOURCE_CALLS
record=dict(status='ROOT_DIRECT_PRICE_MATURITY_CURVATURE_SCOPE_PASS',rows_checked=checked,flat_eligible_n=int(actual.sum()),new_accounts=0,provider_calls=0,study_authorized=True,source_sha256=digest(Path(__file__)),authentication_sha256=digest(a/'authentication.json'),source_freeze_sha256=method['source_freeze_sha256'])
with (a/'root_prestudy_check.json').open('x',encoding='utf-8') as out:json.dump(record,out,ensure_ascii=False,indent=2)
print(record)
