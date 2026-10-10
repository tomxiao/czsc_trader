"""Reproduce two targeted reentry accounts and full-domain parameter conclusion."""
from common import SRC, RUNS, PROTOCOLS, read, write


def main():
    analysis, parameter = read(RUNS / 'analysis.json'), read(RUNS / 'parameter_analysis.json')
    assert analysis['status'] == 'PASS' and parameter['status'] in ('PASS', 'NOT_APPLICABLE')
    labels = ('B0-TIME', 'B0-MEAN', 'B0-TIME-CLOSE', 'B0-TIME-BODY', 'N0', 'N1', 'N2', 'N3')
    assert set(analysis['rows']) == set(labels)
    text = """# S013：按定时退出价格状态区分再次买入的最小机制对照

RSCH阶段三，用户授权自主完成研究，无需逐轮评审。S013既有510500.SH数据固定2020-01-02至2026-09-30共1636交易日、100万元、HFQ信号、整手100、T决策/T+1执行、单边0.1%费用、策略及可执行LimitBuyHold统一1%限买溢价。

原四项经济目标不变：年化至少正基准1.5倍；每自然年回撤严格低于基准；每60日不少于4笔闭合交易（本窗至少110笔）；基准亏损年2022/2023连续账户收益为正。全窗回撤用于诊断，不能替代年度门。

EX042以37个既有完整账户核对退出价格状态及真实资金。原中心2023低于入场价TIME退出后再次入场的持仓来源贡献+2.3049个百分点；MEAN/BODY2024同类贡献约+33.6747/+33.6749个百分点。亏着退出不意味着再次买入有害。EX041对所有下跌TIME再次入场加方向门的两个完整账户均使2023约-1.25%。这些是事前已见反证，不是本轮独立验证，旧组PnL不能相减预测新收益。

本轮MEAN背景四配置：N0/N1仅在上一次最终bear TIME退出Close严格低于自身信号入场Close锚点时，分别要求本T Close>前一日Close或Close>本日Open；N2/N3仅在严格高于锚点时加相同门。EQUAL/NONE/非选中类别沿原MEAN入场。只在原空仓资格合格rawbear机会门控，方向拒绝先于原score。每次bear TIME最终出口分类，其他出口记录None；任意路线成功信号entry消耗并清空reason/route/category，空仓失败/raw变化保留。分类描述信号价格，不能当作实际净盈亏。

原买入确认、全部持仓退出优先级与H8/H4信号日保持，13个原数值坐标及完整域仍有效。MEAN保持原严格过去L均值居中ACF及L+21预热。没有新幅度/容差/未来观察窗/年份例外。四个类别范围与方向选择是13数值域之外的新固定结构，本轮未证明类别选择本身稳定。

四新业务配置、五实际完整评价（N0串行/spawn严格一致），四旧完整账户精确复用。每个新配置全1636行由不导入SRT的独立公式/状态重建核对，日期沿原41v2绑定公共日历保持全部T至T+1及末端。八账户信号/原生身份/真实数量/现金/价格/费用独立核对，五基准账本严格一致，所有失败账户、自然年及尾仓保留。

|账户|候选|年化|全窗回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---:|---:|---:|---:|---:|---|
"""
    for label in labels:
        row = analysis['rows'][label]
        failures = '、'.join(k for k, v in row['gates'].items() if not v)
        text += f"|{label}|{row['candidate_id']}|{row['net_cagr']:.4%}|{row['drawdown']:.4%}|{row['closed_trades']}|{row['annual']['2022']['return']:+.4%}|{row['annual']['2023']['return']:+.4%}|{'通过' if row['qualified'] else failures}|\n"
    text += '\n|账户|自然年|收益|回撤|基准回撤|年度回撤门|\n|---|---:|---:|---:|---:|---|\n'
    for label in labels:
        row = analysis['rows'][label]
        for year, value in row['annual'].items():
            benchmark = row['benchmark_annual'][year]['drawdown']
            text += f"|{label}|{year}|{value['return']:+.4%}|{value['drawdown']:.4%}|{benchmark:.4%}|{'通过' if value['drawdown'] < benchmark else '未通过'}|\n"
    achieved = False
    if parameter['status'] == 'PASS':
        original = parameter['summaries']['B0-TIME']
        text += '\n|中心|收益Q10|回撤Q90|收益退化|回撤退化|邻点四门通过数|\n|---|---:|---:|---:|---:|---:|\n'
        for label, row in parameter['summaries'].items():
            text += f"|{label}|{row['q10_cagr']:.4%}|{row['q90_drawdown']:.4%}|{row['return_degradation']:.4%}|{row['drawdown_degradation']:.4%}|{row['qualified_points']}/32|\n"
            if label != 'B0-TIME':
                achieved |= bool(analysis['rows'][label]['qualified'] and row['q10_cagr'] > original['q10_cagr'] and
                    row['q90_drawdown'] < original['q90_drawdown'] and row['return_degradation'] < original['return_degradation'] and
                    row['drawdown_degradation'] < original['drawdown_degradation'])
        text += '\n参数保持原13完整域、域宽归一总L2=.05、32点、seed13/PCG64、整数HALF_EVEN、LINEAR分位。中心满足四门且绝对尾部与相对退化同时改善才说明开发池实质改善；较弱中心造成退化缩小不算。邻点资格是诊断。原EX01532完整原生身份/计划/绑定/账户精确复用。\n'
    else:
        assert not any(analysis['rows'][label]['qualified'] for label in ('N0', 'N1', 'N2', 'N3'))
        text += '\n四新中心均未通过原四门，按事前方案零新增参数账户。本轮无参数敏感性改善证据。\n'
    correction = read(PROTOCOLS / 'technical_correction.json')
    assert correction['new_account_evaluations'] == 0 and correction['runtime_changed'] is False
    text += '\n静态审查与合成复现发现原冻结汇总器尚未识别43四个机制，会错误拒绝新方向拒绝样本。原源/几何保留，显式v2仅新增类别条件、对应入口导入和完整三字段机制描述；其他资金/年度/四门函数AST保持。合成非法类别与拒绝优先级验证通过，全部新账户以v2独立核对；交易源码及原32点完整域未改，零账户重跑。\n'
    execution_correction = read(PROTOCOLS / 'parameter_execution_correction.json')
    assert execution_correction['new_account_evaluations_for_recovery'] == 0 and execution_correction['runtime_changed'] is False
    text += '\n参数首批发布后，旧队列因共享列表令试验编号重复登记而失败，原代码/checkpoint/study/计划保留。首8点缓存与已正式发布证据逐一严格核对；v3固定原复用数量32并从8个已有结果恢复，零账户重跑，剩余24点照原计划执行。总计32新参数业务账户、33实际评价（2预检+7首批+24后续），不因失败删点/改点/改规则。\n'
    decision = read(PROTOCOLS / 'decision.json')
    text += '\n' + '\n\n'.join(decision['conclusions']) + '\n\n' + decision['next_action'] + '\n'
    text += '\n已见开发池反复选择存在偏差，不是独立验证或未来保证。全路径差异是完整账户对照，不能用删掉旧交易的盈亏相加替代新利润。FULL只核验证据完整性。未推进正式阶段四、冻结、PTE或生产。\n'
    text += '\n合成验证保持完整13维32坐标、全部类别及16种中心资格组合。原41v2仅缺失分类metadata在独立期望None位置允许None/浮点NaN等价，真实非空类别和所有经济字段严格核对。新last_exit_category沿同一明确缺失契约；无 blanket NaN修复或金融值替换。\n'
    write(RUNS / 'conclusion.json', {'objective_achieved': achieved, 'status': 'COMPLETE',
        'new_qualified': sum(analysis['rows'][label]['qualified'] for label in ('N0', 'N1', 'N2', 'N3')),
        'mechanism_actual_evaluations': 5, 'new_mechanism_business_accounts': 4, 'reused_center_accounts': 4,
        'new_parameter_business_accounts': parameter.get('new_parameter_business_accounts', 0),
        'parameter_actual_evaluations': parameter.get('actual_parameter_evaluations', 0),
        'reused_parameter_accounts': parameter.get('reused_parameter_accounts', 0), 'economic_targets': 'UNCHANGED'})
    text += '\n源码静态检查覆盖全src，仅已冻结v3调度源的未使用optuna导入F401明示豁免以保留冻结字节；其他规则通过。未将此豁免视为经济或账户验证。\n'
    target = SRC.parent / 'others/report.md'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8', newline='\n')
    print({'report': 'COMPLETE', 'objective_achieved': achieved}, flush=True)


if __name__ == '__main__':
    main()
