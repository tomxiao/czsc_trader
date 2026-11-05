"""Run a native V4 S011 account on retained exact-cutoff data."""
from pathlib import Path
from datetime import date
import importlib.util,json,sys,shutil
from hashlib import sha256
from copy import deepcopy
import pandas as pd
from dataflows import Dataset,ProviderBinding,ProviderConfig
from czsc_trader.application import create_experiment,ExperimentRequest
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.equity_replay import materialize_equity

ROOT=Path.cwd();OUT=ROOT/'.tmp/rsch-frozen-v4-upgrade/S011';OUT.mkdir(parents=True,exist_ok=True)
retained=OUT/'full'
meta=json.loads((retained/'data.json').read_text(encoding='utf-8'))
observations={Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY:('market',pd.read_parquet(retained/'market.parquet')),
              Dataset.GLOBAL_INDEX_DAILY:('spx',pd.read_parquet(retained/'spx.parquet'))}
def observation(request):
 name,frame=observations[request.dataset];days=pd.to_datetime(frame.Date)
 if request.start < str(days.min().date()) or request.end > '2026-09-30':raise ValueError('outside verified source')
 return frame.loc[(days>=pd.Timestamp(request.start))&(days<pd.Timestamp(request.end)+pd.Timedelta(days=1))].copy(),deepcopy(meta[name]['metadata'])
observation_bindings={dataset:ProviderBinding('s011-retained-cutoff','v1',observation) for dataset in observations}

original=ROOT/'research/S015/experiments/EX092_20261105/src/plan_context.py';text=original.read_text(encoding='utf-8')
namespace={};exec(text[:text.index('ROOT=')],namespace)
namespace.update(ROOT=ROOT,HOME=OUT,OUT=OUT,INPUT=ROOT/'research/S015/experiments/EX087_20261105/others',ZONE=namespace['ZoneInfo']('Asia/Shanghai'),observation_bindings=observation_bindings,RETAINED=retained)
body=text[text.index('def read('):]
body=body.replace("ResearchBatchRef('S015')","ResearchBatchRef('S011')").replace("'s015-saved-tushare-raw'","'s011-retained-tushare-raw'").replace("'s015-saved-tushare-observations'","'s011-retained-tushare-observations'")
body=body.replace('last=date(2026,10,21)','last=date(2026,9,30)').replace('ProviderConfig(bindings={},equity_bindings=bindings)','ProviderConfig(bindings=observation_bindings,equity_bindings=bindings)')
body=body.replace("minute=pd.read_parquet(INPUT/'intraday_complete.parquet')","minute=pd.read_parquet(RETAINED/'bars.parquet')")
body=body.replace("limits=pd.read_parquet(INPUT/'limits_complete.parquet')","raw=raw.loc[pd.to_datetime(raw.Date).dt.date<=last].copy()\n    hfq=hfq.loc[pd.to_datetime(hfq.Date).dt.date<=last].copy()\n    limits=pd.read_parquet(INPUT/'limits_complete.parquet')")
start=body.index('    # Verify refreshed source overlap');end=body.index('    def bar_frame',start)
body=body[:start]+body[end:]
body=body.replace("f['AvailableDate']=f.Date","f['AvailableDate']=[at(d,17) for d in stamps.dt.date]")
body=body.replace("'HFQ' if q.frequency is BarFrequency.DAILY else 'RAW'","'HFQ'").replace("BarFrequency.M30,1,86400*75,'RAW'","BarFrequency.M30,1,86400*75,'HFQ'").replace("100,.001,.01,0.)","100,.001,.003,0.)")
exec(body,namespace)
context,sources,spec=namespace['frozen_context']()
for key in ('ExperimentRef','EquityEvaluationRequest','TimeInterval','ResearchExecutionSession','publish_evidence','EvaluationEvidenceWrite','at','SourceRef','EvaluationBenchmark','EquityBuyHold'):
 globals()[key]=namespace[key]
planfile=OUT/'experiment.json'
if planfile.exists():exp=ExperimentRef.from_dict(json.loads(planfile.read_text(encoding='utf-8')))
else:
 exp=create_experiment(context,ExperimentRequest('冻结S011-v1原生V4迁移等价性验证','固定信号计时、周期数量锁及原研究截止；核对原生V4和当前冻结账户的逐笔成交及逐日权益。',date(2026,11,6)))
 planfile.write_text(json.dumps(exp.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
home=exp.resolve(ROOT);(home/'src'/'run_account.py').write_text(Path(__file__).read_text(encoding='utf-8'),encoding='utf-8')
source_root=ROOT/'research/S011/runtime_upgrade_v4';shutil.copyfile(ROOT/'research/shared/runtime_upgrade_v4/cycle_planner.py',source_root/'cycle_planner.py')
module_spec=importlib.util.spec_from_file_location('s011_upgrade_builder',source_root/'candidate.py');module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
params=json.loads((ROOT/'.tmp/rsch-frozen-v4-upgrade/S011-v1-definition.json').read_text(encoding='utf-8'))['parameters']['values']
candidate=module.build_candidate(params,observation_source=SourceRef('s011-retained-tushare-observations','ex087-v1'))
(OUT/'candidate.json').write_text(json.dumps(candidate.payload,ensure_ascii=False,indent=2),encoding='utf-8')
with ResearchExecutionSession(context,experiment=exp) as execution:
 request=EquityEvaluationRequest(exp,candidate,TimeInterval(at(date(2025,2,6),9,30),at(date(2026,9,30),15)),date(2024,12,26),sources,100000.,.001,window_id='full',scenario_id='STANDARD',measurement_tier='FORMAL',benchmark=EvaluationBenchmark(EquityBuyHold(spec)),drawdown_basis='SESSION_CLOSE',concentration_basis='TOP_DECILE')
 prepared=context.evaluation.prepare(request,execution=execution)
 outcome,=context.evaluation.evaluate_many((prepared,),execution=execution)
 if outcome.result is None:raise RuntimeError(str(outcome.error))
 reference=publish_evidence(context,EvaluationEvidenceWrite(exp,'migration-STANDARD',prepared,outcome.result),execution=execution)
 path=reference.resolve(ROOT);new=materialize_equity(path.read_bytes(),lambda r:(path.parent/(r['sha256']+'.json')).read_bytes()).payload['runs']['candidate']
 refs=json.loads((ROOT/'research/S011/experiments/EX084_20261026/others/S011-v1/published_equivalence_refs.json').read_text(encoding='utf-8'))
 old={};selected=[]
 for table in ('account_daily','fills'):
  ref=EvidenceRef.from_dict(next(r for r in refs if r['name']=='new_CONTINUOUS_'+table));content=ref.resolve(ROOT).read_bytes();assert sha256(content).hexdigest()==ref.sha256
  frame=pd.read_csv(ref.resolve(ROOT));stamp='date' if table=='account_daily' else 'fill_time';frame=frame.loc[frame[stamp].str[:10]<='2026-09-30']
  old[table]=frame.to_dict('records');selected.append(ref.to_dict())
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
 row={'status':'PASS' if not mismatches else 'FAIL','experiment':exp.to_dict(),'old_references':selected,'new_reference':reference.to_dict(),'mismatches':mismatches,'old_fills':len(old['fills']),'new_fills':len(new['fills']),'old_sessions':len(old['account_daily']),'new_sessions':len(new['account_daily']),'max_fill_difference':maxfill,'max_daily_difference':maxdaily}
 (OUT/'account_STANDARD.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(row,ensure_ascii=False),flush=True)
