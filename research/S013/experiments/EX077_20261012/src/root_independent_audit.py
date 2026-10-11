"""Root independent arithmetic and native-policy link; no new account."""
import importlib.util
import json
from pathlib import Path
import sys
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'.tmp/s013-price-event-policy'
WORK=ROOT/'.tmp/s013-price-event-binding-r2'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module
w=load('price_event_r2_root_wrapper',WORK/'technical_driver.py')
d=w.d;c=d.common();ctx=c.context(1)
exp,plan,path=w.stage()
receipt=d.read(WORK/'centre_execution.json')
assert d.digest(WORK/'centre_account.pkl.gz')==receipt['cache_sha256']
bound,result=c.cache_read(WORK/'centre_account.pkl.gz')
assert d.serialize_evaluation_evidence(bound,result)==d.read(d.public(receipt['reference']))
assert d.read(d.public(d.read(path/'protocols/verification_reference.json')))['status']=='PASS'
daily,identity=d.fetched_daily(ctx,bound.input_bindings['full'])
axis=pd.DatetimeIndex(pd.to_datetime(daily.Date)).normalize()
signal_axis=pd.DatetimeIndex(pd.to_datetime(result.runs[0].execution.decisions.signal_date)).normalize()
policy=load('price_event_math_subject',OLD/'policy.py')
checker=load('price_event_math_independent',OLD/'independent_policy_audit.py')
close=pd.Series(daily.Close.to_numpy(),index=axis)
reported=policy.decisions(close,signal_axis,**bound.strategy.payload['parameters'])
proof=checker.verify_native_policy(close,signal_axis,reported,**bound.strategy.payload['parameters'])
native=result.runs[0].execution.decisions.set_index(signal_axis)
for field in ['state_before','state_after','target_position','sigma_available']:
    assert (native[field].to_numpy()==reported[field].to_numpy()).all(),field
assert (native.signal_reason.to_numpy()==reported.reason.to_numpy()).all()
proof.update(whole_formal_native_exact=True,candidate_id=bound.strategy.candidate_id,content_sha256=plan['content_sha256'],references={'plan':d.read(path/'protocols/plan_reference.json'),'native':receipt['reference'],'ledger_audit':d.read(path/'protocols/verification_reference.json')},new_financial_accounts=0,actual_accounts_to_date=1,provider_calls=c.SOURCE_CALLS,clock_scope='T17 mathematical policy availability checked; SRT transport timestamps/date serialization are separately disclosed by the native ledger audit, not treated as T17 evidence')
assert not c.SOURCE_CALLS
target=WORK/'independent_policy_verification.json';d.write(target,proof)
refs={'verification':d.put(ctx,exp,target),'source':d.put(ctx,exp,Path(__file__))}
d.write(path/'protocols/independent_policy_references.json',refs)
print(json.dumps({'status':'PASS','proof':proof,'references':refs},ensure_ascii=False,allow_nan=False))
