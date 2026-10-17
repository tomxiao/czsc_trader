"""Deliver permission feasibility without inventing announcement components."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import (RepositoryContext, create_research_context, publish_evidence,
    assemble_delivery, validate_delivery, update_research_intent, ResearchIntentUpdate)
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, EvidenceRef, MaterialEvidenceWrite,
    DeliveryReference, DeliveryDefinition, DeliveryStage, DeliveryContent, DeliveryStatus, ValidationStatus,
    ComponentPanel, FactValue, FactStatus)

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]


def main():
    if (EXPERIMENT/'others/result.json').exists():
        raise RuntimeError('Preserve published result')
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    repo = RepositoryContext.discover(ROOT)
    context = create_research_context(repo, ResearchBatchRef('S014'))
    ex = ExperimentRef('S014', EXPERIMENT.name)
    prior = read(ROOT/'research/S014/experiments/EX010_20261017/others/result.json')
    mandate = read(ROOT/'research/S014/experiments/EX003_20261016/others/result.json')
    prior_ref, mandate_ref = (DeliveryReference.from_dict(x['delivery']) for x in (prior, mandate))
    assert all(validate_delivery(repo, ref).status is ValidationStatus.PASS for ref in (prior_ref, mandate_ref))
    old = DeliveryContent.from_dict(read(ROOT/'research/S014/assets/deliveries/COMPONENTS/7/delivery.json')['content'])
    audit = read(EXPERIMENT/'others/audit.json')
    assert audit['status'] == 'PASS'
    for item in audit['manifest']:
        assert sha256((ROOT/item['path']).read_bytes()).hexdigest() == item['sha256'], item['path']
    refs = {}
    for name in ('published_design', 'published_followup'):
        refs.update({n: EvidenceRef.from_dict(v) for n, v in read(EXPERIMENT/f'protocols/{name}.json').items()})
    materials = {'last-response': EXPERIMENT/'others/default_fields_verification.json',
        'first-start-guard': EXPERIMENT/'others/attempt_started.json', 'last-start-guard': EXPERIMENT/'others/default_fields_started.json',
        'source-notes': EXPERIMENT/'protocols/source_notes.json', 'audit': EXPERIMENT/'others/audit.json',
        'audit-program': EXPERIMENT/'src/audit.py', 'publication-program': Path(__file__),
        'initial-publication-receipt': EXPERIMENT/'protocols/published_design.json',
        'followup-publication-receipt': EXPERIMENT/'protocols/published_followup.json'}
    for name, p in materials.items():
        refs[name] = publish_evidence(context, MaterialEvidenceWrite(ex, name, p.read_bytes(),
            'text/x-python' if p.suffix == '.py' else 'application/json', p.suffix[1:]))
    evidence = (refs['first-response'], refs['last-response'], refs['source-notes'], refs['audit'])
    facts = old.facts + tuple(FactValue('ex011-'+name, value, unit, FactStatus.AVAILABLE, evidence) for name, value, unit in (
        ('source-calls', 2, 'calls'), ('cumulative-source-calls', 50, 'calls'), ('source-calls-remaining', 0, 'calls'),
        ('permission-related-rejection', True, 'boolean'), ('catalogue-received', False, 'boolean'),
        ('audit-checks', len(audit['checks']), 'checks'), ('new-strategy-accounts', 0, 'accounts'), ('new-supported-return-components', 0, 'components')))
    facts += tuple(FactValue('ex011-'+name, None, unit, FactStatus.INSUFFICIENT_DATA, evidence, reason) for name, unit, reason in (
        ('catalogue-rows', 'rows', '权限拒绝，未取得目录；不得填0冒充没有公告。'),
        ('historical-coverage', 'coverage', '未取得目录，无法核验历史覆盖与截断。'),
        ('publication-time', 'timestamp', '未取得rec_time或原文URL，真实披露时间、时区和修订未知。')))
    conclusion = ('当前同一账号anns_d无接口访问权限：两次HTTP200/40203，默认字段对照仍拒绝且错误明确涉及权限。'
        '历史目录与真实发布时间未核验，不实施平台接入。本轮2次、累计50/50、剩余0。'
        '原25项定义、2项辅助及收益反证保持；无新获支持收益入场，阶段二PARTIAL，不建议阶段三。')
    receipt = assemble_delivery(repo, DeliveryDefinition(context.batch, DeliveryStage.COMPONENTS, 8, (mandate_ref, prior_ref)),
        DeliveryContent(ComponentPanel(old.payload.components, conclusion), DeliveryStatus.PARTIAL, facts=facts, explanations=(),
            incomplete_items=('公司公告接口当前账号无访问权限，未取得同窗口目录。',
                '公告历史覆盖、URL及原始发布时间/时区/修订可得性尚未核验。',
                '原收益入场线索与隔夜亏损竞争解释尚未充分区分，阶段二未完成。'),
            report=(EXPERIMENT/'protocols/report.md').read_text(encoding='utf-8'),
            evidence=tuple(dict.fromkeys((*old.evidence, *refs.values())))))
    validation = validate_delivery(repo, receipt.reference)
    assert validation.status is ValidationStatus.PASS
    report = ROOT/'research/S014/deliveries/COMPONENTS/8/report.md'
    (EXPERIMENT/'others/report.md').write_bytes(report.read_bytes())
    assert report.read_bytes() == (EXPERIMENT/'protocols/report.md').read_bytes()
    copy = {'formal_report': report.relative_to(ROOT).as_posix(),
        'experiment_report': (EXPERIMENT/'others/report.md').relative_to(ROOT).as_posix(),
        'sha256': sha256(report.read_bytes()).hexdigest(), 'bytes': report.stat().st_size, 'status': 'PASS'}
    (EXPERIMENT/'protocols/report_copy_verification.json').write_text(json.dumps(copy, indent=2)+'\n', encoding='utf-8', newline='\n')
    result = {'experiment': ex.to_dict(), 'delivery': receipt.reference.to_dict(), 'validation': validation.to_dict(),
        'status': 'PARTIAL', 'upstream_access': 'PERMISSION_DENIED', 'history_coverage': 'UNVERIFIED', 'publication_time': 'UNVERIFIED',
        'evidence': {n: v.to_dict() for n, v in refs.items()}, 'inherited_evidence': [x.to_dict() for x in old.evidence],
        'report_copy': copy, 'new_source_calls': 2, 'cumulative_source_calls': 50, 'remaining_source_calls': 0,
        'component_definitions': 25, 'supported_auxiliary': 2, 'new_supported_return_components': 0, 'strategy_accounts': 0,
        'phase_two_complete': False, 'phase_three_recommended': False, 'phase_three_approved': False,
        'next_scope_proposed': '先由用户决定公告权限；开通后另批核验额度，再验证目录覆盖和真实时点，之后再提出接入/研究范围。'}
    (EXPERIMENT/'others/result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    intent = read(ROOT/'research/registrations/S014/family.json')['research_intent']
    intent.update(stage='阶段二进行中：公告访问核验完成，当前账号权限阻断，覆盖和时间待核验',
        components=receipt.reference.to_dict(), phase_two_complete=False, phase_three_ready=False, phase_three_approved=False,
        component_definitions=25, supported_components=2, supported_return_entry_components=0, strategy_accounts=0,
        remaining_source_calls=0, pending=[result['next_scope_proposed']], conclusion=conclusion)
    intent['resources']['remaining_source_calls'] = 0
    intent['current_data_authorization'] = {'source': 'Current human conversation', 'verbatim': '同意',
        'approved_proposal': 'research/S014/experiments/EX010_20261017/protocols/next_scope_proposal.json',
        'scope': '600722.SH同周期公告上游可行性，不含事件收益研究或平台实现',
        'window': ['2020-01-01', '2026-10-15'], 'max_calls': 2, 'actual_calls': 2, 'remaining_calls': 0,
        'permission_status': 'DENIED', 'catalogue_received': False}
    intent['announcement_feasibility'] = {'experiment': ex.to_dict(), 'delivery': receipt.reference.to_dict(),
        'access': 'PERMISSION_DENIED', 'coverage': 'UNVERIFIED', 'timestamps': 'UNVERIFIED', 'formal_dataset_added': False,
        'first_response': refs['first-response'].to_dict(), 'last_response': refs['last-response'].to_dict()}
    intent['diagnostic_feedback'].update(authorization='用户批准公司公告上游可行性核验，最多剩余2次。',
        closure_delivery=receipt.reference.to_dict(), reviewed_delivery=receipt.reference.to_dict(), reviewed_commit='eb37b752',
        execution_scope_this_turn='仅同账号两次公告请求、权限及字段对照；无公告目录、正文、事件收益或平台修改。',
        result=conclusion, judgment_update='关键公司信息假设尚未验证；访问受权限阻断不代表供应商无数据或该信息无收益价值。',
        recommended_minimum_design=result['next_scope_proposed'], routing_after_result='保持阶段二，先解决权限和新的有界核验额度。',
        verified=f'COMPONENTS/8 PARTIAL/FULL/PASS；{len(audit["checks"])}项离线检查，权限事实与未知项分开。',
        assessment=['当前账号没有公告接口访问权限，两次都计入预算，剩余0。',
            '覆盖与真实时间均未核验，没有公告数为0或供应商不提供公告的结论。',
            '既有25项定义、2项辅助保持，无新收益入场或账户。',
            '先由用户决定权限及后续核验额度，不先实施平台或事件研究。'])
    update_research_intent(repo, context.batch, ResearchIntentUpdate(research_intent=intent), actor='RSCH',
        reason='完成已批准公告上游访问核验，保存业务拒绝与字段对照，累计50次归零；历史及时点保留未知，阶段二不推进')
    print(json.dumps({'delivery': receipt.reference.to_dict(), 'validation': validation.to_dict(),
        'audit_checks': len(audit['checks']), 'calls': 2, 'remaining': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
