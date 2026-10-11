"""Original four economic gates and original absolute/relative parameter objective."""
from common import SRC, PROTOCOLS, RUNS, read, write


def main():
    centers, parameter = read(RUNS / 'analysis.json'), read(RUNS / 'parameter_analysis.json')
    assert centers['status'] == 'PASS'
    tests = {'center_four_gates': centers['rows']['N0']['qualified']}
    if parameter['status'] == 'PASS':
        original, coupled, new = (parameter['summaries'][key] for key in ('B0-TIME', 'B0-COUPLED', 'N0'))
        tests.update(absolute_q10_return_better=new['q10_cagr'] > original['q10_cagr'],
            absolute_q90_drawdown_better=new['q90_drawdown'] < original['q90_drawdown'],
            relative_return_degradation_better=new['return_degradation'] < original['return_degradation'],
            relative_drawdown_degradation_better=new['drawdown_degradation'] < original['drawdown_degradation'])
    achieved = all(tests.values()) and parameter['status'] == 'PASS'
    conclusion = {'status': 'COMPLETE', 'objective_achieved': achieved, 'tests': tests,
        'new_mechanism_business_accounts': 1, 'mechanism_actual_evaluations': 2,
        'mechanism_reused_controls': 3, 'new_parameter_business_accounts': parameter['new_parameter_business_accounts'],
        'parameter_actual_evaluations': parameter['actual_parameter_evaluations'],
        'parameter_reused_accounts': parameter['reused_parameter_accounts'],
        'parameter_technical_duplicate': int(parameter['status'] == 'PASS'),
        'next_action': ('原经济与参数两尾联合目标已满足；单独决定下一阶段。' if achieved else
            '本机制未满足原联合目标；留存反证，依据完整实际路径继续研究，保持原目标和原参数域。'),
        'limits': 'Observed S013 development pool; original13/same32 are finite dependent diagnostics, no independent market validation or categorical universality.'}
    write(RUNS / 'conclusion.json', conclusion)
    write(PROTOCOLS / 'decision.json', conclusion)
    lines = ['# EX057 局部中性以上确认支持恢复相关资格', '',
        '总目标已达成。' if achieved else '本轮对照完成，改善参数敏感性的总目标尚未达成。', '',
        '仅在空仓、当前下跌路线、上次最终下跌到期退出信号价低于其入场信号价时，允许原相关性不达标机会恢复资格；恢复要求收盘高于开盘，且原综合确认分数达到固定数学中性点0。之后仍须原区间、动量和买入确认全部通过。原相关性通过的机会不增加方向或零分限制；持仓日没有例外。', '',
        '本轮只比EX055增加原确认分数>=0条件。0是原加权经验排名分数的数学中性点，不是预测收益或费用覆盖线；为原相关性失格的额外机会要求支持性确认，原相关合格机会仍沿用原阈值。分数等于0允许例外，原阈值更高时仍须通过原确认。该假设是在看到旧结果后提出，选择偏差明确披露，不能预称修复2023。', '',
        '上下文跨空仓失败、确认拒绝和原路线变化保留，任意路线成功发出入场信号清空。退出分类使用信号价格，不能当作实际亏损；实际成交重试不重置持仓年龄或信号锚点。全部持仓退出、优先级、原13数值中心和全域、同32坐标、暖启动、费用和数据保持。', '',
        '## 完整账户对照', '',
        '| 对照 | 候选 | 年化收益 | 全期回撤 | 闭合交易 | 2022收益 | 2023收益 | 四项目标 |',
        '|---|---|---:|---:|---:|---:|---:|---|']
    titles = {'B0-TIME': '原策略', 'B0-COUPLED': '历史均值相关+CLOSE门',
              'B0-RAW-RECOVERY': '旧局部BODY恢复', 'N0': '新局部确认支持恢复'}
    for key, title in titles.items():
        row = centers['rows'][key]
        lines.append(f"| {title} | {row['candidate_id']} | {row['net_cagr']*100:.4f}% | {row['drawdown']*100:.4f}% | {row['closed_trades']} | {row['annual']['2022']['return']*100:+.4f}% | {row['annual']['2023']['return']*100:+.4f}% | {'通过' if row['qualified'] else '未通过'} |")
    names = {'return': '年化收益', 'annual_drawdown': '各自然年回撤', 'frequency': '闭合交易频率', 'negative_buyhold_year_profit': '基准亏损年份仍盈利'}
    lines += ['', '新中心：' + '；'.join(title + ('通过' if centers['rows']['N0']['gates'][key] else '未通过') for key, title in names.items()) + '。', '',
        '三个旧账户按完整身份、实际请求、载荷、依赖、血缘和原生序列化逐字认证后复用，不新增评价。C7980未达标，仍作为旧中心机制诊断，不能成为新参数面板或新增否决条件。串行与spawn信号及策略、基准双方五账本精确一致；全部成交、费用、现金、状态、锚点和独立公式核对通过。技术PASS只表示这些证据核对通过。', '']
    contrast = centers['center_expectation']['path_contrast']
    lines += [f"相对原中心，目标仓位不同{contrast['target_different_days']}天，原因不同{contrast['reason_different_days']}天；首个仓位分歧{contrast['first_target_divergence']}。", '',
        '固定相同决策前状态时，原资格包含于新资格、新资格包含于旧BODY恢复资格；该逻辑包含关系不能推广为完整交易或资金路径的包含关系，因为早一次入场就会改变后续占仓、上下文和资金。未运行本轮原路径真实机会投影；旧EX055 BODY-only投影不能当作本轮实际交易数或利润。恢复分支入场要求分数>=max(0,原阈值)，负阈值在此分支被条件性屏蔽；原相关合格分支保留原阈值的完整作用。原13仍全局有效，但不能宣称各分支的有效自由度不变。', '']
    if parameter['status'] == 'PASS':
        lines += ['## 原13域同32点参数对照', '',
            '| 指标 | 原C2132 | 历史C4900 | 新C8580 |', '|---|---:|---:|---:|']
        for key, title in (('q10_cagr', '较差一端年化Q10（%）'), ('q90_drawdown', '较差一端全期回撤Q90（%）'),
                           ('return_degradation', '相对中心收益下降（百分点）'), ('drawdown_degradation', '相对中心回撤增加（百分点）')):
            lines.append(f"| {title} | {original[key]*100:.4f} | {coupled[key]*100:.4f} | {new[key]*100:.4f} |")
        lines += ['', '完整原13数值域、域宽标准化联合L2=5%、32点、seed13、HALF_EVEN整数、LINEAR分位数保持。旧两组64个原生账户逐字认证复用，新32完整执行，不删维、不缩域、不替换点。相邻点四门通过数仅诊断，不增加资格否决条件。局部例外会条件性屏蔽相关门，但原资格标记及其他路径继续按原阈值；数值诊断不证明固定类别及价格方向普适。', '']
    else:
        lines += ['新中心未达原四项经济目标，32点参数实验不适用；新增及复用参数账户均为零。', '']
    lines += ['## 最强反证与限制', '',
        'EX055局部BODY恢复虽年化16.8663%、118笔、2022盈利18.9454%，2023仍亏损0.0252%，必须原样认定未达标。全取消下跌相关限制曾有217笔，却2022亏损3.2809%、2023亏损9.1143%、全期回撤29.5711%。局部资格恢复同样可能增加坏交易；确认评分达到中性也不保证持续反转。旧7个恢复成交只有2个分数非负（一亏一赢），2023两笔均负，是已见结果影响选择的最强反证，不能删去它们旧盈亏预测新收益。旧双价格方向对照已在完整中心证明业务信号等价，未追加金融账户。', '',
        '原相关CLOSE和BODY局部门均只剩108笔，未达到最低110笔；本轮不是抑制全部原合格买点。原策略2023只有+0.2841%，低价到期后重入来源贡献+2.3049个百分点，不能把这类信号统称亏损交易或删除旧盈利预测新收益。历史均值+CLOSE中心虽达标，其参数较差一端收益和回撤均劣于原C2132；中心改善不能替代完整参数检验。', '',
        '机制在实际账户前声明，纯runtime、独立oracle、原13域辅助和33合成路径核验完整保留，包括失败源和修正。反复使用已见S013开发池，未作独立市场验证；FULL只检验证据完整性。RSCH阶段三，不推进其他阶段。', '',
        '完成判断：' + str(tests), '', conclusion['next_action'], '',
        f"新增机制业务账户1、实际评价2、旧中心复用3；新参数业务账户{conclusion['new_parameter_business_accounts']}、实际评价{conclusion['parameter_actual_evaluations']}、旧参数复用{conclusion['parameter_reused_accounts']}。", '']
    (SRC.parent / 'others').mkdir(exist_ok=True)
    (SRC.parent / 'others/report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print({'report': 'COMPLETE', 'objective_achieved': achieved, 'tests': tests}, flush=True)


if __name__ == '__main__':
    main()
