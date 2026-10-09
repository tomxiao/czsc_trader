"""User authorization and declared counterfactuals before four-gate search."""
import json
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from common import ROOT, RUNS, context, save, PROTOCOLS
from economics_r4 import apply_constraint


def main():
    research = context(4)
    experiment = ExperimentRef('S013', 'EX004_20261007')
    current = json.loads((ROOT / 'research/S013/assets/deliveries/CANDIDATES/2/delivery.json').read_text(encoding='utf-8'))
    content = d.DeliveryContent.from_dict(current['content'])
    ref = next(r for r in content.evidence if r.name == 'hfq-search-results')
    old = json.loads(ref.resolve(ROOT).read_text(encoding='utf-8'))['rows']
    if (RUNS / 'search_results_r4.json').exists():
        raise ValueError('four-gate work state already exists; inspect before resuming')
    rows = [apply_constraint(r) for r in old]
    assert sum(r.get('qualified', False) for r in rows) == 0
    save('search_results_r4.json', {'rows': rows, 'source_reference': ref.to_dict(),
                                  'mandate_revision': 4})
    by_id = {r['candidate_id']: r for r in rows if r['status'] == 'SUCCEEDED'}
    configs = []
    def add(label, identifier, **updates):
        configs.append({'label': label, 'parameters': {**by_id[identifier]['parameters'], **updates}})
    for hold in (3, 4, 6, 8):
        for acf in (.025, .05, .075, .1):
            add(f'acf-positive-center-hold{hold}-acf{acf}', 'C0315', max_hold=hold,
                acf_min=acf, limit_premium=.01)
    for acf in (-.05, 0., .025, .05, .075, .1):
        add(f'old-high-return-acf{acf}', 'C0385', acf_min=acf)
    for hold in (3, 4, 6):
        for acf in (-.3, -.1, 0.):
            add(f'short-range-positive-hold{hold}-acf{acf}', 'C0058', max_hold=hold,
                acf_min=acf, limit_premium=.01)
    add('acf-positive-center-premium-control', 'C0315', limit_premium=.01)
    for acf in (.05, .1):
        add(f'long-range-acf-hold4-{acf}', 'C0315', range_window=180, max_hold=4,
            acf_min=acf, limit_premium=.01)
    plan = {'name': 'four_gate_acf_1', 'date': '2026-10-08',
        'user_confirmation': {
            'proposal': '建议继续阶段三，针对亏损年份研究盈利机制，暂不进入阶段四。是否继续？',
            'answer': '同意', 'scope': 'S013阶段三；沿用当前分支、数据、资源与已安装依赖'},
        'hypotheses': [
            '正相关性过滤可减少持续下跌中的反复入场；缩短最长持有期限有可能恢复交易频率，同时需核对费用及收益损失。',
            '短窗口低位反转在负基准年份已有盈利线索；缩短持有并放宽相关性过滤可检验收益和频率是否能够同时改善。'],
        'falsification': '以四项同时核验，逐年利润不通过或收益/回撤/频率退化均公开保存；不将诊断设为额外经济否决条件',
        'scope_and_causality': '2022/2023只用于开发目标与归因；策略不得读取自然年盈亏、下一日价格或未来基准走势，不按历史年份硬编码交易',
        'selection_history': '全开发池已用于378个旧配置选择；先对新增条件通过的稀疏路线和旧高收益路线做反事实对照，不视为样本外',
        'implementation': '已有RangeReversion原源码，账户和SRT/TXE口径保持；不新增外部数据源或依赖',
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'configurations': configs, 'budget_note': '34个声明对照为第一轮，结果决定有依据的扩边或新机制；轮数和预算不作为研究充分的独立证明'}
    assert len(configs) == 34
    save('four_gate_acf_1_plan.json', plan, directory=PROTOCOLS)
    published = publish_evidence(research, MaterialEvidenceWrite(experiment, 'four-gate-acf-1-plan',
        (PROTOCOLS / 'four_gate_acf_1_plan.json').read_bytes(), 'application/json', 'json'))
    save('four_gate_acf_1_plan_reference.json', published.to_dict(), directory=PROTOCOLS)
    print(json.dumps({'reference': published.to_dict(), 'configurations': len(configs)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
