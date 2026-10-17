"""Render audited natural short-horizon boundary results without selecting a winner."""
import json
from pathlib import Path

EX = Path(__file__).resolve().parents[1]
KINDS = ('support_entry', 'support_exit_reserve', 'support_first_profit_exit')
NAMES = ('B固定到期', 'R全部破坏退出', 'P首次破坏浮盈退出')
BASES = tuple(f'{k}_H{h}' for h in (10, 3) for k in KINDS)
NEW = ('support_entry_H1',) + tuple(f'{k}_H2' for k in KINDS)


def read(name):
    return json.loads((EX / name).read_text(encoding='utf-8'))


def select(rows, **where):
    found = [r for r in rows if all(str(r[k]) == str(v) for k, v in where.items())]
    assert len(found) == 1, where
    return found[0]


def label(variant):
    kind, h = variant.rsplit('_H', 1)
    return f'H{h}／{NAMES[KINDS.index(kind)]}'


def main():
    comp = read('others/comparison.json')
    paths = read('others/path_diagnostics.json')
    audit = read('others/account_audit.json')
    pre = read('others/precheck.json')
    trials = read('others/optuna_trials.json')['trials']
    assert audit['status'] == paths['status'] == pre['status'] == 'PASS'
    assert read('others/capacity_upper_bound.json')['status'] == 'PASS'
    assert read('others/capacity_review.json')['status'] == 'PASS'
    assert read('others/research_route_review.json')['status'] == 'PASS'
    assert read('others/reservation_state_diagnostics.json')['status'] == 'PASS'
    assert read('others/h15_label_review.json')['status'] == 'PASS'
    assert read('others/reservation_state_review.json')['status'] == 'PASS'
    assert comp['new_accounts'] == 4 and comp['reused_accounts'] == 6 and comp['account_count'] == 10
    assert len(trials) == 4 and all(t['state'] == 'COMPLETE' for t in trials)
    assert len(paths['reconciliations']) == 20
    assert comp.get('conclusion') and comp.get('next_step'), 'Interpret actual audited evidence first.'
    rows = {r['variant']: r for r in comp['summaries']}
    max_error = max(r['absolute_reconciliation_error'] for r in paths['reconciliations'])
    lines = ['# S014 阶段三自主第8轮：自然短周期边界', '', comp['conclusion'], '',
        '## 固定设计与完整目标', '',
        '本轮新增C0068至C0071四个账户：H1只执行B代表，H2执行B/R/P；精确复用H3/H10六个账户，共10格。继承57个候选后累计61个唯一账户候选，交付拟为CANDIDATES/11承接/10。这是10轮自主预算第8轮，新增上游调用0，公告追溯仍暂缓。', '',
        '原支撑入场、60日启动和5日支撑回看不变。实际买入E后，E+H−1收盘到期决策、次日卖出；R/P提前退出仍保留E+H收盘才能重新计划买入的时钟。P只在首次严格早于到期决策的破坏时判断含买费浮盈>0，拒绝后不重新判断。失败买入重置，已发卖出锁存。', '',
        'H1在买入当晚就到期，严格提前窗口为空，B/R/P在现有契约下数学等价，故只运行一个代表；H2仅买入当晚可判断提前退出。H3-P历史未触发正浮盈早退只是已见路径结果，不是结构上的不可能。本轮以T+1允许的自然下界完成短端核对，不做H0同日买卖，不继续逐整数邻域扫描。Optuna事前固定4配置，无自由采样或剪枝。', '',
        '保持600722.SH、2020-01-01至2026-10-15、实际1642交易日、10万元、单边0.1%费率、后复权研究、整数手全仓、原限价买入和开盘／跌停开盘加一价位卖出约定。跨年连续、无期末强平、同一BuyHold。每年收益须达到正BuyHold的1.5倍，否则严格正收益；每年最大回撤严格小于BuyHold，2026为截至10月15日的未年化结果；60×闭合交易数÷1642≥3。无新增诊断硬门。', '',
        '## 全部结果与年度缺口', '',
        '| 构造 | 候选 | 全期收益 | 全期最大回撤 | 年度收益通过 | 年度回撤通过 | 每60日闭合数 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for v in BASES + NEW:
        q = rows[v]
        lines.append(f"| {label(v)} | {q['candidate']} | {q['total_return']:.2%} | {q['full_max_drawdown']:.2%} | {q['annual_return_pass_count']}/7 | {q['annual_drawdown_pass_count']}/7 | {q['frequency_per_60']:.2f} |")
    lines += ['', f"全部原目标通过{comp['all_targets_pass_count']}/10；BuyHold全期收益{comp['buyhold']['total_return']:.2%}、最大回撤{comp['buyhold']['full_max_drawdown']:.2%}。", '',
        '| 年份 | H1-B | H2-B | H2-R | H2-P | 收益门槛 |', '|---|---:|---:|---:|---:|---:|']
    for year in range(2020, 2027):
        values = [select(comp['annual'], variant=v, year=year) for v in NEW]
        q = values[0]
        threshold = f"≥{q['required_return']:.2%}" if q['buyhold_return'] > 0 else '>0%'
        returns = ' | '.join(format(v['return'], '.2%') for v in values)
        lines.append(f'| {year} | {returns} | {threshold} |')
    for v in NEW:
        ret = [str(q['year']) for q in comp['annual'] if q['variant'] == v and not q['return_pass']]
        dd = [str(q['year']) for q in comp['annual'] if q['variant'] == v and not q['drawdown_pass']]
        lines += ['', f"{label(v)}收益未过：{'、'.join(ret) or '无'}；回撤未过：{'、'.join(dd) or '无'}。"]
    lines += ['', 'H1仅2020收益通过，且2021至2026连续亏损；H2-B/P只通过2020、2024，H2-R只通过2024。四个新构造的2021、2022、2023、2025、2026收益均未达标，2026的反弹也没有修复全期亏损。相比H3，H2部分年度亏损较少，但全期和截至2025年末收益均更差，不能视为年度缺口已解决。']
    lines += ['', '## 真实路径、交易频率与费用', '',
        '| 构造 | 截至2025年末收益 | 全期持仓收盘日数 | 闭合／未平仓 | 实付费用（元） |',
        '|---|---:|---:|---:|---:|']
    for v in BASES + NEW:
        early = select(paths['exposure'], variant=v, window='WITHOUT2026')
        q = rows[v]
        lines.append(f"| {label(v)} | {early['return']:.2%} | {q['exposure_close_sessions']} | {q['closed_trades']}／{q['open_trades']} | {q['fees']:.2f} |")
    lines += ['', '| 新构造减对应H3 | 共同入场数／log贡献 | H3独有数／log贡献 | 新独有数／log贡献 | 全期log差 |',
        '|---|---:|---:|---:|---:|']
    for v in NEW:
        base = v.rsplit('_H', 1)[0] + '_H3'
        q = select(paths['decompositions'], window='ALL', entry_cohort='ALL', baseline=base, changed=v)
        cells = [f"{q['counts'][k]}／{q['cycle_log_contributions'][k]:+.6f}" for k in ('matched', 'left_only', 'right_only')]
        lines.append(f"| {label(v)} | {' | '.join(cells)} | {q['total_cycle_log_difference']:+.6f} |")
    lines += ['', '共同入场按实际买入日期匹配，log贡献只用于核对净值复利，不是百分点。改变时钟也改变后续参与路径，不能把每仓退出标签简单叠加。去2026是截至2025年末真实净值，未平仓按当日市值计价。费用已含于收益，绝对金额同时受周转与资金规模影响；不据费用总额推定收益因果。', '',
        '以H2-B减H3-B为例，共同150次入场贡献−0.298888 log，H3独有202次的差分贡献−0.683110，新独有310次仍为−0.182815，三部分均未补回损失。H1减H3-B的共同入场、遗漏和新增部分也均为负。自然短端恶化同时发生在持有段和参与路径上，不能仅归因于增加费用。', '',
        'H2的B/R/P真实入场均为同一460次，因而退出差异可直接比较：R减B的log差−0.181609，P减B+0.066992。P有局部改善，但仅把全期亏损从23.53%减至18.23%，年度收益仍只通过2/7；R则退化为1/7。支持“触及支撑就立即退出”的证据并不跨期限稳定。', '',
        'H1完成661笔、H2各460笔闭合交易，频率已远高于最低目标；实付费用分别约9.29万元、7.02／6.69／7.39万元。高频率不是当前缺口，现有全仓支撑机制下的统一短周期没有提供满足全部年度目标的收益来源。H1是当前T+1契约的自然下界，本轮结束该路线，不再围绕H1/H2继续细调。', '',
        '## 较长期限的容量边界', '',
        '这是本轮账户结果后的零账户诊断，不是新增策略试验。现有频率目标要求至少83笔闭合交易。用1642日中的1202个支撑有效、限价可成交机会，允许跳过任意机会、忽略资金和失败买入重置，并对所有可能入场组合求最多闭合数，得到如下乐观上界。它包含实际规则的可行路径，而非只模拟一次贪心入场。', '',
        '| 统一期限 | 固定到期最多闭合 | 任意提前退出但保留原预约最多闭合 | 对原频率目标的判断 |',
        '|---|---:|---:|---|',
        '| H15 | 96 | 97 | 尚未排除，不能保证实际达到 |',
        '| H18 | 80 | 81 | 均少于83，当前统一H18可排除 |', '',
        '提前退出上界允许最早可成交日退出，未要求R/P条件成立，因此实际规则只会更受约束。H18排除范围限于当前统一期限及预约机制，不能扩展为混合期限或最大持有18日的一概不可行。H15有容量余地不代表存在收益，仍须独立经济依据；最优机会安排是事后容量证明，不是可执行策略。原1025项合成穷举与独立最长兼容路径复核通过，新增账户、trial和上游调用均为0。', '',
        '固定原H10-B的全部138个实际入场，将同一仓的退出假设改为H15：136对完整、2对因期末未到期或未退出而删失，平均收益增量+0.9416个百分点，去掉最大5个增量后为−0.0207个百分点。真正截到2025年末有121对完整、1对删失，平均+0.5353个百分点，去最大3个后为−0.1447个百分点。2022、2024入场队列均值分别−2.1275、−0.4256个百分点。这是有集中性和反例的每仓标签，不包含新入场路径、资金占用与股数变化，不能累计成账户收益，也不能用入场年份替代自然年验收。B标签不先验支持R/P交互。', '',
        '另核对了“早退后按当晚浮盈决定是否继续等待”的未测方向。原R的103次早退中，只有47次与即时重入C有同一买入日及实际卖出日，56次不匹配；其中46个等待窗口完整、1个期末删失，35个窗口结束时C仍持仓。完整窗口中，P>0仅6例，C继续参与相对现金的净值变化均值−1.1619%；P≤0有40例、均值+0.2453%，去最大3例后转−1.1517%。正组覆盖少、非正组依赖少数赢家，不足以优先安排条件预约账户。窗口收益含未平仓市值，并非闭合交易收益；不能把C/R不同路径的总差归因到一次早退状态。', '',
        '## 验证与下一步', '',
        f"预检{pre['check_count']}项PASS、独立账户审计{audit['check_count']}项PASS；20项全期／去2026复利核对最大绝对误差{max_error:.3g}。复用原正式账户证据，未重新执行。", '',
        'H2-P首次破坏81次均发生在买入当晚，仅4次浮盈为正并退出，77次拒绝；正分支证据很少。H2-R实际提前退出81次，预约等待81日、阻止合条件入场48日；P对应4日、1日，日数不能当作可成交交易笔数。H1实际失败买入14次、卖出2次；H2每个账户失败买入11次、卖出1次，均依既定规则处理。真实停牌日全部为0，停复牌边界仅有预检合成样本覆盖。', '',
        '所有配置使用已见数据；相关路径、重复经济结果和H1等价代表均不计作独立样本外证据。沿用日频触及即全量成交约定，不代表验证真实排队撮合。', '',
        '补充独审已核对原H10全部138笔实际买入及260条双截窗H15标签、16项汇总，并独立重算47个共同等待窗口及6组汇总；均PASS。诊断审计只确认计算及覆盖口径，不把小样本或假想每仓收益升级为完整策略证据。', '',
        '以下链接以正式交付报告为基准：[固定设计](../../../experiments/EX027_20261018/protocols/comparison_lock.json)、[账户与全部年度目标](../../../experiments/EX027_20261018/others/comparison.json)、[路径诊断](../../../experiments/EX027_20261018/others/path_diagnostics.json)、[独立审计与完整指纹](../../../experiments/EX027_20261018/others/account_audit.json)、[预检](../../../experiments/EX027_20261018/others/precheck.json)、[机会容量上界](../../../experiments/EX027_20261018/others/capacity_upper_bound.json)、[容量独立复核](../../../experiments/EX027_20261018/others/capacity_review.json)、[H15每仓标签](../../../experiments/EX027_20261018/others/h15_labels.json)、[条件预约诊断](../../../experiments/EX027_20261018/others/reservation_state_diagnostics.json)、[研究路线与反证](../../../experiments/EX027_20261018/others/research_route_review.json)。', '',
        '[H15标签独立复核](../../../experiments/EX027_20261018/others/h15_label_review.json)、[条件预约诊断独立复核](../../../experiments/EX027_20261018/others/reservation_state_review.json)。', '',
        comp['next_step'], '']
    (EX / 'protocols/account_report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'status': 'PASS', 'new_accounts': 4, 'reused_accounts': 6, 'registered_candidates': 61}))


if __name__ == '__main__':
    main()
