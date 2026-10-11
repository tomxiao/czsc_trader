"""Declare one fixed curvature experiment before authentication or statistics."""
from pathlib import Path
from hashlib import sha256
from datetime import date, datetime, timezone
import json
import sys
root=Path.cwd();work=root/'.tmp/s013-cross-day-curvature';audit=work/'independent_audit'
def read(p):return json.loads(p.read_text('utf-8-sig'))
def digest(p):return sha256(p.read_bytes()).hexdigest()
def write(p,v):
 with p.open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2,allow_nan=False)
freeze=read(work/'execution_freeze.json');draft=read(work/'method_draft.json')
assert digest(work/'execution_freeze.json')=='5d78a36fe638e55f3ecae0e794d28b4fefef159ac2e76b43dfc26632b33410d7'
assert digest(work/'method_draft.json')=='45380393db802085b45cd1a61aaf39d147a1434b9136830c724434cd1921605d'
assert draft['source_files']==freeze['source_files'] and len(freeze['source_files'])==15
for n,h in freeze['source_files'].items():assert digest(work/n)==h,n
assert digest(audit/'freeze.json')=='5cc196f03485938de2d75f362c4304a3de43e57b3ace6ffd8431e2f948a2ae08'
for n,h in read(audit/'freeze.json')['source_files'].items():assert digest(audit/n)==h,n
assert read(work/'execution_pureproof.json')['check_count']==25
assert read(work/'pureproof.json')['check_count']==39
for key in ('path','common_path'):assert digest(root/draft['native_cache'][key])==draft['native_cache']['sha256' if key=='path' else 'common_sha256']
from czsc_trader.research_tools.evidence import EvidenceRef
for v in draft['input_references'].values():assert digest(EvidenceRef.from_dict(v).resolve(root))==v['sha256']
sys.path.insert(0,str(root/'research/S013/experiments/EX058_20261011/src'))
import common
from czsc_trader.application import create_experiment, ExperimentRequest, publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
ctx=common.context(1)
write(work/'allocation_attempt.json',dict(expected='EX076_20261011',new_accounts=0,source_freeze_sha256=digest(work/'execution_freeze.json'),root_declaration_source_sha256=digest(Path(__file__))))
exp=create_experiment(ctx,ExperimentRequest('四日价格曲率的固定增量信息检验','相同四日总变化下，跌势减速能否改善未来四日扣费收益预测？固定17控制、全池及原policy-flat两个范围，风险只作诊断。',date(2026,10,11)))
write(work/'experiment.json',exp.to_dict())
assert exp.experiment_id=='EX076_20261011','Unexpected allocation retained; no reallocation'
plan=dict(draft,status='PROSPECTIVE_DECLARED',experiment=exp.to_dict(),declared_utc=datetime.now(timezone.utc).isoformat(),
 prospective_definition=read(work/'prospective_plan.json'),binding_definition=read(work/'execution_binding_plan.json'),
 independent_arithmetic_freeze_sha256=digest(audit/'freeze.json'),original_four_hard_gates_changed=False,
 objective_achieved=False,root_declaration_source_sha256=digest(Path(__file__)),
 predecessors=read(root/'research/S013/experiments/EX075_20261011/protocols/plan.json')['predecessors'])
write(work/'plan.json',plan)
refs={}
paths=[(n,work/n) for n in (*freeze['source_files'],'execution_freeze.json','method_draft.json','plan.json','allocation_attempt.json')]
paths += [('independent_'+n,audit/n) for n in (*read(audit/'freeze.json')['source_files'],'freeze.json')]
paths.append(('root_declaration.py',Path(__file__)))
for name,path in paths:
 media='text/x-python' if path.suffix=='.py' else 'application/json'
 refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(exp,'curvature-'+name.replace('.','-'),path.read_bytes(),media,path.suffix[1:])).to_dict()
 if path.suffix=='.py':
  with (exp.resolve(root)/'src'/name).open('xb') as f:f.write(path.read_bytes())
write(work/'method_references.json',refs);write(work/'method_reference.json',refs['plan.json'])
write(exp.resolve(root)/'protocols/plan.json',plan);write(exp.resolve(root)/'protocols/method_references.json',refs)
assert common.SOURCE_CALLS==0
print({'experiment':exp.experiment_id,'method_sha256':refs['plan.json']['sha256'],'source_evidence_count':len(refs),'new_accounts':0})
