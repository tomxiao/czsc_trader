"""Extend the improving bear entry boundary before stage-three closure."""
from copy import deepcopy
import json
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from common import RUNS, context, save, PROTOCOLS


def main():
    rows = json.loads((RUNS / 'search_results_r4.json').read_text(encoding='utf-8'))['rows']
    center = next(r for r in rows if r['candidate_id'] == 'C0494')
    assert center['qualified']
    configurations = []
    for entry in (.925, .95, .975, .985):
        q = deepcopy(center['parameters'])
        q['bear']['entry'] = entry
        configurations.append({'label': f'extended-bear-entry-{entry}', 'parameters': q})
    for entry in (.95, .985):
        for key, value in (('regime_threshold', .005), ('bear.max_hold', 3)):
            q = deepcopy(center['parameters'])
            q['bear']['entry'] = entry
            if key == 'regime_threshold':
                q[key] = value
            else:
                q['bear']['max_hold'] = value
            configurations.append({'label': f'extended-bear-entry-{entry}-{key}-{value}', 'parameters': q})
    value = {'name': 'four_gate_adaptive_entry_extension', 'date': '2026-10-08',
             'center': {k: center[k] for k in ('candidate_id', 'parameters', 'content_sha256', 'result_hash')},
             'reason': 'C0494的bear入场0.90位于相邻域上沿，净年化13.9456%、116闭合，较C0440略有改善；必须检验扩边而不能在暂定上沿收口。',
             'domain': '将bear入场从0.90扩至0.925/0.95/0.975/0.985，接近入场必须低于既有退出0.99的逻辑边界；并与已达标+0.5%状态阈值和未达标3日持有期做四项交互。源码与其余参数不变。',
             'falsification': '入场放宽后新增年份收益、回撤、频率仍逐项核验；平坦或退化用于判断改善是否饱和，不新增经济硬门。',
             'selection_history': '依据同池已见结果选择C0494；当前仍处阶段三，非样本外或阶段四自检。',
             'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
             'configurations': configurations}
    save('four_gate_adaptive_entry_extension_plan.json', value, directory=PROTOCOLS)
    ref = publish_evidence(context(4), MaterialEvidenceWrite(ExperimentRef('S013', 'EX004_20261007'),
        'four-gate-adaptive-entry-extension-plan', (PROTOCOLS / 'four_gate_adaptive_entry_extension_plan.json').read_bytes(),
        'application/json', 'json'))
    save('four_gate_adaptive_entry_extension_plan_reference.json', ref.to_dict(), directory=PROTOCOLS)
    print(json.dumps({'configurations': len(configurations), 'reference': ref.to_dict()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
