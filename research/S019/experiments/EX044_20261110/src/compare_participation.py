"""Read-only 24-account participation comparison, reusing frozen EX043 diagnostics."""
from collections import defaultdict
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / '.tmp/s019-ex044-participation-comparison'
os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                  NUMEXPR_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
sys.dont_write_bytecode = True
HELPER = WORK.parent / 'EX043_20261110/src/compare_exits.py'
EXPECTED_HELPER = 'e76c0e487c9e46d4f6c8f3f698ff41411eb46dcc271bd7fe09b6fde6c6c68e0a'
assert sha256(HELPER.read_bytes()).hexdigest() == EXPECTED_HELPER
spec = importlib.util.spec_from_file_location('ex043_readonly_comparison', HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
import numpy as np  # noqa: E402

helper.WORK, helper.SCRATCH = WORK, SCRATCH / 'helper'
helper.SCRATCH.mkdir(parents=True, exist_ok=True)
read, save, digest = helper.read, helper.save, helper.digest


def read_with_exposure(row, identity):
    cache = SCRATCH / (row['account_ref']['sha256'] + '.combined.json')
    binding = {'sources': identity, 'reference': row['account_ref'],
               'definition': row['definition'], 'content_hash': row['content_hash'],
               'request_sha256': row['request_sha256']}
    if cache.exists():
        cached = read(cache)
        assert cached['binding'] == binding
        return cached['value'], cached['exposure'], 'VERIFIED_DERIVED_CACHE'
    captured = {}
    public_reader = helper.read_account

    def capture(path):
        ref, payload = public_reader(path)
        run = payload['runs']['candidate']
        captured.update(
            decision_times=[d['execution_start'] for d in run['decisions']],
            targets=[d['target'] for d in run['decisions']],
            point_times=[p['time'] for p in run['account_points']],
            actual_weights=[p['quantity'] * p['close'] / p['equity'] for p in run['account_points']],
            daily_weights=[p['quantity'] * p['close'] / p['equity'] for p in run['account_daily']])
        return ref, payload

    helper_cache = helper.SCRATCH / (row['account_ref']['sha256'] + '.json')
    if helper_cache.exists():
        raise RuntimeError('Partial derived checkpoint without exposure; inspect and explicitly recover before resuming')
    helper.read_account = capture
    try:
        value, mode = helper.analyze(row, identity)
    finally:
        helper.read_account = public_reader
    assert captured and mode == 'PUBLIC_ACCOUNT_MATERIALIZATION'
    save(cache, {'binding': binding, 'value': value, 'exposure': captured})
    return value, captured, mode


def paired(left, right, exposures, accounts):
    a, b = accounts[left], accounts[right]
    x, y = exposures[left], exposures[right]
    assert x['decision_times'] == y['decision_times'] and x['point_times'] == y['point_times']
    target_delta = np.asarray(x['targets']) - np.asarray(y['targets'])
    actual_delta = np.asarray(x['actual_weights']) - np.asarray(y['actual_weights'])
    daily_delta = np.asarray(x['daily_weights']) - np.asarray(y['daily_weights'])
    target_active_changes = int(np.sum((np.asarray(x['targets']) > 0) != (np.asarray(y['targets']) > 0)))
    comparison = helper.compare(a, b)
    same_timing = (comparison['changed_exit_count'] == 0 and not comparison['other_only_closed_cycles']
                   and not comparison['baseline_only_closed_cycles'])
    # The previously noticed November cycle is retained as a prespecified counterexample, alongside all-path summaries.
    nov = {}
    for label, value in ((left, a), (right, b)):
        nov[label] = [c for c in value['cycles'] if c['entry_at'].startswith('2025-11-19')]
    return {'other': left, 'baseline': right,
            'metric_deltas': {k: a['metrics'][k] - b['metrics'][k] for k in ('nar', 'drawdown', 'calmar', 'fees')},
            'path': comparison,
            'allocation': {'decision_count': len(target_delta),
                           'changed_target_decisions': int(np.sum(np.abs(target_delta) > 1e-12)),
                           'target_active_state_changes': target_active_changes,
                           'max_absolute_target_difference': float(np.max(np.abs(target_delta))),
                           'mean_absolute_target_difference': float(np.mean(np.abs(target_delta))),
                           'mean_absolute_actual_weight_difference': float(np.mean(np.abs(actual_delta))),
                           'max_absolute_actual_weight_difference': float(np.max(np.abs(actual_delta))),
                           'mean_absolute_daily_weight_difference': float(np.mean(np.abs(daily_delta))),
                           'actual_point_count': len(actual_delta),
                           'closed_timing_identical': same_timing,
                           'interpretation': 'Primarily allocation paths: same closed entries/exits and target activity.'
                           if same_timing and target_active_changes == 0 else 'Timing/activity and allocation jointly differ.'},
            'previously_seen_november_cycle': nov}


def main():
    begun = perf_counter()
    results_path = WORK / 'others/results.json'
    if not results_path.exists():
        raise SystemExit('NOT_READY: results not yet created; no account reads started')
    results = read(results_path)
    if results['status'] != 'COMPLETE':
        raise SystemExit(f"NOT_READY: {results['status']}, {len(results['accounts'])}/24; no account reads started")
    specs = read(WORK / 'protocols/specs.json')['specs']
    labels = [s['label'] for s in specs]
    assert len(labels) == 24 and set(labels) == set(results['accounts'])
    prepared = read(WORK / 'protocols/prepared_request_manifest.json')
    assert {p['label'] for p in prepared} == set(labels)
    assert len({p['input_snapshot_sha256'] for p in prepared}) == 1
    assert len({p['benchmark_identity'] for p in prepared}) == 1
    assert all(results['accounts'][p['label']]['request_sha256'] == p['request_sha256'] for p in prepared)
    identity = {'analysis_sha256': digest(Path(__file__)), 'helper_sha256': EXPECTED_HELPER,
                'strategy_file_sha256': digest(WORK / 'src/strategy.py'),
                'reader_sha256': digest(WORK.parent / 'EX013_20261110/src/runner.py'),
                'specs_sha256': digest(WORK / 'protocols/specs.json')}
    accounts, exposures, reads = {}, {}, {}
    for s in specs:
        label = s['label']
        row = results['accounts'][label]
        assert row['parameters'] == s['parameters']
        accounts[label], exposures[label], reads[label] = read_with_exposure(row, identity)
        print('READ', label, reads[label], flush=True)
    groups, controls = defaultdict(list), {}
    for s in specs:
        p, label = s['parameters'], s['label']
        key = (p['exit_policy'], p['participation_policy'], p['participation_width'])
        groups[key].append(label)
        if p['participation_policy'] == 'hard':
            controls[(p['exit_policy'], p['participation_threshold'])] = label
    assert len(groups) == 8 and all(len(g) == 3 for g in groups.values()) and len(controls) == 6
    pairs = []
    for s in specs:
        p = s['parameters']
        if p['participation_policy'] == 'linear':
            control = controls[(p['exit_policy'], p['participation_threshold'])]
            fixed = {k:v for k,v in p.items() if k not in ('participation_policy', 'participation_width')}
            baseline_fixed = {k:v for k,v in results['accounts'][control]['parameters'].items()
                              if k not in ('participation_policy', 'participation_width')}
            assert fixed == baseline_fixed
            pairs.append(paired(s['label'], control, exposures, accounts))
    assert len(pairs) == 18
    spans = []
    for (exit_policy, policy, width), members in groups.items():
        thresholds = [results['accounts'][m]['parameters']['participation_threshold'] for m in members]
        assert sorted(thresholds) == sorted([1.175 * .95, 1.175, 1.175 * 1.05])
        spans.append({'exit_policy': exit_policy, 'participation_policy': policy, 'participation_width': width,
                      'members': members, 'thresholds': thresholds,
                      'eligible_count': sum(accounts[m]['metrics']['eligible'] for m in members),
                      'ranges': {k: {'min': min(values), 'max': max(values), 'spread': max(values)-min(values)}
                                 for k in ('nar', 'drawdown', 'calmar', 'fees')
                                 for values in [[accounts[m]['metrics'][k] for m in members]]}})
    compact = {label: {**{k:v for k,v in accounts[label].items() if k not in ('sessions','daily_returns','cycles')},
                       **{k:results['accounts'][label][k] for k in ('candidate_id','parameters','content_hash','request_sha256','definition')}}
               for label in labels}
    out = {'status': 'COMPLETE', 'account_count': 24, 'new_accounts': 0,
           'sources': identity, 'results_sha256': digest(results_path),
           'elapsed_seconds': perf_counter()-begun, 'read_modes': reads,
           'accounts': compact, 'family_threshold_spans': spans, 'linear_vs_matched_hard': pairs,
           'method': ['All 24 configurations retained; 18 matched pairs fix exit, threshold and remaining parameters.',
                      'Target changes and actual marked position value/equity are separate; share counts never define timing.',
                      'Full-sample annual differences and positive/negative concentration are retained for every pair.',
                      'The November 2025 cycle was previously seen and is descriptive, with no independent-validation claim.',
                      'Three threshold points describe local sensitivity. Original six gates remain the eligibility criteria.',
                      'Eight families cover hard/ramp exits only. Daily-close participation interactions require future evidence.']}
    save(WORK / 'others/participation_comparison.json', out)
    lines = ['# EX044 参与连续带完整对照', '', '24 配置，18 组成对比较，8 个阈值三档家族；新增账户 0。', '',
             '|家族|参与半宽|达标点/3|NAR范围|Calmar范围|MDD范围|', '|---|---:|---:|---|---|---|']
    for g in spans:
        r = g['ranges']
        lines.append(f"|{g['exit_policy']}/{g['participation_policy']}|{g['participation_width']}|{g['eligible_count']}|"
                     f"{r['nar']['min']:.2%}–{r['nar']['max']:.2%}|{r['calmar']['min']:.4f}–{r['calmar']['max']:.4f}|"
                     f"{r['drawdown']['min']:.2%}–{r['drawdown']['max']:.2%}|")
    lines.extend(['', '|连续配置|匹配hard|ΔNAR百分点|ΔMDD百分点|ΔCalmar|改退出数|目标变化决策|',
                  '|---|---|---:|---:|---:|---:|---:|'])
    for pair in pairs:
        m = pair['metric_deltas']
        lines.append(f"|{pair['other']}|{pair['baseline']}|{m['nar']*100:.4f}|{m['drawdown']*100:.4f}|"
                     f"{m['calmar']:.5f}|{pair['path']['changed_exit_count']}|{pair['allocation']['changed_target_decisions']}|")
    lines.extend(['', '共同入退场以真实成交时点匹配；实际仓位以持仓数量×估值价格/权益衡量。相同入退场且目标持有状态相同的差异，主要联系仓位路径解释。',
                  'JSON 保留全部年度差、正负贡献日、共同周期、独有周期、已见 2025 年 11 月反例及来源。三档平坦度与原六门达标分别报告。',
                  'daily_close/linear 当前保留为后续待检方向，本轮直接证据覆盖 hard 与 ramp05。', '',
                  f"分析源码 SHA256：`{identity['analysis_sha256']}`", '',
                  f"冻结 EX043 辅助源码 SHA256：`{EXPECTED_HELPER}`", '',
                  '完整数据与引用：`others/participation_comparison.json`。'])
    (WORK / 'others/participation_comparison.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({'status':'COMPLETE','accounts':24,'pairs':18,'seconds':out['elapsed_seconds']}), flush=True)


if __name__ == '__main__':
    main()
