"""Assemble a local, complete zero-new-account evidence delivery."""
import subprocess
from common import ROOT, SRC, PROTOCOLS, RUNS, OUTPUT, EXPERIMENT, context, read, write, file_hash
from native_reference import verified_json
from diagnose import source_check
from czsc_trader.application import publish_evidence, assemble_delivery, validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite, delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateKey


def same_blob(a, b):
    return (a.experiment == b.experiment and a.evidence_id == b.evidence_id and a.sha256 == b.sha256
            and a.media_type == b.media_type and a.schema == b.schema and a.schema_version == b.schema_version)


def main():
    plan = source_check()
    assert not (PROTOCOLS / 'delivery_reference.json').exists()
    output = read(OUTPUT)
    assert output['status'] == 'PASS' and len(output['audits']) == 33 and len(output['pairs']) == 32
    conclusion = read(RUNS / 'conclusion.json')
    assert conclusion == read(PROTOCOLS / 'decision.json') and not conclusion['objective_achieved']
    assert output['summary']['new_account_evaluations'] == output['summary']['new_account_preparations'] == 0
    report = SRC.parent / 'others/report.md'
    before = report.read_bytes()
    subprocess.run([str(ROOT / '.venv/Scripts/python.exe'), str(SRC / 'report.py')], check=True, cwd=ROOT, capture_output=True)
    assert before == report.read_bytes()
    lint = subprocess.run([str(ROOT / '.venv/Scripts/ruff.exe'), 'check', str(SRC)], check=True, cwd=ROOT, capture_output=True, text=True)
    ctx = context(1)
    materials = {'plan': EvidenceRef.from_dict(read(PROTOCOLS / 'plan_reference.json'))}
    materials.update({name: EvidenceRef.from_dict(ref) for name, ref in plan['supplemental_evidence'].items()})
    for name, path in (('complete-single-coordinate-observed-state', OUTPUT),
                       ('pure-coordinate-checks', ROOT / '.tmp/ex047-coordinate-prototype/focused.json'),
                       ('research-conclusion', RUNS / 'conclusion.json')):
        materials[name] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(), 'application/json', 'json'))
    reproduction = {'source_files': {p.name: {'sha256': file_hash(p), 'source': p.read_text(encoding='utf-8')}
        for p in SRC.glob('*.py')}, 'external_source_files': plan['external_source_files'],
        'report_sha256': file_hash(report), 'ruff': lint.stdout.strip(),
        'baseline_commit': subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True, cwd=ROOT).stdout.strip(),
        'source_execution': 'Full diagnostic scripts saved under formal src. Pure focused helper supports formal source but output stays .tmp. Supplement contrast scripts originally execute in .tmp/ex046-native-contrast; archive source bytes do not assert arbitrary relocation compatibility.',
        'unique_native_accounts_full_coordinate_diagnosis': 33, 'supplemental_actual_centers': 2,
        'new_account_evaluations': 0, 'new_business_configurations': 0, 'objective_achieved': False,
        'retention': 'All original bound data/candidate source/native formal evidence and supplemental2 accounts remain required; Git alone is not a data asset backup.'}
    write(RUNS / 'reproduction.json', reproduction)
    materials['reproduction'] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, 'reproduction',
        (RUNS / 'reproduction.json').read_bytes(), 'application/json', 'json'))
    accounts = {name: EvidenceRef.from_dict(ref) for name, ref in output['input_accounts'].items()}
    contrast = verified_json(plan['supplemental_evidence']['native-contrast'])
    for name, audit in contrast['public_native_audits'].items():
        accounts['EX046-' + name] = EvidenceRef.from_dict(audit['reference'])
    assert len(accounts) == 35
    entries = (
        d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013', 'C2132'),
            output['audits']['center']['public_identity']['content_sha256']),
            '原四门达标的参数诊断中心', '32共同参数点绝对尾部仍脆弱；零新增金融账户',
            (d.EvaluationEvidenceRef(accounts['center']),)),
        d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013', 'C4900'),
            contrast['public_native_audits']['old']['content_sha256']),
            '既有四门达标的反证对照', '已有绝对尾部更差；类别过期后新中心未过收益门',
            (d.EvaluationEvidenceRef(accounts['EX046-old']),)))
    search = d.SearchSummary(plan['name'], '原33完整13坐标正反单步诊断，2既有中心增量反证',
        '原目标、完整13域及同32坐标保持，逐日观察state不传播', 0, 0,
        '35既有账户精确复用；新增金融评价0，非独立样本',
        ('已反复查看开发池', '触发次数不可相加或解释为收益贡献', '技术通过不代表总目标完成'),
        (materials['complete-single-coordinate-observed-state'], materials['research-conclusion']))
    payload = d.CandidateSet(entries, (), (search,), 'EX047诊断完成；参数敏感性改善目标继续。')
    evidence, report_text = {}, report.read_text(encoding='utf-8') + '\n## 正式证据引用\n\n'
    for name, ref in {**accounts, **materials}.items():
        assert ref.experiment.strategy_id == 'S013' and file_hash(ref.resolve(ROOT)) == ref.sha256
        if ref.repository_path in evidence:
            assert same_blob(evidence[ref.repository_path], ref)
        else:
            evidence[ref.repository_path] = ref
        report_text += f'- [{name}](../../../assets/deliveries/CANDIDATES/43/{ref.path})\n'
    receipt = assemble_delivery(ctx.repository, d.DeliveryDefinition(ctx.batch, d.DeliveryStage.CANDIDATES, 43,
        (d.DeliveryReference.from_dict(plan['mandate']), d.DeliveryReference.from_dict(plan['previous_delivery']))),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (), report=report_text, evidence=tuple(evidence.values())))
    validation = validate_delivery(ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    assert validation.status.value == 'PASS', validation.to_dict()
    write(PROTOCOLS / 'delivery_reference.json', receipt.reference.to_dict())
    write(RUNS / 'delivery_validation.json', {'status': 'PASS', 'reference': receipt.reference.to_dict(),
        'validation': validation.to_dict(), 'unique_native_accounts': 35, 'new_account_evaluations': 0,
        'objective_achieved': False})
    print({'FULL': 'PASS', 'delivery': receipt.reference.to_dict(), 'objective_achieved': False}, flush=True)


if __name__ == '__main__':
    main()
