"""Interpret fixed original-account2026 arithmetic; no parameter proposal scan."""
import csv
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent


def ref(name):
    path = OUT / name
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def table(name):
    with (OUT / name).open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def save(name, value):
    destination = OUT / name
    content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    with destination.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(content)
    return ref(name)


def main():
    account = json.loads((OUT / 'actual_2026_accounting_review.json').read_bytes())
    exits = json.loads((OUT / 'actual_2026_exit_flat_review.json').read_bytes())
    result = account['annual_actuals'][0]
    phase = [r for r in table('actual_2026_phase.csv') if r['policy'] == 'C9461']
    month = [r for r in table('actual_2026_monthly.csv') if r['policy'] == 'C9461']
    shock = [r for r in table('actual_2026_exit_decisions.csv') if r['policy'] == 'C9461' and float(r['selected_shock_exit']) != 0]
    assert len(shock) == 6
    gap_before_pause = -sum(float(r['relative_buyhold_contribution_pp']) for r in month if r['month'] <= '2026-03')
    fees_pp = result['actual_fees'] / result['opening_equity'] * 100
    sources = [ref(n) for n in ['actual_2026_accounting_review.json', 'actual_2026_exit_flat_review.json', 'actual_2026_phase.csv',
                              'actual_2026_monthly.csv', 'actual_2026_exit_decisions.csv', 'actual_2026_flat_reason_summary.csv', 'actual_2026_pause_slots.csv']]
    findings = {'status': 'COMPLETE_READ_ONLY_ACTUAL_DIAGNOSIS', 'sources': sources, 'implementation': ref(Path(__file__).name),
                'fixed_candidate': 'S014-C9461 EX046001 diagnostic configuration; not formally registered, source/parameters unchanged.',
                'partial2026_original_gate': {k: result[k] for k in ['opening_equity', 'closing_equity', 'return', 'max_drawdown', 'buyhold_return', 'buyhold_drawdown', 'required_return', 'return_pass', 'drawdown_pass', 'gap_to_required_pp']},
                'gap_decomposition_pp': {'extra_original_half_BH_requirement': result['additional_original_1point5_BH_requirement_pp'],
                                        'actual_underperformance_vs_BH': result['underperformance_vs_BH_pp'],
                                        'by_actual_phase_strategy_minus_BH': {r['actual_phase']: float(r['relative_buyhold_contribution_pp']) for r in phase}},
                'findings': [
                    {'finding': 'Insufficient return is not mainly an execution-block or fee failure.',
                     'actuals': 'C9461 actual2026 BUY11/SELL12, including one2025 carry; no failed BUY or blocked SELL. Fees18012.997=3.41614244pp, materially below117.26632303pp target gap. All12 sales filled first planned E.',
                     'limit': 'Costs remain real; no fee/limit/timing contract alteration is proposed.'},
                    {'finding': 'The large participation gap predates the first2026 completed-loss pause.',
                     'actuals': f'Jan-Mar observed strategy contribution less BH by{gap_before_pause:.10f}pp; first actual pause D2026Apr7. Cost comparator also earns only89.09918296% vs required196.46440188%.',
                     'limit': 'This rejects a single-cause all-pause story, not a causal estimate of removing SHOCK.'},
                    {'finding': 'Actual shock exits and original reservations are a discriminating next action responsibility.',
                     'actuals': 'Six selectedSHOCK-only sales: DJan6/Jan9/Jan29/Feb11/Mar6/Sep1; no support/cost/deadline/pending overlap. Ages8/0/3/1/1/3; original reservation still2/10/7/9/9/7 sessions away at D. These same dates occur in original costBASE.',
                     'limit': 'Actual later-flat BH net+128.12531202pp is descriptive, not hold-return. Firstfive+144.05712438pp include old reservation and price qualification; September counterexample-15.93181236pp is retained.'},
                    {'finding': 'Whole-flat days contain missed upward exposure and avoided declines.',
                     'actuals': 'C9461 wholeflat141days: original actualBUY reservation79days/BH net+93.24302812pp; supportnoteligible12/+17.77654853; pauseconsumed5/+14.75788934; following activepause45/-74.79566644. TotalBHnet+50.98179955pp.',
                     'limit': 'Exclusive state labels are accounting classifications; overlap, eligibility and dynamic population do not identify separate causal shares.'},
                    {'finding': 'Five actual pause slots are mixed and the last is censored at cutoff.',
                     'actuals': 'DApr7/May14/Jun22/Jul27/Sep30; first four observed reentryEApr23/Jun2/Jul13/Aug12. September30 slot untilindex1647 remains unexpired at original end. CostBASE sameD BUY forOct8 actually failed; laterOct12 realBUY andOct15sale are a different actual cycle, not an imagined filled skipped slot.',
                     'limit': 'No imagined trade, extended cutoff or future slot value assigned. Wholeflat observed July pause window BHnet+30.85740499pp versus negative-net windows elsewhere is a counterexample to uniform pause benefit.'},
                    {'finding': 'Cross-year capital and economic calendar are respected.',
                     'actuals': 'C9461 openingcash4570.572,88000researchunits carry from2025Dec23.2026 atoms begin at2025Dec31close5.94; carry full trade return8.35450264% is not assigned wholesale to2026. Cutoffcash944894.575/zeroquantity. CostBASE also flat at cutoff.',
                     'limit': 'Last stored decision D2026Oct14 maps to final EOct15. No sourceD15 decision was replayed or inferred.'}
                ],
                'most_discriminating_next_question': 'Keeping current C9461 cost/support/ENTRY_GRACE/H10/reservation/completed-loss pause fixed, does disabling only the positive-P Z>2 SHOCK exit improve full funded original-goal performance, or do other exits/timing and later risk offset the observed early-sale gap?',
                'needed_contrast': 'If root locks it: fresh exact current ON source control and one date-free OFF mechanism, all original2020-2026 goals and own continuous capital, no threshold or action-date search. Existing old noSHOCK cells are background, not current-policy causal evidence.',
                'not_claimed': ['Turning SHOCK off will recover128pp or pass the original target.', 'No pause is always superior.', 'Lower whole-held annual contribution means intentional partial positions.', 'Independent out-of-sample validation.'],
                'original2020_25_evidence': 'Frozen complete-six-year result remains intact; any future policy must be evaluated on all original years, not accepted from2026 alone.',
                'resources': account['resources'], 'additional_semantic_checks': account['check_count'] + exits['check_count']}
    finding_ref = save('actual_2026_findings.json', findings)
    body = '''C9461在2026截至10月15日实际赚79.20%，仍低于原目标196.46%；回撤23.18%已小于基准59.77%，本轮首先解释收益不足。

年初权益527290.572，末期944894.575，净赚417604.003。实际资金桥为：买入日毛损12043，继续持仓毛收益361324，卖出成交前后毛收益86336，减真实费用18012.997。费用占自己年初3.42个百分点，不能解释117.27个百分点的全部缺口。

117.27个百分点分两层：落后原买入持有基准51.78个百分点，加上原合同要求额外超过基准一半收益的65.49个百分点。实际阶段相对基准：整日空仓少50.98个百分点、卖出日少26.51、整日持仓少22.71；买入日反而相对基准多48.42，四者抵消后净少51.78。买入日较好是相对于当日基准的完整价格暴露，不等于该账户买入日赚钱；实买首日实际净损20570.33。

最有辨别力的事实是缺口在暂停之前已很大：1–3月相对基准少80.87个百分点，第一次2026亏损后暂停直到4月7日。原成本止损基线同期也只赚89.10%，所以不能把收益不足都归于新暂停。

12次实际卖出全部在首次计划执行日成交：6次仅由盈利后的SHOCK退出触发，5次仅支撑退出，1次成本与支撑同时触发，没有SHOCK与其他退出重合，也没有受阻SELL。六次SHOCK决策日为1月6日、1月9日、1月29日、2月11日、3月6日、9月1日；此时还需等待原预约2、10、7、9、9、7格，才可按原资格再入场。两条原账户都有这六次SHOCK日期。

六次SHOCK卖出以后、下一次实际入场以前的整日空仓，基准净涨幅贡献合计128.13个百分点；这不是关掉SHOCK就能赚到的钱。前五次合计为正，9月那次却为负15.93个百分点，保留了提前退出规避后续下跌的反例。实际空仓还同时受原预约、价格资格和后续暂停影响。

141个整日空仓中：原真实买入预约等待79天，基准净贡献+93.24个百分点；价格资格不满足12天，+17.78；暂停消费当天5天，+14.76；此后暂停预约活动45天，-74.80。空仓既漏涨也避跌，净数不能解释成某个规则独立造成的损失。整日持仓贡献较少也包含此前资金与股数路径差异，不能称为策略当时主动少持仓。

实际五次暂停也不是同一种结果：4月7日、5月14日、6月22日、7月27日、9月30日；前四次随后真实买入分别是4月23日、6月2日、7月13日、8月12日。7月底暂停期间基准净上涨，是明显机会成本；其他窗口也有净下跌。最后一次预约尚未到期就到了原截止日，不虚构未来重新入场或收益。同日原成本基线的10月8日买单实际未成交，其10月12日后来的实际交易不能冒充那张被暂停的订单。

年初88000研究单位来自2025年12月23日的跨年仓，2026损益从2025末的5.94账面价接续，不把完整周期收益全部塞进2026。末期两账户均空仓。原计算最后决策日是10月14日、执行日10月15日；没有重算截止日当晚的新决策。

最值得检验的下一问：保留当前C9461所有成本、支撑、宽限、H10、预约和亏损后暂停，只关闭盈利SHOCK退出，完整账户能否改善原目标，而不是只获得某段行情的事后收益？若主会话锁定该对照，应先用新源码ON精确控制，再做一个OFF机制，逐一核对全部原年份；旧格数据仅作背景，不替代当前路径反事实。本轮没有派账户、改参数、取新市场数据、拟合或虚构删单收益。

证据入口：[资金与人口](actual_2026_accounting_review.json)、[退出与空仓状态](actual_2026_exit_flat_review.json)、[逐月桥接](actual_2026_monthly.csv)、[真实暂停轨迹](actual_2026_pause_slots.csv)。
'''
    print(json.dumps({'findings': finding_ref, 'readout': save('actual_2026_readout.md', body), 'fee_pp': fees_pp, 'pre_pause_gap': gap_before_pause}))


if __name__ == '__main__':
    main()
