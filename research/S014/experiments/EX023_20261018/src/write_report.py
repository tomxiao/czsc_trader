"""Render the audited reservation account without assuming entry alignment."""
import json
from pathlib import Path

EX = Path(__file__).resolve().parents[1]
A, B, C, R = 'repeated_H10', 'support_entry_H10', 'support_exit_H10', 'support_exit_reserve_H10'
LABELS = {A: 'A：重复入场／固定10日', B: 'B：支撑入场／固定10日',
          C: 'C：支撑破坏退出／可恢复重入', R: 'R：支撑破坏退出／保留原时钟'}


def read(name):
    return json.loads((EX / name).read_text(encoding='utf-8'))


def select(rows, **where):
    values = [r for r in rows if all(str(r[k]) == str(v) for k, v in where.items())]
    assert len(values) == 1, where
    return values[0]


def main():
    comp = read('others/comparison.json')
    paths = read('others/path_diagnostics.json')
    audit = read('others/account_audit.json')
    pre = read('others/precheck.json')
    exceptions = read('others/path_exception_review.json')
    route = read('others/loss_route_review.json')
    trials = read('others/optuna_trials.json')['trials']
    assert paths['status'] == audit['status'] == pre['status'] == exceptions['status'] == 'PASS'
    assert route['status'] == 'PASS'
    assert comp['account_count'] == 4 and comp['new_accounts'] == 1 and comp['reused_accounts'] == 3
    assert len(trials) == 1 and trials[0]['state'] == 'COMPLETE'
    assert len(paths['reconciliations']) == 8
    assert comp.get('conclusion') and comp.get('next_step'), 'Interpret audited evidence before rendering.'
    rows = {r['variant']: r for r in comp['summaries']}
    r = rows[R]
    account_audit = select(audit['accounts'], variant=R)
    br = select(paths['decompositions'], window='ALL', entry_cohort='ALL', baseline=B, changed=R)
    cr = select(paths['decompositions'], window='ALL', entry_cohort='ALL', baseline=C, changed=R)
    early_br = select(paths['decompositions'], window='WITHOUT2026', entry_cohort='ALL', baseline=B, changed=R)
    max_error = max(row['absolute_reconciliation_error'] for row in paths['reconciliations'])
    lines = ['# S014 阶段三自主第4轮：提前退出后保留原10日时钟', '',
        comp['conclusion'], '',
        '## 本轮只改变重新入场的最早时点', '',
        '实际新增C0056一个账户，复用EX021的A、B、C三个原账户，共4个对照；继承前45个候选后累计46个唯一账户候选，交付拟为CANDIDATES/7承接CANDIDATES/6。本轮为10轮自主预算的第4轮，第5轮已另行锁定，尚未分配5轮；新增上游调用0，公告追溯仍暂缓。', '',
        '原C在当日收盘低于此前5个评价交易日最低收盘时提前卖出，最晚仍按真实买入日E后的固定10日退出；卖出后，满足支撑条件即可计划下一日买入。新R保持全部入场和卖出规则，仅增加一个时间约束：即使已经提前卖出，也须等到原买入日E+10收盘才可重新决定买入，最早下一日实际成交。', '',
        '每次真实买入建立自己的时间界限，提前卖出后继续保留；新买入成功才重设。首次入场没有额外等待。正常到期日仍是E+9收盘发出卖出、E+10执行；若卖出受阻，继续退出，实际卖出晚于E+10时可在成交日收盘重新判断。保留时钟不推迟必要卖出，不引用未来行情，也不运行一个假想B账户来决定订单。', '',
        'R−C检验限制提前退出后的重新入场，但包含后续资金、交易日期和复利路径的所有变化；R−B比较主动支撑退出与保留原时钟的整体效果，不能事先假设入场逐笔对齐。A是重复持有的上下文对照。四者均使用原60评价交易日启动，不选择新的初始偏移。', '',
        '原重入诊断的反证保留：2022年C相对B新增交易中，原H10退出时点前及当日的25笔额外重入周期log收益合计−0.27627；但全期同类133笔合计+1.18965，2021、2025也为正。因此等待可能减少亏损，也可能放弃盈利交易，不能只凭2022局部损失宣称改善。此为原C真实路径归因，不等于R的假想收益。', '',
        '固定600722.SH、2020-01-01至2026-10-15研究期、实际1642交易日、初始10万元、单边费用0.1%、后复权研究口径、100股整数手、原全仓限价买入及开盘卖出规则。跌停开盘加一价位卖出须区间触及；无排队、部分成交、额外滑点。跨年连续，无年度重置、无期末强平，固定BuyHold从2020-01-02开始且证据一致。', '',
        '每个自然年BuyHold正收益时策略至少达到其1.5倍，否则严格正收益；每年最大回撤严格小于BuyHold。2026截至10月15日不年化，年度回撤包含年初衔接净值，频率要求60×闭合交易数÷1642≥3。没有新设等待效果或路径匹配的诊断硬门。仅一个事前锁定配置，Optuna记录一次真实回放；无自由搜索、扩阈值或选等待长度。', '',
        '## 全部连续账户', '',
        '| 构造 | 候选 | 全期净收益 | 全期最大回撤 | 年度收益通过 | 年度回撤通过 | 每60日闭合数 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for v in (A, B, C, R):
        q = rows[v]
        lines.append(f"| {LABELS[v]} | {q['candidate']} | {q['total_return']:.2%} | {q['full_max_drawdown']:.2%} | {q['annual_return_pass_count']}/7 | {q['annual_drawdown_pass_count']}/7 | {q['frequency_per_60']:.2f} |")
    lines += ['', f"全部原目标通过{comp['all_targets_pass_count']}/4。固定BuyHold全期收益{comp['buyhold']['total_return']:.2%}、最大回撤{comp['buyhold']['full_max_drawdown']:.2%}。", '',
        '## 逐年收益与R的回撤', '',
        '| 年份 | B收益 | C收益 | R收益 | 收益门槛 | R回撤 | BuyHold回撤 | R收益／回撤通过 |',
        '|---|---:|---:|---:|---:|---:|---:|---|']
    for year in range(2020, 2027):
        b, c, rr = [select(comp['annual'], variant=v, year=year) for v in (B, C, R)]
        threshold = f"≥{rr['required_return']:.2%}" if rr['buyhold_return'] > 0 else '>0%'
        lines.append(f"| {year} | {b['return']:.2%} | {c['return']:.2%} | {rr['return']:.2%} | {threshold} | {rr['max_drawdown']:.2%} | {rr['buyhold_drawdown']:.2%} | {'是' if rr['return_pass'] else '否'}／{'是' if rr['drawdown_pass'] else '否'} |")
    failed_years = [str(q['year']) for q in comp['annual'] if q['variant'] == R and not q['return_pass']]
    failed_dd = [str(q['year']) for q in comp['annual'] if q['variant'] == R and not q['drawdown_pass']]
    lines += ['', f"R收益未通过年份：{'、'.join(failed_years) or '无'}；回撤未通过年份：{'、'.join(failed_dd) or '无'}。各年连续净值独立验收，不用某年改善抵消另一年缺口。", '',
        '## 去2026、持仓暴露与实际费用', '',
        '| 构造 | 截至2025年末净收益 | 全期收盘持仓日数 | 全期闭合／未平仓 | 全期实付费用（元） |',
        '|---|---:|---:|---:|---:|']
    for v in (A, B, C, R):
        early = select(paths['exposure'], variant=v, window='WITHOUT2026')
        q = rows[v]
        lines.append(f"| {LABELS[v]} | {early['return']:.2%} | {q['exposure_close_sessions']} | {q['closed_trades']}／{q['open_trades']} | {q['fees']:.2f} |")
    lines += ['', '截至2025年末以当时真实净值截断，未平仓按当日市值计价，不虚构卖出或卖出费。费用率相同，绝对费用同时取决于换手与当时资金规模，不能把费用差直接当作独立因果贡献。', '',
        f"R真实触发{account_audit['support_triggered_exits_before_time_cap']}次原期限前的支撑退出，"
        f"空仓且仍在保留时钟内的收盘日共{account_audit['reservation_wait_flat_sessions']}日（含提前卖出当天收盘），"
        f"其中{account_audit['reservation_blocked_entry_signal_sessions']}日满足其他买入信号条件而被等待约束阻止。"
        '这些是日期计数，不能当作本来可成交的交易笔数；若其中某日买入，后面资金与持仓路径也会改变。', '',
        '## 入场是否对齐，以及收益差从哪里产生', '',
        '| 对照／窗口 | 共同入场数／log贡献 | 原路径独有数／log贡献 | R独有数／log贡献 | 总log差 |',
        '|---|---:|---:|---:|---:|']
    for window in ('ALL', 'WITHOUT2026'):
        for base, short in ((B, 'R−B'), (C, 'R−C'), (A, 'R−A')):
            p = select(paths['decompositions'], window=window, entry_cohort='ALL', baseline=base, changed=R)
            cells = [f"{p['counts'][k]}／{p['cycle_log_contributions'][k]:+.6f}" for k in ('matched', 'left_only', 'right_only')]
            lines.append(f"| {short}／{'全期' if window == 'ALL' else '截至2025年末'} | {' | '.join(cells)} | {p['total_cycle_log_difference']:+.6f} |")
    lines += ['', f"B与R全期共同入场{br['counts']['matched']}笔，B独有{br['counts']['left_only']}笔、R独有{br['counts']['right_only']}笔。"
        '这里按真实买入日期匹配，不按信号日期配对；是否同日卖出及资金规模仍可能不同。周期log收益差可加总为净值log差，没有百分比点单位；遗漏项取原路径收益相反数。它是已实现路径的算术分解，不是若删除这些交易就能获得相同收益的因果模拟。', '',
        f"R相对B的共同入场贡献{br['cycle_log_contributions']['matched']:+.6f}，总体为负；双方各4笔独有入场全部发生于2026，"
        f"R新增路径贡献{br['cycle_log_contributions']['right_only']:+.6f}，超过遗漏B路径的{br['cycle_log_contributions']['left_only']:+.6f}。"
        '所以全期领先B主要来自2026改变后的参与日期，并不能宣称对同一批交易提前退出普遍增益。', '',
        f"截至2025年末，B与R的{early_br['counts']['matched']}笔入场全部对齐，R−B周期log差为{early_br['total_cycle_log_difference']:+.6f}；"
        'R累计144.54%低于B的163.69%。2021和2023年度收益改善，但2022、2024、2025反而更差。原年度回撤7/7通过是明确进展，仍不能替代三个亏损年的收益约束。', '',
        f"R相对原C共有{cr['counts']['matched']}个共同入场，其贡献仅{cr['cycle_log_contributions']['matched']:+.6f}；"
        '两者保持相同退出规则，主要区别是重新参与的时点。R的改进应归于等待约束改变后的整条路径，而不是把被抑制的全部早重入一概归为坏交易。', '',
        '## 2026错位的具体触发与执行依赖', '',
        '双方2026-07-13同以8.12元买入，R因支撑破坏于07-17以7.90元提前卖出，仍保留到07-27收盘的原时钟。B计划07-27卖出，但07-27、07-28为一字跌停，开盘加一价位分别为10.30、9.27元，均不在当天价格区间；因此延至07-29以9.41元卖出，07-30再买入。R已空仓，在07-27收盘满足条件后，07-28按既定限价规则以9.26元开盘价买入。', '',
        '07-13这笔共同交易本身R周期收益−2.90%，B为+15.64%，提前退出反而受损。R后来的07-28、08-27两笔独有入场分别取得约30.33%、48.63%的资金周期收益，是路径优势的重要来源；09-11独有交易则亏损。B在08-31买入失败、R在10-08买入失败并重置，又改变后续节奏，双方直到10-12实际入场日期重新对齐。', '',
        '这段收益依赖当前已约定的简化日频执行：跌停日卖出价未触及则失败，符合限价含义的买入可按开盘价全仓成交。它不验证真实排队、成交深度或部分成交；本轮保持原约定，不据结果调整执行模型。精确订单、原始行情、涨跌停价及独立资金周期复算见[路径例外核查](../../../experiments/EX023_20261018/others/path_exception_review.json)。', '',
        '## 三个亏损年的共同线索与反证', '',
        '103次提前支撑破坏中，有100次与B同日买入且双方交易均闭合，可比较R提前退出相对B固定持有的收益增量。按首次破坏当晚浮盈P=后复权收盘÷（实际买入成交价×1.001）−1分组；只扣已付买费，不假扣未来卖费。', '',
        '| 首次破坏状态 | 同入场双闭合数 | 平均持仓收益增量（百分点） | 资金周期log增量 |',
        '|---|---:|---:|---:|',
        '| P>0：仍浮盈 | 15 | +2.629 | +0.403079 |',
        '| P≤0：浮亏或持平 | 85 | −0.869 | −0.486463 |', '',
        '2022、2024、2025的主要相对损伤集中于P≤0时提前退出，之后原H10结束前的修复收益未被持有；去2026方向仍一致。但P≤0早退在2021和2023提供保护，P>0组仅15笔，去掉最大的3个正增量后均值约+0.456个百分点，去掉5个则转负；不能当成稳定收益规律。2024没有P>0的早退配对样本，单靠该状态区分也不预期能解决全部入场亏损。', '',
        '这是原R既有交易的状态标签诊断，不是新账户；100笔子集不能解释全部收益提升，尤其不覆盖2026独有交易路径。完整正反数据见[状态诊断](../../../experiments/EX023_20261018/others/loss_state_diagnostics.json)与[后续路线评审](../../../experiments/EX023_20261018/others/loss_route_review.json)。', '',
        '## 审计与证据', '',
        f"因果及公共输入预检{pre['check_count']}项PASS，独立账户审计{audit['check_count']}项PASS。4账户全期及去2026共8项复利核对，最大绝对收益误差{max_error:.3g}。覆盖真实成交时钟、支撑线、等待界限、失败买卖、资金费用、每日状态、无订单日和末日；复用账户核对原证据。"
        f"真实停牌日{account_audit['actual_suspended_sessions']}日，停牌边界以合成预检覆盖，不视作真实停牌经验。", '',
        '以下链接以正式交付报告为基准：[固定设计](../../../experiments/EX023_20261018/protocols/comparison_lock.json)、[账户与年度比较](../../../experiments/EX023_20261018/others/comparison.json)、[路径诊断](../../../experiments/EX023_20261018/others/path_diagnostics.json)、[账户审计与完整指纹](../../../experiments/EX023_20261018/others/account_audit.json)、[预检](../../../experiments/EX023_20261018/others/precheck.json)。全部正式引用和原始CSV在上述文件中保留。', '',
        '## 下一步', '', comp['next_step'], '',
        '所有数据均已用于研究；此轮完整保留正反结果，不将已见样本对照称为样本外验证，也不自动推进阶段四。', '']
    (EX / 'protocols/account_report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'status': 'PASS', 'new_accounts': 1, 'reused_accounts': 3, 'registered_candidates': 46}))


if __name__ == '__main__':
    main()
