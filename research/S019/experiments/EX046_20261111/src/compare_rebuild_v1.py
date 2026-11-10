"""Complete-panel paired diagnostics of reversible risk allocation; no account replay."""
import argparse
from bisect import bisect_left, bisect_right
from collections import defaultdict
from hashlib import sha256
import importlib.util
import os
from pathlib import Path
from statistics import mean, median
import sys
from time import perf_counter

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
sys.dont_write_bytecode = True
HELPER = ROOT/'research/S019/experiments/EX044_20261110/src/compare_participation.py'
HELPER_SHA = '9b7b633dabe52c188726fdd5b54a943a73fa3f977c4cc74e946459f4df55267f'
assert sha256(HELPER.read_bytes()).hexdigest()==HELPER_SHA
spec = importlib.util.spec_from_file_location('rebuild_path_helper',HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
read,save,digest = module.read,module.save,module.digest


def risk_dynamics(run):
    fills = defaultdict(list)
    for f in run['fills']:
        fills[f['cycle_id']].append(f)
    trades = {t['cycle_id']:t for t in run['trades']}
    intervals = sorted((min(f['executed_at'] for f in fs),
                        max(f['executed_at'] for f in fs) if trades[cid]['status']=='CLOSED' else None,cid)
                       for cid,fs in fills.items())
    starts = [x[0] for x in intervals]
    fractions = defaultdict(lambda:1.)
    rises,partial_targets = {},set()
    for d in run['decisions']:
        facts = module.helper.facts(d)
        if 'risk_fraction' not in facts:
            continue
        time = d['execution_start']
        i = bisect_right(starts,time)-1
        assert i>=0
        entry,end,cid = intervals[i]
        assert entry<time and (end is None or time<=end)
        fraction = float(facts['risk_fraction'])
        previous = fractions[cid]
        if d['target']>0 and fraction>previous+1e-12:
            rises[d['decision_id']] = {'cycle_id':cid,'time':time,'before':previous,'after':fraction,'target':d['target']}
        if d['target']>0 and 0<fraction<1:
            partial_targets.add(cid)
        fractions[cid] = fraction
    orders = {o['order_id']:o for o in run['orders']}
    restore_fills = defaultdict(list)
    for fs in fills.values():
        for f in fs:
            if f['side']=='BUY' and orders[f['order_id']]['decision_id'] in rises:
                restore_fills[f['cycle_id']].append(f)
    points = run['account_points']
    point_times = [p['time'] for p in points]
    costs = {}
    for cid,fs in fills.items():
        entry = min(f['executed_at'] for f in fs)
        before = bisect_right(point_times,entry)-1
        capital = points[before]['equity'] if before>=0 else 100000.
        costs[cid] = {'entry_at':entry,'status':trades[cid]['status'],
                      'entry_equity':capital,'fees':sum(f['fees'] for f in fs),
                      'fees_over_entry_equity':sum(f['fees'] for f in fs)/capital,
                      'gross_turnover_over_entry_equity':sum(f['quantity']*f['price'] for f in fs)/capital,
                      'actual_fills':len(fs)}
    cycles = []
    for cid in sorted({r['cycle_id'] for r in rises.values()}):
        trade = trades[cid]
        fs = sorted(fills[cid],key=lambda f:f['executed_at'])
        rf = sorted(restore_fills[cid],key=lambda f:f['executed_at'])
        entry = fs[0]['executed_at']
        entry_i = bisect_right(point_times,entry)-1
        entry_equity = points[entry_i]['equity'] if entry_i>=0 else 100000.
        item = {'cycle_id':cid,'entry_at':entry,'status':trade['status'],
                'risk_increase_decisions':sum(r['cycle_id']==cid for r in rises.values()),
                'actual_restore_buy_fills':len(rf),'actual_restore_buy_fees':sum(f['fees'] for f in rf),
                'full_cycle_fees_over_entry_equity':costs[cid]['fees_over_entry_equity'],
                'restore_buy_fees_over_entry_equity':sum(f['fees'] for f in rf)/entry_equity,
                'first_actual_restore_at':rf[0]['executed_at'] if rf else None}
        if trade['status']=='CLOSED':
            exit_at = fs[-1]['executed_at']
            item.update(exit_at=exit_at,net_return=trade['net_return'],net_pnl=trade['net_pnl'],
                        pnl_over_entry_equity=trade['net_pnl']/entry_equity)
            if rf:
                before = bisect_left(point_times,rf[0]['executed_at'])-1
                after = bisect_left(point_times,exit_at)
                assert after<len(points)
                capital = points[before]['equity'] if before>=0 else 100000.
                item['post_first_restore_marked_account_return'] = points[after]['equity']/capital-1
                item['post_restore_measurement_start'] = point_times[before] if before>=0 else 'INITIAL_CASH'
                item['post_restore_measurement_end'] = point_times[after]
                item['post_restore_fees_over_starting_marked_equity'] = sum(
                    f['fees'] for f in fs if f['executed_at']>=rf[0]['executed_at'])/capital
        cycles.append(item)
    closed_costs = [c['fees_over_entry_equity'] for c in costs.values() if c['status']=='CLOSED']
    return {'risk_increase_decisions':len(rises),'risk_increase_cycles':len(cycles),
            'partial_target_cycles':len(partial_targets),'actual_restore_buy_cycles':len(restore_fills),
            'actual_restore_buy_fills':sum(len(fs) for fs in restore_fills.values()),
            'actual_restore_buy_fees':sum(f['fees'] for fs in restore_fills.values() for f in fs),
            'mean_closed_cycle_fees_over_entry_equity':mean(closed_costs) if closed_costs else None,
            'median_closed_cycle_fees_over_entry_equity':median(closed_costs) if closed_costs else None,
            'cycle_costs':list(costs.values()),'cycles':cycles}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment',type=Path,default=ROOT/'research/S019/experiments/EX046_20261111')
    args = parser.parse_args()
    work = args.experiment.resolve()
    assert work.is_relative_to(ROOT/'research/S019/experiments')
    path = work/'others/results.json'
    if not path.exists() or read(path)['status']!='COMPLETE':
        raise SystemExit('NOT_READY: completed full R4 design required before any account reads')
    started = perf_counter()
    results = read(path)
    design = read(work/'protocols/anchors.json')
    specs = read(work/'protocols/specs.json')['specs']
    assert set(results['accounts'])=={s['label'] for s in specs}
    assert len(specs)==design['design_configurations'] and len(specs)<=27
    source = {'analysis_sha256':digest(Path(__file__)),'ex044_helper_sha256':HELPER_SHA,
              'ex043_helper_sha256':module.EXPECTED_HELPER,
              'reader_sha256':digest(ROOT/'research/S019/experiments/EX013_20261110/src/runner.py'),
              'strategy_file_sha256':digest(work/'src/strategy.py'),
              'specs_sha256':digest(work/'protocols/specs.json'),'anchors_sha256':digest(work/'protocols/anchors.json')}
    scratch = ROOT/'.tmp/s019-rebuild-comparison'
    module.WORK,module.SCRATCH = work,scratch
    module.helper.WORK,module.helper.SCRATCH = work,scratch/'helper'
    module.helper.SCRATCH.mkdir(parents=True,exist_ok=True)
    accounts,exposures,dynamics,modes = {},{},{},{}
    for s in specs:
        key = s['label']
        row = results['accounts'][key]
        assert row['parameters']==s['parameters']
        risk_path = scratch/(row['account_ref']['sha256']+'.risk.json')
        binding = {'source':source,'reference':row['account_ref'],'content_hash':row['content_hash']}
        if risk_path.exists():
            cached = read(risk_path)
            assert cached['binding']==binding
            accounts[key],exposures[key],modes[key] = module.read_with_exposure(row,source)
            dynamics[key] = cached['value']
        else:
            captured = {}
            public_reader = module.helper.read_account

            def capture(account_path):
                ref,payload = public_reader(account_path)
                captured.update(risk_dynamics(payload['runs']['candidate']))
                return ref,payload

            module.helper.read_account = capture
            try:
                accounts[key],exposures[key],modes[key] = module.read_with_exposure(row,source)
            finally:
                module.helper.read_account = public_reader
            assert captured, 'Partial cache requires explicit recovery before resuming'
            dynamics[key] = captured
            save(risk_path,{'binding':binding,'value':captured})
        if row['parameters']['exit_policy']!='ramp_rebuild':
            assert dynamics[key]['risk_increase_decisions']==0
        print('READ',key,modes[key],flush=True)
    comparisons,spans = [],[]
    for anchor in design['anchors']:
        members = anchor['members']
        for level in ('low','center','high'):
            left = members['ramp_rebuild'][level]
            for policy in ('ramp','hard'):
                right = members[policy][level]
                p,q = results['accounts'][left]['parameters'],results['accounts'][right]['parameters']
                assert {k:v for k,v in p.items() if k!='exit_policy'}=={k:v for k,v in q.items() if k!='exit_policy'}
                c = module.paired(left,right,exposures,accounts)
                c.update(anchor=anchor['name'],atr_level=level,baseline_policy=policy)
                base_by_entry = {t['entry_at']:t for t in accounts[right]['cycles']}
                base_costs = {t['entry_at']:t for t in dynamics[right]['cycle_costs']}
                affected = []
                for cycle in dynamics[left]['cycles']:
                    if cycle['status']!='CLOSED' or cycle['actual_restore_buy_fills']==0:
                        continue
                    b = base_by_entry.get(cycle['entry_at'])
                    affected.append({**cycle,'baseline_cycle':b,
                        'baseline_cycle_costs':base_costs.get(cycle['entry_at']),
                        'normalized_pnl_delta':cycle['pnl_over_entry_equity']-b['pnl_over_entry_equity'] if b else None})
                c['actually_restored_closed_cycles'] = affected
                c['restored_cycle_outcomes'] = {
                    'cycles':len(affected),'positive_cycle_count':sum(t['net_pnl']>0 for t in affected),
                    'negative_cycle_count':sum(t['net_pnl']<0 for t in affected),
                    'positive_post_restore_marked_account_count':sum(t['post_first_restore_marked_account_return']>0 for t in affected),
                    'negative_post_restore_marked_account_count':sum(t['post_first_restore_marked_account_return']<0 for t in affected)}
                comparisons.append(c)
        for policy,levels in members.items():
            keys = [levels[x] for x in ('low','center','high')]
            spans.append({'anchor':anchor['name'],'policy':policy,'labels':keys,
                          'six_gate_pass_count':sum(accounts[k]['metrics']['eligible'] for k in keys),
                          'ranges':{metric:{'min':min(v),'max':max(v),'spread':max(v)-min(v)}
                                    for metric in ('nar','drawdown','calmar','fees')
                                    for v in [[accounts[k]['metrics'][metric] for k in keys]]}})
    compact = {key:{**{k:v for k,v in a.items() if k not in ('cycles','sessions','daily_returns','ramp_reductions')},
                   'candidate_id':results['accounts'][key]['candidate_id'],
                   'parameters':results['accounts'][key]['parameters'],'content_hash':results['accounts'][key]['content_hash'],
                   'request_sha256':results['accounts'][key]['request_sha256'],
                   'risk_dynamics':dynamics[key],
                   'largest_losses':sorted(a['cycles'],key=lambda c:c['pnl_over_entry_equity'])[:5]}
               for key,a in accounts.items()}
    out = {'status':'COMPLETE','new_accounts':0,'unique_design_accounts':len(specs),'sources':source,
           'results_sha256':digest(path),'anchors':design,'accounts':compact,'comparisons':comparisons,
           'three_atr_spans':spans,'read_modes':modes,'elapsed_seconds':perf_counter()-started,
           'method':['All prescribed configurations and same-parameter rebuild-minus-ramp/hard comparisons retained.',
                     'Risk increases count only positive-target holding decisions; actual restoration BUY fills are linked to those exact decisions, excluding constant-target rebalancing.',
                     'Post-first-restore return measures total marked account equity from the last valuation strictly before restoration BUY to the first valuation at/after cycle exit; includes pre-existing exposure and fees.',
                     'Total fees accompany per-cycle fees/entry equity, restoration BUY fees/entry equity, and post-restoration fees/start equity. Cash fee differences reflect account scale as well as activity.',
                     'Both winning/losing restored cycles and matched normalized PnL differences retained; share-count compounding does not define timing.',
                     'Original six gates and three-ATR spans are separate; 27-design mechanism study does not replace formal 80% full-neighborhood self-check.']}
    save(work/'others/rebuild_comparison.json',out)
    lines = ['# R4 恢复仓位完整配对比较','',f"完整读取 {len(specs)} 个既有账户；新增账户 0。",'',
             '|锚点|退出|六门达标/3|NAR范围|Calmar范围|MDD范围|','|---|---|---:|---|---|---|']
    for g in spans:
        r = g['ranges']
        lines.append(f"|{g['anchor']}|{g['policy']}|{g['six_gate_pass_count']}|{r['nar']['min']:.2%}–{r['nar']['max']:.2%}|"
                     f"{r['calmar']['min']:.4f}–{r['calmar']['max']:.4f}|{r['drawdown']['min']:.2%}–{r['drawdown']['max']:.2%}|")
    lines.extend(['','JSON 覆盖全部同参数成对差、年度与正负集中性、实际恢复买入、恢复周期最终及后段损益、最大亏损、MDD 区间和已见 11 月反例。',
                  '恢复后段收益按整个账户标记权益计算，包含原有持仓；新增买入的独立贡献由同参数对照帮助解释。',
                  '此处为三档机制比较，正式完整邻域通过率仍按阶段四协议执行。','',
                  f"分析源码 SHA256：`{source['analysis_sha256']}`",'','完整结果：`others/rebuild_comparison.json`。'])
    (work/'others/rebuild_comparison.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print('REBUILD_ANALYSIS_COMPLETE',len(specs),len(comparisons),flush=True)


if __name__=='__main__':
    main()
