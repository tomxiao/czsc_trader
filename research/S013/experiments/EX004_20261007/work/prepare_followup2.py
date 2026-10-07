"""Local falsification and the remaining improving parameter boundary."""
import json
from common import WORK, save, context
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef


def main():
    first = json.loads((WORK / 'hfq_followup_1_comparisons.json').read_text(encoding='utf-8'))
    assert first['status'] == 'COMPLETE' and len(first['comparisons']) == 63
    rows = json.loads((WORK / 'search_results.json').read_text(encoding='utf-8'))['rows']
    valid = [r for r in rows if r['status'] == 'SUCCEEDED' and r['gates']['annual_drawdown']]
    frequent = [r for r in valid if r['gates']['frequency']]
    center = max(frequent, key=lambda r: r['net_cagr'])
    return_center = max(valid, key=lambda r: r['net_cagr'])
    p, rp = center['parameters'], return_center['parameters']
    assert p['range_window'] == 120 and p['entry'] == .85 and p['max_hold'] == 9 and p['limit_premium'] == .02
    configurations = []
    for hold in (7, 8, 10, 11):
        configurations.append({'label': f'local-frequency-center-hold-{hold}', 'parameters': dict(p, max_hold=hold)})
    for entry in (.825, .875):
        configurations.append({'label': f'local-frequency-center-entry-{entry}', 'parameters': dict(p, entry=entry)})
    for premium in (.03, .05, .08):
        configurations.append({'label': f'expanded-limit-premium-{premium}', 'parameters': dict(p, limit_premium=premium)})
    for window in (150, 180):
        configurations.append({'label': f'return-center-window-{window}', 'parameters': dict(rp, range_window=window)})
    selected = lambda row: {key: row[key] for key in ('candidate_id', 'parameters', 'net_cagr', 'closed_trades', 'annual_dd_margins')}
    plan = {'name': 'hfq_followup_2', 'decision': {
        'frequency_DD_center': selected(center), 'return_center': selected(return_center),
        'reason': '第一组63项已经完整完成：高入场/长窗口联合扩边、确认与风险控制无联合改善；限价溢价到2%仍在上边界改善。针对新前沿检验持有期限及入场局部邻域，并扩展溢价；最高收益配置的120日窗口另做150/180日同参数扩边，避免把另一中心的联合网格当成它的单因素反证。',
        'limits': '不把局部敏感性作为新增经济硬门；仍按原三项同时判定。0.08溢价低于当前实现0.09上限，原始报价10%护栏继续生效。',
        'boundary_policy': '若外边界继续提供联合目标改善则继续扩展；若观察到内点峰值或扩大造成明确退化，保存反证并评审是否停止。',
        'new_data_or_dependency': False},
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1},
        'configurations': configurations}
    save('hfq_followup_2_plan.json', plan)
    ref = publish_evidence(context(), MaterialEvidenceWrite(ExperimentRef('S013', 'EX004_20261007'),
        'hfq-followup-2-plan', (WORK / 'hfq_followup_2_plan.json').read_bytes(), 'application/json', 'json'))
    save('hfq_followup_2_plan_reference.json', ref.to_dict())
    print(json.dumps({'plan': ref.to_dict(), 'configurations': len(configurations)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
