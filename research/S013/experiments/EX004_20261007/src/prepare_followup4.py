"""Complete the first qualifying mechanism's neighborhood and relevant boundaries."""
import json
from common import RUNS, save, context, PROTOCOLS
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef


def main():
    previous = json.loads((RUNS / 'hfq_followup_3_comparisons.json').read_text(encoding='utf-8'))
    assert previous['status'] == 'COMPLETE'
    rows = json.loads((RUNS / 'search_results.json').read_text(encoding='utf-8'))['rows']
    center = next(r for r in rows if r['candidate_id'] == 'C0371')
    assert center['qualified']
    returning = next(r for r in rows if r['candidate_id'] == 'C0375')
    p, rp = center['parameters'], returning['parameters']
    configurations = []
    for key, values in (('max_hold', (7, 9)), ('entry', (.65, .70)),
                        ('exit', (.85, .95)), ('limit_premium', (.005, .02)),
                        ('range_window', (150, 240, 360)), ('stop_loss', (.03, .06))):
        for value in values:
            configurations.append({'label': f'qualifying-center-{key}-{value}', 'parameters': dict(p, **{key: value})})
    for loss in (.08, .12):
        configurations.append({'label': f'long-return-loss-boundary-{loss}', 'parameters': dict(rp, stop_loss=loss)})
    subset = lambda row: {key: row[key] for key in ('candidate_id', 'parameters', 'net_cagr', 'closed_trades', 'annual_dd_margins')}
    plan = {'name': 'hfq_followup_4', 'decision': {
        'frequency_DD_center': subset(center), 'return_center': subset(returning),
        'reason': '首次达标不能单独证明研究充分：对C0371的持有期限、入场/退出、执行溢价及损失控制做局部对照，并以相同8日持有检验窗口240/360扩边；C0375在止损0.06处出现新收益改善，再检查0.08/0.12。',
        'scope_boundary': '本组用于阶段三优化及反证，仍按原三项判定；不执行阶段四五项标准自检，不依据敏感性诊断否决经济达标配置。完整保留全部达标点，之后评审阶段三是否具备交接依据。',
        'data_and_implementation': '复用已准备的同标的必要预热；超过180使用既有扩展窗口源码副本，不新增外部依赖或数据源'},
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1},
        'configurations': configurations}
    save('hfq_followup_4_plan.json', plan, directory=PROTOCOLS)
    ref = publish_evidence(context(), MaterialEvidenceWrite(ExperimentRef('S013', 'EX004_20261007'),
        'hfq-followup-4-plan', (PROTOCOLS / 'hfq_followup_4_plan.json').read_bytes(), 'application/json', 'json'))
    save('hfq_followup_4_plan_reference.json', ref.to_dict(), directory=PROTOCOLS)
    print(json.dumps({'plan': ref.to_dict(), 'configurations': len(configurations)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
