"""Independent exact gates, complete handoff and economic-path grouping."""
from pathlib import Path
from collections import defaultdict
import importlib.util,json
H=Path(__file__).resolve().parents[1];B=H.parent;ROOT=H.parents[3]
def read(p):return json.loads(p.read_bytes())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def mod(p,n):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def vector(r):return [r['runs'][w][k]*(1 if k=='net_return' else -1) for w in ('full','s011_common') for k in ('net_return','dd')]
def dominates(a,b):return all(x>=y for x,y in zip(vector(a),vector(b))) and any(x>y for x,y in zip(vector(a),vector(b)))
def main():
 assert not (H/'others/selection.json').exists()
 checker=mod(B/'EX062_20261024/src/publish_candidates.py','gate');rows=[];counts=[];groups=defaultdict(list)
 for ex in ('EX076_20261024','EX077_20261024','EX078_20261024'):
  result=read(B/ex/'others/results.json');assert len(result['rows'])==result['new_configurations'];assert result['formal_accounts']==2*len(result['rows']);assert result['serial_equal']
  for r in result['rows']:
   assert checker.center_pass(r)==r['both_center_pass'];r={**r,'origin_experiment':ex};rows.append(r);groups[tuple(r['runs'][w]['equity_sha256'] for w in ('full','s011_common'))].append(r['candidate_id'])
  counts.append({'experiment':ex,**{k:result[k] for k in ('new_configurations','formal_accounts','technical_accounts','center_pass_count')}})
 assert len({r['candidate_id'] for r in rows})==len(rows)==164
 assert len({json.dumps(r['parameters'],sort_keys=True) for r in rows})==164
 assert len({r['identity']['content_sha256'] for r in rows})==164
 for ex in ('EX077_20261024','EX078_20261024'):
  r=read(B/ex/'others/results.json');assert len(read(B/ex/'others/audit.json')['accounts'])==r['formal_accounts']
  trials=r['optuna'];initial=8 if '077' in ex else 132
  assert all(t['completed_before_ask']==initial+i//8*8 if '078' in ex or i<56 else True for i,t in enumerate(trials))
  # Batches can end at the 60-point fixed-grid boundary; verify real ask snapshots.
  completed=initial
  for p in sorted((B/ex/'others').glob('ask_*.json')):
   a=read(p);assert a['completed_before_ask']==completed;assert len(a['trials'])<=8;completed+=len(a['trials'])
  assert completed==initial+len(trials)
 assert read(B/'EX078_20261024/others/warm_start_check.json')['accounts_replayed']==132
 passing=[r for r in rows if r['both_center_pass']];front=[r for r in rows if not any(dominates(x,r) for x in rows)]
 chosen={r['candidate_id'] for r in passing+front}|{'C7600','C7601','C7604','C7605','C9039','C9040'}
 boundaries=[]
 for r in rows:
  p=r['parameters'];tags=[]
  if p['lookback'] in (2,10):tags.append('background_edge')
  if p['allocation']==.6:tags.append('allocation_edge')
  if p['minimum_repair_space']>=.018:tags.append('near_space_upper_edge')
  if not tags:continue
  f=r['runs']['full'];freq=f['frequency_median']>=6 and f['frequency_good']*10>=9*f['frequency_windows']
  dominators=[x['candidate_id'] for x in rows if dominates(x,r) and x['parameters']['lookback'] not in (2,10) and x['parameters']['allocation']>.6 and x['parameters']['minimum_repair_space']<.018]
  boundaries.append({'candidate':r['candidate_id'],'tags':tags,'center_pass':r['both_center_pass'],'full_frequency_pass':freq,'internal_dominators':dominators,'new_extension_signal':r['both_center_pass'] or (freq and not dominators)})
 result={'status':'EXACT_SELECTION_CHECK_PASS','counts':counts,'new_configurations':164,'formal_search_accounts':328,'formal_fee_accounts':12,'technical_accounts':8,'new_accounts_total':348,'equity_path_groups_two_windows':len(groups),'economic_grouping_scope':'Exact retained account_daily equity hashes in both windows; this is not full-ledger or independent-opportunity equivalence.','equity_path_alias_groups':[v for v in groups.values() if len(v)>1],'passing_ids':[r['candidate_id'] for r in passing],'passing_count':len(passing),'passing_equity_path_groups':len({tuple(r['runs'][w]['equity_sha256'] for w in ('full','s011_common')) for r in passing}),'frontier_ids':[r['candidate_id'] for r in front],'selected_ids':sorted(chosen),'selected_count':len(chosen),'passing_backgrounds':sorted({r['parameters']['lookback'] for r in passing}),'boundary_review':boundaries,'extension_triggered':any(x['new_extension_signal'] for x in boundaries),'rows':rows,'stage4':'NOT_EXECUTED_NOT_AUTHORIZED','new_fully_qualified':'NOT_EVALUATED','historical_qualification':'Existing 16 stage-four numeric passes unchanged; fixed-hold family recommendation remains suspended.'}
 save(H/'others/selection.json',result)
 print(json.dumps({k:v for k,v in result.items() if k not in ('rows','boundary_review')},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
