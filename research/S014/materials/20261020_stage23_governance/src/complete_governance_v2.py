"""Publish successor governance for existing S014 evidence; never replay accounts."""
import argparse
import ast
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import socket

from dataflows import ProviderConfig
from strategy_runtime import StrategyCandidate, StrategyRuntime
from strategy_manager import (
    CandidateKey, CandidateEvidence, CandidateDerivation,
    DecisionAction, ResearchDecision, StageAdvanceSubject,
)
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, CandidateRegistrationRequest,
    assemble_delivery, validate_delivery, register_candidate, load_candidate,
    record_research_decision, create_research_context, publish_evidence,
    update_research_intent,
)
from czsc_trader.research_tools import (
    ResearchBatchRef, ExperimentRef, EvidenceRef, MaterialEvidenceWrite,
    DeliveryContent, DeliveryStatus, DeliveryDefinition, DeliveryReference,
    DeliveryStage, ValidationStatus, ComponentEntry, ComponentPanel,
    ExperimentDefinitionRef, ComponentTestResult, ComponentTestStatus,
    CandidateEntry, CandidateIdentityRef, CandidateSet, EvaluationEvidenceRef,
    SearchSummary, FactValue, FactStatus,
)

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / 'research/registrations/S014/family.json'
BATCH = ResearchBatchRef('S014')
EXPERIMENT = ExperimentRef('S014', 'EX052_20261020')


def blocked(*args, **kwargs):
    raise RuntimeError('Governance uses existing local evidence; network forbidden')


socket.socket.connect = blocked
socket.create_connection = blocked


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True).encode()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')


def refs(value):
    found = []
    if isinstance(value, dict):
        if value.get('type') == 'EvidenceRef':
            found.append(EvidenceRef.from_dict(value))
        for item in value.values():
            found.extend(refs(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(refs(item))
    return tuple(dict.fromkeys(found))


def baseline_check():
    baseline = read(OUT / 'baseline_integrity.json')
    for relative, expected in baseline['protected_files'].items():
        assert digest(ROOT / relative) == expected, relative
    return baseline


def publication_context():
    repo = RepositoryContext.discover(ROOT)
    return repo, create_research_context(repo, BATCH, providers=ProviderConfig(bindings={}))


def publish_file(ctx, path):
    media = {'.py': 'text/x-python', '.json': 'application/json', '.md': 'text/markdown'}
    relative = path.relative_to(ROOT).as_posix()
    name = 'stage23-' + path.stem[:45] + '-' + sha256(relative.encode()).hexdigest()[:10]
    ref = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, name,
        path.read_bytes(), media[path.suffix], path.suffix[1:]))
    assert ref.resolve(ROOT).read_bytes() == path.read_bytes()
    return ref


def candidate_from_spec(spec):
    return StrategyCandidate('S014', spec['candidate_id'], read(ROOT / spec['payload_path']),
                             ROOT / spec['source_root'])


def registration_specs():
    records = read(OUT / 'review/candidate_registration_plan.json')['records']
    hypotheses = {
        'C9461': '原S5宽限、正P急涨与NET1ATR保护加自己的实际严格净亏后跳过一次机会，固定原计划槽。',
        'C9502': '在C9461基础上，首次正P急涨按实际持仓年龄分流：age0原退出，age>=1继续持有，其他保护不变。',
        'C9521': '在C9502基础上，仅在首次age>=1急涨时用此前MA20上升且昨收>=此前MA20授予一次持有许可。',
    }
    judgments = {
        'C9461': '比较对照：原年度收益6/7、回撤7/7及频率通过，但2026收益79.1981%未达原196.4644%要求，不交接阶段四。',
        'C9502': '比较对照：原年度收益6/7、回撤7/7及频率通过，2026达标而2025仅17.9603%未达40.1879%，不交接阶段四。',
        'C9521': '原年度收益7/7、严格回撤7/7、92闭合/1642*60=3.3617539586全部达标，唯一建议交接阶段四；2021机会代价和较低终值、全域已见保留。',
    }
    result = []
    for record in records:
        spec = deepcopy(record)
        spec['candidate_id'] = record['candidate']['candidate_id']
        spec['hypothesis'] = hypotheses[spec['candidate_id']]
        spec['judgment'] = judgments[spec['candidate_id']]
        assert record['dependencies'] == []
        result.append(spec)
    return result


def prepare():
    """Authenticate and serialize proposed typed deliveries before registration."""
    baseline = baseline_check()
    assert sha256(canonical(read(FAMILY)['research_intent'])).hexdigest() == baseline['prior_intent_sha256']
    assert not (OUT / 'prepared.json').exists()
    audit = read(OUT / 'review/component_governance_audit.json')
    proposed = read(OUT / 'review/proposed_components.json')['components']
    coverage = read(OUT / 'review/candidate_coverage_audit.json')
    specifications = registration_specs()
    assert [x['candidate_id'] for x in specifications] == ['C9461', 'C9502', 'C9521']
    for spec in specifications:
        candidate = candidate_from_spec(spec)
        identity = StrategyRuntime().identify(candidate, dependencies=())
        assert identity.content_sha256 == spec['content_sha256']
        assert identity.source_sha256 == spec['source_sha256']
        assert identity.dependency_sha256 == spec['dependency_sha256']
        account_ref = EvidenceRef.from_dict(spec['account_ref'])
        account = read(account_ref.resolve(ROOT))
        assert account['runs'][0]['identity']['content_sha256'] == identity.content_sha256
        assert account['runs'][0]['identity']['candidate']['candidate_id'] == spec['candidate_id']
        derivation = CandidateDerivation.from_dict(spec['derivation'])
        CandidateRegistrationRequest(candidate, ExperimentRef('S014', spec['experiment_id']), (account_ref,), (), derivation)
        parent = read(derivation.evidence.resolve(ROOT))
        assert parent['schema_version'] == 7
        assert all(run['identity']['candidate'] == derivation.parent.to_dict()
                   and run['identity']['content_sha256'] == derivation.parent_content_sha256 for run in parent['runs'])
        assert digest(ROOT / spec['derivation_protocol']['path']) == derivation.protocol_sha256
    assert len(list((ROOT / 'research/registrations/S014/candidates').glob('*.json'))) == 66
    registered_hashes = {read(p)['record']['content_sha256'] for p in (ROOT / 'research/registrations/S014/candidates').glob('*.json')}
    assert not registered_hashes.intersection(x['content_sha256'] for x in specifications)
    repo, ctx = publication_context()
    materials = [OUT / 'authorization.json', OUT / 'baseline_integrity.json',
                 OUT / 'stage2_report.md', OUT / 'stage3_report.md',
                 OUT / 'preparation_revision.json', *sorted((OUT / 'review').glob('*.json')),
                 *sorted((OUT / 'src').glob('*.py'))]
    published = {p.relative_to(ROOT).as_posix(): publish_file(ctx, p) for p in materials}
    prior_components = DeliveryContent.from_dict(read(ROOT / 'research/S014/assets/deliveries/COMPONENTS/22/delivery.json')['content'])
    prior_candidates = DeliveryContent.from_dict(read(ROOT / 'research/S014/assets/deliveries/CANDIDATES/13/delivery.json')['content'])
    assert len(prior_components.payload.components) == 28 and len(prior_candidates.payload.candidates) == 66
    assert [x.to_dict() for x in prior_components.payload.components] == audit['old_entries_exact_for_reuse']
    additions = []
    for index, spec in enumerate(proposed):
        evidence = refs([audit['necessary_formal_evidence'][ex] for ex in spec['necessary_test_experiments']])
        for ref in evidence:
            ref.resolve(ROOT)
        supported = index < 6
        positive_experiment = 'EX052' if supported else ('EX050' if index == 6 else 'EX051')
        protocol = EvidenceRef.from_dict(audit['necessary_formal_evidence'][positive_experiment]['predeclared_protocols'][0])
        tests = [ComponentTestResult(
            'conditional-role-evidence' if supported else 'fixed-action-negative-evidence',
            protocol.experiment.experiment_id,
            protocol, ComponentTestStatus.SUPPORTED if supported else ComponentTestStatus.INEFFECTIVE,
            spec['judgment'] + ' C9521 uses these bounded roles jointly; this is not independent alpha or proof of isolated contribution. Historical contrasts remain restricted to their exact original protocols.',
            evidence,
        )]
        negative_experiment = {0: 'EX043', 1: 'EX044', 2: 'EX048', 3: 'EX046',
                               4: 'EX050', 5: 'EX049', 6: 'EX050', 7: 'EX051'}[index]
        negative_protocol = EvidenceRef.from_dict(audit['necessary_formal_evidence'][negative_experiment]['predeclared_protocols'][0])
        tests.append(ComponentTestResult('counterevidence-and-limits',
            negative_protocol.experiment.experiment_id,
            negative_protocol, ComponentTestStatus.INEFFECTIVE,
            spec['strongest_counterevidence'] + ' Status describes this negative control/use, not a reversal of all component evidence.', evidence))
        horizon = {
            0: '每个实际持仓D检查原支撑条件；买入日宽限与其后保护、H10/预留优先级严格沿原代码。',
            1: '持仓D原正P急涨条件；实际退出次E执行，后继持有许可只在首次eligible SHOCK判断。',
            2: '每个实际持仓D原成本边界；不冻结或替换动态priorATR，次E真实执行。',
            3: '实际完成周期的严格扣费净损益，在随后原计划槽决定一次skip；未成交与未完成不造完成史。',
            4: '首次own eligible正P SHOCK当D；买入日age0与age>=1分流，许可latch至本实际周期退出。',
            5: '首次own SHOCK且age>=1的D0，仅用D0之前价格评估一次S1；其后不逐日重分类。',
            6: '首次own eligible SHOCK当D的形态上下文；固定形态处理已在完整账户失败。',
            7: '首次age>=1 SHOCK继续持有后，i>i0到本实际周期退出；固定原锚与仅1ATR分支的冻结波幅。',
        }[index]
        entrypoint = {5: 'prior_trend_permission', 6: 'state_at_D'}.get(index, 'history')
        definition_ref = EvidenceRef.from_dict(spec['definition_evidence'])
        source_tree = ast.parse(definition_ref.resolve(ROOT).read_text(encoding='utf-8'))
        assert entrypoint in {node.name for node in source_tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}, (spec['proposed_component_id'], entrypoint)
        additions.append(ComponentEntry(spec['proposed_component_id'],
            ExperimentDefinitionRef(definition_ref, entrypoint),
            spec['role'], spec['label'], horizon, spec['control'], spec['availability'],
            spec['price_basis'], spec['applicability'],
            spec['definition'] + ' ' + spec['judgment'] + ' Strong counterevidence: ' + spec['strongest_counterevidence'], tuple(tests)))
    material_refs = tuple(published.values())
    required_old_fact_ids = {fact_id for component in prior_components.payload.components
                             for test in component.tests for fact_id in test.fact_ids}
    inherited_facts = tuple(fact for fact in prior_components.facts if fact.fact_id in required_old_fact_ids)
    assert {fact.fact_id for fact in inherited_facts} == required_old_fact_ids
    facts = inherited_facts + tuple(FactValue('stage23-' + key, value, unit, FactStatus.AVAILABLE, material_refs) for key, value, unit in (
        ('inherited-component-definitions', 28, 'definitions'), ('new-decision-role-definitions', 8, 'definitions'),
        ('new-independent-alpha-claim', 0, 'alphas'), ('new-account-evaluations', 0, 'accounts')))
    component_content = DeliveryContent(ComponentPanel(prior_components.payload.components + tuple(additions),
        '承接原28定义与测试，补8个职责条目，其中6项仅支持特定机制/交互用途、2项保留负面结果；组件组合及全账户达标归阶段三，不宣称8项独立alpha。'),
        DeliveryStatus.COMPLETE, facts, (), report=(OUT / 'stage2_report.md').read_text(encoding='utf-8'), evidence=material_refs)
    entries = list(prior_candidates.payload.candidates)
    for spec in specifications:
        entries.append(CandidateEntry(CandidateIdentityRef(CandidateKey('S014', spec['candidate_id']), spec['content_sha256']),
            spec['hypothesis'], spec['judgment'], (EvaluationEvidenceRef(EvidenceRef.from_dict(spec['account_ref'])),)))
    all_diagnostic_refs = refs(coverage['diagnostic_actual_identity_inventory'])
    unique_content = set()
    for ref in all_diagnostic_refs:
        account = read(ref.resolve(ROOT))
        unique_content.add(account['runs'][0]['identity']['content_sha256'])
    negative_evidence = refs(audit['necessary_formal_evidence'])
    summary = SearchSummary('diagnostic-ex040-through-ex052-governance',
        '用户授权的顺序机制诊断和固定完整账户对照；含固定日期动作动机、退出/成本/暂停时钟消融、SHOCK状态及AGE与S1唯一后继。复用原评价，不新增搜索。',
        '同一600722.SH已见2020-01-02..2026-10-15开发域与原执行、费用、逐年目标；EX049只做事件组件0资金账户。',
        39, len(unique_content),
        '38成功/1失败，成功实际内容配置数单列且不称独立样本；全部原门仅C9521。继承66旧条目，补登记3原身份，handoff仅C9521。',
        tuple(coverage['boundary_and_coverage_gaps']) + (
            'unique_configurations仅计38成功账户实际content_sha256不同值；失败派发在39总数保留，无实际成功content不填造。',
            '38成功账户在保存的现金/股数/权益及成交投影中仅26组；同路径不证明源实现等价，fresh控制不重复登记。',
            '固定20/5均线、1ATR及语义0/1边界没有声明数值最优；不是全域搜索或数学Pareto穷尽。'),
        tuple(dict.fromkeys(material_refs + all_diagnostic_refs + negative_evidence)))
    candidate_content = DeliveryContent(CandidateSet(tuple(entries), (CandidateKey('S014', 'C9521'),),
        prior_candidates.payload.searches + (summary,),
        '阶段三收口：69条正式候选集合中C9521满足全部原目标并作为唯一建议阶段四交接；C9461/C9502为已登记对照，原66资格及历史结论保持。'),
        DeliveryStatus.COMPLETE, facts=tuple(FactValue(key, value, unit, FactStatus.AVAILABLE, material_refs) for key, value, unit in (
            ('formal-candidates-after-registration', 69, 'candidates'), ('original-goal-qualified-count', 1, 'candidates'),
            ('diagnostic-dispatches-reused', 39, 'accounts'), ('new-account-evaluations', 0, 'accounts'),
            ('stage4-executed', False, 'boolean'))), explanations=(), report=(OUT / 'stage3_report.md').read_text(encoding='utf-8'),
        evidence=tuple(dict.fromkeys(material_refs + negative_evidence)))
    write(OUT / 'prepared_components.json', component_content.to_dict())
    write(OUT / 'prepared_candidates.json', candidate_content.to_dict())
    write(OUT / 'prepared.json', {
        'status': 'PREPARED_TYPED_GOVERNANCE_NO_REGISTRATIONS_OR_DELIVERIES_YET',
        'component_definitions': 36, 'candidate_entries': 69, 'new_registrations': 3,
        'handoff': ['S014-C9521'], 'successful_content_configurations': len(unique_content),
        'material_evidence': {key: ref.to_dict() for key, ref in published.items()},
        'bindings': {p.relative_to(ROOT).as_posix(): digest(p) for p in materials + [OUT / 'prepared_components.json', OUT / 'prepared_candidates.json']},
    })
    print(json.dumps({'status': 'PREPARED', 'components': 36, 'candidate_entries': 69,
                      'successful_content_configurations': len(unique_content)}))


def complete():
    baseline = baseline_check()
    prepared = read(OUT / 'prepared.json')
    review = read(OUT / 'review/governance_prepublication_review.json')
    assert review['status'] == 'PASS' and not review['blocking_findings']
    for relative, expected in {**prepared['bindings'], **review['reviewed_hashes']}.items():
        assert digest(ROOT / relative) == expected, relative
    before = read(FAMILY)
    assert sha256(canonical(before['research_intent'])).hexdigest() == baseline['prior_intent_sha256']
    assert not (OUT / 'result.json').exists()
    assert not (ROOT / 'research/S014/deliveries/COMPONENTS/23').exists()
    assert not (ROOT / 'research/S014/deliveries/CANDIDATES/14').exists()
    assert len(list((ROOT / 'research/registrations/S014/candidates').glob('*.json'))) == 66
    repo, ctx = publication_context()
    component_content = DeliveryContent.from_dict(read(OUT / 'prepared_components.json'))
    candidate_content = DeliveryContent.from_dict(read(OUT / 'prepared_candidates.json'))
    review_ref = publish_file(ctx, OUT / 'review/governance_prepublication_review.json')
    component_content = DeliveryContent(component_content.payload, component_content.status,
        facts=component_content.facts, explanations=component_content.explanations,
        report=component_content.report, evidence=component_content.evidence + (review_ref,))
    components = assemble_delivery(repo, DeliveryDefinition(BATCH, DeliveryStage.COMPONENTS, 23,
        (DeliveryReference.from_dict(baseline['previous_components']),)), component_content)
    component_validation = validate_delivery(repo, components.reference)
    assert component_validation.status is ValidationStatus.PASS, component_validation
    write(OUT / 'component_delivery_result.json', {'receipt': components.to_dict(), 'validation': component_validation.to_dict()})
    public_receipt = ROOT / 'research/S014/deliveries/COMPONENTS/23/receipt.json'
    authorization = OUT / 'authorization.json'
    decision = record_research_decision(repo, ResearchDecision('S014-GOV-20261020-STAGE3', 'S014', DecisionAction.APPROVE,
        StageAdvanceSubject(CandidateEvidence(public_receipt.relative_to(ROOT).as_posix(), digest(public_receipt)), 'CANDIDATES'),
        CandidateEvidence(authorization.relative_to(ROOT).as_posix(), digest(authorization)),
        '用户当前明确要求补全阶段二、三治理并完成阶段三收口；该决定对本次新交付及收口生效，不倒签既有诊断，也不授权阶段四。'))
    write(OUT / 'stage3_authorization_decision.json', decision.to_dict())
    specifications = registration_specs()
    registrations = []
    for spec in specifications:
        candidate = candidate_from_spec(spec)
        derivation_spec = spec.get('derivation')
        derivation = None
        if derivation_spec is not None:
            derivation = CandidateDerivation.from_dict(derivation_spec)
        registration = register_candidate(repo, CandidateRegistrationRequest(candidate,
            ExperimentRef('S014', spec['experiment_id']), (EvidenceRef.from_dict(spec['account_ref']),), (), derivation))
        loaded = load_candidate(repo, CandidateKey('S014', spec['candidate_id']))
        identity = StrategyRuntime().identify(loaded, dependencies=())
        definition = StrategyRuntime().describe(loaded)
        assert identity.content_sha256 == registration.content_sha256 == spec['content_sha256']
        assert identity.source_sha256 == registration.source_sha256 == spec['source_sha256']
        assert identity.dependency_sha256 == registration.dependency_sha256 == spec['dependency_sha256']
        assert definition.tradable_symbol == '600722.SH'
        registrations.append({'registration': registration.to_dict(), 'identity': asdict(identity),
                              'loadability': 'PASS', 'source': str(loaded.source_root.relative_to(ROOT)).replace('\\', '/')})
    write(OUT / 'candidate_registrations.json', {'status': 'PASS_3_REGISTERED_AND_LOADED', 'registrations': registrations})
    registration_ref = publish_file(ctx, OUT / 'candidate_registrations.json')
    decision_material_ref = publish_file(ctx, OUT / 'stage3_authorization_decision.json')
    candidate_content = DeliveryContent(candidate_content.payload, candidate_content.status,
        facts=candidate_content.facts, explanations=candidate_content.explanations, report=candidate_content.report,
        evidence=candidate_content.evidence + (review_ref, registration_ref, decision_material_ref))
    candidates = assemble_delivery(repo, DeliveryDefinition(BATCH, DeliveryStage.CANDIDATES, 14,
        (DeliveryReference.from_dict(baseline['previous_candidates']), components.reference)), candidate_content)
    candidate_validation = validate_delivery(repo, candidates.reference)
    assert candidate_validation.status is ValidationStatus.PASS, candidate_validation
    for stage, filename in [('COMPONENTS', 'stage2_report.md'), ('CANDIDATES', 'stage3_report.md')]:
        revision = 23 if stage == 'COMPONENTS' else 14
        for prefix in ('deliveries', 'assets/deliveries'):
            assert (ROOT / f'research/S014/{prefix}/{stage}/{revision}/report.md').read_bytes() == (OUT / filename).read_bytes()
    intent = deepcopy(before['research_intent'])
    intent.update(stage='阶段三已完成正式收口，等待用户决定是否进入阶段四',
        components=components.reference.to_dict(), candidates=candidates.reference.to_dict(),
        component_definitions=36, strategy_accounts=69, all_targets_pass_count=1,
        phase_two_complete=True, phase_three_ready=True, phase_three_approved=True,
        phase_three_complete=True, phase_four_approved=False,
        conclusion='C9521正式登记并满足全部原经济目标，阶段二三治理与阶段三交付完成；阶段四未执行。',
        pending=['请用户决定是否对唯一交接候选C9521进入阶段四五项自检与比较。'])
    intent['stage23_governance_20261020'] = {
        'authorization': '先补全阶段二、阶段三的治理步骤（登记面板、登记候选等），然后完成阶段三收口',
        'status': 'COMPLETE_STAGE_THREE_CLOSEOUT', 'components': components.reference.to_dict(),
        'candidates': candidates.reference.to_dict(), 'stage3_decision': decision.to_dict(),
        'registered_new': ['S014-C9461', 'S014-C9502', 'S014-C9521'], 'handoff': ['S014-C9521'],
        'new_account_evaluations': 0, 'new_fits': 0, 'new_market_calls': 0,
        'historical_66_candidates_and_eligibility': 'UNCHANGED', 'historical_28_component_entries': 'UNCHANGED',
        'stage4_executed': False, 'no_backdated_authority': True,
    }
    update_research_intent(repo, BATCH, ResearchIntentUpdate(research_intent=intent), actor='RSCH',
        reason='按用户当前明确授权补全阶段二三治理：承接旧28条目新增8职责、登记3原身份共69并核加载，C9521唯一达标交接；完成阶段三收口，不倒签诊断或执行阶段四。')
    after = read(FAMILY)
    allowed = {'stage', 'components', 'candidates', 'component_definitions', 'strategy_accounts', 'all_targets_pass_count',
               'phase_two_complete', 'phase_three_ready', 'phase_three_approved', 'phase_three_complete',
               'phase_four_approved', 'conclusion', 'pending', 'stage23_governance_20261020'}
    assert {k: v for k, v in after['research_intent'].items() if k not in allowed} == {k: v for k, v in before['research_intent'].items() if k not in allowed}
    assert after['research_state'] == before['research_state']
    baseline_check()
    result = {'status': 'COMPLETE_STAGE_TWO_GOVERNANCE_AND_STAGE_THREE_CLOSEOUT',
        'components': components.reference.to_dict(), 'components_validation': component_validation.to_dict(),
        'candidates': candidates.reference.to_dict(), 'candidates_validation': candidate_validation.to_dict(),
        'stage3_decision': decision.to_dict(), 'formal_candidate_count': 69, 'component_definition_count': 36,
        'qualified_count': 1, 'handoff': ['S014-C9521'], 'new_account_evaluations': 0,
        'protected_old_files': len(baseline['protected_files']), 'stage4_executed': False,
        'historical_evidence_preserved': True,
        'preparation_failures_preserved': 1,
        'registration_evidence': registration_ref.to_dict()}
    write(OUT / 'result.json', result)
    result_ref = publish_file(ctx, OUT / 'result.json')
    write(OUT / 'result_ref.json', result_ref.to_dict())
    print(json.dumps({'status': result['status'], 'components_revision': 23, 'candidates_revision': 14,
                      'registered': 69, 'qualified': 1, 'handoff': ['S014-C9521'], 'new_account_evaluations': 0}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('prepare', 'complete'))
    args = parser.parse_args()
    if args.phase == 'prepare':
        prepare()
    else:
        complete()
