"""Confirm the completed declaration despite an erroneous final list==0 diagnostic."""
from pathlib import Path
from hashlib import sha256
import ast
import json
root=Path.cwd();w=root/'.tmp/s013-cross-day-curvature'
def read(p):return json.loads(p.read_text('utf-8-sig'))
def digest(p):return sha256(p.read_bytes()).hexdigest()
from czsc_trader.research_tools.evidence import EvidenceRef
refs=read(w/'method_references.json');plan=read(w/'plan.json')
assert len(refs)==24
assert plan['status']=='PROSPECTIVE_DECLARED' and plan['experiment']['experiment_id']=='EX076_20261011'
assert refs['plan.json']==read(w/'method_reference.json') and refs['plan.json']['sha256']=='570ab22bb01e945db96e9facf7dff52b8061500245df74e7a76084295d249a05'
for v in refs.values():assert digest(EvidenceRef.from_dict(v).resolve(root))==v['sha256']
assert digest(root/'.tmp/s013_declare_curvature.py')==refs['root_declaration.py']['sha256']
assert digest(w/'plan.json')==refs['plan.json']['sha256']
assert digest(w/'execution_freeze.json')==plan['source_freeze_sha256']
assert all(digest(w/n)==h for n,h in plan['source_files'].items())
assert not (w/'actual/authentication_attempt.json').exists()
tree=ast.parse((root/'research/S013/experiments/EX058_20261011/src/common.py').read_text('utf-8'))
assign=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SOURCE_CALLS' for t in n.targets))
assert isinstance(assign.value,ast.List) and not assign.value.elts
record=dict(status='COMPLETED_DECLARATION_HASHES_VERIFIED',experiment=plan['experiment'],method_reference=refs['plan.json'],published_references_exact=24,
 preserved_failure='Original root declaration completed all allocation/source/method publication, then final diagnostic asserted empty SOURCE_CALLS list == integer0 and raised. No provider invocation exists in declaration source; no phase was repeated.',
 no_scientific_source_change=True,reallocation=False,authentication_calls=0,statistics_calls=0,new_accounts=0,
 root_check_source_sha256=digest(Path(__file__)))
with (w/'declaration_check.json').open('x',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False,indent=2)
print({'status':record['status'],'references_exact':24,'new_accounts':0})
