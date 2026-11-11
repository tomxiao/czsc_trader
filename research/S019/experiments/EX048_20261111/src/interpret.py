"""Bind the finite interaction findings to completed accounts and business audits."""
import json
from pathlib import Path

WORK = Path(__file__).resolve().parents[1]

def read(relative):
    return json.loads((WORK/relative).read_bytes())

a = read('others/diagnostic_analysis.json')
r = read('others/results.json')
audit = read('others/semantic_audit.json')
assert a['status'] == r['status'] == 'COMPLETE'
assert a['distinct_design_configurations'] == 123 and a['all_point_six_gate_pass_count'] == 92
assert r['workload']['candidate_runs'] == 117 and r['workload']['reused_accounts'] == 6
assert r['workload']['benchmark_runs'] == 1
assert len(audit['results']) == 17 and sum(x['decisions'] for x in audit['results']) == 266934
g = a['groups']
for name in ('ramp_linear_winner', 'rebuild_linear_winner', 'rebuild_linear_control'):
    assert g[name]['finite_noncenter_diagnostic']['economic_pass_fraction'] == 1
assert g['hard_linear_winner']['finite_noncenter_diagnostic']['economic_pass_fraction'] == .9
assert all(x['finite_noncenter_diagnostic']['all_absolute_risk_pass'] for x in g.values())
assert a['point_gate_patterns'] == {'ALL_PASS': 92, 'calmar': 31}
best = {}
for row in r['accounts'].values():
    if row['candidate']['eligible']:
        policy = row['parameters']['exit_policy']
        if policy not in best or row['candidate']['nar'] > best[policy]['candidate']['nar']:
            best[policy] = row
assert {k:v['candidate_id'] for k,v in best.items()} == {
    'hard':'C0966','ramp':'C1010','ramp_rebuild':'C1045'}

findings = [
    '本轮为事前固定因素诊断：5个锚点，各有效轴相对上下5%、渐进退出二轴角点、参与三轴角点及全轴同向变化，共123个配置。6个EX046原型ATR点严格核对原请求，仅实验归属不同后复用；117个新策略账户和1个共享买持全部完成。5个中心复算的逐柱、逐日、目标与成交经济路径精确一致。',
    '硬退出原型控制与C0829的ATR三档Calmar跨度分别为0.887772、0.901875，扩域提高收益后，ATR跳变问题仍在。C0829的ATR下调5%得到Calmar4.361202，全轴下调5%为4.261307；其有限非中心点经济通过率90%（N=20），原型控制为100%（N=20），最低Calmar4.541592。这里保留实际点集分母，完整笛卡尔邻域尚待阶段四。',
    '单向渐进原型C0801（复算C0855/C0993）在本轮26个有限非中心点全部满足邻点经济条件；全组最低Calmar4.920761。ATR三档跨度0.103196，退出二轴含中心跨度0.110033；参与阈值和参与三轴仍有更明显的收益/回撤取舍。参与阈值下调点C0998的Calmar4.999471734按未舍入值未过中心门5。',
    '可恢复渐进C0924和原型C0804（复算C0903/C1047）的26个有限非中心点分别全部满足邻点经济条件；全组最低Calmar4.760296和4.868951。ATR三档跨度分别0.142743和0.314086，退出二轴跨度0.167850和0.323005。本轮联合配置下的ATR反应较平缓；C0924最高NAR的代价是中心Calmar仅5.026881，多个邻近配置低于中心5而仍高于邻点4.5。',
]
for policy, name in [('hard','硬退出'),('ramp','单向渐进'),('ramp_rebuild','可恢复渐进')]:
    row = best[policy]
    m = row['candidate']
    findings.append(f"{name}本轮原六门后最高NAR为{row['candidate_id']}：NAR{m['nar']:.6%}、MDD{m['drawdown']:.6%}、Calmar{m['calmar']:.9f}。该配置作为新的中心达标实现保留；其自身完整邻域尚未展开，所属锚点的有限诊断另列。")
findings += [
    'C0966与C1010来自参与q/t/h联合变化；C1045来自C0924六轴同时下调5%。它们是完整参数协作结果。全部123点中92点通过原中心六门，余31点均仅Calmar未过；全部点通过MDD和原频率目标。正式中心排序保持六门后未舍入NAR，有限诊断未添加新评分或淘汰门。',
    '账本保留完整期末持仓及浮动盈亏。C0966和C1010的MDD均在2024-04-03至04-19，分别于2024-11-05和11-06恢复；C1045同段MDD于2024-07-03恢复。C0924及其全轴上调点的MDD仍在2026-10-07至样本终点10-30，未恢复。C1045相对原可恢复控制的2022、2023年收益较低，2024至2026较高，主要增长增量在2025、2026；近期收益改善与早期反例同时保留。',
    '固定因素对照回答了搜索后的局部敏感方向；这与第1轮Optuna自适应提议各有用途。5个锚点覆盖的跨组反向联动仍有限。17个中心、控制、最高NAR和不利代表共266934条决定完成独立业务重建，全部通过；全部配置完整指标、方向范围、正反例与路径见[有限交互分析](others/diagnostic_analysis.md)及[结构化证据](others/diagnostic_analysis.json)。',
]
value = {
    'title':'新授权阶段三第2轮：连续退出的参数交互与敏感性',
    'conclusion':'123个配置全部完成，92个通过原中心六门。两个渐进族的有限诊断点均守住原邻点经济条件；领先硬退出配置仍暴露ATR下调方向的跳变。新增各族领先点为C0966、C1010、C1045。下一轮以少数代表的费用配对回答连续调仓成本问题，再决定阶段三收口。',
    'findings':findings,
    'next_action':'继续新10轮额度内第3轮阶段三开发性费用诊断：复用共同参数原型C0798/C0801/C0804、三族最新最高NAR点C0966/C1010/C1045和窄退出区间C0909的标准账户，仅新增7个每侧0.2%同参数压力账户与1个共享买持。按完整账本、周期权益归一化费用和实际调仓解释费用反应；保持原中心六门与NAR排序。结果用于决定是否有具体优化问题，全部候选正式阶段四验收及完整邻域80%仍待批准。'
}
target = WORK/'others/interpretation.json'
assert not target.exists()
target.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())
print('INTERPRETATION_READY')
