"""Versioned decision view over sealed evidence. No search, gates or promotion."""
from pathlib import Path
from hashlib import sha256
from decimal import Decimal
from importlib.metadata import version
import argparse
import json
import math
import shutil
import sys
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from ranking import Metric, rank, group_behaviors

REPO = next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').is_file())
SOURCE = Path(__file__).resolve().parent.parent
UPSTREAM = REPO/'research/S011/stage4/iteration_02'
# Reuse the exact sealed identity/schema contracts, not a platform extension.
sys.path.append(str(UPSTREAM/'src'))
from contracts import Registry, Decision, document_schema, validate_document
from inputs import evidence_digest_bytes


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')


def check_upstream(protocol, snapshot):
    if protocol['upstream'] != UPSTREAM.relative_to(REPO).as_posix():
        raise ValueError('unexpected upstream')
    if digest(UPSTREAM/'manifest.json') != protocol['upstream_manifest_sha256']:
        raise ValueError('upstream manifest changed')
    manifest = read(UPSTREAM/'manifest.json')
    for path, expected in manifest['files'].items():
        if digest(UPSTREAM/path) != expected:
            raise ValueError('upstream file changed: '+path)
    for path, expected in manifest['inputs'].items():
        raw = snapshot.read_bytes() if path == 'research/RSCH_AGENT.md' else (REPO/path).read_bytes()
        if evidence_digest_bytes(path, raw) != expected:
            raise ValueError('upstream input changed: '+path)
    return {'sealed_files_checked': len(manifest['files']), 'input_hashes_checked': len(manifest['inputs']),
            'explicit_document_substitution': 'research/RSCH_AGENT.md -> inputs/previous_RSCH_AGENT.md',
            'reason': 'User-authorized successor contract; old canonical digest verified against archived snapshot. No other exceptions.'}


def make_metrics(protocol):
    return [Metric(**{k: m[k] for k in ('name', 'direction', 'resolution', 'origin')}) for m in protocol['metrics']]


def calculations(protocol):
    rows = pd.read_parquet(UPSTREAM/'ranking_metrics.parquet').copy()
    costs = pd.read_parquet(UPSTREAM/'cost_evaluations.parquet')
    fees, evidence = {}, {}
    for cid, chunk in costs.loc[costs.scenario.eq('fee_20bp') & costs.config_id.notna()].groupby('config_id'):
        if not np.allclose(chunk.cagr, chunk.cagr.iloc[0], atol=1e-10, rtol=0):
            raise ValueError('conflicting same-config cost evidence')
        fees[cid] = float(chunk.cagr.iloc[0]); evidence[cid] = sorted(chunk.evaluation_id.tolist())
    rows['fee20_cagr'] = rows.config_id.map(fees)
    rows['fee20_evaluation_ids'] = rows.config_id.map(lambda cid: evidence.get(cid, []))
    for row in rows.itertuples():
        if math.isfinite(row.fee20_cagr):
            if not math.isclose(row.cagr-row.fee20_cagr, row.fee20_cagr_loss, abs_tol=1e-10):
                raise ValueError('cost metric reconstruction differs')
        elif math.isfinite(row.fee20_cagr_loss):
            raise ValueError('lost same-source cost record')
    records = rows.to_dict('records'); metrics = make_metrics(protocol)
    main = rank(records, metrics)
    registry = Registry.model_validate(read(UPSTREAM/'configurations.json'))
    definitions = {c['config_id']: c for c in registry.configurations}
    groups = group_behaviors(records, main, definitions)
    sensitivity = {}
    for case in protocol['sensitivity']:
        mm = [Metric(m.name, m.direction, step, str(Decimal(step)/2) if case['half_cell_shift'] else '0')
              for m, step in zip(metrics, case['resolutions'], strict=True)]
        sensitivity[case['name']] = rank(records, mm)
    # Same complete population when omitting an objective; missing rows cannot gain a front slot silently.
    complete = [r for r in records if r['config_id'] not in main['unranked']]
    for omit in ('cagr', 'fee20_cagr'):
        sensitivity['omit_'+omit+'_same_population'] = rank(complete, [m for m in metrics if m.name != omit])
    sensitivity['previous_six_objectives'] = read(UPSTREAM/'pareto.json')
    layer_maps = {name: {cid: layer['layer'] for layer in result['layers'] for cid in layer['config_ids']}
                  for name, result in sensitivity.items()}
    mainmap = {cid: layer['layer'] for layer in main['layers'] for cid in layer['config_ids']}
    changes = pd.DataFrame([{'config_id': cid, 'main_layer': mainmap.get(cid), 'variant': name,
                             'variant_layer': lm.get(cid), 'both_ranked': cid in lm and cid in mainmap}
                            for cid in rows.config_id for name, lm in layer_maps.items()])
    return rows, main, groups, sensitivity, changes, definitions


def recommendations(rows, main, definitions, groups):
    byid = rows.set_index('config_id'); front = set(main['layers'][0]['config_ids'])
    # Explicit researcher choices for this version, documented rather than hidden in a scalar score.
    choices = [
        ('S011-CFG-000624', '收益优先对照', '同标准账户成员000618/000624中，000624已观测20近邻比例80%，000618为75%，半径同为2；联合邻点数分别11/12。不均匀采样支持暂选阅读代表，尚不能证明参数更稳健。'),
        ('S011-CFG-000628', '回撤优先对照', '同标准账户成员000621/000628中，000628已观测20近邻比例55%，000621为45%，半径同为3；联合邻点数分别1/2。联合覆盖稀疏，代表性选择保留争议。'),
        ('S011-CFG-000649', '历史代表连续性对照', '保留原EX25T014及既有公共SRT/TXE重放证据；同标准账户000653近邻比例同为80%，但半径3而本配置为2、联合邻点数14而本配置为3，不能据此宣称任一配置全面更稳健。')]
    layers = {cid: x['layer'] for x in main['layers'] for cid in x['config_ids']}
    items = []
    for cid, role, reason in choices:
        r = byid.loc[cid]; group = next(g for g in groups if cid in g['config_ids'])
        items.append({'config_id': cid, 'role': role, 'core_layer': layers.get(cid),
                      'parameters': definitions[cid]['definition']['parameters'],
                      'same_standard_behavior_config_ids': group['config_ids'],
                      'representative_reason': reason,
                      'metrics': {n: float(r[n]) for n in ('cagr', 'drawdown_magnitude', 'fee20_cagr', 'worst_rolling60_excess', 'top3_positive_pnl_share', 'knn20_qualified_share', 'knn20_radius', 'joint_observed_count')},
                      'opportunity_cost_vs_return_reference': {'standard_cagr_gap': float(byid.loc['S011-CFG-000624'].cagr-r.cagr),
                                                            'stress_cagr_gap': float(byid.loc['S011-CFG-000624'].fee20_cagr-r.fee20_cagr)},
                      'tradeoff': '较高开发池收益，回撤高于低回撤组。' if cid.endswith('624') else ('较低开发池回撤，标准与成本压力收益较低。' if cid.endswith('628') else '保留连续性；核心绩效被收益组支配，既有重放不构成经济优势。'),
                      'adverse_evidence': ['最差60日仍明显落后同期买入持有', '已见开发池与反复搜索偏差未消除', '未完成均衡联合扰动、容量/延迟及独立前瞻验证'],
                      'evidence': ['ranking_metrics.parquet', 'diagnostics.parquet', 'comparisons.parquet', 'behavior_groups.json', 'evidence_catalog.json'],
                      'approved': False})
    represented = {next(g['behavior_id'] for g in groups if x['config_id'] in g['config_ids']) for x in items[:2]}
    uncovered = [g['behavior_id'] for g in groups if g['front_member_ids'] and g['behavior_id'] not in represented]
    return {'status': 'RESEARCHER_COMPARISON_ONLY', 'automatic_promotion': False, 'items': items,
            'additional_core_front_behavior_ids': uncovered,
            'selection_rule': 'Two observed return/drawdown tradeoff roles plus historical continuity; no forced quota, all other front groups explicitly retained.',
            'all_configurations_remain_selectable': True,
            'warning': 'Recommendations and rounding are retrospective research judgments, not confirmed robustness or user promotion.'}


def report(output, rows, main, groups, sensitivity, advice):
    lines = ['# S011阶段四迭代03：核心绩效与风险分开呈现', '',
             '状态：SELF_CHECK_COMPLETE_PENDING_USER_DECISION。未晋升任何配置，全部是已见开发池证据。', '',
             '主排序：标准成本净年化、最大回撤、单边成本从10bp增至20bp后的净年化。诊断完整保留，不合成为总分。', '',
             f'36个配置中{sum(len(x["config_ids"]) for x in main["layers"])}个可比，1个缺少同源码版本成本证据；共{len(groups)}种标准场景行为。', '',
             '## 核心分层', '', '| 层级 | 配置数 | 标准行为数 |', '| --- | --- | --- |']
    for layer in main['layers']:
        behavior_count = rows.loc[rows.config_id.isin(layer['config_ids']), 'behavior_id'].nunique()
        lines.append(f'| {layer["layer"]} | {len(layer["config_ids"])} | {behavior_count} |')
    lines += ['', '同一标准行为的成员如压力情景或证据状态不同，分别保留层级；行为数不能跨层直接相加。', '',
              '## 代表性取舍（建议，不是晋升）', '', '| 角色 | 配置ID | 年化 | 回撤幅度 | 加倍成本年化 | 核心层 |', '| --- | --- | --- | --- | --- | --- |']
    for item in advice['items']:
        m = item['metrics']
        lines.append(f'| {item["role"]} | {item["config_id"]} | {m["cagr"]:.2%} | {m["drawdown_magnitude"]:.2%} | {m["fee20_cagr"]:.2%} | {item["core_layer"]} |')
    for item in advice['items']:
        lines += ['', f'- {item["config_id"]}：{item["tradeoff"]}{item["representative_reason"]}']
    lines += ['', '完整参数、机会成本及不利证据见[研究建议](recommendations.json)，所有成员及组内差异见[行为组](behavior_groups.json)。', '',
              '## 精度与敏感性', '', '主比较分辨率：年化0.1个百分点、回撤0.01个百分点，零点网格四舍五入。分箱差异不等于统计显著差异；边界两侧的很小差异仍可改变层级。', '',
              '| 口径 | 各层配置数 | 第一层与主口径一致 |', '| --- | --- | --- |']
    for name, result in sensitivity.items():
        same = set(result['layers'][0]['config_ids']) == set(main['layers'][0]['config_ids'])
        lines.append(f'| {name} | '+ '/'.join(str(len(x['config_ids'])) for x in result['layers'])+f' | {"是" if same else "否"} |')
    lines += ['', '逐配置层级变化见[layer_changes.parquet](layer_changes.parquet)。后续层数及成员对精度较敏感，不能把层数差当作经济差距或置信程度。精度设置和主指标变更均发生在已见旧结果之后，不作为独立验证。', '',
              f'标准与压力净年化相关系数为{rows.cagr.corr(rows.fee20_cagr):.6f}，两者高度相关；不做加权计分，另报分别移除一个收益指标的同样本敏感性。', '',
              '## 完整风险与缺口', '',
              '近邻、边界、集中度、年度/季度/滚动区间、区块重抽样及PBO/DSR继续完整披露。PBO 8/10块为62.86%/53.57%，是开发池选优偏差诊断，不是未来亏损概率。沿用已封存统计，没有重跑随机实验。', '',
              'S011-CFG-000193缺少同源码版本的费用压力账户，单列未排序；与000137标准行为相同也不借用费用结果。未新增均衡联合扰动、盘口排队/容量/冲击/延迟、跨标的、新消融或前瞻数据。', '',
              '## 机器入口与复算', '',
              '[清单](manifest.json)、[方案](protocol.json)、[核心排序](pareto.json)、[敏感性](ranking_sensitivity.json)、[全量风险解释](assessment.json)、[用户决定](decision.json)。完整历史数据与可执行代码由[evidence_catalog.json](evidence_catalog.json)按仓库相对路径和哈希引用。', '',
              '从仓库根使用既有环境；复算输出必须是不存在的.tmp子目录：', '', '```powershell',
              '$env:PYTHONDONTWRITEBYTECODE="1"',
              '.venv/Scripts/python.exe -B -m unittest discover -s research/S011/stage4/iteration_03/tests -v',
              '.venv/Scripts/python.exe -B research/S011/stage4/iteration_03/src/build.py validate --package research/S011/stage4/iteration_03',
              '.venv/Scripts/python.exe -B research/S011/stage4/iteration_03/src/build.py build --output .tmp/s011-stage4-v3-user-rebuild',
              '.venv/Scripts/python.exe -B research/S011/stage4/iteration_03/src/verify.py --package research/S011/stage4/iteration_03', '```', '',
              '指定配置公共SRT/TXE重放入口：`src/replay.py --config-id <配置ID> --data-dir <原候选受管数据目录> --output <新.tmp目录>`。受管目录及权限必须显式准备并匹配身份，不自动借用其他候选缓存；临时数据缺失须重新通过公共入口准备。', '',
              '旧包及历史实验不改写。旧合同通过归档文档快照验证，当前合同另有快照，避免文档后继修订破坏历史身份。下一步由用户选择具体配置晋升、补证或暂不晋升。']
    (output/'README.md').write_text('\n'.join(lines)+'\n', encoding='utf-8', newline='\n')


def seal(output, protocol):
    schemas = {p.name: document_schema(read(p)) for p in sorted(output.glob('*.json')) if p.name != 'manifest.json'}
    dump(output/'schemas/documents.json', schemas)
    dump(output/'schemas/tables.json', {p.name: [{'name': f.name, 'type': str(f.type)} for f in pq.read_schema(p)] for p in sorted(output.glob('*.parquet'))})
    files = {p.relative_to(output).as_posix(): digest(p) for p in sorted(output.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.name != 'manifest.json'}
    dump(output/'manifest.json', {'schema_version': 1, 'run_id': protocol['run_id'], 'files': files,
          'upstream': protocol['upstream'], 'upstream_manifest_sha256': protocol['upstream_manifest_sha256'],
          'hash_policy': 'Package and upstream files raw SHA256; upstream inputs use original manifest policy with explicit archived-document substitution only.',
          'python': sys.version, 'environment': {k: version(k) for k in ('pandas', 'numpy', 'pyarrow')},
          'entrypoints': {'build': 'src/build.py build --output <new .tmp directory>', 'validate': 'src/build.py validate --package <package>', 'independent_verify': 'src/verify.py --package <package>', 'replay': 'src/replay.py --config-id <id> --data-dir <same-candidate-managed-data> --output <new .tmp directory>'},
          'dependencies': 'Existing project .venv and hash-verified upstream evidence/code; no new dependency or implicit temporary cache.',
          'decision_authority': 'USER_ONLY', 'stage_five_started': False})


def build(output):
    if output.exists() or not output.is_relative_to(REPO/'.tmp'):
        raise ValueError('use a fresh directory under repository .tmp')
    protocol = read(SOURCE/'protocol.json')
    checked = check_upstream(protocol, SOURCE/'inputs/previous_RSCH_AGENT.md')
    output.mkdir(parents=True)
    for folder in ('src', 'tests', 'inputs'):
        shutil.copytree(SOURCE/folder, output/folder, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    # Snapshot source documents as canonical LF, preserving the upstream declared canonical identity.
    for name, source in [('previous_RSCH_AGENT.md', SOURCE/'inputs/previous_RSCH_AGENT.md'),
                         ('RSCH_AGENT.md', SOURCE/'inputs/RSCH_AGENT.md' if (SOURCE/'inputs/RSCH_AGENT.md').exists() else REPO/'research/RSCH_AGENT.md')]:
        (output/'inputs'/name).write_text(source.read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
    shutil.copyfile(SOURCE/'protocol.json', output/'protocol.json')
    rows, main, groups, sensitivity, changes, definitions = calculations(protocol)
    rows.to_parquet(output/'ranking_metrics.parquet', index=False); changes.to_parquet(output/'layer_changes.parquet', index=False)
    for name in ('diagnostics.parquet', 'comparisons.parquet', 'family_statistics.json'):
        shutil.copyfile(UPSTREAM/name, output/name)
    dump(output/'configurations.json', {'kind': 'IMMUTABLE_REGISTRY_REFERENCE', 'path_base': 'repository_root',
         'path': 'research/S011/stage4/iteration_02/configurations.json', 'sha256': digest(UPSTREAM/'configurations.json'),
         'qualified_config_ids': rows.config_id.tolist(), 'registered_count': len(definitions)})
    dump(output/'pareto.json', main); dump(output/'ranking_sensitivity.json', sensitivity)
    dump(output/'behavior_groups.json', {'grouping_scope': protocol['grouping'], 'groups': groups})
    dump(output/'decision.json', Decision().model_dump())
    advice = recommendations(rows, main, definitions, groups); dump(output/'recommendations.json', advice)
    catalog = {p: {'path': f'{protocol["upstream"]}/{p}', 'sha256': digest(UPSTREAM/p)} for p in read(UPSTREAM/'manifest.json')['files']}
    catalog['upstream_manifest'] = {'path': protocol['upstream']+'/manifest.json', 'sha256': protocol['upstream_manifest_sha256']}
    receipt = 'research/S011/stage4/iteration_02_verification/replay_CFG000649.json'
    catalog['historical_replay_receipt'] = {'path': receipt, 'sha256': digest(REPO/receipt)}
    dump(output/'evidence_catalog.json', {'path_base': 'repository_root', 'items': catalog,
         'account_replay': 'src/replay.py resolves immutable registry and evaluations through this package, validates the archived contract snapshot and runs the original public SRT/TXE implementation. Explicit same-candidate managed input is required; no fallback.',
         'historical_replay_receipt': 'research/S011/stage4/iteration_02_verification/replay_CFG000649.json'})
    diag = pd.read_parquet(output/'diagnostics.parquet')
    profiles = []
    for cid in rows.config_id:
        subset = diag.loc[diag.config_id.eq(cid)]
        profiles.append({'config_id': cid, 'diagnostic_rows': len(subset),
                         'missing_or_inapplicable': subset.loc[~subset.status.eq('COMPLETE'), ['metric', 'scenario', 'status']].to_dict('records'),
                         'evidence': ['diagnostics.parquet', 'comparisons.parquet', 'family_statistics.json', 'evidence_catalog.json']})
    front_ids = main['layers'][0]['config_ids']
    dump(output/'assessment.json', {'status': 'SELF_CHECK_COMPLETE_PENDING_USER_DECISION', 'upstream_checks': checked,
         'summary': {'qualified': len(rows), 'ranked': len(rows)-len(main['unranked']), 'unranked': len(main['unranked']),
                     'behavior_groups': len(groups), 'first_layer_configurations': len(front_ids),
                     'first_layer_behaviors': int(rows.loc[rows.config_id.isin(front_ids), 'behavior_id'].nunique())},
         'core_return_stress_correlation': float(rows.cagr.corr(rows.fee20_cagr)),
         'correlation_interpretation': 'Strongly related outcomes; no additive weighting. Omission tests use the same complete population. Keep both to show absolute net outcome under each cost scenario.',
         'all_config_risk_profiles': profiles, 'unmeasured': protocol['unmeasured'],
         'search_bias_recomputed': False, 'reused_statistical_evidence': 'family_statistics.json',
         'selection_disclosure': protocol['selection_disclosure'], 'no_automatic_elimination_or_promotion': True})
    report(output, rows, main, groups, sensitivity, advice)
    seal(output, protocol); validate(output)


def validate(package):
    manifest = read(package/'manifest.json')
    actual = {p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p != package/'manifest.json'}
    if actual != set(manifest['files']):
        raise ValueError('package inventory mismatch')
    for p, h in manifest['files'].items():
        if digest(package/p) != h:
            raise ValueError('package changed: '+p)
    protocol = read(package/'protocol.json'); check_upstream(protocol, package/'inputs/previous_RSCH_AGENT.md')
    for name, schema in read(package/'schemas/documents.json').items():
        validate_document(read(package/name), schema)
    for name, schema in read(package/'schemas/tables.json').items():
        if schema != [{'name': f.name, 'type': str(f.type)} for f in pq.read_schema(package/name)]:
            raise ValueError('table schema changed')
    Decision.model_validate(read(package/'decision.json'))
    rows, main, groups, sensitivity, changes, definitions = calculations(protocol)
    pd.testing.assert_frame_equal(rows, pd.read_parquet(package/'ranking_metrics.parquet'))
    pd.testing.assert_frame_equal(changes, pd.read_parquet(package/'layer_changes.parquet'))
    for filename, expected in [('pareto.json', main), ('ranking_sensitivity.json', sensitivity),
                                ('recommendations.json', recommendations(rows, main, definitions, groups))]:
        if read(package/filename) != expected:
            raise ValueError('recalculation mismatch: '+filename)
    if read(package/'behavior_groups.json')['groups'] != groups:
        raise ValueError('behavior membership mismatch')
    for name in ('diagnostics.parquet', 'comparisons.parquet', 'family_statistics.json'):
        if digest(package/name) != digest(UPSTREAM/name):
            raise ValueError('risk evidence not preserved')
    for item in read(package/'evidence_catalog.json')['items'].values():
        if digest(REPO/item['path']) != item['sha256']:
            raise ValueError('evidence reference changed')
    print(json.dumps({'status': 'PASS', 'configurations': len(rows), 'layer_counts': [len(x['config_ids']) for x in main['layers']],
                      'unranked': len(main['unranked']), 'behavior_groups': len(groups)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('build').add_argument('--output', required=True, type=Path)
    sub.add_parser('validate').add_argument('--package', required=True, type=Path)
    args = parser.parse_args()
    build(args.output.resolve()) if args.command == 'build' else validate(args.package.resolve())
