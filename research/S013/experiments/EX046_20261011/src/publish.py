"""Local full42 retention, canonical content references prevent name-alias conflicts."""
import subprocess
from common import ROOT, SRC, PROTOCOLS, RUNS, EXPERIMENT, context, read, write, file_hash
from precheck import source_check
from czsc_trader.application import publish_evidence, assemble_delivery, validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite, delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateKey


def main():
    plan = source_check()
    assert not (PROTOCOLS / 'delivery_reference.json').exists()
    analysis, parameter, conclusion = (read(RUNS / (name + '.json')) for name in ('analysis', 'parameter_analysis', 'conclusion'))
    assert analysis['status'] == 'PASS' and conclusion['status'] == 'COMPLETE'
    report = SRC.parent / 'others/report.md'
    before = report.read_bytes()
    subprocess.run([str(ROOT / '.venv/Scripts/python.exe'), str(SRC / 'write_report.py')], cwd=ROOT, check=True, capture_output=True)
    assert before == report.read_bytes()
    lint = subprocess.run([str(ROOT / '.venv/Scripts/ruff.exe'), 'check', str(SRC)], cwd=ROOT, check=True, capture_output=True, text=True)
    write(RUNS / 'reproduction.json', {'source_files': {p.relative_to(SRC).as_posix(): {'sha256': file_hash(p), 'source': p.read_text(encoding='utf-8')}
        for p in SRC.rglob('*.py')}, 'baseline_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'counts': conclusion, 'resources': plan['resources'], 'report_sha256': file_hash(report),
        'report_regeneration': 'EXACT_EQUAL', 'ruff': lint.stdout.strip(),
        'retention': 'Formal native source/data/prepared assets required; Git alone not data backup.'})
    accounts = {label: EvidenceRef.from_dict(ref) for label, ref in read(RUNS / 'account_references.json').items()}
    if parameter['status'] == 'PASS':
        for row in read(RUNS / 'parameter_matrix.json')['rows']:
            key = row['control_key'] + '::' + row['label']
            assert key not in accounts
            accounts[key] = EvidenceRef.from_dict(row['reference'])
    materials = {'plan': EvidenceRef.from_dict(read(PROTOCOLS / 'plan_reference.json')),
        'native-context-diagnosis': EvidenceRef.from_dict(plan['diagnosis_reference']),
        'geometry': EvidenceRef.from_dict(read(PROTOCOLS / 'geometry_reference.json'))}
    for name, ref in read(PROTOCOLS / 'context_diagnosis_references.json').items():
        if name != 'diagnosis':
            materials['context-' + name] = EvidenceRef.from_dict(ref)
    ctx = context(1)
    for directory in (PROTOCOLS, RUNS):
        for path in directory.glob('*.json'):
            if path.name in ('plan.json', 'geometry.json', 'delivery_validation.json'):
                continue
            digest = file_hash(path)
            if any(ref.experiment == EXPERIMENT and ref.sha256 == digest and ref.media_type == 'application/json' for ref in materials.values()):
                continue
            name = ('protocols' if directory == PROTOCOLS else 'runs') + '-' + path.stem.replace('_', '-')
            assert name not in materials
            materials[name] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(), 'application/json', 'json'))
    entries = []
    for label in ('B0-TIME', 'B0-COUPLED', 'N0'):
        row = analysis['rows'][label]
        if row['qualified']:
            entries.append(d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013', row['candidate_id']), row['content_sha256']),
                '原生完整账户机制与参数对照', '原四项目标达标；参数尾部和相对退化完整报告，未正式阶段四交接',
                (d.EvaluationEvidenceRef(accounts[label]),)))
    summary = d.SearchSummary(plan['name'], '事前声明类别记忆只在连续下跌市场段内有效；本地原生中心及条件完整32坐标',
        '原S013数据/四经济目标/完整13域/交易与基准，原确认L与均值背景耦合保持',
        conclusion['mechanism_actual_evaluations'] + conclusion['parameter_actual_evaluations'],
        conclusion['new_mechanism_business_accounts'] + conclusion['new_parameter_business_accounts'],
        '1新中心、2旧中心；通过原四门才复用64参数对照并运行新32点；本次参数状态=' + parameter['status'],
        ('反复使用已见开发池', '旧路径上的跨段拒绝不代表错过利润', '类别有效期是新结构；无额外参数/类别稳健性或独立验证声明'),
        (materials['runs-analysis'], materials['runs-parameter-analysis'],
         next(ref for ref in materials.values() if ref.experiment == EXPERIMENT
              and ref.sha256 == file_hash(RUNS / 'conclusion.json')
              and ref.media_type == 'application/json')))
    payload = d.CandidateSet(tuple(entries), (), (summary,), '完整证据保留；总目标判断见结论，未正式阶段四选择。')
    evidence, report_text = {}, before.decode('utf-8') + '\n## 正式证据引用\n\n'
    for name, ref in {**accounts, **materials}.items():
        assert file_hash(ref.resolve(ROOT)) == ref.sha256
        if ref.repository_path in evidence:
            assert evidence[ref.repository_path] == ref
        evidence[ref.repository_path] = ref
        report_text += f'- [{name}](../../../assets/deliveries/CANDIDATES/42/{ref.path})\n'
    receipt = assemble_delivery(ctx.repository, d.DeliveryDefinition(ctx.batch, d.DeliveryStage.CANDIDATES, 42,
        (d.DeliveryReference.from_dict(plan['mandate']), d.DeliveryReference.from_dict(plan['previous_delivery']))),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (), report=report_text, evidence=tuple(evidence.values())))
    validation = validate_delivery(ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    assert validation.status.value == 'PASS', validation.to_dict()
    write(PROTOCOLS / 'delivery_reference.json', receipt.reference.to_dict())
    write(RUNS / 'delivery_validation.json', {'status': 'PASS', 'reference': receipt.reference.to_dict(), 'validation': validation.to_dict(), 'counts': conclusion})
    print({'FULL': 'PASS', 'delivery': receipt.reference.to_dict(), 'objective_achieved': conclusion['objective_achieved']}, flush=True)


if __name__ == '__main__':
    main()
