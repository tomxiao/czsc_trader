"""Publish exact native diagnosis and complete immutable reproduction evidence."""
import subprocess
from common import ROOT, SRC, PROTOCOLS, RUNS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence, assemble_delivery, validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite, delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateKey


def main():
    assert not (PROTOCOLS / 'delivery_reference.json').exists()
    plan = read(PROTOCOLS / 'plan.json')
    for name, digest in plan['source_files'].items():
        assert file_hash(SRC / name) == digest
    for name, digest in plan['external_source_files'].items():
        assert file_hash(ROOT / name) == digest
    output = read(ROOT / '.tmp/ex039-diagnosis/direction.json')
    assert output['status'] == 'PASS' and output['method_reference'] == plan['method_reference']
    assert output['new_account_evaluations'] == 0 and len(output['input_accounts']) == 35
    report = SRC.parent / 'others/report.md'
    before = report.read_bytes()
    subprocess.run([str(ROOT / '.venv/Scripts/python.exe'), str(SRC / 'write_report.py')], cwd=ROOT, check=True, capture_output=True)
    assert before == report.read_bytes()
    ctx = context(1)
    materials = {'plan': EvidenceRef.from_dict(read(PROTOCOLS / 'plan_reference.json')),
                 'method': EvidenceRef.from_dict(plan['method_reference']),
                 **{'input-' + k: EvidenceRef.from_dict(v) for k, v in plan['input_references'].items()}}
    for name, path in (('native-direction', ROOT / '.tmp/ex039-diagnosis/direction.json'),
                       ('focused-checks', ROOT / '.tmp/ex039-diagnosis/focused.json'),
                       ('research-decision', PROTOCOLS / 'decision.json')):
        value = read(path)
        if name == 'focused-checks':
            assert value['status'] == 'PURE_PASS'
        write(RUNS / (name + '.json'), value)
        materials[name] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, name,
            (RUNS / (name + '.json')).read_bytes(), 'application/json', 'json'))
    accounts = {label: EvidenceRef.from_dict(ref) for label, ref in output['input_accounts'].items()}
    assert len({ref.repository_path for ref in accounts.values()}) == 35
    lint = subprocess.run([str(ROOT / '.venv/Scripts/ruff.exe'), 'check', str(SRC)], cwd=ROOT, check=True, capture_output=True, text=True)
    reproduction = {'source_files': {p.relative_to(SRC).as_posix(): {'sha256': file_hash(p), 'source': p.read_text(encoding='utf-8')}
                                    for p in SRC.glob('*.py')}, 'external_source_files': plan['external_source_files'],
                    'report_sha256': file_hash(report), 'ruff': lint.stdout.strip(), 'unique_native_accounts_reused': 35,
                    'new_account_evaluations': 0, 'new_business_configurations': 0, 'objective_achieved': False,
                    'retention': 'Native formal source/data/prepared assets remain required; Git alone is not a complete data backup.'}
    write(RUNS / 'reproduction.json', reproduction)
    materials['reproduction'] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'reproduction',
        (RUNS / 'reproduction.json').read_bytes(), 'application/json', 'json'))
    entries = (d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013', 'C2132'),
        '939e07357e59fa00b3123a5f0e775303ca1fdd9295c22bbca3f014ffda4aa8ad'),
        '原策略完整账户不可变对照', '本轮零新增配置，未达标MEAN/BODY背景仅作诊断',
        (d.EvaluationEvidenceRef(accounts['center']),)),)
    search = d.SearchSummary(plan['name'], '事前冻结零新账户全原路径方向统计',
        '原S013数据、四项经济目标及13维完整参数域保持，全部信号日期保留', 0, 0,
        '35个不同原生账户精确复用；33账户非独立样本；研究目标继续',
        ('已见开发池', '单步价格判断不是传播后的策略收益', '机会日期与实际经济年度不同'),
        (materials['native-direction'],))
    payload = d.CandidateSet(entries, (), (search,), '本轮诊断完成，总参数敏感性改善目标尚未达成。')
    evidence = {}
    report_text = report.read_text(encoding='utf-8') + '\n## 正式证据引用\n\n'
    for name, ref in {**accounts, **materials}.items():
        assert file_hash(ref.resolve(ROOT)) == ref.sha256
        if ref.repository_path in evidence:
            assert evidence[ref.repository_path] == ref
        evidence[ref.repository_path] = ref
        report_text += f'- [{name}](../../../assets/deliveries/CANDIDATES/35/{ref.path})\n'
    receipt = assemble_delivery(ctx.repository, d.DeliveryDefinition(ctx.batch, d.DeliveryStage.CANDIDATES, 35,
        (d.DeliveryReference.from_dict(plan['mandate']), d.DeliveryReference.from_dict(plan['previous_delivery']))),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (), report=report_text, evidence=tuple(evidence.values())))
    validation = validate_delivery(ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    assert validation.status.value == 'PASS', validation.to_dict()
    write(PROTOCOLS / 'delivery_reference.json', receipt.reference.to_dict())
    write(RUNS / 'delivery_validation.json', {'status': 'PASS', 'reference': receipt.reference.to_dict(),
        'validation': validation.to_dict(), 'unique_native_accounts_reused': 35, 'new_account_evaluations': 0,
        'objective_achieved': False})
    print({'FULL': 'PASS', 'delivery': receipt.reference.to_dict(), 'unique_reused_accounts': 35, 'new_evaluations': 0}, flush=True)


if __name__ == '__main__':
    main()
