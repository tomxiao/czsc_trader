"""Retain every failed full account and verify the complete research delivery."""
import subprocess
from common import ROOT, SRC, PROTOCOLS, RUNS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence, assemble_delivery, validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite, delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateKey
from technical_validation import technical_check


def main():
    technical_check()
    assert not (PROTOCOLS / 'delivery_reference.json').exists()
    plan, analysis = read(PROTOCOLS / 'plan.json'), read(RUNS / 'analysis.json')
    parameter, conclusion = read(RUNS / 'parameter_analysis.json'), read(RUNS / 'conclusion.json')
    assert analysis['status'] == 'PASS' and parameter['status'] in ('PASS', 'NOT_APPLICABLE')
    for name, digest in plan['source_files'].items():
        assert file_hash(SRC / name) == digest
    report = SRC.parent / 'others/report.md'
    before = report.read_bytes()
    subprocess.run([str(ROOT / '.venv/Scripts/python.exe'), str(SRC / 'write_report.py')], cwd=ROOT, check=True, capture_output=True)
    assert before == report.read_bytes()
    lint = subprocess.run([str(ROOT / '.venv/Scripts/ruff.exe'), 'check', str(SRC)], cwd=ROOT, check=True, capture_output=True, text=True)
    write(RUNS / 'reproduction.json', {'source_files': {p.relative_to(SRC).as_posix(): {'sha256': file_hash(p), 'source': p.read_text(encoding='utf-8')}
        for p in SRC.rglob('*.py')}, 'baseline_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'counts': conclusion, 'resources': plan['resources'], 'report_sha256': file_hash(report),
        'report_regeneration': 'EXACT_EQUAL', 'ruff': lint.stdout.strip(),
        'retention': 'Native prepared/data/source assets remain required; Git alone is not a complete data backup.'})
    accounts = {label: EvidenceRef.from_dict(ref) for label, ref in read(RUNS / 'account_references.json').items()}
    if parameter['status'] == 'PASS':
        accounts.update({row['label']: EvidenceRef.from_dict(row['reference']) for row in read(RUNS / 'parameter_matrix.json')['rows']})
    materials = {name: EvidenceRef.from_dict(ref) for name, ref in read(PROTOCOLS / 'plan_references.json').items()}
    materials.update({'previous39-' + name: EvidenceRef.from_dict(ref) for name, ref in plan['diagnosis_references'].items()})
    materials['geometry'] = EvidenceRef.from_dict(read(PROTOCOLS / 'geometry_reference.json'))
    materials.update({name: EvidenceRef.from_dict(ref) for name, ref in read(PROTOCOLS / 'technical_proof_references.json').items()})
    ctx = context(1)
    for directory in (PROTOCOLS, RUNS):
        for path in directory.glob('*.json'):
            if path.name in ('plan.json', 'authorization.json', 'geometry.json', 'delivery_validation.json'):
                continue
            # Explicit correction proofs already have canonical public names.
            # Preserve that reference instead of minting a second name for the same bytes.
            if any(ref.experiment == EXPERIMENT and ref.sha256 == file_hash(path)
                   and ref.media_type == 'application/json' for ref in materials.values()):
                continue
            name = ('protocols' if directory == PROTOCOLS else 'runs') + '-' + path.stem.replace('_', '-')
            assert name not in materials
            materials[name] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(), 'application/json', 'json'))
    entries = []
    for label in ('B0-TIME', 'N0', 'N1', 'N2', 'N3'):
        row = analysis['rows'][label]
        if row['qualified']:
            entries.append(d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013', row['candidate_id']), row['content_sha256']),
                '原策略完整账户不可变对照' if label == 'B0-TIME' else '下跌空仓原资格机会附加严格价格方向门，保留原确认和持仓退出',
                '原四门达标；参数结果与反证完整保留，未正式阶段四交接或冻结', (d.EvaluationEvidenceRef(accounts[label]),)))
    summary = d.SearchSummary(plan['name'], '事前固定RAW/MEAN×两价格门，公共TDR完整账户和串行/spawn一致预检',
        '原S013数据/四经济目标/13完整域/执行与基准，类别谓词新结构披露',
        conclusion['mechanism_actual_evaluations'] + conclusion['parameter_actual_evaluations'],
        conclusion['new_mechanism_business_accounts'] + conclusion['new_parameter_business_accounts'],
        f"4新完整中心/2旧背景复用，{conclusion['new_qualified']}新四门达标，新增参数配置{conclusion['new_parameter_business_accounts']}",
        ('反复使用已见开发池；单步谓词不是新策略利润', '限制入场可能删掉恢复或损害交易次数',
         'FULL仅证据完整性；13维扰动不证明新类别本身稳定'),
        (materials['runs-analysis'], materials['runs-parameter-analysis'], materials['runs-conclusion']))
    payload = d.CandidateSet(tuple(entries), (), (summary,), '全部失败完整账户保留，仅四门达标新中心列候选，未推进正式阶段四或生产。')
    evidence, report_text = {}, before.decode('utf-8') + '\n## 正式证据引用\n\n'
    for name, ref in {**accounts, **materials}.items():
        assert file_hash(ref.resolve(ROOT)) == ref.sha256
        if ref.repository_path in evidence:
            assert evidence[ref.repository_path] == ref
        evidence[ref.repository_path] = ref
        report_text += f'- [{name}](../../../assets/deliveries/CANDIDATES/36/{ref.path})\n'
    receipt = assemble_delivery(ctx.repository, d.DeliveryDefinition(ctx.batch, d.DeliveryStage.CANDIDATES, 36,
        (d.DeliveryReference.from_dict(plan['mandate']), d.DeliveryReference.from_dict(plan['previous_delivery']))),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (), report=report_text, evidence=tuple(evidence.values())))
    validation = validate_delivery(ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    assert validation.status.value == 'PASS', validation.to_dict()
    write(PROTOCOLS / 'delivery_reference.json', receipt.reference.to_dict())
    write(RUNS / 'delivery_validation.json', {'status': 'PASS', 'reference': receipt.reference.to_dict(),
        'validation': validation.to_dict(), 'counts': conclusion})
    print({'FULL': 'PASS', 'delivery': receipt.reference.to_dict(), 'objective_achieved': conclusion['objective_achieved']}, flush=True)


if __name__ == '__main__':
    main()
