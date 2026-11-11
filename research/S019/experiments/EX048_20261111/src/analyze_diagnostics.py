"""Read-only finite stage-three interaction diagnostics; no formal self-check."""
import argparse
from collections import Counter
from hashlib import sha256
import itertools
import json
from pathlib import Path
from time import perf_counter

from analyze_search import ledger

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
AXES = ('weak_fraction', 'quiet_fraction', 'participation_threshold', 'participation_width', 'trail_atr', 'exit_width')
GATES = ('nar', 'calmar', 'absolute_dd', 'relative_dd', 'frequency_median', 'frequency_coverage')


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def save(path, obj):
    path.write_bytes((json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode())


def compact(row):
    return {'label': row['label'], 'candidate_id': row['candidate_id'], 'content_hash': row['content_hash'],
            'parameters': row['parameters'], 'candidate': row['candidate'], 'account_ref': row['account_ref']}


def center_gates(row):
    m, bh = row['candidate'], row['benchmark']
    gates = {'nar': m['nar'] >= .55, 'calmar': m['calmar'] is not None and m['calmar'] >= 5,
             'absolute_dd': m['drawdown'] <= .25, 'relative_dd': m['drawdown'] <= .8*bh['drawdown'],
             'frequency_median': m['frequency_median'] >= 6, 'frequency_coverage': m['frequency_coverage'] >= .9}
    assert gates == m['gates'] and all(gates.values()) == m['eligible']
    return gates


def neighbor_gates(row):
    m, bh = row['candidate'], row['benchmark']
    return {'nar': m['nar'] >= .5, 'calmar': m['calmar'] is not None and m['calmar'] >= 4.5,
            'absolute_dd': m['drawdown'] <= .25, 'relative_dd': m['drawdown'] <= .9*bh['drawdown']}


def summarize(labels, rows, center=None):
    labels = list(dict.fromkeys(labels))
    assert labels
    ranges = {}
    for key in ('nar','drawdown','calmar'):
        valid = [label for label in labels if rows[label]['candidate'][key] is not None]
        if not valid:
            ranges[key] = {'valid_points': 0, 'unavailable_points': len(labels), 'min': None, 'max': None, 'span': None,
                           'minimum_labels': [], 'maximum_labels': []}
            continue
        values = {label: rows[label]['candidate'][key] for label in valid}
        lo, hi = min(values.values()), max(values.values())
        ranges[key] = {'valid_points': len(valid), 'unavailable_points': len(labels)-len(valid),
                       'min': lo, 'max': hi, 'span': hi-lo,
                       'minimum_labels': [label for label, value in values.items() if value == lo],
                       'maximum_labels': [label for label, value in values.items() if value == hi]}
    worst = min(labels, key=lambda label: (rows[label]['candidate']['calmar']
        if rows[label]['candidate']['calmar'] is not None else float('-inf'), label))
    return {'labels': labels, 'center_included': center in labels if center else False,
            'denominator': len(labels), 'six_gate_pass_count': sum(rows[label]['candidate']['eligible'] for label in labels),
            'neighbor_economic_pass_count': sum(all(neighbor_gates(rows[label]).values()) for label in labels),
            'all_absolute_risk_pass': all(rows[label]['candidate']['drawdown'] <= .25 for label in labels),
            'ranges': ranges, 'lowest_calmar': compact(rows[worst]),
            'maximum_mdd': compact(rows[min(labels, key=lambda label:(-rows[label]['candidate']['drawdown'], label))])}


def expected_changes(parameters):
    axes = tuple(key for key in AXES if key != 'exit_width' or parameters['exit_policy'] != 'hard')
    result = {'center': {}}
    result.update({f'{key}_{side}': {key: factor} for key in axes for side, factor in (('lo', .95), ('hi', 1.05))})
    if 'exit_width' in axes:
        result.update({f'exit_pair_{i}': dict(zip(('trail_atr','exit_width'), factors, strict=True))
                       for i, factors in enumerate(itertools.product((.95,1.05), repeat=2))})
    result.update({f'participation_joint_{i}': dict(zip(('quiet_fraction','participation_threshold','participation_width'), factors, strict=True))
                   for i, factors in enumerate(itertools.product((.95,1.05), repeat=3))})
    result.update({f'all_{side}': dict.fromkeys(axes, factor) for side, factor in (('lo',.95),('hi',1.05))})
    return axes, result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment', type=Path, required=True)
    work = parser.parse_args().experiment.resolve()
    assert work.parent == ROOT/'research/S019/experiments'
    assert not (work/'report_ref.json').exists(), 'Published experiments require explicit revised analysis'
    assert not (work/'others/diagnostic_analysis.json').exists() and not (work/'others/diagnostic_analysis.md').exists()
    started = perf_counter()
    paths = {name: work/path for name, path in {
        'results': 'others/results.json', 'specs': 'protocols/specs.json',
        'design': 'protocols/diagnostic_design.json', 'points': 'protocols/diagnostic_points.json',
        'selected': 'protocols/selected_centers.json', 'manifest': 'protocols/run_manifest.json',
        'audit_selection_supplement': 'protocols/audit_selection_supplement.md'}.items()}
    results, specs_doc, design, points, selected, manifest = (read(paths[key]) for key in ('results','specs','design','points','selected','manifest'))
    assert results['status'] == 'COMPLETE' and results['manifest'] == manifest
    assert manifest['specs_sha256'] == digest(paths['specs'])
    rows = results['accounts']
    specs = {s['label']: s for s in specs_doc['specs']}
    assert len(specs) == len(specs_doc['specs']) == len(rows) and set(specs) == set(rows)
    assert set(design) == {'anchors'}
    choices = {s['anchor']: s for s in selected}
    assert len(choices) == len(selected) == len(design['anchors'])
    assert set(choices) == {a['name'] for a in design['anchors']}
    for label, row in rows.items():
        assert row['label'] == label and row['parameters'] == specs[label]['parameters']
        assert read(work/f'others/{label}_definition.json') == row['definition']
        assert read(work/f'others/{label}_account.json') == row['account_ref']
        assert json.loads(row['definition']['parameters_json']) == row['parameters']
        assert row['definition']['state_schema'] == specs_doc['state_schema']
        center_gates(row)
    assert all(set(p) == {'anchor','label','factors','kind'} for p in points)
    assert {p['anchor'] for p in points} == set(choices)
    assert {p['label'] for p in points} == set(rows)
    groups, covered, ledger_labels = {}, set(), set()
    for anchor in design['anchors']:
        assert set(anchor) == {'name','center_label','members'}
        name, center, members = anchor['name'], anchor['center_label'], anchor['members']
        assert len(members) == len(set(members)) and center in members
        chosen = choices[name]
        assert chosen['role'] in ('winner','control')
        row = rows[center]
        assert row['parameters'] == chosen['parameters'] and row['content_hash'] == chosen['content_hash']
        assert row['candidate'] == chosen['candidate']
        source = (ROOT/specs[center]['control_account']).resolve()
        assert source.is_relative_to(ROOT/'research/S019') and read(source) == chosen['account']
        parity = read(work/f'others/{center}_parity.json')
        assert parity['status'] == 'PASS' and parity['control'] == specs[center]['control_account']
        assert parity['new_account'] == row['account_ref']
        assert parity['daily_and_bar_economic_paths'] == parity['targets_and_fills'] == 'EXACT_EQUAL'
        axes, expected = expected_changes(row['parameters'])
        observations = [p for p in points if p['anchor'] == name]
        by_kind = {p['kind']: p for p in observations}
        assert len(by_kind) == len(observations) and set(by_kind) == set(expected)
        assert set(members) == {p['label'] for p in observations}
        for kind, factors in expected.items():
            observation = by_kind[kind]
            assert observation['factors'] == factors
            parameters = {**row['parameters'], **{key: row['parameters'][key]*factor for key, factor in factors.items()}}
            assert rows[observation['label']]['parameters'] == parameters
        assert by_kind['center']['label'] == center
        neighbors = [label for label in members if label != center]
        assert neighbors
        neighbor_summary = summarize(neighbors, rows)
        categories = {f'axis:{axis}': summarize([center, by_kind[f'{axis}_lo']['label'], by_kind[f'{axis}_hi']['label']], rows, center)
                      for axis in axes}
        for category, prefix in (('participation_triple','participation_joint_'), ('all_axes_same_direction','all_')):
            labels = [p['label'] for kind, p in by_kind.items() if kind.startswith(prefix)]
            categories[category] = summarize([center, *labels], rows, center)
        if 'exit_width' in axes:
            categories['exit_pair'] = summarize([center, *(p['label'] for kind, p in by_kind.items() if kind.startswith('exit_pair_'))], rows, center)
        aggregate = summarize(members, rows, center)
        better = sorted([rows[label] for label in neighbors if rows[label]['candidate']['eligible']
                         and rows[label]['candidate']['nar'] > row['candidate']['nar']],
                        key=lambda r: (-r['candidate']['nar'], r['candidate_id']))
        eligible_members = [label for label in members if rows[label]['candidate']['eligible']]
        highest_nar = min(eligible_members, key=lambda label:(-rows[label]['candidate']['nar'],
            rows[label]['candidate_id'], label)) if eligible_members else None
        groups[name] = {'family': chosen['family'], 'role': chosen['role'], 'original_candidate_id': chosen['id'],
            'center': compact(row), 'active_axes': list(axes), 'all_points': aggregate,
            'finite_noncenter_diagnostic': {**neighbor_summary,
                'economic_pass_fraction': neighbor_summary['neighbor_economic_pass_count']/len(neighbors),
                'formal_80pct_acceptance_evaluated': False,
                'scope': 'Prespecified finite diagnostic points, center excluded, exact labels deduplicated within anchor; full Cartesian neighborhood untested.'},
            'categories': categories, 'six_gate_nar_improvements': [compact(r) for r in better],
            'highest_nar_eligible': compact(rows[highest_nar]) if highest_nar is not None else None,
            'gate_failure_counts': {gate: sum(not rows[label]['candidate']['gates'][gate] for label in members) for gate in GATES},
            'neighbor_gate_failure_counts': {gate: sum(not neighbor_gates(rows[label])[gate] for label in neighbors)
                                            for gate in ('nar','calmar','absolute_dd','relative_dd')}}
        ledger_labels.update((center, aggregate['lowest_calmar']['label']))
        if highest_nar is not None:
            ledger_labels.add(highest_nar)
        covered.update(members)
    assert covered == set(rows)
    comparisons = []
    for family in sorted({c['family'] for c in selected}):
        matches = {g['role']: (name, g) for name, g in groups.items() if g['family'] == family}
        assert len(matches) == sum(g['family'] == family for g in groups.values())
        assert 'winner' in matches
        if 'control' not in matches:
            comparisons.append({'family': family, 'status': 'WINNER_IS_ORIGINAL_CONTROL', 'winner': matches['winner'][0]})
            continue
        wn, winner = matches['winner']
        cn, control = matches['control']
        assert winner['active_axes'] == control['active_axes']
        assert set(winner['categories']) == set(control['categories'])
        changes = {}
        for category in winner['categories']:
            left, right = winner['categories'][category], control['categories'][category]
            assert left['denominator'] == right['denominator']
            changes[category] = {'winner': left['ranges'], 'control': right['ranges'],
                'range_span_delta': {key: left['ranges'][key]['span']-right['ranges'][key]['span']
                                     if left['ranges'][key]['span'] is not None and right['ranges'][key]['span'] is not None else None
                                     for key in ('nar','drawdown','calmar')},
                'lowest_calmar_delta': left['ranges']['calmar']['min']-right['ranges']['calmar']['min']
                                      if left['ranges']['calmar']['min'] is not None and right['ranges']['calmar']['min'] is not None else None}
        left, right = winner['finite_noncenter_diagnostic'], control['finite_noncenter_diagnostic']
        assert left['denominator'] == right['denominator']
        comparisons.append({'family': family, 'status': 'PAIRED_DIAGNOSTIC_DESIGN', 'winner': wn, 'control': cn,
            'finite_diagnostic_denominator_each': left['denominator'],
            'winner_economic_pass_count': left['neighbor_economic_pass_count'], 'control_economic_pass_count': right['neighbor_economic_pass_count'],
            'category_changes': changes,
            'interpretation': 'Same factor design around different complete parameter configurations; sensitivity changes are development evidence.'})
    ledgers = {}
    for label in sorted(ledger_labels):
        account_spec = {**specs[label], 'account_path': f'others/{label}_account.json'}
        value = ledger(work, rows[label], account_spec)
        ledgers[label] = {key: item for key, item in value.items() if key not in ('sessions','daily_returns')}
        print('DIAGNOSTIC_LEDGER', label, flush=True)
    eligible_by_content = {}
    for row in rows.values():
        if row['candidate']['eligible']:
            eligible_by_content.setdefault(row['content_hash'], row)
    all_eligible = sorted(eligible_by_content.values(), key=lambda r: (-r['candidate']['nar'], r['candidate_id']))
    centers = {a['center_label'] for a in design['anchors']}
    output = {'status': 'COMPLETE', 'new_accounts': 0, 'sources': {**{key+'_sha256': digest(path) for key, path in paths.items()},
        'analysis_sha256': digest(Path(__file__)), 'ledger_helper_sha256': digest(Path(__file__).with_name('analyze_search.py')),
        'public_reader_sha256': digest(ROOT/'research/S019/experiments/EX013_20261110/src/runner.py')},
        'distinct_design_configurations': len(rows), 'anchor_count': len(groups),
        'center_unique_count': len(centers), 'center_original_six_gate_pass_count': sum(rows[label]['candidate']['eligible'] for label in centers),
        'all_point_six_gate_pass_count': sum(row['candidate']['eligible'] for row in rows.values()),
        'eligible_unique': [compact(r) for r in all_eligible], 'groups': groups, 'winner_control_comparisons': comparisons,
        'selected_ledgers': ledgers, 'point_gate_patterns': dict(Counter('+'.join(key for key in GATES if not row['candidate']['gates'][key]) or 'ALL_PASS' for row in rows.values())),
        'elapsed_seconds': perf_counter()-started,
        'method': ['Each factor is checked against the exact original selected center and the frozen point specification; every result is covered.',
                   'Category metric ranges include center plus the stated factors. Finite-neighbor statistics exclude center and deduplicate labels within each anchor.',
                   'Diagnostic economic conditions are NAR>=0.5, Calmar>=4.5, MDD<=0.25 and <=0.9 same-fee BH MDD; original six center gates are independently retained.',
                   'This finite factor design is phase-three development, with no formal 80% full-neighborhood decision.',
                   'MDD and returns use full marked accounts, including terminal open holdings. Closed-cycle summaries and partial 2026 annual returns keep their separate meanings.',
                   'Ledger coverage retains every original center and lowest-Calmar case and adds each anchor highest unrounded NAR passing the original six gates; exact NAR ties use candidate ID then label.']}
    lines = ['# 有限参数交互诊断', '',
        f"已核对全部 {len(rows)} 个不同配置、{len(groups)} 组锚点；原中心六门通过 {output['center_original_six_gate_pass_count']}/{len(centers)}。新增账户 0。", '',
        '|锚点|原配置|中心NAR|中心Calmar|有限邻点经济通过率（N）|全组最低Calmar|全组最高MDD|',
        '|---|---|---:|---:|---:|---:|---:|']
    for name, group in groups.items():
        m, neighbor, ranges = group['center']['candidate'], group['finite_noncenter_diagnostic'], group['all_points']['ranges']
        lines.append(f"|{name}|{group['original_candidate_id']}|{m['nar']:.4%}|{m['calmar']:.6f}|{neighbor['economic_pass_fraction']:.2%}（N={neighbor['denominator']}）|{ranges['calmar']['min']}|{ranges['drawdown']['max']:.4%}|")
    lines += ['', '通过数采用事前固定有限点集，分母排除中心并在锚点内精确去重。本轮未作完整笛卡尔邻域的80%验收。', '',
              '## 分方向敏感性', '', '|锚点|方向|含中心点数|NAR跨度|MDD跨度|Calmar跨度|最低Calmar点|', '|---|---|---:|---:|---:|---:|---|']
    for name, group in groups.items():
        for category, item in group['categories'].items():
            r = item['ranges']
            lines.append(f"|{name}|{category}|{item['denominator']}|{r['nar']['span']:.6f}|{r['drawdown']['span']:.6f}|{r['calmar']['span']}|{item['lowest_calmar']['candidate_id']}|")
    lines += ['', '## 领先配置与原型控制', '']
    for pair in comparisons:
        if pair['status'] == 'WINNER_IS_ORIGINAL_CONTROL':
            lines.append(f"- {pair['family']}：领先配置与原控制相同。")
        else:
            change = pair['category_changes']['axis:trail_atr']
            lines.append(f"- {pair['family']}：ATR三档Calmar跨度由控制的 {change['control']['calmar']['span']} 变为领先配置的 {change['winner']['calmar']['span']}；有限邻点经济通过数由 {pair['control_economic_pass_count']} 变为 {pair['winner_economic_pass_count']}，各组分母 {pair['finite_diagnostic_denominator_each']}。")
    lines += ['', '## 完整路径核对', '']
    for label, item in ledgers.items():
        mdd = item['mdd_episode']
        lines.append(f"- {item['candidate_id']}（{label}）：MDD峰 {mdd['peak']}、谷 {mdd['trough']}、恢复 {mdd['recovery']}；末端持仓周期 {item['terminal']['confirmed_open_cycle_count']}，年度收益 {json.dumps(item['annual_returns'], ensure_ascii=False)}。")
    lines += ['', '全部原六门通过且NAR优于各锚点的配置、方向最差点、赢家与控制的所有方向差值及完整账户证据见 [结构化分析](diagnostic_analysis.json)。', '',
              '下一步根据退出二轴、参与三轴与全轴方向结果选择阶段三优化问题；正式完整邻域与费用压力仍按阶段四协议安排。']
    save(work/'others/diagnostic_analysis.json', output)
    (work/'others/diagnostic_analysis.md').write_bytes(('\n'.join(lines)+'\n').encode())
    print('DIAGNOSTIC_ANALYSIS_COMPLETE', len(rows), len(groups), len(all_eligible), flush=True)


if __name__ == '__main__':
    main()
