"""Bind cost-response findings and the stage-three stop decision to full accounts."""
import json
from pathlib import Path

WORK = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((WORK/path).read_bytes())


a = read('others/fee_analysis.json')
r = read('others/results.json')
audit = read('others/semantic_audit.json')
assert a['status'] == r['status'] == 'COMPLETE'
assert a['pressure_pass_count'] == 6 and len(a['pairs']) == 7
assert {cid for cid,v in a['pairs'].items() if not v['pressure_eligible']} == {'C1045'}
assert r['workload']['candidate_runs'] == 7 and r['workload']['benchmark_runs'] == 1
assert r['workload']['reused_accounts'] == 7 and r['workload']['scenario_accounts'] == 14
assert len(audit['results']) == 7 and sum(v['decisions'] for v in audit['results']) == 109914
pairs = a['pairs']
for v in pairs.values():
    c = v['matched_cycles']
    assert not c['standard_only_entries'] and not c['pressure_only_entries']
    assert c['common_closed_entries'] == c['common_entries_and_exits']
bad = pairs['C1045']
assert {k for k,v in bad['pressure_gates'].items() if not v} == {'calmar'}
assert bad['pressure']['mdd_episode']['peak'] == '2022-11-30'
assert bad['pressure']['mdd_episode']['trough'] == '2023-04-05'
turnover_ratio = bad['standard']['execution']['mean_closed_cycle_turnover_over_entry_equity']/pairs['C0804']['standard']['execution']['mean_closed_cycle_turnover_over_entry_equity']-1
rebuild_turnover = pairs['C0804']['standard']['execution']['mean_closed_cycle_turnover_over_entry_equity']/pairs['C0801']['standard']['execution']['mean_closed_cycle_turnover_over_entry_equity']-1
rebuild_gain = pairs['C0804']['pressure']['metrics']['nar']-pairs['C0801']['pressure']['metrics']['nar']
fixed_dd = bad['pressure']['metrics']['nar']/bad['standard']['metrics']['drawdown']
fixed_nar = bad['standard']['metrics']['nar']/bad['pressure']['metrics']['drawdown']
value = {
    'title':'新授权阶段三第3轮：连续调仓的费用配对与收口判断',
    'conclusion':'7份标准证据复用、7个每侧0.2%压力策略账户和1个共享压力买持全部完成。6个代表通过原费用条件；C1045仅压力Calmar未达4.5。结果支持保留渐进退出与已有替代配置，阶段三在第3轮收口，剩余7轮保留，下一步申请完整阶段四自检。',
    'findings':[
        '固定共同参数原型C0798/C0801/C0804、三族最新中心最高NAR点C0966/C1010/C1045及窄区间参考C0909。保留原候选ID、content、源码和参数，标准账户不重算。当前标准准备请求与历史请求仅实验归属不同；压力仅改变费用、场景、测量层级及费用导致的审计输入派生哈希，行情和执行合同逐字段核验。',
        '原型硬退出C0798压力NAR62.6526%、Calmar4.926382；单向渐进C0801为60.2186%、4.787433；恢复型C0804为61.5828%、4.698414。三者均通过原压力四门，恢复机制的费用尚未表现为共同瓶颈。',
        '最新硬退出C0966的标准NAR71.4803%、Calmar5.065577，压力NAR66.2844%、Calmar4.628892；单向渐进C1010标准66.9452%、5.014322，压力62.2042%、4.588179。两者保留优化后的收益增益且通过本轮费用条件，自身完整参数邻域继续待检。',
        'C1045标准NAR70.9005%、MDD14.1122%、Calmar5.024053；压力NAR64.9797%、MDD14.8903%、Calmar4.363890。费用后NAR减少5.9208个百分点、MDD增加0.7781个百分点，最大回撤由2024-04-03至04-19转为2022-11-30至2023-04-05。这是完整资金路径变化，保留原中心合格及压力Calmar失败两项事实。',
        f'C1045平均闭合周期成交金额/首次成交时记录权益为1.4527，较C0804高{turnover_ratio:.2%}；标准实际成交数3025，低于C0804的3086。其平均周期费用占权益由0.1453%增至0.2906%，原型C0804为0.1208%增至0.2414%。证据指向完整配置的较大仓位和成交规模；恢复动作的独立成本贡献尚未被这些多参数对照分离。',
        f'原同参数单向渐进C0801到恢复型C0804，平均周期成交金额/权益仅增加{rebuild_turnover:.2%}，压力NAR仍提高{rebuild_gain*100:.4f}个百分点且两者均达标。C0909标准NAR67.8111%、Calmar5.345863，压力62.9391%、4.727664，提供另一份中心及费用均达标的恢复型配置。C0909与其他点存在多参数差异，窄退出宽度本身的因果贡献保留待证。',
        f'算术拆分辅助理解C1045：压力NAR除以标准MDD为{fixed_dd:.6f}，标准NAR除以压力MDD为{fixed_nar:.6f}；实际两项同时变化后Calmar4.363890。该拆分解释收益和回撤两项共同作用，未增加账户回放或构造交易反事实。',
        '7个标准/压力配对的全部实际闭合入场与退出时点分别一致，成本通过费用、现金及整数单位调整影响后续资金路径；各账户的成交笔数仍可变化。完整年度、回撤段、末端未闭合持仓、归一化成交与费用、正反例及全部共同周期见[费用分析](others/fee_analysis.md)和[结构化分析](others/fee_analysis.json)。',
        '7份压力账户共109914条决定全部完成独立业务重建。新10轮额度累计3轮，标准联合搜索、有限交互和少数费用配对回答了各自问题；目前已有多份中心及费用达标实现，最有价值的未决问题转为完整邻域和正式自检。继续泛搜预期会增加相近候选，暂不以消耗额度为目标。'
    ],
    'next_action':'完成新授权阶段三的全部原中心达标实现登记、精确去重和CANDIDATES交付；原中心六门及NAR排序保持，C1045费用失败另列，剩余7轮保留。建议下一阶段先全候选费用与可复用账本诊断，再对费用通过者计算完整合法邻域；费用失败者保留失败事实和参数未测状态。该减少无效回放的正式阶段四覆盖方案须呈现资源与范围后取得用户批准。'
}
target = WORK/'others/interpretation.json'
assert not target.exists()
target.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())
print('FEE_INTERPRETATION_READY')
