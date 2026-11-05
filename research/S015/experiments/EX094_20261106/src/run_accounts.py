"""Explicit V4 migration account comparison; no frozen package mutation."""
from pathlib import Path
from datetime import date
import importlib.util,json,sys
from dataclasses import replace
from hashlib import sha256
import shutil
import pandas as pd
from czsc_trader.application import create_experiment,ExperimentRequest
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.equity_replay import materialize_equity

ROOT=Path.cwd();OUT=ROOT/'.tmp/rsch-frozen-v4-upgrade/S015';OUT.mkdir(parents=True,exist_ok=True)
original=ROOT/'research/S015/experiments/EX092_20261105/src/plan_context.py'
text=original.read_text(encoding='utf-8')
namespace={}
exec(text[:text.index('ROOT=')],namespace)
namespace.update(ROOT=ROOT,HOME=OUT,OUT=OUT,INPUT=ROOT/'research/S015/experiments/EX087_20261105/others',ZONE=namespace['ZoneInfo']('Asia/Shanghai'))
exec(text[text.index('def read('):],namespace)
context,sources,spec=namespace['frozen_context']()
for key in ('ExperimentRef','EquityEvaluationRequest','TimeInterval','ResearchExecutionSession','publish_evidence','EvaluationEvidenceWrite','at','SourceRef','EvaluationBenchmark','EquityBuyHold'):
 globals()[key]=namespace[key]
planfile=OUT/'experiment.json'
if planfile.exists():
 exp=ExperimentRef.from_dict(json.loads(planfile.read_text(encoding='utf-8')))
else:
 exp=create_experiment(context,ExperimentRequest('冻结S015-v1原生V4迁移等价性验证','保留原信号、锁定现金周期预算和补买规则，验证旧冻结账户与原生V4的全期标准及双倍费用等价性；不改变研究参数。',date(2026,11,6)))
 planfile.write_text(json.dumps(exp.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
home=exp.resolve(ROOT)
(home/'src'/'run_accounts.py').write_text(Path(__file__).read_text(encoding='utf-8'),encoding='utf-8')
source_root=ROOT/'research/S015/runtime_upgrade_v4'
shutil.copyfile(ROOT/'research/shared/runtime_upgrade_v4/cycle_planner.py',source_root/'cycle_planner.py')
module_spec=importlib.util.spec_from_file_location('s015_upgrade_builder',source_root/'candidate.py');module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
params=json.loads((ROOT/'.tmp/rsch-frozen-v4-upgrade/S015-v1-definition.json').read_text(encoding='utf-8'))['parameters']['values']
candidate=module.build_candidate(params,observation_source=SourceRef('s015-saved-tushare-observations','ex087-v1'))
(OUT/'candidate.json').write_text(json.dumps(candidate.payload,ensure_ascii=False,indent=2),encoding='utf-8')
oldrefs=json.loads((ROOT/'research/S015/experiments/EX087_20261105/others/input_sources.json').read_text(encoding='utf-8'))['old_accounts']
results=[]
with ResearchExecutionSession(context,experiment=exp) as execution:
 for scenario,fee,key in [('STANDARD',.001,'standard'),('FEE_X2',.002,'fee_x2')]:
  request=EquityEvaluationRequest(exp,candidate,TimeInterval(at(date(2025,1,2),9,30),at(date(2026,10,21),15)),date(2024,9,9),sources,100000.,fee,window_id='full',scenario_id=scenario,measurement_tier='FORMAL' if scenario=='STANDARD' else 'STRESS',benchmark=EvaluationBenchmark(EquityBuyHold(spec)),drawdown_basis='SESSION_CLOSE',concentration_basis='TOP_DECILE')
  prepared=context.evaluation.prepare(request,execution=execution)
  outcome,=context.evaluation.evaluate_many((prepared,),execution=execution)
  if outcome.result is None:raise RuntimeError(str(outcome.error))
  reference=publish_evidence(context,EvaluationEvidenceWrite(exp,'migration-'+scenario,prepared,outcome.result),execution=execution)
  oldref=EvidenceRef.from_dict(oldrefs[key]);content=oldref.resolve(ROOT).read_bytes();assert sha256(content).hexdigest()==oldref.sha256
  oldpayload=json.loads(content);oldrun=next(r for r in oldpayload['runs'] if r['window_id']=='full');old=oldrun['replay_evidence']
  path=reference.resolve(ROOT);newpayload=materialize_equity(path.read_bytes(),lambda r:(path.parent/(r['sha256']+'.json')).read_bytes()).payload;new=newpayload['runs']['candidate']
  mismatches=[];maxfill={k:0. for k in ('price','quantity','fees')};maxdaily={k:0. for k in ('cash','quantity','close','equity')}
  if len(old['fills'])!=len(new['fills']):mismatches.append('fill_count')
  for i,(a,b) in enumerate(zip(old['fills'],new['fills'])):
   if a['side']!=b['side'] or a['fill_time'][:10]!=pd.Timestamp(b['interval_start']).tz_convert('Asia/Shanghai').date().isoformat():mismatches.append('fill_identity_'+str(i))
   for k in maxfill:maxfill[k]=max(maxfill[k],abs(a[k]-b[k]))
  if len(old['account_daily'])!=len(new['account_daily']):mismatches.append('daily_count')
  for i,(a,b) in enumerate(zip(old['account_daily'],new['account_daily'])):
   if a['date'][:10]!=b['session']:mismatches.append('daily_date_'+str(i))
   for k in maxdaily:maxdaily[k]=max(maxdaily[k],abs(a[k]-b[k]))
  if max(maxfill.values())>1e-8:mismatches.append('fill_numeric')
  if max(maxdaily.values())>1e-8:mismatches.append('daily_numeric')
  row={'scenario':scenario,'status':'PASS' if not mismatches else 'FAIL','old_reference':oldrefs[key],'new_reference':reference.to_dict(),'mismatches':mismatches,'old_fills':len(old['fills']),'new_fills':len(new['fills']),'old_sessions':len(old['account_daily']),'new_sessions':len(new['account_daily']),'max_fill_difference':maxfill,'max_daily_difference':maxdaily}
  results.append(row);(OUT/('account_'+scenario+'.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(row,ensure_ascii=False),flush=True)
(OUT/'accounts.json').write_text(json.dumps({'experiment':exp.to_dict(),'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
