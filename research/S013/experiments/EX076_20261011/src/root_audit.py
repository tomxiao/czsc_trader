"""One arithmetic audit of the unique prospective EX076 statistics."""
from pathlib import Path
from hashlib import sha256
import json
import sys
root=Path.cwd();work=root/'.tmp/s013-cross-day-curvature';audit=work/'independent_audit'
actual=Path(sys.argv[1]).resolve()
def read(p):return json.loads(p.read_text('utf-8-sig'))
def digest(p):return sha256(p.read_bytes()).hexdigest()
def write(p,v):
 with p.open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2,allow_nan=False)
assert actual.is_relative_to(work.resolve())
authority=read(actual/'root_audit_authorization.json')
assert authority['status']=='ROOT_AUTHORIZED_EX076_ARITHMETIC_AUDIT' and authority['new_accounts']==0
assert authority['root_audit_source_sha256']==digest(Path(__file__))
for name,h in authority['actual_file_sha256'].items():assert Path(name).name==name and digest(actual/name)==h
assert digest(audit/'freeze.json')=='5cc196f03485938de2d75f362c4304a3de43e57b3ace6ffd8431e2f948a2ae08'
for n,h in read(audit/'freeze.json')['source_files'].items():assert digest(audit/n)==h
assert not (actual/'verification_attempt.json').exists()
write(actual/'verification_attempt.json',dict(authority_sha256=digest(actual/'root_audit_authorization.json'),root_audit_source_sha256=digest(Path(__file__)),new_accounts=0,provider_calls=0))
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
refs=read(work/'active_result_references.json')
for v in refs.values():assert digest(EvidenceRef.from_dict(v).resolve(root))==v['sha256']
proof=read(actual/'authentication.json');methodref=proof['method_reference']
method=read(EvidenceRef.from_dict(methodref).resolve(root))
assert proof['status']=='PASS' and proof['new_accounts']==0 and proof['provider_calls']==0
assert method['experiment']['experiment_id']=='EX076_20261011' and method['status']=='PROSPECTIVE_DECLARED'
for n,h in method['source_files'].items():assert digest(work/n)==h
cache=method['native_cache'];assert digest(root/cache['path'])==cache['sha256']
assert digest(root/cache['common_path'])==cache['common_sha256']
sys.path.insert(0,str((root/cache['common_path']).parent))
import common
bound,result=common.cache_read(root/cache['path'])
native=method['input_references']['native_ref']
assert serialize_evaluation_evidence(bound,result)==read(EvidenceRef.from_dict(native).resolve(root))
assert not common.SOURCE_CALLS
sys.path.insert(0,str(audit));import independent_curvature_verification as checker
sys.path.insert(0,str(work));import reading
import pandas as pd
def frame(name):
 value=pd.read_csv(actual/name,index_col='signal_date',float_precision='round_trip')
 value.index=pd.to_datetime(value.index).as_unit('ns')
 if name=='labels.csv':value['label_end4']=pd.to_datetime(value['label_end4']).dt.as_unit('ns')
 return value
features,labels=frame('features.csv'),frame('labels.csv')
outcome=checker.verify_statistics(features,labels,frame('price_calendar.csv').index,read(actual/'statistics.json'),flat_eligible=frame('flat_eligible.csv').iloc[:,0])
assert reading.summarize(read(actual/'statistics.json'))==read(actual/'reading.json')
outcome.update(method_reference=methodref,result_references=refs,authority_sha256=digest(actual/'root_audit_authorization.json'),cache_serialized_public_native_exact=True,provider_calls=0)
write(actual/'verification.json',outcome)
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
exp=ExperimentRef.from_dict(method['experiment']);published={}
for name,path in [('verification.json',actual/'verification.json'),('verification_attempt.json',actual/'verification_attempt.json'),('root_audit_authorization.json',actual/'root_audit_authorization.json'),('root_audit.py',Path(__file__))]:
 published[name]=publish_evidence(common.context(1),MaterialEvidenceWrite(exp,'curvature-'+name.replace('.','-'),path.read_bytes(),'text/x-python' if path.suffix=='.py' else 'application/json',path.suffix[1:])).to_dict()
write(work/'verification_references.json',published);write(exp.resolve(root)/'protocols/verification_references.json',published)
with (exp.resolve(root)/'src/root_audit.py').open('xb') as f:f.write(Path(__file__).read_bytes())
assert not common.SOURCE_CALLS
print({k:outcome[k] for k in ('status','bootstrap_records_checked','comparison','new_accounts','provider_calls')})
