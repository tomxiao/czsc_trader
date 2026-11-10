"""Read-only entry-state coverage around the 63-day relative-trend zero threshold."""
from bisect import bisect_right
from collections import defaultdict
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path.cwd()
WORK = ROOT/'.tmp/s019-stage2-resume'
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
sys.dont_write_bytecode = True
sys.path.insert(0,str(ROOT/'research/S019/experiments/EX013_20261110/src'))
from runner import read_account, metrics  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HELPER = ROOT/'research/S019/experiments/EX043_20261110/src/compare_exits.py'
spec = importlib.util.spec_from_file_location('quarter_episode_helper',HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def group(frame):
    if frame.empty:
        return {'n':0,'win_count':0,'mean_net_return':None,'median_net_return':None,'mean_pnl_over_entry_equity':None}
    return {'n':len(frame),'win_count':int((frame.net_return>0).sum()),
            'mean_net_return':float(frame.net_return.mean()),'median_net_return':float(frame.net_return.median()),
            'mean_pnl_over_entry_equity':float(frame.pnl_over_entry_equity.mean()),
            'tail_below_minus5pct':int((frame.net_return<-.05).sum()),
            'relative63_min':float(frame.relative63.min()),'relative63_max':float(frame.relative63.max()),
            'mean_initial_target':float(frame.allocation.mean())}


def analyze(candidate, path):
    ref,payload = read_account(path)
    assert payload['request']['candidate_id']==candidate
    run = payload['runs']['candidate']
    parameters = json.loads(payload['request']['candidate_definition']['parameters_json'])
    daily = run['account_daily']
    sessions = [x['session'] for x in daily]
    assert len(sessions)==1212 and sessions[-1]=='2026-10-30'
    episode = helper.episode(sessions,np.array([x['equity'] for x in daily]))
    orders = {x['order_id']:x for x in run['orders']}
    decisions = {x['decision_id']:x for x in run['decisions']}
    fills_by_cycle = defaultdict(list)
    for fill in run['fills']:
        fills_by_cycle[fill['cycle_id']].append(fill)
    point_times = [x['time'] for x in run['account_points']]
    rows,open_rows = [],[]
    for trade in run['trades']:
        fills = sorted(fills_by_cycle[trade['cycle_id']],key=lambda f:f['executed_at'])
        assert fills and fills[0]['side']=='BUY'
        decision = decisions[orders[fills[0]['order_id']]['decision_id']]
        facts = {x['key']:x['text'] for x in decision['explanation']['basis']}
        relative = float(facts['relative63'])
        allocation = float(facts['allocation'])
        multiplier = float(facts['participation_factor'])
        quarter_multiplier = 1. if relative>0 else parameters['weak_fraction']
        assert abs(allocation-quarter_multiplier*multiplier)<1e-10
        entry = fills[0]['executed_at']
        previous = bisect_right(point_times,entry)-1
        capital = run['account_points'][previous]['equity'] if previous>=0 else 100000.
        row = {'entry_at':entry,'year':entry[:4],'relative63':relative,
               'quarter_state':'STRONG' if relative>0 else 'WEAK','quarter_multiplier':quarter_multiplier,
               'participation_multiplier':multiplier,'allocation':allocation}
        if trade['status']!='CLOSED':
            open_rows.append(row)
            continue
        assert fills[-1]['side']=='SELL'
        exit_at = fills[-1]['executed_at']
        row.update(exit_at=exit_at,net_return=trade['net_return'],net_pnl=trade['net_pnl'],
                   pnl_over_entry_equity=trade['net_pnl']/capital,
                   overlaps_maximum_drawdown=entry[:10]<=episode['trough'] and exit_at[:10]>=episode['peak'])
        rows.append(row)
    frame = pd.DataFrame(rows)
    assert len(rows)==run['metrics']['closed_cycles']
    bands = {}
    for width in (.05,.1,.2):
        selected = frame.loc[frame.relative63.abs()<=width]
        bands[str(width)] = {'coverage_fraction':len(selected)/len(frame),'all':group(selected),
                            'weak':group(selected.loc[selected.relative63<=0]),
                            'strong':group(selected.loc[selected.relative63>0]),
                            'annual':{year:group(selected.loc[selected.year==year]) for year in sorted(frame.year.unique())},
                            'mdd_overlap_count':int(selected.overlaps_maximum_drawdown.sum()),
                            'mdd_overlap_cycles':selected.loc[selected.overlaps_maximum_drawdown].to_dict('records'),
                            'largest_losses':selected.sort_values('pnl_over_entry_equity').head(5).to_dict('records'),
                            'largest_gains':selected.sort_values('pnl_over_entry_equity',ascending=False).head(5).to_dict('records')}
    return {'candidate_id':candidate,'account_ref':ref.to_dict(),
            'content_hash':payload['request']['content_sha256'],
            'definition':payload['request']['candidate_definition'],
            'metrics':metrics(run,payload['runs']['buy_hold']['metrics']['daily_max_drawdown']),
            'quarter_rule':'quarter_multiplier = 1 if relative63 > 0 else weak_fraction',
            'quarter_multiplier_jump':1-parameters['weak_fraction'],
            'mdd_episode':episode,'all_closed':group(frame),'bands':bands,'closed_cycles':rows,'open_entries':open_rows}


def main():
    accounts = {}
    for candidate,path in [('C0355','research/S019/experiments/EX041_20261110/others/C0355_center_ref.json'),
                           ('C0678','research/S019/experiments/EX044_20261110/others/ramp_linear10_center_account.json')]:
        accounts[candidate] = analyze(candidate,ROOT/path)
        print('READ',candidate,accounts[candidate]['all_closed']['n'],flush=True)
    out = {'status':'COMPLETE','new_accounts':0,'source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
           'reader_sha256':sha256((ROOT/'research/S019/experiments/EX013_20261110/src/runner.py').read_bytes()).hexdigest(),
           'episode_helper_sha256':sha256(HELPER.read_bytes()).hexdigest(),'accounts':accounts,
           'method':['Actual first BUY links to the decision that set entry allocation; entry facts were available at that decision.',
                     'Nested symmetric bands are fixed at |relative63|<=.05/.1/.2; yearly grouping uses actual entry year.',
                     'Full trade returns and PnL/entry-equity are descriptive; overlapping MDD cycles can extend outside the MDD dates.',
                     'Both complete account configurations have been seen; group outcomes do not isolate a zero-threshold causal effect.',
                     'No new experimental design is selected automatically from these statistics.']}
    (WORK/'quarter_threshold_diagnostics.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({k:{b:v['all']['n'] for b,v in a['bands'].items()} for k,a in accounts.items()}))


if __name__=='__main__':
    main()
