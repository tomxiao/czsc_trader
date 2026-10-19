"""Read audited local labels only; no replay, new label, fit or account."""
import csv
import json
from pathlib import Path

import authenticate_shock_population as P


def main():
    with (P.OUT / 'local_event_labels.csv').open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row['advantage'] = float(row['advantage'])
        row['age'] = int(float(row['holding_age_D']))
        row['remaining'] = int(float(row['remaining_D_sessions_to_deadline']))
        for key in ['PRIOR_TREND_ESTABLISHED', 'NON_FINAL_DAY_DOMINATED']:
            row[key] = {'True': True, 'False': False}[row[key]]

    def group(selected):
        values = [r['advantage'] for r in selected]
        return {'N': len(values), 'positive': sum(v > 0 for v in values), 'negative': sum(v < 0 for v in values),
                'mean_pp': 100 * sum(values) / len(values) if values else None}

    always = group(rows)['mean_pp']
    states = {}
    for key in ['PRIOR_TREND_ESTABLISHED', 'NON_FINAL_DAY_DOMINATED']:
        frozen = 100 * sum(r['advantage'] if r[key] else 0. for r in rows) / len(rows)
        shared = []
        for remaining in range(10):
            true = [r for r in rows if r['remaining'] == remaining and r[key]]
            false = [r for r in rows if r['remaining'] == remaining and not r[key]]
            if true and false:
                shared.append({'remaining': remaining, 'true': group(true), 'false': group(false),
                               'weight': min(len(true), len(false)), 'true_minus_false_pp': group(true)['mean_pp'] - group(false)['mean_pp']})
        states[key] = {'true': group([r for r in rows if r[key]]), 'false': group([r for r in rows if not r[key]]),
                       'frozen_all21_mean_pp': frozen, 'frozen_minus_always_hold_pp': frozen - always,
                       'common_remaining_cells': shared,
                       'common_remaining_min_count_weighted_true_minus_false_pp': sum(c['weight'] * c['true_minus_false_pp'] for c in shared) / sum(c['weight'] for c in shared) if shared else None,
                       'yearly': [{'year': year, **group([r for r in rows if int(r['year_of_D']) == year]),
                                   'frozen_all_events_mean_pp': 100 * sum(r['advantage'] if r[key] else 0. for r in rows if int(r['year_of_D']) == year) / sum(int(r['year_of_D']) == year for r in rows) if any(int(r['year_of_D']) == year for r in rows) else None}
                                  for year in range(2020, 2027)]}
    cases = [{k: r[k] for k in ['event_id', 'D', 'year_of_D', 'age', 'remaining', 'PRIOR_TREND_ESTABLISHED', 'NON_FINAL_DAY_DOMINATED',
                               'actual_exit_fill_E', 'actual_exit_price_ledger', 'modeled_OFF_exit_E', 'modeled_OFF_price_ledger', 'advantage']}
             for r in rows if not r['NON_FINAL_DAY_DOMINATED'] or r['age'] == 0 or r['advantage'] < 0]
    on = P.read(P.OUT / 'local_on_independent_review.json')
    off = P.read(P.OUT / 'local_off_independent_review.json')
    findings = {'status': 'INDEPENDENT_COMPONENT_RESEARCH_COMPLETE', 'meaning': 'All pp are equally weighted original-cycle normalized liquidation differences, not funded policy or annual returns.',
                'inputs': [P.ref(P.OUT / name) for name in ['local_event_labels.csv', 'local_state_summary.csv', 'local_on_independent_review.json', 'local_off_independent_review.json']],
                'population': group(rows), 'always_hold_mean_pp': always, 'always_exit_mean_pp': 0., 'states': states,
                'age0': group([r for r in rows if r['age'] == 0]), 'age_ge1': group([r for r in rows if r['age'] >= 1]),
                'all_age0_both_states_true': all(r['PRIOR_TREND_ESTABLISHED'] and r['NON_FINAL_DAY_DOMINATED'] for r in rows if r['age'] == 0),
                'counterexample_and_excluded_cases': cases,
                'judgment': [
                    'S1 fixed TRUE-hold direction is not supported; do not reverse it or optimize its window.',
                    'S2 retains18/excludes3 and gains only0.420319pp against always-hold on already-seen local history. Shared remaining2/5 contrast is negative; no claim of independent predictive information.',
                    'Age0 versus age>=1 is the existing GRACE boundary; remaining=9-age is the same clock. Age0 contains a positive2021Dec24 counterexample, and age>=1 still has five losing extensions.',
                    '2025Jun19 and2026Jan9 are BOTH stateTRUE and BOTH negative local extensions. Full-policy January reentry/pause benefits do not establish the sign of the original single-cycle label.',
                    'A separately locked freshcontrol/S2/age>=1-latched-hold full-policy test is feasible as action translation and clock competition. The age direction is selected after these labels and must be disclosed; it is not held-out validation.',
                    'Future policy must recompute its own actual funded entry, first SHOCK, completed-net feedback, pending and clocks; never transplant original21 dates/states. Original7 annual return/DD and frequency gates remain unchanged.'
                ],
                'resources': {'original_actual_population': 21, 'C_modelled_ON': 21, 'C_modelled_OFF': 21,
                              'independent_ON_checks': on['check_count'], 'independent_OFF_checks': off['check_count'],
                              'new_funded_dispatched': 0, 'funded_success': 0, 'funded_failed': 0, 'funded_unknown': 0, 'funded_retries': 0,
                              'new_fits': 0, 'new_supplier_calls': 0, 'audit_expression_corrections': 1,
                              'component_unknown': 0, 'component_censored': 0},
                'implementation': P.ref(Path(__file__).resolve())}
    report = P.save('local_research_findings.json', findings)
    text = '''# 原持仓急涨退出：局部组件研究结论

21个原C9461持仓周期全部保留，独立ON精确控制1773项、OFF独立重建4304项通过；12个延持有利、9个不利，零未知或截尾。2022没有此类周期，均值保持空值。本轮零新账户、零拟合、零供应商调用。

S1按原方向分流不获支持。S2保留18例、排除3例；全21等权冻结处置均值3.7674个百分点，相对一律延持3.3471个百分点只多0.4203个百分点。相同剩余期限2/5的共同层中，TRUE减FALSE加权差为−0.9739个百分点，尚不能排除时钟构成解释。

买入当日SHOCK共5例，延持均值−6.804个百分点（4负1正）；此前已持仓16例均值+6.519个百分点（11正5负）。两状态把全部买入当日例都判为延持。2021-12-24是买入当日延持正例，不能把年龄差当无例外规律。年龄与剩余期限是同一个持仓时钟。

2025-06-19和2026-01-09两状态均TRUE，延持标签分别−21.4365和−7.9778个百分点。2026-01-29、02-11、03-06、09-01则为延持正例。2021-12-24当日下跌仍属于S2 TRUE，必须保留，不能将S2描述为平滑持续上涨。

局部标签是固定原股数、原入场成本的两次清算净额差，原ON卖后现金冻结，不含重新参与。它们不是新真实交易，也不能相加成为年度收益。旧整策略退出后重新参与、暂停链的改善，不能推断本原仓延持有利。

下一步可单独锁定freshcontrol、S2首次自有SHOCK锁存延持、年龄≥1首次自有SHOCK锁存延持三档完整政策，用自身资金和完成史检验动作及纯时钟解释。年龄方向来自已见标签，必须披露；不得宣称S2已有独立信息或样本外验证。保留所有原年度收益、回撤和频率硬门，不新增门。本组件研究不派发这些账户。

来源：`local_event_labels.csv`、`local_state_summary.csv`、`local_on_independent_review.json`、`local_off_independent_review.json`、`local_research_findings.json`。原ON审计时间字符串表达失败、原助手及精确Timestamp后继审计全部保留，未重跑组件ON或修改执行结果。
'''
    with (P.OUT / 'local_readout.md').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    print(json.dumps({'findings': report, 'readout': P.ref(P.OUT / 'local_readout.md'), 'age0': findings['age0'], 'age_ge1': findings['age_ge1'], 'states': {k: {f: v for f, v in value.items() if f not in ['yearly', 'common_remaining_cells']} for k, value in states.items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
