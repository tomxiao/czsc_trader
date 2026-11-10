"""Instantiate the predeclared rebuild comparison from completed family adaptation."""
import json
from hashlib import sha256
from pathlib import Path

root = Path.cwd()
previous = root/'research/S019/experiments/EX045_20261111'
assert json.loads((previous/'others/execution.json').read_bytes())['status'] == 'COMPLETE'
rows = list(json.loads((previous/'others/summary.json').read_bytes()).values())
ramp = [r for r in rows if r['family'] == 'ramp_linear']
qualified = [r for r in ramp if r['candidate']['eligible']]
if qualified:
    chosen = max(qualified, key=lambda r: r['candidate']['nar'])
    reason = 'ORIGINAL_SIX_GATES_THEN_MAXIMUM_NAR'
else:
    diagnostic = [r for r in ramp if all(v for k, v in r['candidate']['gates'].items() if 'calmar' not in k.lower())]
    assert diagnostic, 'Root review required: no ramp point passes the other five original gates'
    chosen = max(diagnostic, key=lambda r: (r['candidate']['calmar'], r['candidate']['nar']))
    reason = 'CALMAR_GAP_DIAGNOSTIC_OTHER_FIVE_GATES_THEN_MAXIMUM_CALMAR'

old = root/'research/S019/experiments/EX044_20261110'
old_spec = json.loads((old/'protocols/specs.json').read_bytes())
first = json.loads((old/'others/results.json').read_bytes())['accounts']['ramp_linear10_center']
anchors = [
    {'name': 'original', 'parameters': first['parameters'], 'candidate_id': first['candidate_id'],
     'control_policy': 'ramp',
     'reference': 'research/S019/experiments/EX044_20261110/others/ramp_linear10_center_account.json',
     'selection': 'PREDECLARED_C0678'},
    {'name': 'adapted', 'parameters': chosen['parameters'], 'candidate_id': chosen['id'],
     'control_policy': 'ramp',
     'reference': f"research/S019/experiments/EX045_20261111/others/trials/{chosen['name']}_account.json",
     'selection': reason},
]
qualified_linear = [r for r in rows if r['family'] == 'hard_linear' and r['candidate']['eligible']]
if qualified_linear:
    linear = max(qualified_linear, key=lambda r: r['candidate']['nar'])
    identity = {k: v for k, v in linear['parameters'].items() if k != 'exit_policy'}
    assert all(identity != {k: v for k, v in a['parameters'].items() if k != 'exit_policy'} for a in anchors), 'Review duplicate qualified linear anchor before opening'
    anchors.append({'name': 'qualified_linear', 'parameters': linear['parameters'],
        'candidate_id': linear['id'], 'control_policy': 'hard',
        'reference': f"research/S019/experiments/EX045_20261111/others/trials/{linear['name']}_account.json",
        'selection': 'ORIGINAL_SIX_GATES_THEN_MAXIMUM_NAR_IN_HARD_LINEAR',
        'rationale': 'Result-driven extension fixed before this comparison: test ATR response and rebuild tradeoff at a qualified continuous-participation configuration.'})
configs, seen, duplicates = [], {}, []
for anchor in anchors:
    anchor['members'] = {}
    for policy in ('hard', 'ramp', 'ramp_rebuild'):
        anchor['members'][policy] = {}
        for level, factor in (('center', 1.0), ('low', .95), ('high', 1.05)):
            p = {**anchor['parameters'], 'exit_policy': policy,
                 'trail_atr': anchor['parameters']['trail_atr']*factor}
            label = f"{anchor['name']}_{policy}_{level}"
            identity = json.dumps(p, sort_keys=True)
            if identity in seen:
                duplicates.append({'label': label, 'reuse': seen[identity]})
                anchor['members'][policy][level] = seen[identity]
                continue
            seen[identity] = label
            anchor['members'][policy][level] = label
            item = {'label': label, 'parameters': p}
            if policy == anchor['control_policy'] and level == 'center':
                item['control_account'] = anchor['reference']
            configs.append(item)
manifest = json.loads((previous/'protocols/run_manifest.json').read_bytes())
assert manifest['next_candidate_start'] == 780
spec = {k: old_spec[k] for k in ('base_candidate', 'parameter_schema', 'state_schema')}
spec.update(candidate_start=780, round_budget={'allocated_rounds': 6, 'round_index': 4,
    'total_round': 8, 'remaining_after_completion': 2}, specs=configs)
plan = '''# 第8轮／本次机制研究第4轮：回落后恢复敞口

EX043与EX044的完整周期对照显示，逐步减仓后始终保留低仓位，在若干价格回升路径中产生收益遗漏，2025年11月及5月等反例已留存。本轮辨别其原因：风险下降后恢复部分仓位，能否改善收益代价，还是会在震荡中增加费用和损失？仍处阶段二，原中心及正式自检标准保持。

在原ramp基础上增加ramp_rebuild。令d=(周期最高已知收盘价−当前已完成柱收盘价)/入场ATR，f=clip((k+w/2−d)/w,0,1)。原ramp用min(历史风险比例,f)；新分支使用当前f，允许部分减仓后的敞口恢复。目标仍为入场配置乘风险比例，占当前权益；全零退出锁定、五日上限、原入场/参与规则及执行合同保持。高水位只使用已完成行情；新分支新增参数0、新增状态字段0。

事前固定两个参数锚点：EX044 C0678的原参数，以及EX045 ramp_linear中原六门合格后NAR最高者；若无全门者，在其余五门合格中选Calmar最高、再以NAR打平，明确作为Calmar缺口诊断锚点。没有符合后者条件的点则暂停该选择并重新作研究判断。选点规则在EX045完成前记录，未使用新机制结果选锚点。

EX045出现连续参与结构的原六门达标中心后，在本轮冻结前扩展第三锚点：取该hard_linear族全部合格者中NAR最高者，保留其hard中心作为控制，以直接检验已获达标余量的配置是否仍有ATR突变，以及恢复敞口的收益代价。选择使用完整EX045结果，当前中途出现的C0720仅是扩展动因。若该族最终无合格者则省略第三锚点。

每锚点比较hard、ramp、ramp_rebuild，并各取ATR中心及上下5%，最多27项设计配置；精确重复去重并留证。前两个锚点的ramp中心和第三锚点的hard中心先与原账户逐柱/逐日权益、目标及成交精确复算，随后执行其余配置。三档点集用于机制对照，正式完整邻域80%验收另按阶段四协议开展。

预定判断覆盖全部账户、同参数配对与全部共同周期，比较原六门、收益、MDD、费用/周转、恢复敞口次数、年度表现和真实损益路径；既看已知回升反例，也看重新加仓后亏损、卖低买高及最大回撤。仅改善个别已见周期、同时恶化整体账户时，应削弱该机制；跨锚点及ATR档一致改善，才支持进一步发展。

采用直接配对实验回答新增状态规则的作用，沿用公共TDR执行会话/检查点，最高12进程、每进程1原生线程。2021预热及2022-01-03至2026-10-30已见历史、MU/SOXX、HFQ整数单位、10万美元、每侧0.1%费用与原限买市卖保持。预计最多27策略加1共享买持，实际重复、成功、失败及未知分别记录。完成扣本轮1轮，原10轮额度已用8、剩2；未自动推进阶段。

具体锚点和完整点集见[配置](specs.json)及[选择记录](anchors.json)。前置证据见[EX043](../../EX043_20261110/report.md)、[EX044](../../EX044_20261110/report.md)、[EX045](../../EX045_20261111/report.md)。
'''
recipe = {'experiment_id': 'EX046_20261111', 'date': '2026-11-11',
    'title': '可逆渐进风险配置与回升参与的配对机制检验',
    'question': '减仓后随价格修复恢复敞口，能否补回收益并维持原风险目标，还是增加反复交易与回撤？',
    'previous_experiment': 'research/S019/experiments/EX045_20261111',
    'specs': spec, 'plan': plan,
    'source_paths': {
        'strategy.py': '.tmp/s019-stage2-resume/strategy_reversible.py',
        'batch_runner.py': '.tmp/s019-stage2-resume/batch_runner_reversible.py',
        'semantic_audit.py': '.tmp/s019-stage2-resume/semantic_reversible.py',
        'prepare_audit.py': '.tmp/s019-stage2-resume/prepare_reversible_audit.py',
        'close_round.py': 'research/S019/experiments/EX043_20261110/src/close_round.py',
    }}
target = root/'.tmp/s019-stage2-resume'
selection = {
    'anchors': anchors, 'selected_ex045_record': chosen, 'duplicates': duplicates,
    'design_configurations': len(configs), 'selection_uses_rebuild_results': False,
    'predeclared_design': '.tmp/s019-stage2-resume/reversible_design.json',
    'effective_unique_parameter_anchors': len({json.dumps({k: v for k, v in a['parameters'].items() if k != 'exit_policy'}, sort_keys=True) for a in anchors})}
if anchors[0]['parameters'] == anchors[1]['parameters']:
    assert chosen['trial_number'] == 0
    path = previous/'others/trials/ramp_linear_000_parity.json'
    parity = json.loads(path.read_bytes())
    assert parity['status'] == 'PASS' and parity['daily_bar_targets_fills'] == 'EXACT_EQUAL'
    assert parity['original'] == anchors[0]['reference']
    assert parity['account'] == json.loads((root/anchors[1]['reference']).read_bytes())
    selection.update(dedup_control_parity=path.relative_to(root).as_posix(),
        dedup_control_parity_sha256=sha256(path.read_bytes()).hexdigest())
for name, payload in (('ex046_recipe.json', recipe), ('ex046_anchor_selection.json', selection)):
    (target/name).write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print('RECIPE_READY', len(configs), chosen['id'], reason)
