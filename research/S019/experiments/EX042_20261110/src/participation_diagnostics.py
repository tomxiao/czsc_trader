import sys
import os
import importlib.util
from pathlib import Path
import json
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[5]
OWNER=Path(__file__).resolve().parents[1]
OUT=OWNER/'others'
WORK=OWNER.parent/'EX041_20261110'
SCRATCH=ROOT/'.tmp/s019-stage2-resume'
SCRATCH.mkdir(parents=True,exist_ok=True)
os.environ.update(TEMP=str(SCRATCH),TMP=str(SCRATCH),OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
sys.path.insert(0,str(ROOT/'research/S019/experiments/EX013_20261110/src'))
from runner import read_account  # noqa: E402
from czsc_trader import research_tools as d  # noqa: E402

def read(path):
    return json.loads(path.read_bytes())
def save(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')

prior=read(WORK/'others/exit_diagnostics.json')
assert prior['status']=='COMPLETE'
accounts=prior['centers']['C0355']['accounts']
helper_path=OWNER.parent/'EX040_20261110/src/prior_diagnostics.py'
assert sha256(helper_path.read_bytes()).hexdigest()==prior['helper_sha256']
spec=importlib.util.spec_from_file_location('s019_full_path_helper',helper_path)
helper=importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
values={}
bindings={}
for label,a in accounts.items():
    typed=d.EvidenceRef.from_dict(a['reference'])
    header_raw=typed.resolve(ROOT).read_bytes()
    assert sha256(header_raw).hexdigest()==typed.sha256
    request=json.loads(header_raw)['request']
    assert request['content_sha256']==a['content_sha256']
    assert request['candidate_definition']['source_sha256']==a['strategy_source_sha256']
    assert json.loads(request['candidate_definition']['parameters_json'])==a['parameters']
    bindings[label]={'reference':a['reference'],'content_sha256':a['content_sha256'],
        'strategy_source_sha256':a['strategy_source_sha256'],'window':request['window'],
        'fee_rate':request['fee_rate'],'drawdown_basis':request['drawdown_basis']}
    cache_path=ROOT/f".tmp/s019-stage4-041/exit/{a['reference']['sha256']}.json"
    if cache_path.exists():
        cached=read(cache_path)
    else:
        reference_path=SCRATCH/f"{a['reference']['sha256']}_ref.json"
        save(reference_path,a['reference'])
        cached={'helper_sha256':prior['helper_sha256'],'reference':a['reference'],'parameters':a['parameters'],
            'value':helper.analyze(reference_path,a['parameters'])}
        cache_path.parent.mkdir(parents=True,exist_ok=True)
        save(cache_path,cached)
    assert cached['helper_sha256']==prior['helper_sha256'] and cached['reference']==a['reference']
    assert cached['parameters']==a['parameters']
    values[label]=cached['value']
statistics={}
for label,value in values.items():
    cycles=pd.DataFrame(value['cycles'])
    ret=np.asarray(value['daily_returns'])
    logs=np.log1p(ret)
    statistics[label]={'reference':value['reference'],'parameters':value['parameters'],'metrics':value['metrics'],
        'closed_cycles':len(cycles),'wins':int((cycles.net_pnl>0).sum()),'losses':int((cycles.net_pnl<0).sum()),
        'cycle_net_return_mean':float(cycles.net_return.mean()),'cycle_net_return_median':float(cycles.net_return.median()),
        'cycle_net_return_q10':float(cycles.net_return.quantile(.1)),'cycle_net_return_q90':float(cycles.net_return.quantile(.9)),
        'cycle_loss_below_5pct':int((cycles.net_return<-.05).sum()),
        'exit_reason_counts':value['exit_reason_counts'],'mdd_episode':value['mdd_episode'],
        'log_growth':float(logs.sum()),'log_growth_2025_2026_share':float(logs[[s>='2025-01-01' for s in value['sessions']]].sum()/logs.sum())}
base=values['CENTER']
base_cycles={x['entry_at']:x for x in base['cycles']}
comparison={}
for label in ('P002','P005'):
    value=values[label]
    cycles={x['entry_at']:x for x in value['cycles']}
    common=set(cycles)&set(base_cycles)
    changed=[k for k in common if cycles[k]['exit_at']!=base_cycles[k]['exit_at']]
    unchanged=[k for k in common if k not in changed]
    logdelta=np.log1p(value['daily_returns'])-np.log1p(base['daily_returns'])
    dates=np.asarray(base['sessions'])
    mask=np.zeros(len(dates),dtype=bool)
    for k in changed:
        lo=min(cycles[k]['exit_at'],base_cycles[k]['exit_at'])[:10]
        hi=max(cycles[k]['exit_at'],base_cycles[k]['exit_at'])[:10]
        mask|=(dates>=lo)&(dates<=hi)
    for c in [cycles[k] for k in set(cycles)-common]+[base_cycles[k] for k in set(base_cycles)-common]:
        mask|=(dates>=c['entry_at'][:10])&(dates<=c['exit_at'][:10])
    comparison[label]={'common_entries':len(common),'same_entry_exit_cycles':len(unchanged),'changed_exit_cycles':len(changed),
        'perturbed_only_entries':len(set(cycles)-common),'center_only_entries':len(set(base_cycles)-common),
        'same_timing_mean_absolute_trade_return_delta':float(np.mean([abs(cycles[k]['net_return']-base_cycles[k]['net_return']) for k in unchanged])),
        'same_timing_max_absolute_trade_return_delta':float(max(abs(cycles[k]['net_return']-base_cycles[k]['net_return']) for k in unchanged)),
        'changed_exposure_calendar_days':int(mask.sum()),'total_calendar_days':len(mask),
        'changed_exposure_days_abs_log_difference_share':float(np.abs(logdelta[mask]).sum()/np.abs(logdelta).sum()),
        'net_log_growth_difference':float(logdelta.sum()),'net_log_growth_difference_outside_changed_exposure_days':float(logdelta[~mask].sum()),
        'annual_log_growth_differences':{str(y):float(logdelta[np.char.startswith(dates,str(y))].sum()) for y in range(2022,2027)},
        'common_winner_to_loss':sum(base_cycles[k]['net_pnl']>0 and cycles[k]['net_pnl']<0 for k in common),
        'common_loser_to_win':sum(base_cycles[k]['net_pnl']<0 and cycles[k]['net_pnl']>0 for k in common)}
save(SCRATCH/'C0355_center_ref.json',accounts['CENTER']['reference'])
ref,payload=read_account(SCRATCH/'C0355_center_ref.json')
run=payload['runs']['candidate']
decisions={x['decision_id']:x for x in run['decisions']}
orders={x['order_id']:x for x in run['orders']}
fills={}
for fill in run['fills']:
    fills.setdefault(fill['cycle_id'],[]).append(fill)
records=[]
for cycle_id,rows in fills.items():
    first=min(rows,key=lambda x:x['executed_at'])
    decision=decisions[orders[first['order_id']]['decision_id']]
    facts={x['key']:x['text'] for x in decision['explanation']['basis']}
    q=max(float(facts['participation']),float(facts['prior_participation']))
    record={'entry_at':first['executed_at'],'q':q,'relative63':float(facts['relative63']),
        'allocation':float(facts['allocation']),'long_strong':facts['long_strong']=='True',
        'opening_participation':float(facts['participation']),'prior_participation':float(facts['prior_participation'])}
    trade=next((t for t in run['trades'] if t['cycle_id']==cycle_id),None)
    record['closed']=trade is not None and trade['status']=='CLOSED'
    if record['closed']:
        record['cycle_net_return']=trade['net_return']
    records.append(record)
closed_ids={t['cycle_id'] for t in run['trades'] if t['status']=='CLOSED'}
intervals=[]
for cid,rows in fills.items():
    ordered=sorted(rows,key=lambda x:x['executed_at'])
    intervals.append((cid,ordered[0]['executed_at'],ordered[-1]['executed_at'] if cid in closed_ids else None))
active=[]
for decision in run['decisions']:
    facts={x['key']:x['text'] for x in decision['explanation']['basis']}
    if 'high_water' not in facts:
        continue
    cycle_id,= [cid for cid,start,end in intervals if start<decision['execution_start'] and (end is None or decision['execution_start']<=end)]
    active.append({'decision_at':decision['decision_at'],'cycle_id':cycle_id,
        'z':(float(facts['high_water'])-float(facts['price']))/float(facts['entry_atr']),
        'held':int(facts['held']),'stopped':facts['stopped']=='True'})
# cycle_before can be structured; normalized identity comes from the declared plan state.
for row in active:
    if isinstance(row['cycle_id'],dict):
        row['cycle_id']=row['cycle_id'].get('cycle_id')
active_frame=pd.DataFrame(active)
active_frame=active_frame.loc[active_frame.held<5]
tau=accounts['CENTER']['parameters']['participation_threshold']
closed=pd.DataFrame([r for r in records if r['closed']])
participation={'actual_entries':len(records),'closed_entries':len(closed),'threshold':tau,
    'q_quantiles':{str(q):float(closed.q.quantile(q)) for q in (0,.1,.25,.5,.75,.9,1)},
    'near_threshold':{},'all_entry_records':records}
for width in (.05,.10,.20):
    selected=closed.loc[(closed.q>=tau*(1-width))&(closed.q<=tau*(1+width))]
    participation['near_threshold'][str(width)]={'closed_count':len(selected),'wins':int((selected.cycle_net_return>0).sum()),
        'losses':int((selected.cycle_net_return<0).sum()),'mean_cycle_return':float(selected.cycle_net_return.mean()) if len(selected) else None,
        'median_cycle_return':float(selected.cycle_net_return.median()) if len(selected) else None,
        'mean_excluding_largest_for_description_only':float(selected.cycle_net_return.sort_values().iloc[:-1].mean()) if len(selected)>1 else None,
        'years':selected.entry_at.str[:4].value_counts().sort_index().to_dict()}
for label,selected in [('quiet',closed.loc[closed.q<tau]),('full',closed.loc[closed.q>=tau])]:
    participation[label]={'count':len(selected),'wins':int((selected.cycle_net_return>0).sum()),
        'mean_cycle_return':float(selected.cycle_net_return.mean()),'median_cycle_return':float(selected.cycle_net_return.median()),
        'loss_below_5pct':int((selected.cycle_net_return<-.05).sum()),
        'annual_mean':selected.groupby(selected.entry_at.str[:4]).cycle_net_return.mean().to_dict()}
risk={'pre_expiry_observed_holding_decisions':len(active_frame),'cycle_identity_non_null':int(active_frame.cycle_id.notna().sum()),
      'z_quantiles':{str(q):float(active_frame.z.quantile(q)) for q in (.5,.75,.9,.95,.99,1)},
      'observed_band_coverage':{str(level):{'decisions':int((active_frame.z>=level).sum()),
          'cycles':int(active_frame.loc[active_frame.z>=level,'cycle_id'].nunique())} for level in (1.5,2.,2.02,2.2,2.42,2.82)},
      'limitation':'Holding observations end at actual center exits. Exposure beyond them requires a new complete account, not extrapolation.'}
assert risk['cycle_identity_non_null']==risk['pre_expiry_observed_holding_decisions']
assert len(closed)==117 and len(base['sessions'])==1212
assert len(bindings)==3 and all(x['fee_rate']==.001 and x['drawdown_basis']=='SESSION_CLOSE' for x in bindings.values())
output={'status':'COMPLETE_READ_ONLY','new_strategy_accounts':0,'statistics':statistics,'full_path_comparisons':comparison,
    'participation':participation,'observed_atr_distance':risk,'source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
    'prior_exit_diagnostics_sha256':sha256((WORK/'others/exit_diagnostics.json').read_bytes()).hexdigest(),
    'implementation_bindings':bindings,'helper_sha256':prior['helper_sha256'],
    'public_reader_sha256':sha256((OWNER.parent/'EX013_20261110/src/runner.py').read_bytes()).hexdigest(),
    'proposed_participation_expression':{'q':'max(opening participation, prior participation)',
        'a0':'(1 if relative63>0 else 0.30)*(0.645+0.355*clip((q/1.175-(1-h))/(2*h),0,1))',
        'relative_half_widths':[.05,.10,.20],'allocation':'Fixed at entry as in the control; five-day cap and selected exit structure preserved.'},
    'tool_choice':'Public account reader, pandas and NumPy directly answer event coverage, position discontinuity and full-path contribution. No fitted predictive model required for this mechanism comparison.',
    'reviewed_report_sha256':{f'EX{i:03d}_20261110':sha256((OWNER.parent/f'EX{i:03d}_20261110/report.md').read_bytes()).hexdigest() for i in range(26,41)},
    'account_reference':ref.to_dict(),'limitations':['Previously seen development history; descriptive conditional groups.',
    'Closed cycle return distributions inherit the current allocation and exit rules.',
    'Nonzero differences in same-timing cycles include integer sizing, fees and compounding effects; no new timing implied.']}
save(OUT/'participation_diagnostics.json',output)
print(json.dumps({'stats':statistics,'comparisons':comparison,'participation':{k:v for k,v in participation.items() if k!='all_entry_records'},'risk':risk}))
