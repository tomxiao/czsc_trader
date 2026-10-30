"""Render fixed event/account comparisons without selecting another configuration."""
from common import WORK, NAMES, read, digest
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def pct(value):
    return '无定义' if value is None else f'{value*100:.2f}%'


def main():
    census, analysis, judgment = (read(WORK/'others'/n) for n in ('census.json', 'account_analysis.json', 'judgment.json'))
    if analysis['status'] != 'PASS' or judgment['account_analysis_sha256'] != digest(WORK/'others/account_analysis.json'):
        raise ValueError('Current checked account judgment required')
    summaries = analysis['summaries']
    sequence = census['temporal']['sequential']
    names = {'C0055': 'S017-M012＋S017-M015', 'C0056': 'S017-M017＋S017-M015',
             'C0057': 'S017-M018＋S017-M015', 'C0058': 'S017-M017＋S017-M016'}
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    keys = list(summaries)
    axes[0].bar(keys, [100*summaries[k]['candidate']['annualized_return'] for k in keys])
    axes[0].axhline(100*summaries[keys[0]]['benchmark']['annualized_return'], color='red', label='Buy-hold')
    axes[0].set_ylabel('Net annualized return (%)')
    axes[0].legend()
    axes[1].bar(keys, [100*summaries[k]['candidate']['bar_max_drawdown'] for k in keys])
    axes[1].axhline(25, color='red', label='Confirmed 25% maximum')
    axes[1].set_ylabel('30-minute close max drawdown (%)')
    axes[1].legend()
    fig.savefig(WORK/'others/account_comparison.png', dpi=150)
    plt.close(fig)
    lines = ['# EX029：低于近期均价的突破修复定向验证', '', 'Status: COMPLETED', '', '## 结论', '',
        judgment['conclusion'], '', *judgment['interpretation'], '',
        '## 机制、授权及合同', '',
        '用户先同意定向续研，随后明确“不用受额度约束，可以继续开展实验”。旧20轮发起20、完成19、失败1的历史保持；本轮另记为解除轮数限制后的第1轮。无阶段三、2026封存行情、平台修改或生产授权。', '',
        '|编号|完整定义|', '|---|---|',
        '|S017-M012|当前完成收盘高于此前6柱最高价，原突破对照，定义不变。|',
        '|S017-M017|M012，且突破前一柱Close严格低于其截至当时65柱均价。|',
        '|S017-M018|仅满足上述低于均价条件，每个完成柱均可触发，不等待突破。|',
        '|S017-M015 / S017-M016|实际买入起，分别完成6 / 13根30分钟柱后持续要求退出，直到真实卖出。|', '',
        '低于均价不证明此前持续下跌、见底或估值便宜；当前突破柱不进入背景均价。窗口允许跨日，不强制日内平仓。只有M017新增背景过滤，未加量能、波动、大盘或日线条件。', '',
        '2018-11/12预热、2019—2025开发，LITE只做多不加杠杆、初始10万美元、全可用资金整数股、固定1%买入限价溢价、每侧0.1%、下一段执行。买持同合同，期末不强平；卖出资金即时可用沿用原研究假设。', '',
        '## 入场普查', '',
        '复用EX028已认证3/6/13柱标签，共68370条，重新计算本轮信号与背景。主期限仍6柱。M017的主要对照为同月、同美东计划入场时刻、同低均价背景的非M017机会；M012、M018对照排除自身，不将相反背景的差额当作突破贡献。', '',
        '|编号|原始信号|6柱完整去重事件|平均净收益|匹配增量|支持事件|', '|---|---:|---:|---:|---:|---:|']
    for n in NAMES:
        item = census['horizons']['6'][n]['nonoverlap']
        lines.append(f"|{n}|{census['signal_counts'][n]}|{item['summary']['complete']}|{pct(item['summary']['net_mean'])}|{pct(item['ordinary']['net_increment'])}|{item['ordinary']['supported_targets']}|")
    lines += ['', '这些是固定单股事件收益，不能报告为策略年化或账户成交频率。各机制分别选取去重成员，因此均值差不能直接当作同一组交易的过滤贡献。', '',
        f"252日训练、63日测试共{len(sequence['folds'])}折，仅选择M017启用或空选；{sum(f['choice'] is None for f in sequence['folds'])}折空选。训练只用当时已完成退出的标签、同背景对照；测试跨折连续去重。{sequence['pooled']['selected_events']}个预选事件，{sequence['pooled']['mature_events']}个成熟，平均净收益{pct(sequence['pooled']['net_return']['mean'])}，有支持{sequence['pooled']['matched_supported_events']}个、增量{pct(sequence['pooled']['matched_increment_mean'])}。这不是动态账户或独立验证。", '',
        'M017最近252日去重均值约+0.521%、此前约+0.079%；年度2021/2022均值仍为负，不能只选近期好年份。20日移动块1000次中，M017主期限全部增量抽样因至少部分目标失去匹配支持而无定义，不能给出可靠区间或宣称统计显著。此限制不因点估计为正消失，不继续加细格拆解。', '',
        '## 正式完整账户', '',
        '|账户及机制|净年化|30分钟最大回撤|闭合交易|60日闭合中位数|至少3笔窗口覆盖|全部目标|', '|---|---:|---:|---:|---:|---:|---|']
    for key, entry in summaries.items():
        q = entry['candidate']
        lines.append(f"|{key} {names[key]}|{pct(q['annualized_return'])}|{pct(q['bar_max_drawdown'])}|{q['closed_cycles']}|{q['rolling_60_closed_cycle_median']}|{pct(q['frequency_60_sessions']['coverage_at_least_three'])}|{'是' if entry['all_goals_met'] else '否'}|")
    baseline = summaries['C0055']['benchmark']
    lines += [f"|同合同买入持有|{pct(baseline['annualized_return'])}|{pct(baseline['bar_max_drawdown'])}|{baseline['closed_cycles']}|—|—|基准|", '',
        '原目标保持：正买持下净年化至少1.5倍，本窗口约54.48%；30分钟回撤同时不超过基准80%及25%；完整滚动60交易日闭合中位数至少6，至少90%窗口不少于3笔。各项必须同时满足。', '',
        '![完整账户比较](others/account_comparison.png)', '',
        '过滤和持有时间同时改变后续资金、实际入场序列及忽略信号。此处比较完整策略用途，不把账户差额全部归因于某几笔删掉的交易；单股标签的去重间隔也与真实账户受阻退出、未成交和重入时序存在差别。', '',
        '|年份|M012＋6柱|M017＋6柱|M018＋6柱|M017＋13柱|', '|---|---:|---:|---:|---:|']
    annuals = {k: {str(r['year']): r['net_return'] for r in v['candidate']['year_returns']} for k, v in summaries.items()}
    for year in map(str, range(2019, 2026)):
        lines.append('|'+year+'|'+'|'.join(pct(annuals[k][year]) for k in summaries)+'|')
    lines += ['', '年度为连续账户年末净值变化，年初不重置本金，不按平仓年损益替代；252交易日、步长21日切片继承原账户资金和持仓，详[账户分析](others/account_analysis.json)。', '',
        '## 核验与限制', '',
        '- 旧实现四配置合成七表串行/两个spawn一致、未来后缀和实际成交计时通过；新版与旧版四配置合成完整七表及关键状态一致，全开发68370次入场信号零差异，两侧合成原表均保留。此模式不是全七年V2/V3双账本比较。',
        '- 68370条旧标签逐点复现，68370次信号标量/向量比较、背景严格等号、24折成熟训练/选择与未来扰动通过。',
        '- 四份正式评价和配对基准已发布；3项公共完整账户诊断覆盖全部新账户，身份、共同数据/合同、完整买持路径与损益对账通过；独立账户数字核验通过。技术PASS不代表经济达标。',
        '- 初次统计加载因旧证据路径键分隔符中断，study_v2仅规范键；初次候选装载缺少既有numpy/pandas版本声明，accounts_v2与account_candidate只补全已安装版本，不安装依赖、不改策略或平台。旧兼容回放耗时过长，核实进程后取消，未发布正式账户；随后按[V3接入约定](protocols/v3_adoption.md)完成上述等价核验，使用V3正式回放并认证，身份为C0055至C0058。没有依据旧账户成绩改变规则或引擎；旧实现及技术事实保留。',
        '- 开发池反复观察、背景由EX028事后分组启发；新顺序检验不恢复独立性。2026封存价格与绩效未使用，已知中断及公司行动NONE仍不等于完整停牌和含分红总回报认证。',
        '- 未执行参数邻域、费用压力和阶段四稳健性验收；未登记候选、推进阶段三、冻结、PTE、合并或推送。', '',
        '## 下一步', '', judgment['next_step'], '',
        '证据：[事前设计](protocols/design.md)、[授权](protocols/authorization.md)、[冻结来源](others/pre_run_evidence.json)、[事件结果](others/census.json)、[独立事件核验](others/result_validation.json)、[账户清单](others/accounts_v3.json)、[账户分析](others/account_analysis.json)、[独立账户核验](others/account_result_validation.json)。']
    (WORK/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8', newline='\n')
    print('REPORT_RENDERED', flush=True)


if __name__ == '__main__':
    main()
