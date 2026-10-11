"""Fail-only EX080 formal delivery, quota receipt and exact report copy."""
from pathlib import Path
import sys
from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.evidence import EvidenceRef

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_confirm_execution_v3 as d


def run():
    exp, path, plan = d.stage()
    ctx = d.common().context(1)
    refs = {}
    for filename in ('method_references.json', 'technical_repair_references.json', 'method_references_v2.json',
                     'prepare_references_v2.json', 'audit_references.json', 'review_references.json'):
        for name, ref in d.read(path / 'protocols' / filename).items():
            key = 'v1/' + name if filename in ('method_references.json', 'technical_repair_references.json') else name
            refs[key] = ref
    refs['native.json'] = d.read(path / 'protocols/centre_reference.json')
    refs['independent_preaccount.json'] = d.read(path / 'protocols/independent_preaccount_reference_v2.json')
    audit = d.read(d.public(refs['verification.json']))
    review = d.read(d.public(refs['root_review.json']))
    if audit['status'] != 'PASS' or audit['qualified'] or review['objective_achieved']:
        raise ValueError('Fail-only closeout cannot substitute for required passing-centre checks')
    if review['economics'] != audit['economics'] or review['original_four_hard_gates_changed']:
        raise ValueError('Actual unchanged hardgate economics required')
    if review['evidence_references']['verification.json'] != refs['verification.json'] or review['evidence_references']['native.json'] != refs['native.json']:
        raise ValueError('Reviewed exact evidence')
    if review['evidence_references']['plan.json'] != refs['plan.json']:
        raise ValueError('Reviewed successor prospective plan required')
    for ref in (*refs.values(), *plan['input_references'].values(), plan['continuation_budget_reference']):
        d.public(ref)
    budget = {'status': 'ROUND2_COMPLETED_SUBJECT_TO_FULL_CLOSEOUT', 'authorization_reference': plan['continuation_budget_reference'],
              'maximum_additional_experiments': 10, 'started': 2, 'completed': 2, 'completed_experiment': exp.to_dict(),
              'remaining': 8, 'next_allowed': 'EX081', 'last_allowed': 'EX088', 'pause_after_EX088': True,
              'actual_new_accounts_this_round': 1, 'failed_evaluate_before_account': 1, 'financial_repeats': 0,
              'objective_achieved': False}
    d.write(d.OUT / 'budget_receipt.json', budget)
    refs['budget_receipt.json'] = d.put(ctx, exp, d.OUT / 'budget_receipt.json')
    refs['closeout_driver.py'] = d.put(ctx, exp, Path(__file__))
    # Keep published Python sources recoverable without mutable .tmp materials.
    recovery = path / 'src/reproduction'
    recovery.mkdir(exist_ok=True)
    for name, ref in refs.items():
        p = d.public(ref)
        if p.suffix == '.py':
            target = recovery / (EvidenceRef.from_dict(ref).sha256[:12] + '_' + Path(name).name)
            if target.exists():
                if target.read_bytes() != p.read_bytes():
                    raise ValueError('Source recovery collision')
            else:
                with target.open('xb') as stream:
                    stream.write(p.read_bytes())
    evidence = tuple(dict.fromkeys(EvidenceRef.from_dict(x) for x in (*refs.values(), *plan['input_references'].values(), plan['continuation_budget_reference'])))
    summary = m.SearchSummary(exp.experiment_id + '-fixed-confirm-net-centre',
        '原年度确认净预测大于0、固定四日持有和退出优先，单中心原执行兑现检验，无参数优化',
        '原510500.SH完整HFQ开发池/100万元/每侧0.1%/原1%LimitBuyHold；新增真实中心1、原C8880只读复用1；信号准备失败调用1不冒充账户',
        1, 1, review['judgment'],
        ('同一已见开发池适应性研究，不是独立封存验证',
         '中心原四门失败；新增合格候选集合为空，不删除此前正式候选',
         '参数32/双费未运行，参数收益Q10/回撤Q90/32点达标率不可得；三项账本诊断不等于完整五项自检',
         '重叠信号及非重叠OPEN代理不是可执行账户；不把差异作可加总因果利润',
         '源码输入声明修订以新C9080身份保留，确认表达/参数/经济目标保持；无实际账户重跑'), evidence)
    report = review['report_markdown'] + '\n\n正式证据（项目根目录相对路径）：\n\n' + ''.join(f'- [{name}]({EvidenceRef.from_dict(ref).path})\n' for name, ref in refs.items())
    predecessors = tuple(m.DeliveryReference.from_dict(x) for x in plan['predecessors'])
    if len(predecessors) != 1 or predecessors[0].stage != m.DeliveryStage.MANDATE or predecessors[0].revision != 6:
        raise ValueError('Original MANDATE6 required')
    receipt = assemble_delivery(ctx.repository,
        m.DeliveryDefinition(m.ResearchBatchRef('S013'), m.DeliveryStage.CANDIDATES, 62, predecessors),
        m.DeliveryContent(m.CandidateSet((), (), (summary,), review['judgment']), m.DeliveryStatus.COMPLETE, (), (), report=report, evidence=evidence))
    d.write(path / 'protocols/delivery_reference.json', receipt.reference.to_dict())
    validation = validate_delivery(ctx.repository, receipt.reference, scope=m.DeliveryValidationScope.FULL)
    d.write(path / 'protocols/delivery_validation.json', validation.to_dict())
    d.write(path / 'protocols/closeout_references.json', refs)
    if validation.status.value != 'PASS':
        raise RuntimeError(validation.to_dict())
    formal = ROOT / 'research/S013/deliveries/CANDIDATES/62/report.md'
    copy = path / 'others/report.md'
    with copy.open('xb') as stream:
        stream.write(formal.read_bytes())
    if formal.read_bytes() != copy.read_bytes():
        raise ValueError('Report copy differs')
    proof = {'status': 'PASS', 'formal_report': formal.relative_to(ROOT).as_posix(),
             'experiment_report': copy.relative_to(ROOT).as_posix(), 'formal_sha256': d.digest(formal),
             'copy_sha256': d.digest(copy), 'exact_bytes': True,
             'human_instruction': 'RSCH，请在后续的每个实验目录下保存一份report副本'}
    d.write(path / 'protocols/report_copy_verification.json', proof)
    print({'status': 'FULL_PASS', 'CANDIDATES': 62, 'report_copy': 'EXACT', 'completed': 2, 'remaining': 8}, flush=True)


if __name__ == '__main__':
    run()
