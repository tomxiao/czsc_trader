"""Read-only complete-panel exit diagnosis, using verified public account materialization."""
from bisect import bisect_right
from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / '.tmp/s019-ex043-exit-comparison'
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                  NUMEXPR_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
sys.dont_write_bytecode = True
sys.path.insert(0, str(WORK.parent / 'EX013_20261110/src'))
from runner import read_account, metrics  # noqa: E402
from strategy_runtime import equity_source_hash  # noqa: E402
import numpy as np  # noqa: E402


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def facts(decision):
    return {x['key']: x['text'] for x in decision['explanation']['basis']}


def episode(sessions, equity):
    values = np.r_[100000., equity]
    dd = 1 - values / np.maximum.accumulate(values)
    trough = int(np.argmax(dd))
    peak = int(np.argmax(values[:trough + 1]))
    recovery = np.flatnonzero(values[trough + 1:] >= values[peak])
    dates = ['INITIAL_CASH', *sessions]
    return {'peak': dates[peak], 'trough': dates[trough], 'magnitude': float(dd[trough]),
            'recovery': dates[trough + 1 + int(recovery[0])] if len(recovery) else None}


def analyze(row, source_identity):
    cache = SCRATCH / (row['account_ref']['sha256'] + '.json')
    identity = {'analysis_sha256': digest(Path(__file__)), 'source_identity': source_identity,
                'reference': row['account_ref'], 'request_sha256': row['request_sha256'],
                'content_hash': row['content_hash'], 'definition': row['definition']}
    if cache.exists():
        cached = read(cache)
        assert cached['identity'] == identity, 'Explicit cache identity mismatch; inspect before replacement'
        return cached['value'], 'VERIFIED_DERIVED_CACHE'
    ref, payload = read_account(WORK / f"others/{row['label']}_account.json")
    assert ref.to_dict() == row['account_ref']
    header = read(ref.resolve(ROOT))
    assert header['request_hash'] == row['request_sha256']
    request = payload['request']
    assert request['content_sha256'] == row['content_hash']
    assert request['initial_cash'] == 100000. and request['drawdown_basis'] == 'SESSION_CLOSE'
    assert request['fee_rate'] == .001 and request['scenario_id'] == 'STANDARD'
    assert request['window_id'] == 'FULL' and request['measurement_tier'] == 'FORMAL'
    assert request['candidate_definition'] == row['definition']
    assert row['definition']['source_sha256'] == equity_source_hash(
        WORK / 'src', tuple(row['definition']['source_files']))
    run = payload['runs']['candidate']
    measured = metrics(run, payload['runs']['buy_hold']['metrics']['daily_max_drawdown'])
    assert measured == row['candidate']
    daily = run['account_daily']
    sessions = [x['session'] for x in daily]
    assert len(sessions) == 1212 and sessions[-1] == '2026-10-30'
    equity = np.array([x['equity'] for x in daily], dtype=float)
    returns = equity / np.r_[100000., equity[:-1]] - 1
    mdd = episode(sessions, equity)
    assert abs(mdd['magnitude'] - measured['drawdown']) < 1e-10
    decisions = {x['decision_id']: x for x in run['decisions']}
    orders = {x['order_id']: x for x in run['orders']}
    by_cycle = defaultdict(list)
    for fill in run['fills']:
        by_cycle[fill['cycle_id']].append(fill)
    point_times = [x['time'] for x in run['account_points']]
    assert point_times == sorted(point_times)
    cycles, intervals = [], []
    partial_sell_cycles, partial_sell_fills = set(), []
    for trade in run['trades']:
        fills = sorted(by_cycle[trade['cycle_id']], key=lambda x: x['executed_at'])
        assert fills and fills[0]['side'] == 'BUY'
        entry = fills[0]['executed_at']
        closed = trade['status'] == 'CLOSED'
        exit_at = fills[-1]['executed_at'] if closed else None
        intervals.append((entry, exit_at, trade['cycle_id']))
        quantity = 0
        for fill in fills:
            quantity += fill['quantity'] * (1 if fill['side'] == 'BUY' else -1)
            decision = decisions[orders[fill['order_id']]['decision_id']]
            fraction = float(facts(decision).get('risk_fraction', 1.))
            if (row['parameters']['exit_policy'] == 'ramp' and fill['side'] == 'SELL'
                    and quantity > 0 and decision['target'] > 0 and 0 < fraction < 1):
                partial_sell_cycles.add(trade['cycle_id'])
                partial_sell_fills.append(fill)
        if not closed:
            continue
        assert fills[-1]['side'] == 'SELL' and quantity == 0
        decision = decisions[orders[fills[-1]['order_id']]['decision_id']]
        position = bisect_right(point_times, entry) - 1
        capital = run['account_points'][position]['equity'] if position >= 0 else 100000.
        cycles.append({'cycle_id': trade['cycle_id'], 'entry_at': entry, 'exit_at': exit_at,
                       'net_pnl': trade['net_pnl'], 'net_return': trade['net_return'],
                       'pnl_over_entry_equity': trade['net_pnl'] / capital,
                       'exit_reason': decision['explanation']['judgment']})
    assert len(cycles) == measured['closed_cycles']
    intervals.sort()
    entries = [x[0] for x in intervals]
    partial_targets, partial_decisions = set(), 0
    if row['parameters']['exit_policy'] == 'ramp':
        for decision in run['decisions']:
            fraction = float(facts(decision).get('risk_fraction', 1.))
            if not (decision['target'] > 0 and 0 < fraction < 1):
                continue
            t = decision['execution_start']
            i = bisect_right(entries, t) - 1
            assert i >= 0
            start, end, cid = intervals[i]
            assert start < t and (end is None or t <= end)
            partial_targets.add(cid)
            partial_decisions += 1
    assert partial_sell_cycles <= partial_targets
    fees = sum(x['fees'] for x in run['fills'])
    assert abs(fees - measured['fees']) < 1e-6
    value = {'reference': ref.to_dict(), 'metrics': measured, 'mdd_episode': mdd,
             'sessions': sessions, 'daily_returns': returns.tolist(), 'cycles': cycles,
             'open_cycles': sum(t['status'] != 'CLOSED' for t in run['trades']),
             'exit_reason_counts': dict(Counter(c['exit_reason'] for c in cycles)),
             'execution': {'actual_fills': len(run['fills']),
                           'buy_fills': sum(f['side'] == 'BUY' for f in run['fills']),
                           'sell_fills': sum(f['side'] == 'SELL' for f in run['fills']),
                           'fees': fees,
                           'gross_turnover': sum(f['quantity'] * f['price'] for f in run['fills'])},
             'ramp_reductions': {'target_partial_cycles': len(partial_targets),
                                 'target_partial_decisions': partial_decisions,
                                 'actual_partial_sell_cycles': len(partial_sell_cycles),
                                 'actual_partial_sell_fills': len(partial_sell_fills),
                                 'actual_partial_sell_fees': sum(f['fees'] for f in partial_sell_fills)}}
    save(cache, {'identity': identity, 'value': value})
    return value, 'PUBLIC_ACCOUNT_MATERIALIZATION'


def compare(other, baseline):
    assert other['sessions'] == baseline['sessions']
    delta = np.log1p(other['daily_returns']) - np.log1p(baseline['daily_returns'])
    total_abs = float(np.abs(delta).sum())
    order = np.argsort(np.abs(delta))[::-1]
    def largest(indices):
        return [{'session': other['sessions'][int(i)], 'log_growth_delta': float(delta[i])} for i in indices]
    left = {x['entry_at']: x for x in other['cycles']}
    right = {x['entry_at']: x for x in baseline['cycles']}
    assert len(left) == len(other['cycles']) and len(right) == len(baseline['cycles'])
    common = sorted(set(left) & set(right))
    differences = [{'entry_at': t, 'other_exit': left[t]['exit_at'], 'baseline_exit': right[t]['exit_at'],
                    'normalized_pnl_delta': left[t]['pnl_over_entry_equity'] - right[t]['pnl_over_entry_equity'],
                    'trade_return_delta': left[t]['net_return'] - right[t]['net_return']} for t in common]
    changed = [d for d in differences if d['other_exit'] != d['baseline_exit']]
    differences.sort(key=lambda x: x['normalized_pnl_delta'])
    years = sorted({s[:4] for s in other['sessions']})
    return {'daily_log_growth_delta': float(delta.sum()), 'absolute_daily_log_delta_sum': total_abs,
            'top_absolute_day_shares': {str(k): float(np.abs(delta[order[:k]]).sum() / total_abs)
                                       if total_abs > 0 else None for k in (1, 5, 10)},
            'identical_daily_return_path': bool(np.array_equal(other['daily_returns'], baseline['daily_returns'])),
            'largest_positive_days': largest([i for i in np.argsort(delta)[::-1] if delta[i] > 0][:5]),
            'largest_negative_days': largest([i for i in np.argsort(delta) if delta[i] < 0][:5]),
            'yearly_log_growth_delta': {y: float(sum(d for s, d in zip(other['sessions'], delta, strict=True)
                                                       if s.startswith(y))) for y in years},
            'common_actual_entries': len(common), 'same_entry_and_exit': len(common) - len(changed),
            'changed_exit_count': len(changed), 'changed_exits': changed,
            'other_only_closed_cycles': [left[t] for t in sorted(set(left) - set(right))],
            'baseline_only_closed_cycles': [right[t] for t in sorted(set(right) - set(left))],
            'largest_common_cycle_losses': [d for d in differences if d['normalized_pnl_delta'] < 0][:5],
            'largest_common_cycle_gains': [d for d in differences[::-1] if d['normalized_pnl_delta'] > 0][:5]}


def main():
    start = perf_counter()
    results_path, specs_path = WORK / 'others/results.json', WORK / 'protocols/specs.json'
    results, specs = read(results_path), read(specs_path)['specs']
    labels = [s['label'] for s in specs]
    if results['status'] != 'COMPLETE':
        raise SystemExit(f"NOT_READY: {results['status']}, {len(results['accounts'])}/19 accounts; no reads started")
    assert len(labels) == 19 and set(results['accounts']) == set(labels)
    prepared = read(WORK / 'protocols/prepared_request_manifest.json')
    assert {p['label'] for p in prepared} == set(labels)
    assert len({p['input_snapshot_sha256'] for p in prepared}) == 1
    assert len({p['benchmark_identity'] for p in prepared}) == 1
    assert all(results['accounts'][p['label']]['request_sha256'] == p['request_sha256'] for p in prepared)
    source_identity = {'strategy_file_sha256': digest(WORK / 'src/strategy.py'),
                       'reader_sha256': digest(WORK.parent / 'EX013_20261110/src/runner.py'),
                       'specs_sha256': digest(specs_path)}
    all_accounts, reads = {}, {}
    for spec in specs:
        label = spec['label']
        row = results['accounts'][label]
        assert row['parameters'] == spec['parameters']
        all_accounts[label], reads[label] = analyze(row, source_identity)
        print('READ', label, reads[label], flush=True)
    comparisons = {label: compare(all_accounts[label], all_accounts['hard_center']) for label in labels}
    groups = defaultdict(list)
    for label in labels:
        p = results['accounts'][label]['parameters']
        groups[(p['exit_policy'], p['exit_width'], p['confirm_bars'])].append(label)
    spans = []
    for (policy, width, confirm), members in groups.items():
        spans.append({'exit_policy': policy, 'exit_width': width, 'confirm_bars': confirm,
                      'labels': members, 'n': len(members),
                      'trail_atr_levels': [results['accounts'][x]['parameters']['trail_atr'] for x in members],
                      'eligible_count': sum(all_accounts[x]['metrics']['eligible'] for x in members),
                      'metric_ranges': {metric: {'min': min(values), 'max': max(values), 'spread': max(values)-min(values)}
                                        for metric in ('nar', 'drawdown', 'calmar', 'fees')
                                        for values in [[all_accounts[x]['metrics'][metric] for x in members]]}})
    accounts = {label: {**{k: v for k, v in all_accounts[label].items()
                          if k not in ('sessions', 'daily_returns', 'cycles')},
                        'candidate_id': results['accounts'][label]['candidate_id'],
                        'parameters': results['accounts'][label]['parameters'],
                        'content_hash': results['accounts'][label]['content_hash'],
                        'request_sha256': results['accounts'][label]['request_sha256'],
                        'definition': results['accounts'][label]['definition']} for label in labels}
    out = {'status': 'COMPLETE', 'new_accounts': 0, 'account_count': 19,
           'source_identity': source_identity, 'analysis_sha256': digest(Path(__file__)),
           'results_sha256': digest(results_path), 'cache_reads': reads,
           'elapsed_seconds': perf_counter() - start, 'baseline': 'hard_center',
           'accounts': accounts, 'comparisons': comparisons, 'three_level_spans': spans,
           'method': ['Previously seen development sample; all 19 prespecified configurations retained.',
                      'Actual entry/exit are first BUY and final SELL fill times; closed cycles matched by entry.',
                      'Daily log differences are additive. Cycle PnL/entry equity is descriptive and allocation-sensitive.',
                      'Equal entry/exit times can coexist with different intracycle exposure and integer rounding.',
                      'Ramp actual partial sells require positive remaining quantity, positive target and risk_fraction in (0,1).',
                      'Ramp counts include rebalancing sells while reduced risk applies; target counts are reported separately.',
                      'Three ATR levels describe local sensitivity; phase-four robustness requires its full protocol.',
                      'Cash fees and turnover reflect compounded equity; compare together with fills and return differences.']}
    save(WORK / 'others/exit_comparison.json', out)
    lines = ['# EX043 退出机制完整账户对照', '',
             '19 个预设配置全部保留；参考为 hard_center；新增账户 0。样本为已见开发池，截止 2026-10-30。', '',
             '|配置|NAR|MDD|Calmar|原硬门|费用|实际成交笔数|部分减仓周期|相对基准 log 增长|前10日绝对差占比|',
             '|---|---:|---:|---:|---|---:|---:|---:|---:|---:|']
    for label in labels:
        a, c = accounts[label], comparisons[label]
        m, x = a['metrics'], a['execution']
        share = c['top_absolute_day_shares']['10']
        text_share = f'{share:.2%}' if share is not None else '同路径'
        lines.append(f"|{label}|{m['nar']:.4%}|{m['drawdown']:.4%}|{m['calmar']:.5f}|{m['eligible']}|"
                     f"{x['fees']:.2f}|{x['actual_fills']}|{a['ramp_reductions']['actual_partial_sell_cycles']}|"
                     f"{c['daily_log_growth_delta']:.6f}|{text_share}|")
    lines.extend(['', '## 同政策与宽度的三档 ATR 跨度', '',
                  '|政策|宽度|点数|达标点|NAR范围|Calmar范围|MDD范围|', '|---|---:|---:|---:|---|---|---|'])
    for g in spans:
        r = g['metric_ranges']
        lines.append(f"|{g['exit_policy']}|{g['exit_width']}|{g['n']}|{g['eligible_count']}|"
                     f"{r['nar']['min']:.2%}–{r['nar']['max']:.2%}|"
                     f"{r['calmar']['min']:.4f}–{r['calmar']['max']:.4f}|"
                     f"{r['drawdown']['min']:.2%}–{r['drawdown']['max']:.2%}|")
    lines.extend(['', '## 核验与解释口径', '',
                  '真实入退场由成交账本识别，股数复利及取整变化单独归入仓位变化。JSON 同时保留各配置最大正、负贡献日、共同入场的退出变化、双方独有周期及 MDD 区间。',
                  'ramp 部分减仓为风险比例进入 (0,1) 后实际卖出且仍持仓的周期数；对应目标部分仓位周期数另列于 JSON。现金费用随账户复利规模变化，与成交笔数及净收益共同解读。',
                  '三档结果用于本轮机制比较；阶段四通过率按正式完整点集另行判断。', '',
                  f"分析源码 SHA256：`{out['analysis_sha256']}`", '',
                  f"结果输入 SHA256：`{out['results_sha256']}`", '',
                  '引用及实现身份见 `others/exit_comparison.json`；来源为公共 `EX013/src/runner.py:read_account`，账户读取逐层校验内容哈希。'])
    (WORK / 'others/exit_comparison.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'status': out['status'], 'accounts': 19, 'seconds': out['elapsed_seconds']}), flush=True)


if __name__ == '__main__':
    main()
