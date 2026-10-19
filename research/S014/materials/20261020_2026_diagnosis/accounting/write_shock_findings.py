"""Freeze human interpretation of the two completed fixed policies."""
import csv
import json
from pathlib import Path

import consolidate_shock_audit as S

OUT, A = S.OUT, S.A


def main():
    summary = A.read(OUT / 'independent_shock_audit_summary.json')
    reports = [A.read(OUT / f'shock_account_{i:03d}_independent_review.json') for i in (0, 1)]
    on, off = reports
    pause = A.read(OUT / 'shock_pause_actual_review.json')
    with (OUT / 'shock_2026_actual_pause_slots.csv').open(encoding='utf-8', newline='') as stream:
        slots = list(csv.DictReader(stream))
    first_off_slot = next(r for r in slots if r['shock_profile'] == 'SHOCK_OFF')
    A.check('new early OFF own feedback chain actual slot', first_off_slot['slot_D'] == '2026-01-23' and first_off_slot['next_actual_BUY_E'] == '2026-02-10')
    results = {'status': 'COMPLETE_FIXED_PAIR_DIAGNOSIS', 'sources': [S.ref(OUT / 'independent_shock_audit_summary.json'), S.ref(OUT / 'shock_pause_actual_review.json')],
               'implementation': S.ref(Path(__file__).resolve()),
               'goal_judgment': {'SHOCK_ON': {'original_return_pass': '6/7', 'original_drawdown_pass': '7/7', 'frequency_pass': True, 'all_original_goals_pass': False},
                                 'SHOCK_OFF': {'original_return_pass': '5/7', 'original_drawdown_pass': '7/7', 'frequency_pass': True, 'all_original_goals_pass': False},
                                 'decision': 'OFF cannot replace C9461 on this evidence: improved2026 still misses its original target and sacrifices2025.'},
               'factual_2026': {r['policy_id']: {**r['boundary2026_actuals'], **r['actual2026_phase_summary']} for r in reports},
               'first_divergence': off['prefix'], 'actual_suppressed_counts': off['actual_suppressed_SHOCK_counts'],
               'strongest_crossyear_counterexample': {'year': 2025, 'ON_return': on['original_annual_goal_audit'][5]['return'],
                                                     'OFF_return': off['original_annual_goal_audit'][5]['return'],
                                                     'required': off['original_annual_goal_audit'][5]['required_return'],
                                                     'OFF_actual_suppressed_cycles': list({r['cycle_id']: r for r in off['actual_suppressed_SHOCK_rows'] if r['D'][:4] == '2025'}.values())},
               'remaining2026_question': {'observed_new_OFF_early_loss_slot': first_off_slot,
                                         'interpretation': 'OFF allows Jan9 actual position to exitJan19 at a net loss, then consumes Jan23 own loss-pause slot and reentersFeb10. This establishes a changed feedback mechanism, not a hypothetical recoverable return.',
                                         'minimal_discriminating_followup': 'Keep SHOCK_OFF, NET1ATR cost, support, H10, clock and fees fixed; compare own-loss-pause ON versus BASE in full historical funded accounts, with a new-source exact OFF control. No parameter/date/threshold search.',
                                         'evidence_for_diagnosing_not_adopting': True,
                                         'counterevidence': 'OFF actual pause-to-next-entry windows include both strong upward missed exposure and stronger net downward avoided exposure overall; removing pause may harm2024/25 and later2026.',
                                         'no_claim_new_arm_will_improve': True},
               'resources': summary['resource_accounting'], 'independent_actual_checks': summary['independent_actual_checks'],
               'independent_phase_checks': summary['independent_phase_checks'],
               'observed_pause_chain_summary': pause['summary'],
               'limits': ['Whole policy first diverges2020Jul6; each2026 own opening differs. Annual return changes cannot be multiplied by a shared opening or assigned to only six oldSHOCK actions.',
                          'Partial2026 remains an original unannualized hard-goal year. All seven years were seen; no holdout or automatic formal registration.',
                          'Original first five postSHOCK flat windows include four positive and one zero BH-net window, with September negative; this is only observed alternate exposure, not OFF profit proof.',
                          'Actual OFF September cycle exitsSep10 by original H10 with51.2436% full-trade net return. Old ON September flat drawdown is not proof that this OFF cycle lost.',
                          'Full-flat phase versus pause-to-next-entry window totals differ because the latter also includes post-expiry eligibility waiting. Neither defines a new action label.',
                          'New active account counts one fixed alternative, not seven independent validation samples; no fitted model, new market API or new strategy registration.']}
    path = OUT / 'shock_research_findings.json'
    S.H.write(path, results)
    text = '''# EX047 固定退出职责对照独立结论

关闭 SHOCK 改善了2026收益，但不能替代当前 C9461。SHOCK_ON（C9470）严格复现 C9461；SHOCK_OFF（C9471）是诊断配置，未正式注册。

|原口径|SHOCK_ON|SHOCK_OFF|
|---|---:|---:|
|2025收益|47.0320%|−4.7050%|
|2026截至10/15收益|79.1981%|123.2509%|
|2026原收益门|196.4644%|196.4644%|
|原七年度收益通过|6/7|5/7|
|原七年度回撤通过|7/7|7/7|
|原频率（每60交易日闭合周期）|3.361754|3.215591|
|原截止连续终值|944,894.575|899,477.470|

OFF在2020/21年改善，在2022/23/24年分别下降约2.43/0.30/4.27个百分点，2025下降51.74个百分点。七年原目标仍未全部通过；没有修改目标或历史候选资格。

OFF从2020-07-06决策、07-07资金开始分叉。其2026年初权益402,899.81、持仓67,200；ON为527,290.572、88,000。二者同为2025-12-23实际入仓，资金与数量不同。OFF截止空仓899,477.47；不能把全年效果说成只撤销旧2026六次卖出。

OFF2026真实净增496,577.66：买入当日毛损益−52,014，继续持有+450,892，卖出前收盘至实际卖价+111,754，费用14,054.34。相对原买入持有差7.7254个百分点，另有原1.5倍目标溢价65.4881个百分点，总缺口73.2135个百分点。118个全程空仓日的买入持有净变化为−26.6648个百分点，不能将剩余缺口全部解释为漏涨。

OFF原SHOCK条件被抑制57个D，涉及21个真实周期；2026为12个D、5个周期。2026实际卖出为4个原期限、6个原支持、1个成本与支持重合。SHOCK关闭仍保留支持/成本/期限。2025三个被抑制条件对应的真实完整周期最终分别约−8.66%、−10.56%、−1.81%，是禁止全局关闭的重要反证；这些也不是单次取消SHOCK的局部收益标签。

下一项最有辨别力的问题是：关闭SHOCK后产生的自身亏损反馈，是否重新限制了早期参与。OFF的1/9真实入仓在1/19支持退出净亏1.6076%，随后1/23消费亏损暂停名额，2/10才实际再入仓。其间11个全空仓日买入持有净上涨40.7519个百分点；这仅证明机制发生变化，不能视为取消暂停就可赚回的收益。OFF全年六个实际暂停名额里同时存在明显风险规避，最后名额在截止仍未到期。若继续，只值得做固定成本和SHOCK_OFF、单独开关亏损暂停的完整账户对照；不支持调阈值或按已见日期挑窗口。

两次真实派发全部成功，0失败、0未知、0重试；独立完整账务/状态检查672,682，年度桥接检查1,149。复算实现、两份独审、14行年度表、2行汇总及实际退出/暂停/资金分解均在本目录，清单见 shock_final_accounting_delivery.json。旧封存材料和源码保持原字节。所有年份均为已见研究开发样本。
'''
    md = OUT / 'shock_readout.md'
    with md.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    print(json.dumps({'findings': S.ref(path), 'readout': S.ref(md)}))


if __name__ == '__main__':
    main()
