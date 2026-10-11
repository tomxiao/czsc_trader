"""Root-reviewed held information closeout; no financial evaluations."""
from driver import ROOT, WORK, common, read, write, public, check_sources
from czsc_trader.application import assemble_delivery, validate_delivery, publish_evidence
from czsc_trader.research_tools import delivery as d, MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef


def save_exact(path, value):
    if path.exists():
        assert read(path) == value, 'Prior immutable output differs'
    else:
        write(path, value)


def put(ctx, exp, path):
    media = {'.py': 'text/x-python', '.md': 'text/markdown', '.json': 'application/json'}[path.suffix]
    return publish_evidence(ctx, MaterialEvidenceWrite(exp, path.stem.replace('_', '-'),
        path.read_bytes(), media, path.suffix[1:])).to_dict()


def main():
    exp = ExperimentRef.from_dict(read(WORK / 'experiment.json'))
    plan = read(WORK / 'plan.json')
    check_sources(plan)
    refs = read(exp.resolve(ROOT) / 'protocols/verification_references.json')
    assert read(public(refs['verification.json']))['status'] == 'PASS'
    review = read(WORK / 'root_review.json')
    assert review['status'] == 'ROOT_SCIENTIFIC_REVIEWED'
    assert review['statistics_reference'] == refs['statistics.json']
    assert review['verification_reference'] == refs['verification.json']
    assert review['objective_achieved'] is False
    assert review['new_accounts'] == 0
    result = read(public(refs['statistics.json']))
    compact = {
        s: {label: {
            'components': b['components'],
            'models': b['walk_forward']['aggregate_models'],
            'groups': b['walk_forward']['aggregate_groups'],
            'yearly_groups': {y: v['groups'] for y, v in b['walk_forward']['yearly'].items()},
        } for label, b in p['labels'].items()}
        for s, p in result['scopes'].items()
    }
    save_exact(WORK / 'compact_statistics.json', compact)
    save_exact(WORK / 'conclusion.json', {
        'status': 'PHASE_TWO_ACTUAL_HELD_COMPLETE',
        'objective_achieved': False,
        'economic_targets_unchanged': True,
        'new_accounts': 0,
        'next': review['next'],
    })
    report = review['report_markdown']
    (WORK / 'report.md').write_text(report, encoding='utf-8')
    ctx = common.context(1)
    amendment = {
        'status': 'NON_FINANCIAL_CLOSEOUT_TECHNICAL_AMENDMENT',
        'failure': "KeyError: 'predecessors' before delivery assembly; source plan did not declare that field",
        'original_closeout_source': put(ctx, exp, WORK / 'finish_v1.py'),
        'change': 'Explicit actual MANDATE/6, COMPONENTS/8, CANDIDATES/57 receipt references; accept only identical prior compact/conclusion artifacts',
        'new_accounts': 0, 'statistical_reexecution': 0,
        'scientific_review_and_results_unchanged': True,
    }
    save_exact(WORK / 'closeout_amendment.json', amendment)
    refs['finish_v1.py'] = amendment['original_closeout_source']
    for n in ('root_review.json', 'compact_statistics.json', 'conclusion.json', 'report.md', 'closeout_amendment.json', 'finish.py'):
        refs[n] = put(ctx, exp, WORK / n)
        if n.endswith('.py'):
            (exp.resolve(ROOT) / 'src' / n).write_bytes((WORK / n).read_bytes())
    j = review['late_weakness']
    test = d.ComponentTestResult(
        'LATE_WEAKNESS-ACTUAL-HELD-H4', exp.experiment_id,
        EvidenceRef.from_dict(refs['plan.json']), d.ComponentTestStatus(j['status']),
        j['judgment'], tuple(EvidenceRef.from_dict(refs[n]) for n in
            ('statistics.json', 'verification.json', 'root_review.json')),
    )
    entry = d.ComponentEntry(
        'LATE_WEAKNESS-ACTUAL-HELD',
        d.ExperimentDefinitionRef(EvidenceRef.from_dict(refs['driver.py']), 'study'),
        '真实持仓中已知尾盘弱势的继续持有信息',
        'return4/downside4主，8日辅助；close记账仅分解不另拟合',
        'T+1 Open继续与立即卖出增量；T close清算辅助',
        '原20控制排除自身反向再加实际age/PnL/falling，共22；残差df至少10；500x40seed13；成熟训练ridge10两模型同样本',
        'T收盘实际quantity与当日信号计划；nextOpen执行；初始隔夜不可避免',
        '原后复权；两种卖出路径相同卖费抵消；标记清算仅一次卖费',
        '原真实持仓、下跌、计划继续/退出四池；非封存验证',
        j['judgment'], (test,),
    )
    links = '\n## 正式证据引用\n\n' + ''.join(
        f'- [{n}]({EvidenceRef.from_dict(r).path})\n' for n, r in refs.items()
    )
    predecessors = tuple(d.DeliveryReference.from_dict(read(
        ROOT / f'research/S013/assets/deliveries/{stage}/{revision}/receipt.json'
    )['reference']) for stage, revision in (('MANDATE', 6), ('COMPONENTS', 8), ('CANDIDATES', 57)))
    for previous in predecessors:
        assert validate_delivery(ctx.repository, previous, scope=d.DeliveryValidationScope.INTEGRITY).status.value == 'PASS'
    receipt = assemble_delivery(ctx.repository,
        d.DeliveryDefinition(ctx.batch, d.DeliveryStage.COMPONENTS, 9,
            predecessors),
        d.DeliveryContent(d.ComponentPanel((entry,), j['judgment']),
            d.DeliveryStatus.COMPLETE, (), (), report=report + links,
            evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(x) for x in refs.values()))))
    write(exp.resolve(ROOT) / 'protocols/delivery_reference.json', receipt.reference.to_dict())
    validation = validate_delivery(ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    write(exp.resolve(ROOT) / 'protocols/delivery_validation.json', validation.to_dict())
    write(exp.resolve(ROOT) / 'protocols/final_evidence_references.json', refs)
    (exp.resolve(ROOT) / 'others').mkdir(exist_ok=True)
    (exp.resolve(ROOT) / 'others/report.md').write_text(report + '\n## 正式证据引用\n\n' + ''.join(
        f'- [{n}](../../../assets/deliveries/COMPONENTS/9/{EvidenceRef.from_dict(r).path})\n'
        for n, r in refs.items()), encoding='utf-8')
    assert validation.status.value == 'PASS', validation.to_dict()
    assert not common.SOURCE_CALLS
    print({'experiment': exp.experiment_id, 'FULL': validation.status.value, 'objective_achieved': False}, flush=True)


if __name__ == '__main__':
    main()
