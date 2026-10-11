"""Publish the single fixed EX076 authentication or statistics, never calculate them."""
from pathlib import Path
from hashlib import sha256
import json
import sys
root=Path.cwd();w=root/'.tmp/s013-cross-day-curvature';actual=Path(sys.argv[2]).resolve();phase=sys.argv[1]
def read(p):return json.loads(p.read_text('utf-8-sig'))
def digest(p):return sha256(p.read_bytes()).hexdigest()
def write(p,v):
 with p.open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2,allow_nan=False)
assert phase in ('authentication','study') and actual.is_relative_to(w.resolve())
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
plan=read(w/'plan.json');exp=ExperimentRef.from_dict(plan['experiment'])
assert exp.experiment_id=='EX076_20261011'
proof=read(actual/'authentication.json')
assert proof['status']=='PASS' and proof['new_accounts']==0 and proof['provider_calls']==0
for name,h in proof['output_sha256'].items():assert digest(actual/name)==h
method=read(EvidenceRef.from_dict(proof['method_reference']).resolve(root))
assert digest(EvidenceRef.from_dict(proof['method_reference']).resolve(root))==proof['method_reference']['sha256']
assert method['experiment']==plan['experiment'] and method['status']=='PROSPECTIVE_DECLARED'
for n,h in method['source_files'].items():assert digest(w/n)==h
cache=method['native_cache'];assert digest(root/cache['common_path'])==cache['common_sha256']
sys.path.insert(0,str((root/cache['common_path']).parent));import common
names=['authentication_attempt.json','authentication.json',*proof['output_sha256']] if phase=='authentication' else ['study_attempt.json','statistics.json','reading.json','study_completed.json']
if phase=='study':
 completed=read(actual/'study_completed.json');assert completed['status']=='COMPLETE' and completed['analyze_calls']==1
 assert completed['statistics_sha256']==digest(actual/'statistics.json') and completed['reading_sha256']==digest(actual/'reading.json')
write(actual/('publication_'+phase+'_attempt.json'),dict(phase=phase,files={n:digest(actual/n) for n in names},root_publisher_sha256=digest(Path(__file__))))
published={}
for name in names:
 path=actual/name;published[name]=publish_evidence(common.context(1),MaterialEvidenceWrite(exp,'curvature-'+name.replace('.','-'),path.read_bytes(),'text/csv' if path.suffix=='.csv' else 'application/json',path.suffix[1:])).to_dict()
write(w/(phase+'_references.json'),published);write(exp.resolve(root)/'protocols'/(phase+'_references.json'),published)
if phase=='study':
 combined=read(w/'method_references.json')
 for manifest in ('technical_references_v2.json','authentication_references.json'):
  for n,v in read(w/manifest).items():
   assert n not in combined or combined[n]==v,n
   combined[n]=v
 for n,v in published.items():assert n not in combined;combined[n]=v
 write(w/'active_result_references.json',combined);write(exp.resolve(root)/'protocols/result_references.json',combined)
assert not common.SOURCE_CALLS
print({'phase':phase,'published':len(published),'new_accounts':0})
