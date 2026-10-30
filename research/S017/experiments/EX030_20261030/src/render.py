"""Render the fixed-exit background comparison without adding configurations."""
from common import WORK, NAMES, read, digest
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def pct(value):
    return '无定义' if value is None else f'{100*value:.2f}%'


def main():
    census = read(WORK/'others/census.json')
    a, judgment = read(WORK/'others/account_analysis.json'), read(WORK/'others/judgment.json')
    v = read(WORK/'others/account_result_validation.json')
    if a['status'] != 'PASS' or v['status'] != 'PASS' or judgment['account_analysis_sha256'] != digest(WORK/'others/account_analysis.json'):
        raise ValueError('Current checked account analysis and judgment required')
    summaries = a['summaries']
    keys = ['C0056', *[k for k in ('C0059', 'C0060') if k in summaries]]
    names = {'C0056': 'S017-M017', 'C0059': 'S017-M019', 'C0060': 'S017-M020'}
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    for ax, field, title in ((axes[0], 'annualized_return', 'Net annualized return (%)'),
                             (axes[1], 'bar_max_drawdown', '30-minute close max drawdown (%)')):
        ax.bar([names[k] for k in keys], [100*summaries[k]['candidate'][field] for k in keys], color=['gray', '#367bb5', '#58a65c'][:len(keys)])
        ax.set_ylabel(title)
    axes[0].axhline(100*summaries['C0056']['benchmark']['annualized_return'], color='red', label='Buy-hold')
    axes[1].axhline(25, color='red', label='Confirmed maximum 25%')
    for ax in axes:
        ax.legend()
    fig.savefig(WORK/'others/account_comparison.png', dpi=150)
    plt.close(fig)
    lines = ['# EX030：均价方向与低点结构的竞争验证', '', 'Status: COMPLETED', '', '## 结论与研究决定', '',
        judgment['conclusion'], '', *judgment['interpretation'], '',
        '## 固定机制与合同', '',
        '|编号|完整规则|', '|---|---|',
        '|S017-M017|当前Close突破此前6柱最高价，且前Close低于截至前柱的65柱均价；复用原机制。|',
        '|S017-M019|M017，且SMA65[t-1]>SMA65[t-14]；前置均价仍在上移，严格大于。|',
        '|S017-M020|M017，且min Low[t-6..t-1]>=min Low[t-12..t-7]；近期低点不再下移，等号属于。|', '',
        '两新机制分别验证，不叠加。全部固定S017-M015：实际买入后完成6根30分钟柱退出，到期受阻则继续要求退出，失败买入不启动周期。当前柱不进入背景窗口；均价方向和低点结构只是价格行为代理，不证明真实卖压或见底。', '',
        '沿用2018-11/12预热、2019—2025开发、初始10万美元、只做多不加杠杆、全可用资金整数股、每侧0.1%、固定1%买入限价溢价、下一段执行、期末不强平。卖出即时可用沿用原研究假设，买持同合同。未改变原收益、双回撤和双频率要求。', '',
        '## 入场结果与时间延续', '',
        '复用EX029已认证3/6/13柱执行标签，重新计算背景和信号；M017逐点复现910次。主6柱，辅助3、13不替代主结果。先选成员再检查成交与成熟，下一去重信号i严格大于上次i+N+1。', '',
        '|机制|原始信号|6柱完整去重事件|平均净收益|同背景增量|支持事件|自身净均值区间95%|', '|---|---:|---:|---:|---:|---:|---|']
    for name in NAMES:
        q = census['horizons']['6'][name]['nonoverlap']
        interval = q['net_bootstrap']['interval95']
        ci = '无定义' if interval is None else '['+pct(interval[0])+', '+pct(interval[1])+']'
        lines.append(f"|{name}|{census['signal_counts'][name]}|{q['summary']['complete']}|{pct(q['summary']['net_mean'])}|{pct(q['ordinary']['net_increment'])}|{q['ordinary']['supported_targets']}|{ci}|")
    sequence = census['temporal']['sequential']
    pooled = sequence['pooled']
    lines += ['', '普通控制同月、同美东计划入场时刻、同各自前置背景并排除该机制信号。M019、M020的支持范围不同，不能把它们的增量点估计直接排名当因果。区间仅针对自身净均值，20日移动块1000次，全部有定义但跨零；匹配增量不构造区间，避免重复此前细格缺少控制导致无定义的问题。未把区间设为新增硬门，选择偏差仍存在。', '',
        f"只用此前252日成熟标签，在两个新机制中按事前规则选择，随后63日观察：共{len(sequence['folds'])}折、{sum(f['choice'] is None for f in sequence['folds'])}折空选；{pooled['selected_events']}个预选事件、{pooled['mature_events']}个成熟，平均净收益{pct(pooled['net_return']['mean'])}；有控制支持{pooled['matched_supported_events']}个、增量{pct(pooled['matched_increment_mean'])}。原始历史均值改善没有自动成为可持续的选择能力。此为事件检验，不是动态账户，不是独立验证。", '',
        '## 完整账户', '',
        '复用EX029的C0056原M017/6柱账户，不重放、不改写；两新账户C0059、C0060均为公开V3。不同特征图和source保留各自身份，共同市场输入、资金、费用、执行合同与完整买持路径核对一致。', '',
        '|机制及身份|净年化|30分钟最大回撤|闭合交易|60日闭合中位数|至少3笔窗口覆盖|持仓柱占比|五项达标|', '|---|---:|---:|---:|---:|---:|---:|---|']
    for key in keys:
        entry, q = summaries[key], summaries[key]['candidate']
        lines.append(f"|{names[key]} / {key}|{pct(q['annualized_return'])}|{pct(q['bar_max_drawdown'])}|{q['closed_cycles']}|{q['rolling_60_closed_cycle_median']}|{pct(q['frequency_60_sessions']['coverage_at_least_three'])}|{pct(q['holding_bar_fraction'])}|{'是' if entry['all_goals_met'] else '否'}|")
    base = summaries['C0056']['benchmark']
    lines += [f"|同合同买入持有|{pct(base['annualized_return'])}|{pct(base['bar_max_drawdown'])}|{base['closed_cycles']}|—|—|100%|基准|", '',
        '原目标：净年化至少正买持1.5倍，本窗口约54.48%；回撤同时不超过基准80%及25%；60交易日闭合中位至少6，至少90%完整窗口不少于3笔。不得以风险改善抵扣收益或频率失败，也不以通过目标的数量排序。', '',
        '![账户比较](others/account_comparison.png)', '',
        '|年份|M017原控制|M019均价方向|M020低点结构|', '|---|---:|---:|---:|']
    annuals = {key: {str(r['year']): r['net_return'] for r in summaries[key]['candidate']['year_returns']} for key in keys}
    for year in map(str, range(2019, 2026)):
        lines.append('|'+year+'|'+'|'.join(pct(annuals[key][year]) for key in keys)+'|')
    lines += ['', '年度继承连续账户，不重置本金或把平仓年损益当年度收益。M019最大回撤由2020-12峰至2024-06谷形成，直到2025-11才恢复峰值；幅度达标不等于没有漫长损伤期。该事实只诊断，不新增时间硬门。', '',
        'M019实际单笔净收益均值约+0.4385%、盈利比例58.18%，优于父M017的+0.1235%和51.05%；但持仓柱仅2.90%，七年110笔，比原M005固定65柱的145笔还少，重新引入用户指出的机会稀疏问题。前5盈利笔贡献正收益42.29%，样本选择和集中性不能忽视。', '',
        '公共路径中，M019与父控制同入场108次、父独有415、新独有2；M020同入场222、父独有301、新独有59。因此不能从父账本删除若干损失就证明过滤因果，也不能将回撤下降全部归因于一个条件。资金和后续入场路径已改变。', '',
        '## 核验、资源和边界', '',
        '- 两新机制公共V3合成均实际10次买入、10次闭合；严格均价、等号低点、失败买入、卖出受阻延至第7柱及未来后缀完整七表不变通过。',
        '- 独立核验68370条复用标签和68370项信号/背景、净均值抽样区间、24折成熟训练/顺序选择及未来扰动通过。正式运行信号与普查全点一致。',
        '- 两份新正式评价和共享基准已发布，复用父账户1份；两项公共诊断覆盖新/旧账户、共同合同、完整基准路径及金额对账，独立账户数字核验PASS。',
        '- 本轮直接采用V3，无旧兼容回放。两个新候选＋共享基准计算约18.1秒，端到端准备/认证/发布约69.2秒；回放本体与完整接口耗时分别说明。没有修改平台或A股实现。',
        '- 全部仍在反复使用的开发池；不将顺序回放称独立验证，2026封存行情及绩效未使用。原已知中断、公司行动NONE与RAW仍不等于完整停牌史或独立认证含分红总回报。',
        '- 没有参数搜索、费用压力、邻域或其他阶段四验收、候选登记、阶段三、冻结、PTE、生产、合并或推送。技术PASS不能代替研究达标。', '',
        '## 收口及下一步', '', judgment['next_step'], '',
        '用户已解除轮数限制；本次停止是因为当前竞争结果和取舍，不是额度用完。不改变旧20轮历史；本次续研新增EX029、EX030两轮、6个新正式策略账户、2个会话内共享买持、5项公共诊断。旧V2被取消技术尝试单列，不把它们算成额外独立配置或经济结果。', '',
        '证据：[协议](protocols/design.md)、[授权](protocols/authorization.md)、[冻结来源](others/pre_run_evidence.json)、[入场与时间结果](others/census.json)、[独立事件核验](others/result_validation.json)、[正式账户](others/accounts.json)、[账户分析](others/account_analysis.json)、[独立账户核验](others/account_result_validation.json)。']
    (WORK/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8', newline='\n')
    print('REPORT_RENDERED', flush=True)


if __name__ == '__main__':
    main()
