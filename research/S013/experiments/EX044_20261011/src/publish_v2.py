"""Explicit publication-only alias dedup correction; native66 unchanged."""
import subprocess
from publication_validation import technical_check, same_blob
from common import ROOT, SRC, PROTOCOLS, RUNS, OUTPUT, EXPERIMENT, context, read, write, file_hash
from diagnose import source_check
from czsc_trader.application import publish_evidence, assemble_delivery, validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite, delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateKey


def main():
    technical_check()
    plan = source_check()
    assert not (PROTOCOLS / 'delivery_reference.json').exists()
    output = read(OUTPUT)
    assert output['status'] == 'PASS' and len(output['input_accounts']) == 66
    assert output['new_account_evaluations'] == 0
    report = SRC.parent / 'others/report.md'
    before = report.read_bytes()
    subprocess.run([str(ROOT / '.venv/Scripts/python.exe'), str(SRC / 'report.py')], check=True, cwd=ROOT, capture_output=True)
    assert before == report.read_bytes()
    lint = subprocess.run([str(ROOT / '.venv/Scripts/ruff.exe'), 'check', str(SRC)], check=True, cwd=ROOT, capture_output=True, text=True)
    ctx = context(1)
    materials = {'plan': EvidenceRef.from_dict(read(PROTOCOLS / 'plan_reference.json')),
                 'method': EvidenceRef.from_dict(read(PROTOCOLS / 'method_reference.json'))}
    previous_refs = read(ROOT / 'research/S013/experiments/EX043_20261011/protocols/parameter_analysis_references.json')
    materials.update({name: EvidenceRef.from_dict(ref) for name, ref in read(PROTOCOLS / 'publication_correction_references.json').items()})
    materials['existing-economic-analysis'] = EvidenceRef.from_dict(previous_refs['analysis'])
    for name, path in (('complete-native-input-state', OUTPUT), ('focused-checks', ROOT / '.tmp/ex044-diagnosis/focused.json'),
                       ('research-decision', PROTOCOLS / 'decision.json'), ('research-conclusion', RUNS / 'conclusion.json')):
        write(RUNS / (name + '.json'), read(path))
        materials[name] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, name,
            (RUNS / (name + '.json')).read_bytes(), 'application/json', 'json'))
    reproduction = {'source_files': {p.name: {'sha256': file_hash(p), 'source': p.read_text(encoding='utf-8')}
        for p in SRC.glob('*.py')}, 'external_source_files': plan['external_source_files'],
        'report_sha256': file_hash(report), 'ruff': lint.stdout.strip(), 'unique_native_accounts_reused': 66,
        'new_account_evaluations': 0, 'new_business_configurations': 0, 'objective_achieved': False,
        'retention': 'Formal native source/data/prepared inputs remain needed; Git alone not data backup.'}
    write(RUNS / 'reproduction_v2.json', reproduction)
    materials['reproduction'] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'reproduction-v2',
        (RUNS / 'reproduction_v2.json').read_bytes(), 'application/json', 'json'))
    accounts = {label: EvidenceRef.from_dict(ref) for label, ref in output['input_accounts'].items()}
    entries = tuple(d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013', identifier),
        output['audits'][label + '-center']['public_identity']['content_sha256']),
        '既有完整账户参数机制诊断对照', '中心经济达标不代表完整32点参数稳健性改善；本轮无新配置',
        (d.EvaluationEvidenceRef(accounts[label + '-center']),)) for label, identifier in (('B0-TIME', 'C2132'), ('N0', 'C4900')))
    search = d.SearchSummary(plan['name'], '事前冻结零新增66账户完整触发/状态一步对照',
        '原数据、四项目标、完整13维及32共同坐标保留', 0, 0, '66不同账户精确复用，非独立样本',
        ('已见开发池', '一步对照不产生修改后的收益', '技术通过不代表总目标达成'),
        (materials['complete-native-input-state'],))
    payload = d.CandidateSet(entries, (), (search,), 'EX044诊断完成，总参数敏感性改善目标继续。')
    evidence, report_text = {}, report.read_text(encoding='utf-8') + '\n发布v1因同一内容不同名称的引用比较失败；v2只修正内容去重，完整失败和纠正证据保留，零账户重跑。\n\n## 正式证据引用\n\n'
    for name, ref in {**accounts, **materials}.items():
        assert file_hash(ref.resolve(ROOT)) == ref.sha256
        if ref.repository_path in evidence:
            assert same_blob(evidence[ref.repository_path], ref)
        evidence[ref.repository_path] = ref
        report_text += f'- [{name}](../../../assets/deliveries/CANDIDATES/40/{ref.path})\n'
    receipt = assemble_delivery(ctx.repository, d.DeliveryDefinition(ctx.batch, d.DeliveryStage.CANDIDATES, 40,
        (d.DeliveryReference.from_dict(plan['mandate']), d.DeliveryReference.from_dict(plan['previous_delivery']))),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (), report=report_text, evidence=tuple(evidence.values())))
    validation = validate_delivery(ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    assert validation.status.value == 'PASS', validation.to_dict()
    write(PROTOCOLS / 'delivery_reference.json', receipt.reference.to_dict())
    write(RUNS / 'delivery_validation.json', {'status': 'PASS', 'reference': receipt.reference.to_dict(),
        'validation': validation.to_dict(), 'unique_native_accounts_reused': 66, 'new_account_evaluations': 0, 'objective_achieved': False})
    print({'FULL': 'PASS', 'delivery': receipt.reference.to_dict()}, flush=True)


if __name__ == '__main__':
    main()
