"""Declare bounded mechanism controls after the entire old-domain HFQ replay."""
import json
from datetime import datetime, timezone, timedelta
from common import WORK, save, context
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef


def main():
    compared = json.loads((WORK / 'all_replay_comparisons.json').read_text(encoding='utf-8'))
    assert compared['status'] == 'COMPLETE' and len(compared['comparisons']) == 270
    rows = json.loads((WORK / 'search_results.json').read_text(encoding='utf-8'))['rows']
    valid = [r for r in rows if r['status'] == 'SUCCEEDED' and r['gates']['annual_drawdown']]
    frequent = [r for r in valid if r['gates']['frequency']]
    assert frequent
    center = max(frequent, key=lambda r: r['net_cagr'])
    return_center = max(valid, key=lambda r: r['net_cagr'])
    risk_center = max((r for r in rows if r['status'] == 'SUCCEEDED' and r['gates']['frequency']),
                      key=lambda r: r['net_cagr'])
    p, rp = center['parameters'], return_center['parameters']
    configurations = [{'label': 'frequency-DD-center', 'parameters': dict(p)},
                      {'label': 'return-center', 'parameters': dict(rp)}]
    grid = risk_center['parameters']
    windows = sorted({grid['range_window'], 150, 180})
    entries = sorted({grid['entry'], .85, .90, .95})
    for window in windows:
        for entry in entries:
            for hold in (6, 9, 12):
                configurations.append({'label': f'joint-window-{window}-entry-{entry}-hold-{hold}',
                    'parameters': dict(grid, range_window=window, entry=entry, exit=.99, max_hold=hold)})
    for key, values in (
        ('acf_min', (-.3, -.1, .1)),
        ('stop_loss', (.005, .015, .03, .06)),
        ('trailing_stop', (.01, .03, .06)),
        ('momentum_min', (-.05, 0., .025)),
        ('exit', (.95, 1.)),
    ):
        for value in values:
            altered = dict(p, **{key: value})
            if altered['entry'] < altered['exit']:
                configurations.append({'label': f'frequency-center-{key}-{value}', 'parameters': altered})
    for hold in (4, 6, 8, 12, 32, 40, 60):
        configurations.append({'label': f'return-center-hold-{hold}', 'parameters': dict(rp, max_hold=hold)})
    for label, parameters in (('frequency-center', p), ('return-center', rp)):
        for premium in (0., .001, .005, .01, .02):
            configurations.append({'label': f'{label}-limit-premium-{premium}',
                                   'parameters': dict(parameters, limit_premium=premium)})
    for acf in (-.1, .1):
        configurations.append({'label': f'frequency-center-direction-acf-{acf}',
                               'parameters': dict(p, acf_min=acf, momentum_min=0.)})
    if risk_center['candidate_id'] != center['candidate_id']:
        risk = risk_center['parameters']
        configurations.append({'label': 'frequency-return-risk-center', 'parameters': dict(risk)})
        for key, values in (('stop_loss', (.005, .015, .03, .06)),
                            ('trailing_stop', (.01, .03, .06)),
                            ('acf_min', (-.3, -.1, .1)),
                            ('momentum_min', (-.05, 0., .025))):
            for value in values:
                configurations.append({'label': f'risk-center-{key}-{value}',
                                       'parameters': dict(risk, **{key: value})})
        for cooldown in (1, 3):
            configurations.append({'label': f'risk-center-loss-cooldown-{cooldown}',
                'parameters': dict(risk, stop_loss=.015, cooldown=cooldown)})
    plan = {'name': 'hfq_followup_1',
        'decision': {'recorded_at': datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
            'frequency_DD_center': {k: center[k] for k in ('candidate_id', 'parameters', 'net_cagr', 'closed_trades', 'annual_dd_margins')},
            'return_center': {k: return_center[k] for k in ('candidate_id', 'parameters', 'net_cagr', 'closed_trades', 'annual_dd_margins')},
            'risk_center': {k: risk_center[k] for k in ('candidate_id', 'parameters', 'net_cagr', 'closed_trades', 'annual_dd_margins')},
            'reason': '联合网格从新口径中频率通过且收益最高的配置出发，检验更长区间和高入场覆盖与短持有的交互；频率/逐年回撤通过的收益中心与高收益频率中心分别检查相关性确认、方向和损失控制；收益中心同时做缩短/延长持有期限对照。',
            'hypotheses': ['扩大入场覆盖可能增加上涨期参与，但也可能扩大亏损年回撤与摩擦成本',
                           '高相关性可能属于持续下跌，以20日动量方向作竞争解释对照，不宣称已有Alpha',
                           '延长持有可能增加收益却减少闭合交易，短持有可核验频率改善的代价',
                           '基线限价溢价20bp可能漏掉向上跳空机会；0/10/50/100/200bp对照检验成交覆盖与买入成本的取舍，仍为T日形成限价、T+1撮合'],
            'execution_parameter_authority': 'MANDATE/3的确认项要求限价买入、市价卖出，未固定溢价；报告中的20bp为当时基线。按RSCH阶段三执行参数自主权预声明该对照，不改变费用、用户硬门或价格口径。',
            'old_unexecuted_plan': 'EX003的100项边界计划没有执行；该中心来自旧原始价格排名。本轮不复用其结论，重新据HFQ结果声明当前联合网格及控制项。',
            'boundary_policy': '若外边界带来可解释的联合目标改善，则继续扩边；某项改善而其他约束显著恶化时保留取舍证据并判断是否仍值得延伸。参数域与本次预算不能单独证明研究充分。',
            'economic_gates_unchanged': True, 'new_data_or_dependency': False},
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1,
                      'reason': '8并发Windows管道两次中断后的显式调整，保持多进程及同一完整账户评价'},
        'configurations': configurations}
    save('hfq_followup_1_plan.json', plan)
    ref = publish_evidence(context(), MaterialEvidenceWrite(ExperimentRef('S013', 'EX004_20261007'),
        'hfq-followup-1-plan', (WORK / 'hfq_followup_1_plan.json').read_bytes(), 'application/json', 'json'))
    save('hfq_followup_1_plan_reference.json', ref.to_dict())
    print(json.dumps({'plan': plan['name'], 'configurations': len(configurations),
                      'centers': [center['candidate_id'], return_center['candidate_id']],
                      'published': ref.to_dict()}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
