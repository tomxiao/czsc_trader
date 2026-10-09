"""Publish a prospective 79-center protocol before any new account evaluation."""
from copy import deepcopy
from hashlib import sha256
from dataclasses import replace, asdict
import json
import numpy as np
from strategy_runtime import StrategyCandidate
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from strategy_evaluator import SelfCheckProtocol, QuantileMethod, ComparisonPolicy, MetricBinSpec, ResearchMetric, BinRounding, ComparisonVariant, ParetoBasis, MissingEvidencePolicy
from czsc_trader.application import load_candidate
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from common import PROTOCOLS, RUNS, ROOT, d, context, centers, cache_read, center_cache, read, write, reference, material

def main():
    assert not (PROTOCOLS/'plan.json').exists()
    research = context(4)
    entries = centers()
    assert len(entries) == 79
    protocol = SelfCheckProtocol('S013-stage4-complete-v2', 'full', 'baseline', 'stress_20bp_per_side',
        126, 21, QuantileMethod.LINEAR, 8, 20, 2000, 20, 13, 1e-6, 10)
    metrics = (ResearchMetric.NET_ANNUAL_RETURN, ResearchMetric.DRAWDOWN_MAGNITUDE,
        ResearchMetric.PARAMETER_RETURN_DEGRADATION, ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION,
        ResearchMetric.ROLLING_EXCESS_Q10, ResearchMetric.STRESS_ANNUAL_LOSS, ResearchMetric.PROFIT_CONCENTRATION)
    bins = tuple(MetricBinSpec(m, .01 if m is ResearchMetric.PROFIT_CONCENTRATION else .001,
        0., BinRounding.NEAREST_HALF_EVEN) for m in metrics)
    variants = tuple(ComparisonVariant(name, tuple(replace(b, resolution=b.resolution*scale) for b in bins))
        for name, scale in (('half-resolution', .5), ('double-resolution', 2.)))
    variants += tuple(ComparisonVariant(f'adjacent-swap-{i}', bins, i) for i in range(6))
    policy = ComparisonPolicy('S013-stage4-seven-v2', bins, ParetoBasis.RAW,
        MissingEvidencePolicy.REQUIRE_COMPLETE, variants)
    base_deltas = [('bull.range_window', 15), ('bear.range_window', 10), ('bull.entry', .025),
        ('bear.entry', .002), ('bull.exit', .025), ('bear.exit', .002), ('bull.max_hold', 1),
        ('bear.max_hold', 1), ('bear.acf_min', .025), ('regime_window', 2), ('regime_threshold', .0025)]
    cases, authentication, standard = [], [], []
    number = 4000
    for entry in entries:
        loaded = load_candidate(research.repository, entry.identity.key)
        cached, result = cache_read(center_cache(loaded.candidate_id))
        identity = research.runtime.identify(loaded, dependencies=cached.dependencies)
        assert identity.content_sha256 == entry.identity.content_sha256
        assert research.runtime.identify(cached.strategy, dependencies=cached.dependencies).content_sha256 == identity.content_sha256
        ref = entry.evaluations[0].evidence
        original = read(ref.resolve(ROOT))
        validate_evaluation_evidence(original)
        assert original['result_hash'] == result.result_hash and original['request_hash'] == result.request_hash
        baseline = next(x for x in result.runs if x.scenario_id == 'baseline')
        standard.append((baseline.observation.net_cagr, loaded.candidate_id))
        authentication.append({'candidate': entry.identity.to_dict(), 'cache': center_cache(loaded.candidate_id).relative_to(ROOT).as_posix(),
            'source_sha256': identity.source_sha256, 'result_hash': result.result_hash, 'request_hash': result.request_hash,
            'formal_account': ref.to_dict(), 'data_identity': result.data_identity,
            'dependencies': [asdict(x) for x in cached.dependencies]})
        params = json.loads(json.dumps(dict(loaded.payload['parameters']), default=dict))
        deltas = base_deltas.copy()
        if params['bull']['acf_min'] is not None:
            deltas.append(('bull.acf_min', .025))
        for key in ('confirmation', 'opportunity_confirmation'):
            if key in params and params[key]['enabled']:
                deltas.append((key+'.threshold', .01))
        rng = np.random.default_rng(13)
        signs = []
        while len(signs) < 8:
            v = tuple(int(x) for x in rng.choice((-1, 1), len(deltas)))
            reverse = tuple(-x for x in v)
            if v not in signs and reverse not in signs:
                signs += [v, reverse]
        for index, vector in enumerate(signs):
            perturbed = deepcopy(params)
            changes = {}
            for (path, delta), sign in zip(deltas, vector, strict=True):
                parts = path.split('.')
                target = perturbed[parts[0]] if len(parts) == 2 else perturbed
                key = parts[-1]
                before = target[key]
                after = before + sign*delta
                if isinstance(before, float):
                    after = round(after, 10)
                target[key] = after
                changes[path] = {'before': before, 'after': after}
            payload = json.loads(json.dumps(dict(loaded.payload), default=dict))
            payload['parameters'] = perturbed
            child = StrategyCandidate('S013', f'C{number:04}', payload, source_root=loaded.source_root)
            child_identity = research.runtime.identify(child, dependencies=cached.dependencies)
            assert child_identity.source_sha256 == identity.source_sha256
            cases.append({'kind': 'PARAMETERS', 'candidate_id': child.candidate_id, 'parent': entry.identity.to_dict(),
                'parent_source_sha256': identity.source_sha256, 'child_source_sha256': child_identity.source_sha256,
                'child_content_sha256': child_identity.content_sha256, 'parameters': perturbed, 'changes': changes,
                'index': index, 'deltas': dict(deltas), 'sign_vector': list(vector), 'parent_account': ref.to_dict()})
            number += 1
        cases.append({'kind': 'STRESS', 'candidate_id': loaded.candidate_id, 'parent': entry.identity.to_dict(),
            'parent_source_sha256': identity.source_sha256, 'child_source_sha256': identity.source_sha256,
            'child_content_sha256': identity.content_sha256, 'parameters': params})
    assert len(cases) == 711 and len({x['data_identity'] for x in authentication}) == 1
    auth = {'date':'2026-10-10', 'source':'本主会话真实用户指令', 'user_message':'同意，请继续执行阶段四',
        'branch':'codex/s013-research-continuation', 'scope':'CANDIDATES/6全部79个交接身份的阶段四自检和比较',
        'excluded':['阶段五及冻结','平台修改','其他批次数据及结果','外部数据或依赖','生产','合并/tag/推送']}
    write(PROTOCOLS/'authorization.json', auth)
    plan = {'version':'S013-stage4-complete-v2', 'declared_before_evaluation':True,
        'source_candidates':reference('CANDIDATES',6).to_dict(), 'source_mandate':reference('MANDATE',5).to_dict(),
        'authorization':material('stage4-authorization', PROTOCOLS/'authorization.json').to_dict(),
        'protocol':protocol.to_dict(), 'comparison_policy':policy.to_dict(), 'centers':[e.identity.to_dict() for e in entries],
        'base_deltas':dict(base_deltas), 'additional_active_deltas':{'bull.acf_min':.025,'confirmation.threshold':.01,'opportunity_confirmation.threshold':.01},
        'design':'每中心独立8个联合点，4组正反向、种子13；活跃确认阈值纳入，实际维度由case记录。父子源码严格一致，不借同经济路径中心的邻域。有限局部诊断不代表完整参数空间或单参数归因。',
        'fixed_parameters':'limit_premium维持1%；所有cooldown为0；结构开关/方向/配置/权重/确认窗口固定；None过滤项不启用；stable_range的整数状态确认与regime_band=0保持原设置。确认窗口40..120合法域与RAW固定40不对称，故未覆盖窗口扰动。',
        'cost_scenarios':{'stress_20bp_per_side':.002,'stress_30bp_per_side':.003},
        'resources':{'max_workers':4,'native_threads':1,'request_workers':1,'seed':13},
        'family_selected':max(standard)[1], 'family_raw_trial_count':1536,
        'trial_count_basis':'已见历史510次尝试(含16UNKNOWN)+旧阶段四80扰动+EX005的89配置+EX006的183配置+EX007的42配置+本次632扰动=1536。包含同内容控制与源码迁移重复，非1536个独立发现；费用场景/技术对账复算不作为新配置。',
        'limitations':['族收益矩阵仅包含79个交接后达标中心，不包含所有历史成功/失败/未知路径或本次632扰动，PBO/有效DSR条件于有偏子集。原始DSR增加试验数也不能弥补缺失的Sharpe分布。',
            'selected事前按上阶段标准最高CAGR指定；PBO内部Sharpe选择，与七项最终政策不同。',
            '原2020-2026开发池反复使用，无独立保留验证。统计区间不是未来收益区间或成功概率。'],
        'diagnostic_boundary':'原四门决定标准资格；扰动、成本压力、集中度和统计只诊断，不新增门槛。', 'cases':cases}
    write(PROTOCOLS/'plan.json', plan)
    plan_hash = sha256((PROTOCOLS/'plan.json').read_bytes()).hexdigest()
    write(RUNS/'center_authentication.json', {'status':'PASS','centers':authentication})
    lineages = {}
    for case in cases:
        if case['kind'] != 'PARAMETERS':
            continue
        parent = d.CandidateIdentityRef.from_dict(case['parent'])
        ref = EvidenceRef.from_dict(case['parent_account'])
        item = CandidateDerivation(parent.key, parent.content_sha256, CandidateKey('S013',case['candidate_id']),
            case['child_content_sha256'], CandidateDerivationKind.PARAMETERS, case['changes'], plan_hash,
            CandidateEvidence(ref.repository_path,ref.sha256))
        lineages[case['candidate_id']] = item.to_dict()
    write(RUNS/'lineages.json',lineages)
    refs = {name:material('stage4-'+name,path).to_dict() for name,path in
        (('plan',PROTOCOLS/'plan.json'),('center-authentication',RUNS/'center_authentication.json'),('lineages',RUNS/'lineages.json'))}
    write(PROTOCOLS/'plan_references.json',refs)
    print({'published':True,'centers':79,'perturbations':632,'stress_requests':79,'selected':plan['family_selected'],'plan_hash':plan_hash},flush=True)

if __name__ == '__main__':
    main()
