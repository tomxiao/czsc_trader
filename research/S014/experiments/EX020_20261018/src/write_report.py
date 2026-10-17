"""Render EX020 fixed renewal grid from authenticated comparisons and diagnostics."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
BEST = 'renewal_parent_H3_cap0'
read = lambda p: json.loads((EX / p).read_text(encoding='utf-8'))


def label(variant):
    if variant == 'baseline_H3':return '原固定3日'
    if variant == 'baseline_H6':return '原固定6日'
    _, kind, horizon, cap = variant.split('_')
    return f"{horizon[1:]}日／{'原完整信号' if kind == 'qualified' else '低开收阳'}续持／{'无上限' if cap == 'cap0' else '最长12日'}"


def select(rows, **where):
    matches = [row for row in rows if all(str(row[key]) == str(value) for key, value in where.items())]
    assert len(matches) == 1, where
    return matches[0]


def main():
    comparison = read('others/comparison.json')
    audit = read('others/account_audit.json')
    paths = read('others/path_diagnostics.json')
    precheck = read('others/precheck.json')
    trials = read('others/optuna_trials.json')['trials']
    assert audit['status'] == paths['status'] == precheck['status'] == 'PASS'
    assert len(trials) == 8 and all(t['state'] == 'COMPLETE' for t in trials)
    assert comparison['account_count'] == 10 and comparison['all_targets_pass_count'] == 0
    best = select(comparison['summaries'], variant=BEST)
    h3 = select(comparison['summaries'], variant='baseline_H3')
    h6 = select(comparison['summaries'], variant='baseline_H6')
    assert best['annual_return_pass_count'] == 3 and best['annual_drawdown_pass_count'] == 7
    ignored_after_latch = sum(row.get('renewal_signals_ignored_after_exit_latch', 0) for row in audit['accounts'])
    comparison['parameter_search'] = True
    comparison['search_semantics'] = 'Eight predeclared grid parameter contrasts; all enqueued before results; no free or adaptive sampling, no pruning or expansion.'
    comparison['free_parameter_search'] = False
    comparison['sampler_class'] = 'optuna.samplers.RandomSampler'
    comparison['conclusion'] = (
        f"第1轮8格原信号续持对照形成有限正面证据：H3基础四构造提高原H3全期收益并保持频率，"
        f"C0028全期收益{best['total_return']:.2%}、年度回撤7/7通过，但年度收益仍仅3/7；"
        "10个对照全部原目标通过0个。H6基础续持恶化回撤且频率不足。保留H3续持为后续比较材料，"
        "不能据全期收益选择已达标策略，也不能把增加持仓暴露的路径变化视作独立Alpha。"
    )
    comparison['next_step'] = (
        "在已授权10轮预算内继续已公开锁定的第2轮EX021：采用EX007既有A/B/C构造，比较固定10日重复入场、"
        "前5日收盘低点支撑入场、以及支撑破坏退出与重新入场。C0028漏失的43笔原H3入场没有退出当日冲突，"
        "因此不追加一日记忆规则。新轮保持费用、执行和年度目标，明确入场及启动机制不同；"
        "不事后切换年度，不自动推进阶段四。"
    )
    (EX / 'others/comparison.json').write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    all_path = select(paths['decomposition'], window='ALL', baseline='baseline_H3', candidate=BEST, entry_cohort='ALL')
    early_path = select(paths['decomposition'], window='WITHOUT2026', baseline='baseline_H3', candidate=BEST, entry_cohort='ALL')
    all_exposure = select(paths['exposure'], window='ALL', variant=BEST)
    early_exposure = select(paths['exposure'], window='WITHOUT2026', variant=BEST)
    early_h3 = select(paths['exposure'], window='WITHOUT2026', variant='baseline_H3')
    early_h6 = select(paths['exposure'], window='WITHOUT2026', variant='baseline_H6')
    best_2026 = select(comparison['annual'], variant=BEST, year=2026)
    h6_2026 = select(comparison['annual'], variant='baseline_H6', year=2026)
    missed = select(paths['best_missed_summary'], window='ALL', entry_cohort='ALL', kind='ALL')
    exit_missed = select(paths['best_missed_summary'], window='ALL', entry_cohort='ALL', kind='EXIT_SESSION')
    assert exit_missed['n'] == 0
    lines = ['# S014 阶段三自主第1轮：持仓期间原信号续持', '',
        f"**形成部分改进，尚未达到阶段四准备度。** 新增8个固定构造中，C0028全期净收益{best['total_return']:.2%}，"
        f"高于原H3的{h3['total_return']:.2%}，年度回撤7/7通过；但年度收益仅3/7通过。本轮10个对照全部目标通过0个，不能用全期收益替代逐年验收。", '',
        '## 授权与固定设计', '',
        '本轮为新授权10轮阶段三自主预算的第1轮。实际执行8个新账户，另精确复用C0011、C0016两个原基线；继承前14个正式候选后共22个唯一账户候选。第2轮EX021已另行锁定，尚未分配的8轮为上限，不是必须耗尽的实验清单。', '',
        '沿用600722.SH既有固定数据，名义区间2020-01-01至2026-10-15，实际1642交易日。初始10万元、单侧费用0.1%、后复权研究口径、100股单位、全额可用资金、原前收盘上浮1%限价买入，以及市价卖出/跌停开盘加一价位规则不变。跨年连续，无年度重置或期末强平。初始入场仍要求成熟启动、低开收阳及原高环境，原年度校准完全保留。', '',
        '实际买入日记为E，基础期限h为3或6，初始退出决策日在E+h−1收盘。持仓中的当晚i出现指定续持信号时，把退出决策日改为max(原决策日,i+h)。i+h对应“这次信号若在下一交易日建立新仓”的原期限，但当前规则直接继续持有，不要求假想新买单未来可成交，不产生卖出重买、额外股数或费用。', '',
        '- qualified：续持也要求原完整信号，即ready、低开收阳及高环境。',
        '- parent：仅续持阶段放宽高环境，仍要求ready与低开收阳；首次入场完全不变。',
        '- cap12：退出决策日不得超过E+11，即最晚计划E+12卖出；真实卖出受阻可延期。cap0：没有绝对持仓天数上限。',
        '- 到期当晚先判断续持，再决定是否发出卖出；但已经发出而执行失败的卖出保持锁存，后来的信号不能撤回退出。', '',
        '本轮严格比较h3/h6 × qualified/parent × cap12/cap0共8格。Optuna实际使用RandomSampler(seed=17)，全部8格在任何结果产生前enqueue，然后ask/suggest核对固定映射，公共批量回放后tell真实分数。没有自由采样、适应性扩格、剪枝或虚拟收益trial；不能称实际使用了GridSampler类。目标分数仅用于记录最弱目标余量，严格验收仍单独计算。', '',
        '逐年收益要求：BuyHold当年正收益时策略至少达到其1.5倍，否则策略严格正收益；每个自然年的最大回撤必须严格小于BuyHold。2026截至10月15日直接纳入、不年化。平均频率为60×闭合交易数÷1642≥3。年度回撤包含前一年底衔接净值；全期回撤单列诊断。', '',
        '## 全部连续账户', '',
        '| 构造 | 候选 | 全期净收益 | 全期最大回撤 | 年度收益通过 | 年度回撤通过 | 每60日闭合数 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for row in comparison['summaries']:
        lines.append(f"| {label(row['variant'])} | {row['candidate']} | {row['total_return']:.2%} | {row['full_max_drawdown']:.2%} | {row['annual_return_pass_count']}/7 | {row['annual_drawdown_pass_count']}/7 | {row['frequency_per_60']:.2f} |")
    lines += ['', f"固定BuyHold全期净收益{comparison['buyhold']['total_return']:.2%}、全期最大回撤{comparison['buyhold']['full_max_drawdown']:.2%}。所有基准证据一致。",
        '', '四个H3基础续持均提高原H3全期收益并保持频率；C0025、C0027、C0028年度回撤7/7通过，C0026为6/7，年度收益均仍为3/7。四个H6基础续持的频率均低于3，且全期最大回撤均高于原H6；不能将H3的改善外推为任意延长持仓都有效。', '',
        '## C0028逐年缺口', '',
        'C0028是本轮全期收益最高的已见样本构造，仅作为路径诊断对象，不等于独立验证后的最优策略。', '',
        '| 年份 | 策略收益 | BuyHold收益 | 收益门槛 | 策略回撤 | BuyHold回撤 | 收益通过 |',
        '|---|---:|---:|---:|---:|---:|---|']
    for row in comparison['annual']:
        if row['variant'] != BEST:continue
        threshold = f"≥{row['required_return']:.2%}" if row['buyhold_return'] > 0 else '>0%'
        lines.append(f"| {row['year']} | {row['return']:.2%} | {row['buyhold_return']:.2%} | {threshold} | {row['max_drawdown']:.2%} | {row['buyhold_drawdown']:.2%} | {'是' if row['return_pass'] else '否'} |")
    lines += ['', '收益仍在2021、2022、2025、2026未达标。其中2022和2025实际亏损；2021虽盈利但远未达到上涨年份要求；2026盈利较高仍未达到BuyHold的1.5倍门槛。年度回撤7/7通过是正面变化，不能代替收益目标。', '',
        '## 路径、暴露和反证', '',
        f"C0028相对原H3全期共有{all_path['matched_n']}个共同入场，资金周期log收益差{all_path['matched_cycle_log']:+.6f}；"
        f"遗漏{all_path['left_only_n']}个原入场贡献{all_path['left_only_cycle_log']:+.6f}；新增{all_path['right_only_n']}个入场贡献{all_path['right_only_cycle_log']:+.6f}，"
        f"合计{all_path['total_cycle_log_difference']:+.6f}。这是账户路径的加总核对，不是相互独立的因果贡献。", '',
        f"真实截到2025年末，C0028累计收益{early_exposure['actual_return']:.2%}，原H3为{early_h3['actual_return']:.2%}。"
        f"共同{early_path['matched_n']}个入场的log贡献仅{early_path['matched_cycle_log']:+.6f}，遗漏{early_path['left_only_n']}个原入场贡献"
        f"{early_path['left_only_cycle_log']:+.6f}，合计{early_path['total_cycle_log_difference']:+.6f}。因此早期改善更多来自改变参与路径，"
        '不能把全期共同入场增益直接解释成各年份稳定的续持收益；2026对全期共同入场增益贡献较大。', '',
        f"相对原H6，C0028全期累计收益高{100 * (best['total_return'] - h6['total_return']):.2f}个百分点，"
        f"但截到2025年末累计收益{early_exposure['actual_return']:.2%}低于原H6的{early_h6['actual_return']:.2%}，"
        f"相差{100 * (early_exposure['actual_return'] - early_h6['actual_return']):.2f}个百分点。"
        f"2026年C0028收益{best_2026['return']:.2%}、原H6为{h6_2026['return']:.2%}。"
        '因此C0028相对H6的全期收益排序依赖2026，不能认定其在多个独立时期稳定优于固定H6；年度风险与频率改善另按完整表判断。', '',
        f"C0028收盘有仓{all_exposure['exposure_close_sessions']}日，原H3为{h3['exposure_close_sessions']}日；最长实际持仓{all_exposure['max_elapsed_sessions']}个交易日，"
        f"超过12日的持仓{all_exposure['holds_over12']}笔。C0028累计费用{best['fees']:.2f}元，原H3为{h3['fees']:.2f}元；"
        '交易次数下降并不意味着绝对费用必然下降，因为资金规模与后续成交金额一起改变。增加暴露、机会替换和复利均是竞争解释。', '',
        f"C0028遗漏的{missed['n']}个原H3入场中，没有发生在该账户退出当日的冲突（{exit_missed['n']}笔）；"
        f"其中原交易盈利{missed['underlying_trade_returns']['positive']}笔、亏损{missed['underlying_trade_returns']['negative']}笔。"
        '剩余差异不是可以直接靠一日信号记忆补回的全部赢家，因此不追加该规则，也不追溯性补单。', '',
        f"十个账户分别在全期及2025年末截止，共{paths['checks']['reconciliations']}项资金周期复利核对，最大绝对收益误差"
        f"{paths['checks']['max_absolute_return_error']:.3g}。尚未平仓按实际截止价估值，不虚构卖出费用。", '',
        '## 结论与已锁定下一轮', '', comparison['conclusion'], '', comparison['next_step'], '',
        '第2轮将检验不同的完整入场/退出解释，不能把其不同启动条件下的结果称作仅修改本轮续持的一项纯效应。继续研究以可证伪问题和完整账户目标为依据，不以用完10轮或候选数量为依据。', '',
        '## 验证和证据', '',
        f"{precheck['check_count']}项预检、{audit['check_count']:,}项独立逐日审计通过。覆盖真实入场、续持截止日、12日上限、退出锁存、失败卖出、实际费用股数与资金账；"
        '原H3/H6所有历史及展示列逐值一致后才复用其正式账户证据。验证通过只确认实现及证据一致，不表示经济目标通过。', '',
        f"真实样本中，卖出锁存后再次出现续持信号的特殊情形为{ignored_after_latch}次；该分支由合成测试验证，不能称历史行情已实际覆盖。"
        '合成测试明确构造卖出未成交、随后停牌且出现有效续持信号，验证既定卖出不能撤回。', '',
        '本轮上游调用0；公告追溯继续暂停。全部数据已见，历史发布时间、修订及复权因子历史可得性未独立验证，不声称存在独立未见样本。无平台、生产或远端操作，不自动推进阶段四。', '',
        '- [本轮事前锁定](../../../experiments/EX020_20261018/protocols/comparison_lock.json)',
        '- [全部账户引用](../../../experiments/EX020_20261018/others/comparison_accounts.json)',
        '- [年度比较](../../../experiments/EX020_20261018/others/annual_comparison.csv)',
        '- [实际Optuna记录](../../../experiments/EX020_20261018/others/optuna_trials.json)',
        '- [路径诊断](../../../experiments/EX020_20261018/others/path_diagnostics.json)',
        '- [独立账本审计](../../../experiments/EX020_20261018/others/account_audit.json)',
        '- [第2轮既定设计](../../../experiments/EX021_20261018/protocols/comparison_lock.json)', '']
    (EX / 'protocols/account_report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print('EX020_REPORT_READY')


if __name__ == '__main__':main()
