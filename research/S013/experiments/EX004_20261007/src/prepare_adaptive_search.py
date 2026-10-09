"""Declare dual-route controls and causal regime interaction before evaluation."""
import json
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from common import RUNS, context, save, PROTOCOLS
from common_adaptive import SOURCE, FILES
from strategy_runtime import implementation_sha256


def main():
    old = json.loads((RUNS / 'search_results.json').read_text(encoding='utf-8'))['rows']
    by_id = {r['candidate_id']: r for r in old if r['status'] == 'SUCCEEDED'}
    bull = by_id['C0385']['parameters']
    sparse = {**by_id['C0315']['parameters'], 'limit_premium': .01}
    deep = {**by_id['C0058']['parameters'], 'limit_premium': .01}
    control = {'name': 'four_gate_premium_controls', 'configurations': [
        {'label': 'sparse-route-premium1pct', 'parameters': sparse},
        {'label': 'deep-route-premium1pct', 'parameters': deep}],
        'reason': '状态分工统一使用1%限价溢价，先建立相同执行参数的两条原策略对照；已完成相同配置复用，原件保持',
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1}}
    configurations = []
    for name, route in (('high-return', bull), ('sparse-acf', sparse), ('deep-range', deep)):
        configurations.append({'label': f'identical-routes-{name}', 'parameters': {
            'bull': route, 'bear': route, 'regime_window': 20,
            'regime_threshold': 0., 'exit_on_regime_change': False},
            'equivalence_original_parameters': route})
    for name, route in (('sparse-acf', sparse), ('deep-range', deep)):
        for threshold in (-.02, 0., .02):
            for hold in (4, 6, 9):
                for switch_exit in (False, True):
                    configurations.append({'label': f'{name}-threshold{threshold}-hold{hold}-exit{switch_exit}',
                        'parameters': {'bull': bull, 'bear': {**route, 'max_hold': hold},
                            'regime_window': 20, 'regime_threshold': threshold,
                            'exit_on_regime_change': switch_exit}})
    plan = {'name': 'four_gate_adaptive_1', 'date': '2026-10-08',
        'hypothesis': '长期低位、无相关性过滤的高收益路线在负动量时可能反复持有下跌；负动量状态改用相关性过滤或更深短窗口反转，可能保留上涨段收益并减少亏损年度损失。该假设有单一动量过滤失败的反证，需要真实评价。',
        'causal_definition': 'T日momentum20>=阈值选bull，否则bear；仅flat时决定入场路线并锁定至退出；可选信号状态改变时退出。不得读取未来基准年度收益或按历史年份分路。',
        'controls': '先比较两路线相同的三个控制与相同参数原策略完整账户，核对逐日现金/数量/净值及真实成交经济字段；随后比较无状态退出与状态退出，以及两类负动量路线',
        'falsification': '全部四目标同时核验；不因费用降低或单年改善就宣布成功；状态联合退化、频率不足或负基准年份亏损均作为必要反证',
        'source_sha256': implementation_sha256(FILES, source_root=SOURCE),
        'source_files': list(FILES), 'synthetic_precheck': '独立相同路线等价、未来隔离、入场路线锁定、切换退出、14个非法参数拒绝均PASS；完整账户控制仍须验证',
        'data_scope': '510500.SH原开发池及同标的最小必要预热；现有DFLS权限和已安装依赖；不改平台',
        'selection_history': '已见完整开发池及旧378配置、新ACF对照正在执行；本机制设计依据已发布亏损诊断，属于同池开发而非样本外',
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1, 'seed': 13},
        'configurations': configurations,
        'budget_note': '39个事前对照，结果决定是否有依据扩边；首个达标或次数耗尽不独立构成充分性'}
    assert len(configurations) == 39
    experiment = ExperimentRef('S013', 'EX004_20261007')
    for filename, value in (('four_gate_premium_controls_plan.json', control),
                            ('four_gate_adaptive_1_plan.json', plan)):
        save(filename, value, directory=PROTOCOLS)
        ref = publish_evidence(context(4), MaterialEvidenceWrite(experiment,
            value['name'].replace('_', '-') + '-plan', (PROTOCOLS / filename).read_bytes(),
            'application/json', 'json'))
        save(filename.replace('.json', '_reference.json'), ref.to_dict(), directory=PROTOCOLS)
        print(json.dumps({'reference': ref.to_dict(), 'configurations': len(value['configurations'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
