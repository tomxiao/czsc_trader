"""Read back the four completed direct FULLs and signed old h60 paths; no simulate."""
from hashlib import sha256
import gzip
import importlib.util
from io import StringIO
import json
from math import isclose
from pathlib import Path
import shutil
import pandas as pd
from czsc_trader.experiment_archive import build_experiment_manifest, validate_experiment_archive
from research_experiment import experiment_source_sha256, load_experiment_input

root=Path.cwd(); task=root/'.tmp/s012-stage3-native-20261006'; exp=root/'experiments/S012/EX055_20261006'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
ref=lambda p:{'path':p.relative_to(root).as_posix(),'sha256':sha256(p.read_bytes()).hexdigest()}
def module(name,path):
 s=importlib.util.spec_from_file_location(name,path); v=importlib.util.module_from_spec(s); s.loader.exec_module(v); return v
engine=module('s012_readonly_audit55',task/'independent_account_check.py')
assert ref(task/'accelerator.py')['sha256']=='95dd7fb438fd978f7bd0da0201ba9d69c121ab93794d70f4674daa319d434ffa'
comparator=module('s012_pure_ledger_comparator55',task/'accelerator.py')
receipt=read(exp/'artifacts/rex/execution_receipt.json'); binding=read(exp/'experiment_binding.json')
assert receipt['source_sha256']==binding['source_sha256']==experiment_source_sha256(exp,tuple(binding['source_files']))
load_experiment_input(exp/'artifacts/rex',expected_receipt_sha256=receipt['receipt_sha256'])
rows=read(exp/'artifacts/rex/trials.json')
assert [r['candidate_id'] for r in rows]==['C5000','C5001','C5002','C5003']
assert len(receipt['trace']['evaluations'])==4 and all(r['record']['status']=='SUCCEEDED' for r in rows)
audit_path=task/'audit_EX055.json'; audit=read(audit_path)
assert audit['status']=='PASS' and not audit['errors'] and audit['experiments']==[exp.name]
assert audit['verified_receipt_hashes'][exp.name]==receipt['receipt_sha256']
old_workspace=root/'experiments/S012/EX049_20261006/artifacts/rex'
old_receipt=read(old_workspace/'execution_receipt.json'); old_search=read(old_workspace/'search.json')
actual=[]
for row in rows:
 result=exp/'artifacts/rex'/row['record']['result_artifact']['path']
 assert ref(result)['sha256']==row['record']['result_artifact']['sha256']
 full=read(result); run=full['runs'][0]
 actual.append((row,full,run,result))
comparisons=[]
for i,pid in ((0,'OPTUNA_1011'),(2,'OPTUNA_0607')):
 row,full,run,result=actual[i]; original=next(r for r in old_search['proposals'] if r['proposal_id']==pid)
 assert row['parameters']==original['parameters']
 assert full['request_identity']['data_identity']==original['scope']['execution_data_fingerprint']
 old={}; evidence=[]
 for name,item in original['raw_ledgers'].items():
  p=old_workspace/item['path']; assert ref(p)['sha256']==item['sha256']==old_receipt['artifact_sha256'][item['path']]
  raw=gzip.decompress(p.read_bytes()); assert sha256(raw).hexdigest()==item['uncompressed_sha256']
  old[name]=pd.read_json(StringIO(raw.decode('utf-8')),orient='table'); evidence.append(ref(p))
 ledger={n:engine.table(t,exp/'artifacts/rex') for n,t in run['ledgers'].items()}
 economics=comparator.compare_economics(old,ledger)
 for key in ('net_cagr','max_drawdown','closed_trades','frequency','final_equity','total_fees','exposure'):
  assert isclose(row['metrics'][key],original['metrics'][key],rel_tol=1e-10,abs_tol=1e-8),key
 comparisons.append({'candidate_id':row['candidate_id'],'original_proposal_id':pid,
  'same_execution_market_fingerprint':True,'same_parameters':True,'financial_ledger_comparison':economics,
  'original_mode':original['mode'],'original_scope':original['scope'],'new_runtime_sha256':row['payload']['runtime']['source_sha256'],
  'evidence':[ref(result),*evidence],'gate_credit':'NONE; descriptive backward-h60 behavior check only'})
pairs=[]
for i in (0,2):
 baseline=rows[i]; candidate=rows[i+1]; assert candidate['parameters']=={**baseline['parameters'],'hold_days':80}
 delta={k:candidate['metrics'][k]-baseline['metrics'][k] for k in
        ('net_cagr','max_drawdown','closed_trades','frequency','final_equity','total_fees','exposure')}
 pairs.append({'baseline':baseline['candidate_id'],'candidate':candidate['candidate_id'],'only_parameter_delta':{'hold_days':[60,80]},
   'delta':delta,'baseline_metrics':baseline['metrics'],'candidate_metrics':candidate['metrics'],
   'continuing_return_boundary':delta['net_cagr']>0})
comparison={'status':'PASS','experiment_id':exp.name,'direct_full_count':4,
 'source_change':read(exp/'source_change.json'),'backward_h60_comparisons':comparisons,
 'holding_period_pairs':pairs,'evidence':[ref(audit_path)],'qualified':[r['candidate_id'] for r in rows if r['passed_all']],
 'new_screening_accounts':0,'accelerator_gate_credit':'NONE','stage_three_complete':False}
dest=task/'delivery-prep/long_holding55_comparison.json'
with dest.open('x',encoding='utf-8',newline='\n') as f:
 json.dump(comparison,f,ensure_ascii=False,indent=2,allow_nan=False); f.write('\n')
assert not (exp/'experiment_manifest.json').exists()
for source,target in [(audit_path,exp/'artifacts/independent_account_audit.json'),
 (task/'delivery-prep/EX055_20261006_full_diagnosis.json',exp/'artifacts/scientific_diagnosis.json'),
 (dest,exp/'artifacts/long_holding_pair_comparison.json')]:
 assert not target.exists(); shutil.copyfile(source,target)
text=(task/'delivery-prep/EX055_20261006_04_conclusion.md').read_text(encoding='utf-8')
text+='\n## 长持有边界的实际回答\n\n'
for pair in pairs:
 text+=f"{pair['baseline']}→{pair['candidate']}仅持有60→80，净年化变化{pair['delta']['net_cagr']*100:+.6f}个百分点；80日实际净年化{pair['candidate_metrics']['net_cagr']:.6%}，实际闭合{pair['candidate_metrics']['closed_trades']}。\n\n"
text+='新源码仅一处hold guard60→120；h60实际FULL与原签名筛选的金融账本逐项一致、价格指纹及原参数相同，未把数据修订当成源码效果。该读回不是新加速gate，h80只取得真实FULL信用。\n\n'
text+='长持有OPEN按真实期末市值进入权益及年化，不计实际CLOSED；固定h80的交易容量不能被机械拆单补足。直接完整账户与原三门保持，连续年度、费用、最终数量见scientific_diagnosis。边界是否继续由实际pair及根会话判断承接，不由四项数量或0达标自动停止。\n'
(exp/'04_conclusion.md').write_text(text,encoding='utf-8',newline='\n')
supp=exp/'supplementary'; supp.mkdir(exist_ok=False)
for p in [task/'independent_account_check.py',task/'accelerator.py',root/'.tmp/s012_build_full_checkpoint.py',Path(__file__).resolve()]:
 shutil.copyfile(p,supp/p.name)
assert experiment_source_sha256(exp,tuple(binding['source_files']))==binding['source_sha256']
if not comparison['qualified']:
 manifest=build_experiment_manifest(exp,{'strategy_id':'S012','experiment_id':exp.name,'symbol':'518850.SH',
  'development_cutoff':'2026-09-30','outcome':'FAIL','economic_outcome':'NO_QUALIFIED','complete_rex':True,
  'receipt_sha256':receipt['receipt_sha256'],'source_sha256':binding['source_sha256'],'successful_full':4,'qualified':0,
  'independent_account_audit':'PASS','direct_source_extension':'PASS','stage_three_complete':False})
 assert validate_experiment_archive(exp)==manifest
print(json.dumps({'status':'PASS','pairs':pairs,'h60_financial_ledgers_match':True,'qualified':comparison['qualified']},ensure_ascii=False))
