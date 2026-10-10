"""Fix eight unscreened joint points before any new account evaluation."""
from copy import deepcopy
from math import isclose
import numpy as np
from strategy_runtime import StrategyCandidate
from common import ROOT, FROZEN_SOURCE, PROTOCOLS, RUNS, context, read, write, fingerprint, material, DEPENDENCIES


def payload():
    return read(ROOT/'strategies/S007/versions/v1.json')['strategy_payload']


def candidate(identifier='C9000', parameters=None):
    value = deepcopy(payload())
    if parameters is not None:
        value['parameters'] = parameters
    return StrategyCandidate('S007', identifier, value, source_root=FROZEN_SOURCE)


def coordinates(score):
    w = score['base_weights']
    risk = w['risk_shibor_on_change_5d'] + w['price_intraday_range']
    opportunity = w['risk_global_spx_return'] + w['risk_chinext_turnover_z20']
    return {'risk_context_total': risk,
            'opportunity_share_nonrisk': opportunity / (1-risk),
            'opp_spx_fraction': w['risk_global_spx_return'] / opportunity,
            'confirm_share_fraction': score['confirmation_weights']['micro_share_change_5d_lag1'],
            'risk_shibor_fraction': w['risk_shibor_on_change_5d'] / risk,
            **{key: score[key] for key in ('entry_threshold', 'exit_threshold', 'confirmation_threshold')}}


def weights(value):
    risk = value['risk_context_total']
    opportunity = (1-risk) * value['opportunity_share_nonrisk']
    return {
        'price_close_vwap_deviation': (1-risk)*(1-value['opportunity_share_nonrisk']),
        'price_intraday_range': risk*(1-value['risk_shibor_fraction']),
        'risk_chinext_turnover_z20': opportunity*(1-value['opp_spx_fraction']),
        'risk_global_spx_return': opportunity*value['opp_spx_fraction'],
        'risk_shibor_on_change_5d': risk*value['risk_shibor_fraction'],
    }


def main():
    assert not (PROTOCOLS/'plan.json').exists()
    parameters = deepcopy(payload()['parameters'])
    score = parameters['rule']['score']
    center = coordinates(score)
    assert all(isclose(weights(center)[k], v, abs_tol=1e-15) for k, v in score['base_weights'].items())
    scales = dict(zip(center, (.0125, .015, .025, .025, .025, .01, .01, .01), strict=True))
    bounds = {'risk_context_total': [.10, .35], 'opportunity_share_nonrisk': [.50, .80],
              'opp_spx_fraction': [.25, .75], 'confirm_share_fraction': [.25, .75],
              'risk_shibor_fraction': [.25, .75], 'entry_threshold': [-.5, .5],
              'exit_threshold': [-.5, .5], 'confirmation_threshold': [-.5, .5]}
    rng = np.random.default_rng(13)
    vectors = []
    while len(vectors) < 8:
        vector = tuple(int(v) for v in rng.choice((-1, 1), len(center)))
        reverse = tuple(-v for v in vector)
        if vector not in vectors and reverse not in vectors:
            vectors += [vector, reverse]
    research = context(4)
    identity = research.runtime.identify(candidate(), dependencies=DEPENDENCIES)
    cases = []
    for index, vector in enumerate(vectors):
        values = {k: center[k]+s*scales[k] for k, s in zip(center, vector, strict=True)}
        assert all(bounds[k][0] <= v <= bounds[k][1] for k, v in values.items())
        assert values['exit_threshold'] < values['entry_threshold']
        child = deepcopy(parameters)
        target = child['rule']['score']
        target['base_weights'] = weights(values)
        fraction = values['confirm_share_fraction']
        target['confirmation_weights'] = {'micro_share_change_5d_lag1': fraction,
                                         'tsfresh__log_volume_change__mean__lb20': 1-fraction}
        target.update({k: values[k] for k in ('entry_threshold', 'exit_threshold', 'confirmation_threshold')})
        assert max(target['base_weights'].values()) <= .35
        assert isclose(sum(target['base_weights'].values()), 1., abs_tol=1e-15)
        assert isclose(sum(target['confirmation_weights'].values()), 1., abs_tol=1e-15)
        identifier = f'C{9001+index}'
        child_identity = research.runtime.identify(candidate(identifier, child), dependencies=DEPENDENCIES)
        assert child_identity.source_sha256 == identity.source_sha256
        cases.append({'candidate_id': identifier, 'index': index, 'coordinates': values,
                      'sign_vector': vector, 'parameters': child,
                      'content_sha256': child_identity.content_sha256,
                      'source_sha256': child_identity.source_sha256})
    source_paths = [ROOT/'strategies/S007/versions/v1.json',
                    ROOT/'strategies/S007/releases/v1/runtime_binding.json',
                    ROOT/'strategies/S007/releases/v1/release_manifest.json',
                    ROOT/'experiments/S007/20260915_S007_EX31/candidate_payload.json',
                    ROOT/'experiments/S007/20260915_S007_EX27/run_experiment.py',
                    ROOT/'research/S013/experiments/EX008_20261010/protocols/plan.json']
    source_paths += [candidate().source_root/x for x in payload()['runtime']['source_files']]
    plan = {'version': 'S007-four-diagnostics-v1', 'declared_before_new_account_evaluations': True,
        'authorization': {'human_scope': 'S007-v1与S013-C2132四维诊断补证；用户批准后转主会话执行，后明确在当前分支执行',
                          'relay_thread': '01a1241b-479e-7e32-a7cf-074970a434b9',
                          'current_branch': 'codex/s007-v1-robustness',
                          'excluded': ['新增截止日或封存样本', '新增经济门', '综合评分或总体赢家',
                                       '统计或互补性补充研究', '冻结部署PTE生产', '合并tag推送', '平台修改']},
        'center': {'candidate_id': 'S007-C9000', 'original_candidate_id': 'S007-C001',
                   'interpretation': '当前C+4位公共契约下的复算别名，已认证S007-v1冻结实现与原参数；不登记、不改原候选或运行身份',
                   'source_sha256': identity.source_sha256, 'content_sha256': identity.content_sha256,
                   'parameters': parameters, 'coordinates': center},
        'parameter_design': {'seed': 13, 'count': 8, 'direction_pairs': 4,
            'coordinate_order': list(center), 'scales': scales, 'bounds': bounds,
            'weights_basis': 'EX27显式分组权重映射；五个坐标沿用EX28历史域，每坐标扰动历史域宽度5%',
            'threshold_basis': '三个冻结数值阈值各±0.01，即归一化分数理论宽度1%；不重估发现期分位阈值',
            'legality': '事前按合法域、权重总和、单权重<=0.35、exit<entry校验全部点；无收益筛选',
            'failures': '经济未达标点保留；技术失败单列，不填零，不换点，不改尺度',
            's013_comparability': '双方种子13与8点相同，参数结构/维数/尺度不同，不能解释为同等强度压力',
            'fixed': ['标的', '方向', '归一化252/20', '执行规则', '价格角色', '资本', '成本', '日期', '特征及方向'],
            'quantile': 'LINEAR',
            'return_degradation': 'max(0, center_net_cagr - Q10(neighborhood_net_cagr))',
            'drawdown_worsening': 'max(0, Q90(neighborhood_drawdown_magnitude) - center_drawdown_magnitude)'},
        'account': {'symbol': '588080.SH', 'start': '2021-01-05', 'cutoff': '2026-09-02',
                    'feature_start': '2021-01-04', 'cash': 100000, 'lot': 100,
                    'signal_prices': 'HFQ/immutable feature seed', 'account_prices': 'UNADJUSTED',
                    'entry': 'LIMIT previous_close*1.2 floor tick .001',
                    'exit': 'LIMIT previous_close*.8 nearest_half_up; marketable_limit_at_open',
                    'benchmark': 'NextOpenBuyHold(100)', 'costs': {'baseline': .001, 'stress': .002},
                    'stress_method': 'FULL account rerun; affordable quantity responds to fees/cash, not fixed-quantity rededuction'},
        'profit_concentration': 'top ceil(10% * positive closed cycle count) CASH net profit / all positive closed cycle CASH net profit',
        'time_stability': {'window': 126, 'step': 21, 'quantile': 'LINEAR Q10',
                           'formula': 'own[start+126]/own[start] - own_BH[start+126]/own_BH[start]',
                           'initial_cash_prefix': True},
        'center_precondition': 'Authenticate source/input/execution/metrics; reproduce both original centers before interpreting new results',
        'sample_limits': 'Both original development pools already used in selection; different instruments/capital/windows/benchmarks/environments; no unseen validation',
        'resources': {'workers': 4, 'per_account_workers': 1, 'native_threads': 1},
        'sources': [fingerprint(p) for p in source_paths], 'cases': cases}
    write(PROTOCOLS/'plan.json', plan)
    reference = material('four-diagnostics-prospective-plan', PROTOCOLS/'plan.json')
    write(PROTOCOLS/'plan_reference.json', reference.to_dict())
    write(RUNS/'declaration.json', {'plan': reference.to_dict(), 'cases': len(cases)})
    print({'plan': reference.to_dict(), 'case_count': len(cases)}, flush=True)


if __name__ == '__main__':
    main()
