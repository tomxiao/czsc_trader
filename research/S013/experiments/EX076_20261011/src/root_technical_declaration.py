"""Declare the exact decision-calendar correction; never reallocate EX076."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import ast,json,sys
root=Path.cwd();w=root/'.tmp/s013-cross-day-curvature'
def read(p):return json.loads(p.read_text('utf-8-sig'))
def digest(p):return sha256(p.read_bytes()).hexdigest()
def write(p,v):
 with p.open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2,allow_nan=False)
assert digest(w/'execution_freeze_v2.json')=='5123faa7d0473d56a59243e871276595d480779abab4d61563cff6039c466332'
assert digest(w/'technical_method_draft_v2.json')=='f92208ac03a463d53b5a8961290377aa9a0c9b77ed2c2e178729a90b8d7d10e2'
freeze=read(w/'execution_freeze_v2.json');old=read(w/'plan.json');draft=read(w/'technical_method_draft_v2.json')
for n,h in freeze['source_files'].items():assert digest(w/n)==h,n
original=(w/'input_authentication.py').read_text('utf-8')
assert original.count('if not decision_axis.equals(sessions):')==1
changed=original.replace('if not decision_axis.equals(sessions):','if not decision_axis.equals(full_axis[:-1]):')
assert ast.dump(ast.parse(changed))==ast.dump(ast.parse((w/'input_authentication_v2.py').read_text('utf-8')))
allowed={'status','source_files','source_freeze_sha256','technical_continuation','root_required_before_execution'}
assert {k:v for k,v in old.items() if k not in allowed}=={k:v for k,v in draft.items() if k not in allowed}
assert draft['source_files']==freeze['source_files'] and draft['technical_continuation']==freeze['technical_continuation']
record=freeze['technical_continuation']
for key in ('original_attempt','original_failure'):
 p=root/record[key]['path'];assert digest(p)==record[key]['sha256'] and read(p)==record[key+'_content']
assert read(w/'execution_pureproof_v2.json')['check_count']==27
from czsc_trader.research_tools.evidence import EvidenceRef
public_original=EvidenceRef.from_dict(record['original_method_reference']).resolve(root)
assert digest(public_original)=='570ab22bb01e945db96e9facf7dff52b8061500245df74e7a76084295d249a05' and read(public_original)==old
write(w/'technical_declaration_attempt_v2.json',dict(status='ROOT_AUTHORIZED_SCHEMA_CORRECTION',source_freeze_sha256=digest(w/'execution_freeze_v2.json'),root_source_sha256=digest(Path(__file__)),new_experiments=0,new_accounts=0,new_statistics=0))
method=dict(draft,status='PROSPECTIVE_DECLARED',technical_declared_utc=datetime.now(timezone.utc).isoformat())
write(w/'technical_method_v2.json',method)
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
sys.path.insert(0,str(root/'research/S013/experiments/EX058_20261011/src'));import common
exp=ExperimentRef.from_dict(old['experiment']);refs={}
paths=[(n,w/n) for n in freeze['source_files'] if n not in old['source_files']]
paths += [(n,w/n) for n in ('execution_freeze_v2.json','technical_method_draft_v2.json','technical_method_v2.json','technical_declaration_attempt_v2.json','declaration_check.json') if n not in dict(paths)]
paths += [('original_authentication_attempt.json',root/record['original_attempt']['path']),('original_authentication_failure.json',root/record['original_failure']['path']),('root_technical_declaration.py',Path(__file__)),('root_declaration_check.py',root/'.tmp/s013_check_curvature_declaration.py')]
for n,p in paths:
 refs[n]=publish_evidence(common.context(1),MaterialEvidenceWrite(exp,'curvature-'+n.replace('.','-'),p.read_bytes(),'text/x-python' if p.suffix=='.py' else 'application/json',p.suffix[1:])).to_dict()
 if p.suffix=='.py':
  with (exp.resolve(root)/'src'/n).open('xb') as f:f.write(p.read_bytes())
write(w/'technical_references_v2.json',refs);write(w/'method_reference_v2.json',refs['technical_method_v2.json'])
write(exp.resolve(root)/'protocols/technical_references_v2.json',refs)
assert not common.SOURCE_CALLS
print({'status':'PROSPECTIVE_TECHNICAL_CORRECTION_DECLARED','references':len(refs),'method_sha':refs['technical_method_v2.json']['sha256'],'new_accounts':0,'new_experiments':0})
