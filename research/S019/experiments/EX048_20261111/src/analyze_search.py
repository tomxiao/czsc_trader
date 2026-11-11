"""Read-only, complete-search analysis using public account materialization."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import perf_counter

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                  NUMEXPR_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT/'research/S019/experiments/EX013_20261110/src'))
from runner import read_account, metrics  # noqa: E402
import numpy as np  # noqa: E402
import sklearn  # noqa: E402
from sklearn.ensemble import RandomForestRegressor  # noqa: E402
from sklearn.inspection import permutation_importance  # noqa: E402
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score  # noqa: E402
from sklearn.model_selection import KFold  # noqa: E402

GATES = ('nar', 'calmar', 'absolute_dd', 'relative_dd', 'frequency_median', 'frequency_coverage')
OLD_SEARCH = ROOT/'research/S019/experiments/EX045_20261111/protocols/search.json'
SEED = 20261124


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def save(path, obj):
    path.write_bytes((json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode())


def finite(value):
    return float(value) if np.isfinite(value) else None


def boundary(parameters, space):
    result = {}
    for key, bounds in space.items():
        value = parameters[key]
        position = (value-bounds['low'])/(bounds['high']-bounds['low'])
        assert 0 <= position <= 1
        result[key] = {'value': value, 'domain_fraction': position,
                       'near_lower_5pct': position <= .05, 'near_upper_5pct': position >= .95,
                       'exact_lower': value == bounds['low'], 'exact_upper': value == bounds['high']}
    return result


def compact(row):
    return {'key': row['label'], 'candidate_id': row['candidate_id'], 'family': row['family'],
            'content_hash': row['content_hash'], 'parameters': row['parameters'],
            'metrics': row['candidate'], 'account_ref': row['account_ref']}


def unique_rows(rows):
    grouped = {}
    for row in rows:
        identity = row['content_hash']
        if identity in grouped:
            prior = grouped[identity]
            assert prior['parameters'] == row['parameters'] and prior['candidate'] == row['candidate']
        else:
            grouped[identity] = row
    return list(grouped.values())


def distribution(rows):
    return {metric: {'count': len(values), 'min': float(min(values)),
                     'median': float(np.median(values)), 'max': float(max(values))}
            for metric in ('nar', 'drawdown', 'calmar')
            for values in [[r['candidate'][metric] for r in rows if r['candidate'][metric] is not None]]
            if values}


def old_domain_info(parameters, family, old_families):
    policy = parameters['exit_policy']
    old_name = 'hard_linear' if policy == 'hard' else 'ramp_linear'
    old_space = old_families[old_name]['space']
    assert set(family['space']) == set(old_space)
    outside = [k for k, b in old_space.items() if not b['low'] <= parameters[k] <= b['high']]
    return {'inside_old_effective_domain': not outside, 'outside_parameters': outside,
            'old_domain_family': old_name,
            'scope': 'Shared continuous-parameter bounds only; rebuild mechanism was absent in EX045.'
            if policy == 'ramp_rebuild' else 'Same active-parameter bounds from EX045.'}


def ledger(work, row, spec):
    ref, payload = read_account(work/spec['account_path'])
    assert ref.to_dict() == row['account_ref']
    request = payload['request']
    assert request['content_sha256'] == row['content_hash']
    assert request['candidate_definition'] == row['definition']
    assert request['initial_cash'] == 100000. and request['drawdown_basis'] == 'SESSION_CLOSE'
    assert request['fee_rate'] == .001 and request['scenario_id'] == 'STANDARD'
    assert request['window_id'] == 'FULL' and request['measurement_tier'] == 'FORMAL'
    run, bh = payload['runs']['candidate'], payload['runs']['buy_hold']
    measured = metrics(run, bh['metrics']['daily_max_drawdown'])
    assert measured == row['candidate']
    daily = run['account_daily']
    sessions = [x['session'] for x in daily]
    assert len(sessions) == 1212 and sessions[0] == '2022-01-03' and sessions[-1] == '2026-10-30'
    equity = np.asarray([100000., *(x['equity'] for x in daily)], dtype=float)
    dd = 1-equity/np.maximum.accumulate(equity)
    trough = int(np.argmax(dd))
    peak = int(np.argmax(equity[:trough+1]))
    recovery = np.flatnonzero(equity[trough+1:] >= equity[peak])
    dates = ['INITIAL_CASH', *sessions]
    episode = {'peak': dates[peak], 'trough': dates[trough], 'magnitude': float(dd[trough]),
               'recovery': dates[trough+1+int(recovery[0])] if len(recovery) else None,
               'unrecovered_at_sample_end': len(recovery) == 0,
               'sample_end_drawdown_from_running_peak': float(dd[-1])}
    assert abs(episode['magnitude']-measured['drawdown']) < 1e-10
    by_cycle = defaultdict(list)
    for fill in run['fills']:
        by_cycle[fill['cycle_id']].append(fill)
    points = run['account_points']
    times = [p['time'] for p in points]
    assert times == sorted(times)
    closed, all_balances = [], {}
    closed_ids = {t['cycle_id'] for t in run['trades']}
    assert len(closed_ids) == len(run['trades']) and all(t['status'] == 'CLOSED' for t in run['trades'])
    for cid, fs in by_cycle.items():
        all_balances[cid] = sum(f['quantity']*(1 if f['side'] == 'BUY' else -1) for f in fs)
        assert all_balances[cid] >= 0
    for trade in run['trades']:
        cid = trade['cycle_id']
        fills = sorted(by_cycle[cid], key=lambda f: f['executed_at'])
        assert fills and fills[0]['side'] == 'BUY' and fills[-1]['side'] == 'SELL'
        assert all_balances[cid] == 0
        entry, exit_at = fills[0]['executed_at'], fills[-1]['executed_at']
        index = bisect_right(times, entry)-1
        capital = points[index]['equity'] if index >= 0 else 100000.
        assert capital > 0
        closed.append({'cycle_id': cid, 'entry_at': entry, 'exit_at': exit_at,
                       'entry_equity': capital, 'net_pnl': trade['net_pnl'],
                       'net_return': trade['net_return'],
                       'pnl_over_entry_equity': trade['net_pnl']/capital,
                       'fees_over_entry_equity': sum(f['fees'] for f in fills)/capital,
                       'actual_fill_count': len(fills)})
    open_ids = set(by_cycle)-closed_ids
    assert all(all_balances[cid] > 0 for cid in open_ids)
    terminal = points[-1]
    assert sum(all_balances.values()) == terminal['quantity']
    assert len(open_ids) == int(terminal['quantity'] > 0)
    if open_ids:
        assert open_ids == {terminal['cycle_id']}
    assert len(closed) == measured['closed_cycles']
    assert len({c['entry_at'] for c in closed}) == len(closed)
    fees = sum(f['fees'] for f in run['fills'])
    assert abs(fees-measured['fees']) < 1e-6
    return {'key': row['label'], 'candidate_id': row['candidate_id'], 'account_ref': ref.to_dict(),
            'metrics': measured, 'annual_returns': measured['year_returns'], 'mdd_episode': episode,
            'execution': {'actual_fills': len(run['fills']), 'buy_fills': sum(f['side']=='BUY' for f in run['fills']),
                          'sell_fills': sum(f['side']=='SELL' for f in run['fills']), 'fees': fees,
                          'gross_turnover': sum(f['quantity']*f['price'] for f in run['fills']),
                          'mean_closed_cycle_fees_over_entry_equity': float(np.mean([c['fees_over_entry_equity'] for c in closed])) if closed else None},
            'terminal': {'equity': terminal['equity'], 'cash': terminal['cash'], 'quantity': terminal['quantity'],
                         'confirmed_open_cycle_count': len(open_ids), 'open_cycle_ids': sorted(open_ids)},
            'largest_closed_losses': sorted([c for c in closed if c['net_pnl'] < 0], key=lambda c: c['pnl_over_entry_equity'])[:5],
            'largest_closed_gains': sorted([c for c in closed if c['net_pnl'] > 0], key=lambda c: -c['pnl_over_entry_equity'])[:5],
            'cycles': closed, 'sessions': sessions, 'daily_returns': (equity[1:]/equity[:-1]-1).tolist()}


def compare(other, control, other_row, control_row):
    assert other['sessions'] == control['sessions']
    left = {c['entry_at']: c for c in other['cycles']}
    right = {c['entry_at']: c for c in control['cycles']}
    common = sorted(set(left)&set(right))
    changes = [{'entry_at': t, 'other_exit': left[t]['exit_at'], 'control_exit': right[t]['exit_at'],
                'other_pnl_over_entry_equity': left[t]['pnl_over_entry_equity'],
                'control_pnl_over_entry_equity': right[t]['pnl_over_entry_equity'],
                'normalized_pnl_delta': left[t]['pnl_over_entry_equity']-right[t]['pnl_over_entry_equity']}
               for t in common]
    logdelta = np.log1p(other['daily_returns'])-np.log1p(control['daily_returns'])
    return {'other': other['key'], 'control': control['key'],
            'parameter_differences': {k: {'other': v, 'control': control_row['parameters'][k]}
                                     for k, v in other_row['parameters'].items() if v != control_row['parameters'][k]},
            'metric_deltas': {k: other['metrics'][k]-control['metrics'][k] for k in ('nar','drawdown','calmar','fees')
                              if other['metrics'][k] is not None and control['metrics'][k] is not None},
            'common_actual_closed_entries': len(common),
            'common_actual_closed_entries_and_exits': sum(c['other_exit'] == c['control_exit'] for c in changes),
            'changed_closed_exits': sum(c['other_exit'] != c['control_exit'] for c in changes),
            'other_only_closed_cycles': [left[t] for t in sorted(set(left)-set(right))],
            'control_only_closed_cycles': [right[t] for t in sorted(set(right)-set(left))],
            'common_cycle_differences': changes,
            'largest_common_cycle_gains': sorted([c for c in changes if c['normalized_pnl_delta'] > 0], key=lambda c: -c['normalized_pnl_delta'])[:5],
            'largest_common_cycle_losses': sorted([c for c in changes if c['normalized_pnl_delta'] < 0], key=lambda c: c['normalized_pnl_delta'])[:5],
            'full_period_log_growth_delta': float(logdelta.sum()),
            'annual_log_growth_delta': {year: float(sum(v for day, v in zip(other['sessions'], logdelta, strict=True) if day.startswith(year)))
                                        for year in sorted(other['annual_returns'])},
            'interpretation': 'Complete-configuration comparison; multiple parameter differences and changed exposure/timing are jointly attributed.'}


def model_relations(rows, space):
    """Use library CV and held-out permutation importance; never select candidates."""
    unique = unique_rows(rows)
    names = sorted(space)
    output = {'status': 'COMPLETE', 'sklearn_version': sklearn.__version__, 'numpy_version': np.__version__,
              'feature_names': names, 'unique_configuration_count': len(unique), 'seed': SEED,
              'model': {'name': 'RandomForestRegressor', 'n_estimators': 256, 'min_samples_leaf': 3,
                        'max_features': 1.0, 'n_jobs': 1, 'random_state': SEED},
              'cv': {'name': 'KFold', 'n_splits': 5, 'shuffle': True, 'random_state': SEED},
              'importance': {'name': 'sklearn.inspection.permutation_importance', 'n_repeats': 20,
                             'scoring': 'neg_mean_squared_error', 'evaluation_set': 'held-out fold',
                             'units': 'Increase in validation mean squared error; raw target units squared'},
              'limitations': ['Adaptively selected, previously seen development configurations; CV assesses interpolation among these configurations, not future trading performance.',
                              'Correlated parameters and small finite search coverage affect permutation importance. Negative importance and negative R2 remain visible.',
                              'No feature importance changes the original six gates, NAR ranking, or phase-four criteria.'], 'targets': {}}
    for target in ('nar','drawdown','calmar'):
        valid = [r for r in unique if r['candidate'][target] is not None and np.isfinite(r['candidate'][target])]
        if len(valid) < 10:
            output['targets'][target] = {'status': 'INSUFFICIENT_CONFIGURATIONS', 'valid_points': len(valid), 'required_for_five_folds': 10}
            continue
        x = np.asarray([[r['parameters'][name] for name in names] for r in valid], dtype=float)
        y = np.asarray([r['candidate'][target] for r in valid], dtype=float)
        predicted = np.full(len(y), np.nan)
        folds, means, sizes = [], [], []
        for index, (train, test) in enumerate(KFold(5, shuffle=True, random_state=SEED).split(x)):
            estimator = RandomForestRegressor(n_estimators=256, min_samples_leaf=3,
                max_features=1.0, n_jobs=1, random_state=SEED)
            estimator.fit(x[train], y[train])
            guess = estimator.predict(x[test])
            predicted[test] = guess
            importance = permutation_importance(estimator, x[test], y[test], n_repeats=20,
                random_state=SEED+index, scoring='neg_mean_squared_error', n_jobs=1)
            means.append(importance.importances_mean)
            sizes.append(len(test))
            folds.append({'fold': index, 'train_candidate_ids': [valid[i]['candidate_id'] for i in train],
                          'test_candidate_ids': [valid[i]['candidate_id'] for i in test],
                          'r2': finite(r2_score(y[test], guess, force_finite=False)),
                          'mae': float(mean_absolute_error(y[test], guess)),
                          'mse': float(mean_squared_error(y[test], guess)),
                          'permutation_importance': {name: {'mean': float(importance.importances_mean[i]),
                              'std_across_repeats': float(importance.importances_std[i]),
                              'values': importance.importances[i].tolist()} for i, name in enumerate(names)}})
        assert np.isfinite(predicted).all()
        importance_mean = np.average(np.asarray(means), axis=0, weights=sizes)
        r2 = finite(r2_score(y, predicted, force_finite=False))
        output['targets'][target] = {'status': 'COMPLETE', 'valid_points': len(valid),
            'excluded_unavailable_points': len(unique)-len(valid), 'oof_r2': r2,
            'oof_mae': float(mean_absolute_error(y, predicted)), 'oof_mse': float(mean_squared_error(y, predicted)),
            'beats_constant_mean_by_r2': r2 is not None and r2 > 0,
            'fit_note': 'Cross-validated fit must be interpreted using its measured R2/MAE; no model-quality acceptance gate.',
            'weighted_heldout_permutation_importance': {name: float(importance_mean[i]) for i, name in enumerate(names)},
            'oof_predictions': [{'candidate_id': r['candidate_id'], 'actual': float(y[i]), 'predicted': float(predicted[i])}
                                for i, r in enumerate(valid)], 'folds': folds}
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment', type=Path, required=True)
    work = parser.parse_args().experiment.resolve()
    assert work.parent == ROOT/'research/S019/experiments'
    assert not (work/'report_ref.json').exists(), 'Published experiments require an explicit revised analysis path'
    assert not (work/'others/search_analysis.json').exists() and not (work/'others/search_analysis.md').exists(), 'Inspect existing analysis before rerunning'
    sys.path.insert(0, str(work/'src'))
    from family_close_inputs import load
    started = perf_counter()
    results, spec, manifest = load(work)
    rows = results['accounts']
    old_families = {f['name']: f for f in read(OLD_SEARCH)['families']}
    all_eligible = sorted(unique_rows([r for r in rows.values() if r['candidate']['eligible']]),
                          key=lambda r: (-r['candidate']['nar'], r['candidate_id']))
    families, controls, representatives, trial_panel = {}, {}, {}, []
    for family in spec['families']:
        name = family['name']
        group = sorted([r for r in rows.values() if r['family'] == name], key=lambda r: r['trial_number'])
        controls[name] = next(r['label'] for r in group if r['trial_number'] == 0)
        eligible = sorted(unique_rows([r for r in group if r['candidate']['eligible']]),
                          key=lambda r: (-r['candidate']['nar'], r['candidate_id']))
        representatives[name] = eligible[0]['label'] if eligible else None
        domains, failures = defaultdict(list), Counter()
        for row in group:
            assert set(row['candidate']['gates']) == set(GATES)
            assert row['candidate']['eligible'] == all(row['candidate']['gates'].values())
            failed = [key for key in GATES if not row['candidate']['gates'][key]]
            failures['+'.join(failed) or 'ALL_PASS'] += 1
            old = old_domain_info(row['parameters'], family, old_families)
            domains['inside' if old['inside_old_effective_domain'] else 'outside'].append(row)
            trial_panel.append({**compact(row), 'failed_gates': failed,
                                'boundary': boundary(row['parameters'], family['space']), 'old_domain': old})
        families[name] = {'proposals': len(group), 'unique_configurations': len(unique_rows(group)),
            'imported_observations': manifest['imported_trial_counts'][name],
            'eligible_proposals': sum(r['candidate']['eligible'] for r in group), 'eligible_unique': len(eligible),
            'eligible': [compact(r) for r in eligible], 'control': controls[name],
            'representative': compact(eligible[0]) if eligible else None,
            'selection_rule': 'All original six gates, then descending unrounded NAR; candidate ID resolves exact ties.',
            'gate_failure_counts': {gate: sum(not r['candidate']['gates'][gate] for r in group) for gate in GATES},
            'failure_patterns': dict(failures),
            'representative_boundary': boundary(eligible[0]['parameters'], family['space']) if eligible else None,
            'old_domain_groups': {kind: {'proposals': len(items), 'eligible_proposals': sum(r['candidate']['eligible'] for r in items),
                                        'metrics': distribution(items)} for kind, items in domains.items()},
            'parameter_model': model_relations(group, family['space'])}
        print('FAMILY_ANALYSIS', name, len(eligible), 'eligible_unique', flush=True)
    specs = {s['label']: s for s in spec['specs']}
    needed = sorted(set(controls.values()) | {key for key in representatives.values() if key is not None})
    ledgers = {}
    for key in needed:
        ledgers[key] = ledger(work, rows[key], specs[key])
        print('LEDGER_ANALYSIS', key, flush=True)
    comparisons = [compare(ledgers[key], ledgers[controls[name]], rows[key], rows[controls[name]])
                   for name, key in representatives.items() if key is not None]
    output = {'status': 'COMPLETE', 'new_accounts': 0, 'sources': {
        'analysis_sha256': digest(Path(__file__)), 'adapter_sha256': digest(work/'src/family_close_inputs.py'),
        'reader_sha256': digest(ROOT/'research/S019/experiments/EX013_20261110/src/runner.py'),
        'search_sha256': digest(work/'protocols/search.json'), 'summary_sha256': digest(work/'others/summary.json'),
        'execution_sha256': digest(work/'others/execution.json'), 'old_domain_sha256': digest(OLD_SEARCH)},
        'proposal_count': len(rows), 'eligible_unique': [compact(r) for r in all_eligible],
        'all_gate_failure_counts': {gate: sum(not r['candidate']['gates'][gate] for r in rows.values()) for gate in GATES},
        'families': families, 'all_trials': trial_panel,
        'selected_ledgers': {key: {k: v for k, v in value.items() if k not in ('sessions','daily_returns')} for key, value in ledgers.items()},
        'comparisons': comparisons, 'elapsed_seconds': perf_counter()-started,
        'notes': ['All original gates and NAR selection are unchanged. Model relations and boundary proximity are diagnostic only.',
                  '2022-01-03 through 2026-10-30 is previously seen development history, with 2021 warmup; 2026 annual return is through sample end.',
                  'MDD includes the initial cash and all daily marked account equity, including terminal open holdings.',
                  'Closed cycle contributions are net PnL divided by account equity at entry, and matched by actual first-fill entry time. Compounding/exposure differences affect these descriptive comparisons.',
                  'Imported historical observations are recorded separately. All-trial counts include every new proposal; models deduplicate those proposal configurations. Controls remain included as declared proposals.',
                  'Formal full-neighborhood 80% qualification and stress testing remain for phase four.']}
    lines = ['# 联合搜索只读分析', '',
             f"完成 {len(rows)} 次本轮提议的分析，去重后 {len(all_eligible)} 个配置通过原六门；新增账户 0。", '',
             '|研究族|提议|达标唯一配置|代表|NAR|MDD|Calmar|', '|---|---:|---:|---|---:|---:|---:|']
    for name, family in families.items():
        rep = family['representative']
        if rep:
            m = rep['metrics']
            lines.append(f"|{name}|{family['proposals']}|{family['eligible_unique']}|{rep['candidate_id']}|{m['nar']:.4%}|{m['drawdown']:.4%}|{m['calmar']:.6f}|")
        else:
            lines.append(f"|{name}|{family['proposals']}|0|无六门合格代表|—|—|—|")
    lines += ['', '## 原域、边界及完整配置差异', '',
              '原域采用 EX045 的有效连续参数范围；恢复族沿用渐进族六轴范围作为比较，EX045 当时未包含恢复机制。边界5%指搜索域宽度的5%，独立于参数相对±5%扰动。', '']
    for name, family in families.items():
        edges = family['representative_boundary'] or {}
        near = [k+('下边' if v['near_lower_5pct'] else '上边') for k, v in edges.items() if v['near_lower_5pct'] or v['near_upper_5pct']]
        groups = family['old_domain_groups']
        lines.append(f"- {name}：代表贴边参数 {', '.join(near) or '无'}；原域内外统计：{json.dumps(groups, ensure_ascii=False)}。")
    lines += ['', '## 代表与控制的完整账户路径', '']
    for pair in comparisons:
        a = ledgers[pair['other']]
        lines.append(f"- {a['candidate_id']}：MDD峰值 {a['mdd_episode']['peak']}，低点 {a['mdd_episode']['trough']}，恢复日 {a['mdd_episode']['recovery']}；期末持有周期 {a['terminal']['confirmed_open_cycle_count']}。实际成交 {a['execution']['actual_fills']} 笔、费用 {a['execution']['fees']:.2f}；与控制共同闭合入场 {pair['common_actual_closed_entries']}、入场退出均同 {pair['common_actual_closed_entries_and_exits']}。")
        lines.append(f"  年度收益：{json.dumps(a['annual_returns'], ensure_ascii=False)}；相对控制年度log增长差：{json.dumps(pair['annual_log_growth_delta'], ensure_ascii=False)}。")
    lines += ['', '完整JSON保留各代表和控制的前五归一化亏损、前五盈利、全部闭合周期、公共账户引用，以及共同入场周期改善与恶化的完整差值。多参数配置差异联合归因。', '',
              '## 参数关系的探索模型', '', '|研究族|目标|五折OOF R²|五折OOF MAE|', '|---|---|---:|---:|']
    for name, family in families.items():
        for target, model in family['parameter_model']['targets'].items():
            if model['status'] == 'COMPLETE':
                lines.append(f"|{name}|{target}|{model['oof_r2']}|{model['oof_mae']:.6f}|")
            else:
                lines.append(f"|{name}|{target}|样本不足|—|")
    lines += ['', '采用现有scikit-learn RandomForest、五折KFold及每折留出集permutation_importance。参数关系限于自适应搜索所得配置的插值解释；负R²、负重要性和拟合误差完整保留，不用于修改硬门、NAR排序或正式自检要求。', '',
              '全部门失败计数、达标去重名单、域内外分布、模型参数/版本/随机种子/各折预测和重要性见 [完整分析](search_analysis.json)。', '',
              '下一步依据边界与路径证据选择阶段三交互诊断；完整邻域和压力验收按阶段四协议开展。']
    save(work/'others/search_analysis.json', output)
    (work/'others/search_analysis.md').write_bytes(('\n'.join(lines)+'\n').encode())
    print('SEARCH_ANALYSIS_COMPLETE', len(rows), len(all_eligible), 'eligible_unique', flush=True)


if __name__ == '__main__':
    main()
