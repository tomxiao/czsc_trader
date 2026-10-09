"""Publish authorization, lossless mandate representation and design before runs."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import numpy as np
from strategy_evaluator import (
    SelfCheckProtocol, QuantileMethod, ComparisonPolicy, MetricBinSpec,
    ResearchMetric, BinRounding, ComparisonVariant, ParetoBasis, MissingEvidencePolicy,
)
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from czsc_trader.application import assemble_delivery, validate_delivery, load_candidate
from phase4_common import (
    PLANS, CACHE, DEPENDENCIES, context, save, source, reference, material, centers, candidate, d,
)


def main():
    research = context(4)
    for stage, revision in (('CANDIDATES', 3), ('MANDATE', 4)):
        checked = validate_delivery(research.repository, reference(stage, revision))
        assert checked.status is d.ValidationStatus.PASS, checked.to_dict()
    save('authorization.json', {
        'date': '2026-10-08', 'source': '本主会话真实用户指令',
        'user_message': '批准进入阶段四', 'branch': 'codex/s013-research',
        'scope': '全部10个交接候选、S013/510500.SH原开发池、现有数据和依赖、RSCH五项自检与比较',
        'candidate_selection_and_freeze': '尚未授权，阶段五待用户选择精确候选',
    }, directory=PLANS)
    authorization = material(research, 'stage-four-authorization', PLANS / 'authorization.json')
    old = source('MANDATE', 4)
    items = tuple(replace(i, requirement=None) if i.item_id == 'drawdown_interpretation' else i
                  for i in old.payload.items)
    confirmed = next(i for i in items if i.item_id == 'trade_frequency').confirmation
    items += (d.MandateItem('frequency_window_days', d.MandateItemKind.EXECUTION,
        '用户已确认平均频率按总闭合交易数×60÷开发池实际交易日数计算；精确统计窗口为60交易日。',
        confirmed, d.NumericRequirement('frequency_window_days', 'sessions', 60., 60.)),)
    report = old.report + '\n\n## 阶段四表示修订（2026-10-08）\n\n'
    report += ('经济目标、年度口径、费用、数据与执行约束全部保持。现有SE类型的回撤指标没有年度维度；'
        '逐自然年回撤约束保留原文字及用户确认，由连续账户逐年核验，不映射为全窗回撤硬门。'
        '负BuyHold年份严格正收益亦以年度账户证据核验。全窗回撤仍是标准比较指标。'
        '增加已确认60交易日的精确数值表示，以供频率契约校验；无新增目标或用户确认。'
        '阶段四比较仅对可表达的整体年化收益、全样本频率做SE类型目标绑定，并同时关联完整四门年度核验。\n')
    mandate = assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch, d.DeliveryStage.MANDATE, 5, (reference('MANDATE', 4),)),
        replace(old, payload=d.ResearchMandate(items), report=report,
                evidence=old.evidence + (authorization,)))
    checked = validate_delivery(research.repository, mandate.reference)
    assert checked.status is d.ValidationStatus.PASS, checked.to_dict()
    save('mandate_reference.json', mandate.reference.to_dict())
    save('mandate_validation.json', checked.to_dict())
    protocol = SelfCheckProtocol('S013-stage4-v1', 'full', 'baseline', 'stress_20bp_per_side',
        126, 21, QuantileMethod.LINEAR, 8, 20, 2000, 20, 13, 1e-6, 10)
    metrics = (ResearchMetric.NET_ANNUAL_RETURN, ResearchMetric.DRAWDOWN_MAGNITUDE,
        ResearchMetric.PARAMETER_RETURN_DEGRADATION, ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION,
        ResearchMetric.ROLLING_EXCESS_Q10, ResearchMetric.STRESS_ANNUAL_LOSS,
        ResearchMetric.PROFIT_CONCENTRATION)
    bins = tuple(MetricBinSpec(m, .01 if m is ResearchMetric.PROFIT_CONCENTRATION else .001,
                               0., BinRounding.NEAREST_HALF_EVEN) for m in metrics)
    variants = tuple(ComparisonVariant(name, tuple(replace(b, resolution=b.resolution*scale) for b in bins))
                     for name, scale in (('half-resolution', .5), ('double-resolution', 2.)))
    variants += tuple(ComparisonVariant(f'adjacent-swap-{i}', bins, i) for i in range(6))
    policy = ComparisonPolicy('S013-stage4-seven-v1', bins, ParetoBasis.RAW,
                              MissingEvidencePolicy.REQUIRE_COMPLETE, variants)
    deltas = [('bull.range_window', 15), ('bear.range_window', 10),
        ('bull.entry', .025), ('bear.entry', .002), ('bull.exit', .025), ('bear.exit', .002),
        ('bull.max_hold', 1), ('bear.max_hold', 1), ('bear.acf_min', .025),
        ('regime_window', 2), ('regime_threshold', .0025)]
    rng = np.random.default_rng(13)
    signs = []
    while len(signs) < 8:
        vector = tuple(int(x) for x in rng.choice((-1, 1), len(deltas)))
        reverse = tuple(-x for x in vector)
        if vector not in signs and reverse not in signs:
            signs += [vector, reverse]
    entries = centers()
    for entry in entries:
        loaded = load_candidate(research.repository, entry.identity.key)
        assert research.runtime.identify(loaded, dependencies=DEPENDENCIES).content_sha256 == entry.identity.content_sha256
    plan = {
        'version': 'S013-stage4-v1', 'declared_before_evaluation': True,
        'source_candidates': reference('CANDIDATES', 3).to_dict(),
        'source_mandate': mandate.reference.to_dict(), 'authorization': authorization.to_dict(),
        'protocol': protocol.to_dict(), 'comparison_policy': policy.to_dict(),
        'centers': [e.identity.to_dict() for e in entries],
        'perturbation_deltas': dict(deltas), 'sign_vectors': signs,
        'design': '每中心8个等权联合扰动，4组正反向成对种子13样本。源码、执行规则和费用固定；同时变动11项活跃数值参数。不能据此辨识单参数因果或声称完整邻域覆盖。',
        'cost_scenarios': {'stress_20bp_per_side': .002, 'stress_30bp_per_side': .003},
        'resources': {'max_workers': 4, 'native_threads': 1, 'request_workers': 1},
        'family_matrix': 'CANDIDATES/3全部17个正式保留成员；选择后有偏子集，缺少其余477个成功配置及16个UNKNOWN收益路径。',
        'family_raw_trial_count': 590,
        'trial_count_basis': '阶段三510次尝试（494成功+16UNKNOWN）加本次80个预声明参数扰动，保守包括未知尝试；成本场景为共同诊断而非新配置。',
        'family_selected': 'C0494',
        'selection': '族统计预指定阶段三最高CAGR成员C0494，PBO内部按Sharpe分块选择，与最终七项政策不同。',
        'diagnostic_boundary': '所有自检、压力下资格及邻域四门通过率仅诊断；不新增用户经济门或自动淘汰。原始标准中心四门独立核验。',
        'holdout': '无；原开发池重复使用。Bootstrap与PBO不提供独立样本外验证或未来成功概率。',
        'cases': [],
    }
    number = 511
    for entry in entries:
        loaded = load_candidate(research.repository, entry.identity.key)
        original = dict(loaded.payload['parameters'])
        original = __import__('json').loads(__import__('json').dumps(original, default=dict))
        for index, vector in enumerate(signs):
            params = deepcopy(original)
            changes = {}
            for (path, delta), sign in zip(deltas, vector, strict=True):
                parts = path.split('.')
                obj = params[parts[0]] if len(parts) == 2 else params
                key = parts[-1]
                before = obj[key]
                after = before + sign * delta
                if isinstance(before, float):
                    after = round(after, 10)
                obj[key] = after
                changes[path] = {'before': before, 'after': after}
            child = candidate(number, params)
            identity = research.runtime.identify(child, dependencies=DEPENDENCIES)
            assert identity.source_sha256 == research.runtime.identify(loaded, dependencies=DEPENDENCIES).source_sha256
            for route in ('bull', 'bear'):
                assert params[route]['entry'] < params[route]['exit'] <= 1
            plan['cases'].append({'kind': 'PARAMETERS', 'number': number,
                'candidate_id': child.candidate_id, 'parent': entry.identity.to_dict(),
                'child_content_sha256': identity.content_sha256,
                'parameters': params, 'changes': changes, 'index': index,
                'parent_account': entry.evaluations[0].evidence.to_dict()})
            number += 1
        plan['cases'].append({'kind': 'STRESS', 'number': int(entry.identity.key.candidate_id[1:]),
            'candidate_id': entry.identity.key.candidate_id, 'parameters': original})
    save('plan.json', plan, directory=PLANS)
    plan_ref = material(research, 'stage-four-predeclared-plan', PLANS / 'plan.json')
    save('plan_reference.json', plan_ref.to_dict(), directory=PLANS)
    protocol_hash = sha256((PLANS/'plan.json').read_bytes()).hexdigest()
    lineages = {}
    for case in plan['cases']:
        if case['kind'] != 'PARAMETERS':
            continue
        parent = d.CandidateIdentityRef.from_dict(case['parent'])
        ref = __import__('czsc_trader.research_tools', fromlist=['EvidenceRef']).EvidenceRef.from_dict(case['parent_account'])
        lineage = CandidateDerivation(parent.key, parent.content_sha256,
            CandidateKey('S013', case['candidate_id']), case['child_content_sha256'],
            CandidateDerivationKind.PARAMETERS, case['changes'], protocol_hash,
            CandidateEvidence(ref.repository_path, ref.sha256))
        lineages[case['candidate_id']] = lineage.to_dict()
    save('lineages.json', lineages)
    material(research, 'stage-four-parameter-lineages', 'lineages.json')
    CACHE.mkdir(parents=True, exist_ok=True)
    print({'centers': len(entries), 'perturbations': 80, 'stress_requests': 10,
           'plan_sha256': protocol_hash, 'mandate': mandate.reference.to_dict()}, flush=True)


if __name__ == '__main__':
    main()
