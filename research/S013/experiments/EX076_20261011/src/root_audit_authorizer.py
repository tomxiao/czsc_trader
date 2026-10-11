from pathlib import Path
from hashlib import sha256
import json
from czsc_trader.research_tools.evidence import EvidenceRef
root=Path.cwd();w=root/'.tmp/s013-cross-day-curvature';a=w/'actual_v2'
def read(p):return json.loads(p.read_text('utf-8-sig'))
def digest(p):return sha256(p.read_bytes()).hexdigest()
refs=read(w/'active_result_references.json')
for v in refs.values():assert digest(EvidenceRef.from_dict(v).resolve(root))==v['sha256']
for n in ('statistics.json','reading.json','authentication.json','features.csv','labels.csv','flat_eligible.csv','price_calendar.csv'):assert digest(a/n)==refs[n]['sha256']
assert read(a/'root_prestudy_check.json')['status']=='ROOT_DIRECT_PRICE_MATURITY_CURVATURE_SCOPE_PASS'
assert read(a/'study_completed.json')['analyze_calls']==1
assert not (a/'verification_attempt.json').exists()
record=dict(status='ROOT_AUTHORIZED_EX076_ARITHMETIC_AUDIT',new_accounts=0,new_statistics=0,
 root_audit_source_sha256=digest(root/'.tmp/s013_audit_curvature.py'),
 actual_file_sha256={n:digest(a/n) for n in ('authentication.json','features.csv','labels.csv','flat_eligible.csv','price_calendar.csv','statistics.json','reading.json','study_completed.json')},
 root_authorization_source_sha256=digest(Path(__file__)))
with (a/'root_audit_authorization.json').open('x',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False,indent=2)
print({'status':record['status'],'actual_stat_sha256':refs['statistics.json']['sha256'],'refs_checked':len(refs)})
