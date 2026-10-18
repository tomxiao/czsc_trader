"""Publish the authorized recovery diagnosis without new accounts or components."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, assemble_delivery,
    create_research_context, publish_evidence, update_research_intent,
    validate_delivery,
)
from czsc_trader.research_tools import (
    CandidateSet, ComponentPanel, DeliveryContent, DeliveryDefinition,
    DeliveryReference, DeliveryStage, DeliveryStatus, FactStatus, FactValue,
    MaterialEvidenceWrite, ExperimentRef, ResearchBatchRef, ValidationStatus,
)

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
                    + '\n', encoding='utf-8', newline='\n')


def main():
    if (EX / 'others/result.json').exists():
        raise RuntimeError('Preserve completed diagnostic delivery')
    analysis = read(EX / 'others/analysis.json')
    audit = read(EX / 'others/independent_audit.json')
    binding = read(EX / 'others/input_binding_review.json')
    judgment = read(EX / 'others/diagnostic_judgment.json')
    assert analysis['status'] == 'COMPLETE' and audit['status'] == binding['status'] == 'PASS'
    assert read(EX / 'others/precheck.json')['status'] == 'PASS'
    assert analysis['evaluation_sessions'] == 1642
    assert analysis['new_accounts'] == analysis['new_candidates'] == analysis['new_upstream_calls'] == 0
    assert judgment['new_component_definitions'] == judgment['new_supported_components'] == 0
    for key in ('conclusion', 'judgment_update', 'next_step'):
        assert isinstance(judgment[key], str) and judgment[key].strip(), key

    # Calculation and narrative have separate immutable review receipts.
    paths = set()
    for item in (*audit['manifest'], *binding['manifest']):
        path = (ROOT / item['path']).resolve()
        assert path.is_relative_to(ROOT), item['path']
        assert sha256(path.read_bytes()).hexdigest() == item['sha256'], item['path']
        paths.add(path)
    required = {
        EX / 'src/study.py', EX / 'protocols/design.json',
        EX / 'protocols/published_design.json',
        EX / 'others/analysis.json', EX / 'others/features.csv', EX / 'others/labels.csv',
        EX / 'others/precheck.json',
        EX.parent / 'EX023_20261018/others/loss_state_diagnostics.json',
    }
    assert required <= paths, sorted(str(p.relative_to(ROOT)) for p in required - paths)
    for relative, expected in analysis['source_sha256'].items():
        path = ROOT / relative
        assert sha256(path.read_bytes()).hexdigest() == expected, relative
        assert path in paths, relative
    for name, expected in analysis['output_sha256'].items():
        assert sha256((EX / f'others/{name}.csv').read_bytes()).hexdigest() == expected
    paths.add(EX / 'others/independent_audit.json')
    paths.add(EX / 'others/input_binding_review.json')
    review = read(EX / 'others/report_review.json')
    assert review['status'] == 'PASS'
    narrative_paths = set()
    for item in review['manifest']:
        path = (ROOT / item['path']).resolve()
        assert path.is_relative_to(ROOT), item['path']
        assert sha256(path.read_bytes()).hexdigest() == item['sha256'], item['path']
        narrative_paths.add(path)
    assert {Path(__file__).resolve(), EX / 'protocols/report.md',
            EX / 'others/diagnostic_judgment.json'} <= narrative_paths
    paths |= narrative_paths | {EX / 'others/report_review.json'}

    repo = RepositoryContext.discover(ROOT)
    ctx = create_research_context(repo, ResearchBatchRef('S014'))
    exp = ExperimentRef('S014', EX.name)
    prior = DeliveryReference.from_dict(read(EX.parent / 'EX016_20261017/others/result.json')['delivery'])
    accounts = DeliveryReference.from_dict(read(EX.parent / 'EX029_20261018/others/result.json')['delivery'])
    old = DeliveryContent.from_dict(read(ROOT / 'research/S014/assets/deliveries/COMPONENTS/12/delivery.json')['content'])
    account_content = DeliveryContent.from_dict(read(ROOT / 'research/S014/assets/deliveries/CANDIDATES/13/delivery.json')['content'])
    assert isinstance(old.payload, ComponentPanel) and len(old.payload.components) == 26
    assert isinstance(account_content.payload, CandidateSet)
    assert len(account_content.payload.candidates) == 66 and not account_content.payload.handoff
    intent = read(ROOT / 'research/registrations/S014/family.json')['research_intent']
    before_budget = deepcopy(intent['stage_three_autonomous_budget'])
    assert before_budget['total_rounds'] == before_budget['allocated_rounds'] == before_budget['completed_rounds'] == 10
    assert before_budget['remaining_unallocated_rounds'] == 0
    assert intent['strategy_accounts'] == 66 and intent['all_targets_pass_count'] == 0
    assert intent['targeted_recovery_diagnosis']['experiment'] == exp.to_dict()

    refs = {}
    media = {'.py': 'text/x-python', '.json': 'application/json', '.csv': 'text/csv', '.md': 'text/markdown'}
    for path in sorted(paths):
        name = 'ex030-' + path.relative_to(ROOT).as_posix().replace('/', '-').replace('.', '-')
        refs[path.relative_to(ROOT).as_posix()] = publish_evidence(ctx,
            MaterialEvidenceWrite(exp, name, path.read_bytes(), media[path.suffix], path.suffix[1:]))
    diagnostic_evidence = tuple(refs.values())
    # Component evidence remains directly resolvable; candidate evidence is inherited
    # through the CANDIDATES/13 predecessor, without copying all account material.
    evidence = tuple(dict.fromkeys((*old.evidence, *diagnostic_evidence)))
    facts = old.facts + tuple(FactValue('ex030-' + key, value, unit,
        FactStatus.AVAILABLE, diagnostic_evidence) for key, value, unit in (
            ('evaluation-sessions', 1642, 'sessions'),
            ('ready-sessions', analysis['ready_sessions'], 'sessions'),
            ('local-break-episodes', analysis['local_break_episodes'], 'episodes'),
            ('first-recoveries', analysis['first_recoveries'], 'signals'),
            ('new-accounts', 0, 'accounts'), ('new-candidates', 0, 'candidates'),
            ('new-upstream-calls', 0, 'calls'), ('new-component-definitions', 0, 'components'),
            ('historical-candidates', 66, 'candidates'), ('all-target-pass-count', 0, 'candidates'),
            ('completed-account-rounds', 10, 'rounds'), ('remaining-account-rounds', 0, 'rounds'),
    ))
    receipt = assemble_delivery(repo,
        DeliveryDefinition(ctx.batch, DeliveryStage.COMPONENTS, 13, (prior, accounts)),
        DeliveryContent(ComponentPanel(old.payload.components, judgment['conclusion']),
            DeliveryStatus.COMPLETE, facts=facts, explanations=(), incomplete_items=(),
            report=(EX / 'protocols/report.md').read_text(encoding='utf-8'), evidence=evidence))
    validation = validate_delivery(repo, receipt.reference)
    assert validation.status is ValidationStatus.PASS, validation
    formal = ROOT / 'research/S014/deliveries/COMPONENTS/13/report.md'
    report = EX / 'protocols/report.md'
    assert formal.read_bytes() == report.read_bytes()
    mirror = EX / 'others/report.md'
    mirror.write_bytes(formal.read_bytes())
    report_bytes = formal.stat().st_size
    assert report_bytes == report.stat().st_size == mirror.stat().st_size
    copy_check = {'status': 'PASS', 'formal': formal.relative_to(ROOT).as_posix(),
        'source': report.relative_to(ROOT).as_posix(), 'mirror': mirror.relative_to(ROOT).as_posix(),
        'sha256': sha256(formal.read_bytes()).hexdigest(), 'bytes': report_bytes, 'byte_identical': True}
    assert formal.read_bytes() == mirror.read_bytes()
    write(EX / 'protocols/report_copy_verification.json', copy_check)
    result = {'status': 'COMPLETE', 'experiment': exp.to_dict(), 'delivery': receipt.reference.to_dict(),
        'validation': validation.to_dict(), 'evidence': {k: v.to_dict() for k, v in refs.items()},
        'component_definitions': 26, 'new_component_definitions': 0, 'new_supported_components': 0,
        'new_accounts': 0, 'new_candidates': 0, 'new_source_calls': 0,
        'historical_candidates': 66, 'all_targets_pass_count': 0,
        'stage_three_completed_rounds': 10, 'stage_three_remaining_rounds': 0,
        'phase_four_approved': False, 'new_stage_three_accounts_authorized': False,
        'report_copy': copy_check, 'conclusion': judgment['conclusion'], 'next_step': judgment['next_step']}
    write(EX / 'others/result.json', result)

    # Re-read mutable research intent immediately before the public update.
    intent = read(ROOT / 'research/registrations/S014/family.json')['research_intent']
    assert intent['stage_three_autonomous_budget'] == before_budget
    assert intent['strategy_accounts'] == 66 and intent['all_targets_pass_count'] == 0
    intent.update(stage='研究诊断及学习反馈：定向诊断完成，等待研究路由决定',
        components=receipt.reference.to_dict(), conclusion=judgment['conclusion'],
        phase_four_approved=False, pending=[judgment['next_step']])
    diagnosis = intent['targeted_recovery_diagnosis']
    diagnosis.update(status='COMPLETE', delivery=receipt.reference.to_dict(),
        conclusion=judgment['conclusion'], judgment_update=judgment['judgment_update'],
        next_step=judgment['next_step'], routing=judgment['routing'],
        new_accounts=0, new_candidates=0, new_source_calls=0,
        new_component_definitions=0, new_supported_components=0,
        new_stage_three_accounts_authorized=False, phase_four_approved=False)
    intent['diagnostic_feedback'].update(
        authorization=diagnosis['authorization'], reviewed_delivery=accounts.to_dict(),
        priority_question=read(EX / 'protocols/design.json')['question'],
        execution_scope_this_turn=diagnosis['scope'], result=judgment['conclusion'],
        judgment_update=judgment['judgment_update'], routing=judgment['routing'],
        routing_after_result=judgment['next_step'], closure_delivery=receipt.reference.to_dict(),
        verified='EX030 independent audit PASS; COMPONENTS/13 COMPLETE/FULL/PASS; no new accounts or upstream calls')
    update_research_intent(repo, ctx.batch, ResearchIntentUpdate(research_intent=intent),
        actor='RSCH', reason='完成获准旧支撑恢复定向诊断，保存反证与判断更新；保留66历史候选、10轮额度耗尽状态及原目标，不自动追加账户或进入阶段四')
    print(json.dumps({'delivery': receipt.reference.to_dict(), 'validation': validation.to_dict(),
        'new_evidence': len(refs), 'component_definitions': 26, 'new_accounts': 0,
        'report_copy': copy_check}, ensure_ascii=False))


if __name__ == '__main__':
    main()
