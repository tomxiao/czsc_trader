"""Publish directed boundary and competing explanations before FULL evaluation."""
from copy import deepcopy
import json
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from common import RUNS, context, save, PROTOCOLS
from search import configuration_hash


def main():
    rows = json.loads((RUNS / 'search_results_r4.json').read_text(encoding='utf-8'))['rows']
    center = next(r for r in rows if r['candidate_id'] == 'C0440')
    assert center['qualified'] and center['status'] == 'SUCCEEDED'
    p = center['parameters']
    configurations = []

    def add(label, path, value):
        q = deepcopy(p)
        if len(path) == 1:
            q[path[0]] = value
        else:
            q[path[0]][path[1]] = value
        configurations.append({'label': label, 'parameters': q})

    for x in (-.04, -.01, -.005, .005, .01, .04):
        add(f'regime-threshold-{x}', ('regime_threshold',), x)
    for x in (5, 10, 15, 25, 30, 40, 60):
        add(f'regime-window-{x}', ('regime_window',), x)
    for x in (1, 2, 3, 5, 12):
        add(f'bear-hold-{x}', ('bear', 'max_hold'), x)
    for x in (.075, .125):
        add(f'bear-acf-{x}', ('bear', 'acf_min'), x)
    for x in (6, 10):
        add(f'bull-hold-{x}', ('bull', 'max_hold'), x)
    for x in (.625, .725):
        add(f'bull-entry-{x}', ('bull', 'entry'), x)
    for x in (.8, .9):
        add(f'bear-entry-{x}', ('bear', 'entry'), x)
    for x in (.005, .015):
        q = deepcopy(p)
        q['bull']['limit_premium'] = q['bear']['limit_premium'] = x
        configurations.append({'label': f'global-limit-premium-{x}', 'parameters': q})
    for hold in (2, 3, 5):
        for threshold in (-.005, .005):
            q = deepcopy(p)
            q['bear']['max_hold'], q['regime_threshold'] = hold, threshold
            configurations.append({'label': f'joint-bear-hold-{hold}-threshold-{threshold}', 'parameters': q})
    assert len(configurations) == len({configuration_hash(c['parameters']) for c in configurations}) == 34
    value = {'name': 'four_gate_adaptive_followup_1', 'date': '2026-10-08',
             'center': {k: center[k] for k in ('candidate_id', 'content_sha256', 'result_hash', 'parameters', 'annual', 'closed_trades')},
             'reason': '首个四门达标点2023盈利仅0.303%、113闭合距最低110较近，bear持有4位于初始域下沿。扩至1/2/3及12，并检验状态阈值/期限、入场过滤、上涨持有期和限价的单变量及六个持有期×阈值交互。',
             'hypotheses': ['更短负动量持有期能否维持收益并提高实际闭合交易数',
                            '状态退出改善是否依赖精确20日与零阈值，若相邻值亏损则作为反证',
                            '正相关性与两路线阈值是否有必要，溢价造成的填单变化是否主导结果'],
             'parameters_domain': '全部原强类型合法域内；不是新增目标。初始阈值[-.02,.02]扩至±.04，初始bear持有[4,9]扩至[1,12]；原有信号锚点语义保持。',
             'selection_history': 'C0440是在已见全开发池中选择；39点初轮尚在完成，扩边设计仅依据已出现C0440。仍为开发搜索，未执行阶段四自检。',
             'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
             'budget_note': '结果与机制、边界及竞争解释共同决定收口；次数和首个达标本身不构成停止依据',
             'configurations': configurations}
    save('four_gate_adaptive_followup_1_plan.json', value, directory=PROTOCOLS)
    ref = publish_evidence(context(4), MaterialEvidenceWrite(ExperimentRef('S013', 'EX004_20261007'),
        'four-gate-adaptive-followup-1-plan', (PROTOCOLS / 'four_gate_adaptive_followup_1_plan.json').read_bytes(),
        'application/json', 'json'))
    save('four_gate_adaptive_followup_1_plan_reference.json', ref.to_dict(), directory=PROTOCOLS)
    print(json.dumps({'configurations': len(configurations), 'reference': ref.to_dict()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
