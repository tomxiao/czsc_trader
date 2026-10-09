"""Resolve specific failing years and extend the newly observed window boundary."""
import json
from common import RUNS, save, context, SOURCE, EXTENDED_SOURCE, PROTOCOLS
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef


def main():
    previous = json.loads((RUNS / 'hfq_followup_2_comparisons.json').read_text(encoding='utf-8'))
    assert previous['status'] == 'COMPLETE'
    rows = json.loads((RUNS / 'search_results.json').read_text(encoding='utf-8'))['rows']
    near = next(r for r in rows if r['candidate_id'] == 'C0351')
    returning = next(r for r in rows if r['candidate_id'] == 'C0357')
    assert near['annual_dd_margins']['2020'] < 0 and returning['annual_dd_margins']['2024'] < 0
    old_source = (SOURCE / 'strategies/range_reversion.py').read_text(encoding='utf-8')
    extended = (EXTENDED_SOURCE / 'strategies/range_reversion.py').read_text(encoding='utf-8')
    assert extended == old_source.replace("not 21 <= p['range_window'] <= 180", "not 21 <= p['range_window'] <= 360").replace('range_window must be 21..180 sessions', 'range_window must be 21..360 sessions')
    p, rp = near['parameters'], returning['parameters']
    configurations = []
    for key, values in (('stop_loss', (.005, .015, .03, .06)),
                        ('trailing_stop', (.01, .02, .03)),
                        ('acf_min', (-.3, -.1)), ('momentum_min', (-.05, 0.))):
        for value in values:
            configurations.append({'label': f'near-center-{key}-{value}', 'parameters': dict(p, **{key: value})})
    for cooldown in (1, 3):
        configurations.append({'label': f'near-center-loss-cooldown-{cooldown}',
                               'parameters': dict(p, stop_loss=.015, cooldown=cooldown)})
    for hold in (8, 10, 12):
        configurations.append({'label': f'return180-short-hold-{hold}', 'parameters': dict(rp, max_hold=hold)})
    for loss in (.03, .06):
        configurations.append({'label': f'return180-loss-{loss}', 'parameters': dict(rp, stop_loss=loss)})
    for loss in (.03, .06):
        configurations.append({'label': f'return180-short-loss-{loss}', 'parameters': dict(rp, max_hold=10, stop_loss=loss)})
    for window in (240, 360):
        configurations.append({'label': f'return180-expanded-window-{window}', 'parameters': dict(rp, range_window=window)})
    subset = lambda row: {key: row[key] for key in ('candidate_id', 'parameters', 'net_cagr', 'closed_trades', 'annual_dd_margins')}
    plan = {'name': 'hfq_followup_3', 'decision': {
        'risk_center': subset(near), 'return_center': subset(returning),
        'reason': '局部点C0351只在2020年回撤失败，且收益缺口缩小到0.62个百分点；对其做损失控制、方向及冷却反证。C0357收益门通过但频率不足、2024回撤失败；检验缩短持有与止损的独立及联合效果。180窗口处出现新收益改善，必须继续240/360窗口扩边。',
        'implementation_change': '仅新增研究源码副本，将range_window合法上限由180放宽到360；逐字验证仅两处上限说明变化，计算与执行逻辑不变；超过180的配置使用该新源码身份，旧候选源码原样保留。',
        'history_scope': '仅510500.SH指标所需最小前置历史；不计入开发池账户和目标统计，不新增数据源或依赖',
        'limits': '2020/2024为研究定位年份，评价仍用全1636日连续账户和全部逐年硬门；不筛除亏损年，也不以局部诊断另增硬门。'},
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1},
        'configurations': configurations}
    save('hfq_followup_3_plan.json', plan, directory=PROTOCOLS)
    ref = publish_evidence(context(), MaterialEvidenceWrite(ExperimentRef('S013', 'EX004_20261007'),
        'hfq-followup-3-plan', (PROTOCOLS / 'hfq_followup_3_plan.json').read_bytes(), 'application/json', 'json'))
    save('hfq_followup_3_plan_reference.json', ref.to_dict(), directory=PROTOCOLS)
    print(json.dumps({'plan': ref.to_dict(), 'configurations': len(configurations)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
