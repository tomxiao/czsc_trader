"""Public immutable delivery, complete account references and source reproduction."""
from importlib.metadata import version
from hashlib import sha256
import subprocess
from czsc_trader.application import publish_evidence, assemble_delivery, validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools import delivery as d
from strategy_manager import CandidateKey
from common import ROOT,SRC,PROTOCOLS,RUNS,EXPERIMENT,context,read,write,file_hash


def main():
    assert not (PROTOCOLS/'delivery_reference.json').exists()
    analysis=read(RUNS/'analysis.json')
    parameters=read(RUNS/'parameter_analysis.json')
    assert analysis['status']=='PASS' and parameters['status'] in ('PASS','NOT_APPLICABLE')
    plan=read(PROTOCOLS/'plan.json')
    for path,digest in plan['source_files'].items():
        assert file_hash(SRC/path)==digest
    report_path=SRC.parent/'others/report.md'
    before=report_path.read_bytes()
    subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(SRC/'write_report.py')],cwd=ROOT,check=True,capture_output=True)
    assert before==report_path.read_bytes()
    lint=subprocess.run([str(ROOT/'.venv/Scripts/ruff.exe'),'check',str(SRC)],cwd=ROOT,check=True,capture_output=True,text=True)
    conclusion=read(RUNS/'conclusion.json')
    reconstruction={'baseline_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'files':{p.relative_to(SRC).as_posix():{'sha256':file_hash(p),'source':p.read_text(encoding='utf-8')} for p in SRC.rglob('*.py')},
        'versions':{name:version(name) for name in ('numpy','pandas','optuna','czsc-strategy-runtime')},
        'resources':plan['resources'],'counts':{k:conclusion[k] for k in ('new_mechanism_business_accounts','mechanism_actual_evaluations','new_parameter_business_accounts','parameter_actual_evaluations','reused_parameter_accounts')},
        'report_regeneration':'EXACT_EQUAL bytes','ruff':{'status':'PASS','output':lint.stdout.strip()},
        'retention':'All S013 data/prepared inputs, original/native full accounts, source snapshots and parameter bindings are required; .tmp transports are regenerable and Git is not a full data backup.'}
    write(RUNS/'reproduction.json',reconstruction)
    refs={label:EvidenceRef.from_dict(ref) for label,ref in read(RUNS/'account_references.json').items()}
    diagnosis_ref=EvidenceRef.from_dict(read(ROOT/'research/S013/experiments/EX016_20261011/protocols/previous_account_diagnosis_reference.json'))
    assert sha256(diagnosis_ref.resolve(ROOT).read_bytes()).hexdigest()==diagnosis_ref.sha256
    diagnosis=read(diagnosis_ref.resolve(ROOT))
    write(RUNS/'previous_diagnosis_binding.json',{'reference':diagnosis_ref.to_dict(),
        'reuse':'Exact immutable EX016 descriptive evidence; no new diagnosis or account evaluation.'})
    prior_accounts={label:EvidenceRef.from_dict(ref) for label,ref in diagnosis['input_accounts'].items()}
    prior_run=ROOT/'research/S013/assets/runs/EX017_20261011'
    previous_parameters=read(ROOT/'research/S013/experiments/EX017_20261011/protocols/parameter_analysis_references.json')
    previous_parameter_ref=EvidenceRef.from_dict(previous_parameters['analysis'])
    assert sha256(previous_parameter_ref.resolve(ROOT).read_bytes()).hexdigest()==previous_parameter_ref.sha256
    write(RUNS/'previous_parameter_counterevidence.json',{'reference':previous_parameter_ref.to_dict(),
        'reuse':'Immutable EX017 full parameter counterexample used to motivate bull price-direction gates; no new evaluation.'})
    prior_accounts.update({'EX017-'+label:EvidenceRef.from_dict(ref)
        for label,ref in read(prior_run/'account_references.json').items()})
    prior_accounts.update({'EX017-'+row['label']:EvidenceRef.from_dict(row['reference'])
        for row in read(prior_run/'parameter_matrix.json')['rows']})
    prior_accounts.update({'EX018-'+label:EvidenceRef.from_dict(ref) for label,ref in read(ROOT/'research/S013/assets/runs/EX018_20261011/account_references.json').items()})
    prior_accounts.update({'EX019-'+label:EvidenceRef.from_dict(ref) for label,ref in read(ROOT/'research/S013/assets/runs/EX019_20261011/account_references.json').items()})
    prior_accounts.update({'EX020-'+label:EvidenceRef.from_dict(ref) for label,ref in read(ROOT/'research/S013/assets/runs/EX020_20261011/account_references.json').items()})
    prior_accounts.update({'EX021-'+label:EvidenceRef.from_dict(ref) for label,ref in read(ROOT/'research/S013/assets/runs/EX021_20261011/account_references.json').items()})
    prior_accounts.update({'EX016-'+label:EvidenceRef.from_dict(ref) for label,ref in read(ROOT/'research/S013/assets/runs/EX016_20261011/account_references.json').items()})
    prior_accounts.update({'EX022-'+label:EvidenceRef.from_dict(ref) for label,ref in read(ROOT/'research/S013/assets/runs/EX022_20261011/account_references.json').items()})
    for old in ('EX023_20261011','EX024_20261011','EX025_20261011','EX026_20261011','EX027_20261011'):
        prior_accounts.update({old+'-'+label:EvidenceRef.from_dict(ref) for label,ref in read(ROOT/f'research/S013/assets/runs/{old}/account_references.json').items()})
    if parameters['status']=='PASS':
        refs.update({row['label']:EvidenceRef.from_dict(row['reference']) for row in read(RUNS/'parameter_matrix.json')['rows']})
    path_ref=EvidenceRef.from_dict(read(PROTOCOLS/'previous_path_diagnosis_reference.json'))
    assert sha256(path_ref.resolve(ROOT).read_bytes()).hexdigest()==path_ref.sha256
    path_diagnosis=read(path_ref.resolve(ROOT))
    prior_accounts.update({'EX028-path-'+label:EvidenceRef.from_dict(ref) for label,ref in path_diagnosis['input_accounts'].items()})
    material_paths=list(PROTOCOLS.glob('*.json'))+[p for p in RUNS.glob('*.json') if p.name not in ('delivery_validation.json','previous_path_diagnosis.json')]
    ctx=context(1)
    materials={'final-previous-path-diagnosis':path_ref}
    for path in material_paths:
        name='final-'+path.stem.replace('_','-')
        assert name not in materials
        materials[name]=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,name,path.read_bytes(),'application/json','json'))
    report=before.decode('utf-8')+'\n## 正式证据引用\n\n'
    for label,ref in refs.items():
        report+=f'- [{label}完整账户](../../../assets/deliveries/CANDIDATES/24/{ref.path})\n'
    for label,ref in prior_accounts.items():
        report+=f'- [既有诊断输入{label}](../../../assets/deliveries/CANDIDATES/24/{ref.path})\n'
    for name,ref in materials.items():
        report+=f'- [{name}](../../../assets/deliveries/CANDIDATES/24/{ref.path})\n'
    report+=f'- [既有年度描述归因](../../../assets/deliveries/CANDIDATES/24/{diagnosis_ref.path})\n'
    report+=f'- [原32完整账户路径描述](../../../assets/deliveries/CANDIDATES/24/{path_ref.path})\n'
    report+=f'- [EX017完整参数反证](../../../assets/deliveries/CANDIDATES/24/{previous_parameter_ref.path})\n'
    entries=[]
    for label in ['B0-TIME']+[cfg['label'] for cfg in plan['configurations'] if analysis['rows'][cfg['label']]['qualified']]:
        row=analysis['rows'][label]
        entries.append(d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013',row['candidate_id']),row['content_sha256']),
            '原中心不可变控制' if label=='B0-TIME' else '原bearACF20减严格过去lookback中位数或均值基准，原期限与买入确认保持',
            '原四门达标；参数诊断与负面证据保留，非PTE选择或未来保证。',(d.EvaluationEvidenceRef(refs[label]),)))
    actual=conclusion['mechanism_actual_evaluations']+conclusion['parameter_actual_evaluations']
    count=conclusion['new_mechanism_business_accounts']+conclusion['new_parameter_business_accounts']
    summary=d.SearchSummary(plan['name'],'Optuna事前固定机制与参数队列，公共TDR完整账户及串行/spawn预检。',
        'S013既有数据、原四门、统一1%执行合同和每侧10bp；全部13维原共同域、5%总L2、32点、seed13。',actual,count,
        f"2新机制完成，{conclusion['new_qualified']}新四门达标；参数新评价{conclusion['new_parameter_business_accounts']}点完整保留。",
        ('反复查看的开发池，非独立验证','基准适应可能引入不良机会；原确认lookback新增基准职责耦合，期限与阈值仍可能脆弱','诊断不追加经济硬门'),
        (materials['final-analysis'],materials['final-parameter-analysis'],materials['final-conclusion']))
    payload=d.CandidateSet(tuple(entries),(),(summary,),'完整对照证据保留；正式阶段四排名/交接、冻结及PTE均未推进。')
    mandate=d.DeliveryReference.from_dict(plan['mandate'])
    evidence={}
    for ref in (*refs.values(),*prior_accounts.values(),*materials.values(),EvidenceRef.from_dict(diagnosis['source']),diagnosis_ref,previous_parameter_ref,path_ref):
        if ref.repository_path in evidence:
            assert evidence[ref.repository_path]==ref
        evidence[ref.repository_path]=ref
    receipt=assemble_delivery(ctx.repository,d.DeliveryDefinition(ctx.batch,d.DeliveryStage.CANDIDATES,24,(mandate,)),
        d.DeliveryContent(payload,d.DeliveryStatus.COMPLETE,(),(),report=report,
            evidence=tuple(evidence.values())))
    validation=validate_delivery(ctx.repository,receipt.reference,scope=d.DeliveryValidationScope.FULL)
    assert validation.status.value=='PASS',validation.to_dict()
    write(PROTOCOLS/'delivery_reference.json',receipt.reference.to_dict())
    write(RUNS/'delivery_validation.json',{'status':'PASS','reference':receipt.reference.to_dict(),'validation':validation.to_dict(),
        'report_regeneration':'EXACT_EQUAL','new_registered_qualified_candidates':conclusion['new_qualified']})
    print({'final_delivery':receipt.reference.to_dict(),'full_validation':'PASS'})


if __name__=='__main__':
    main()
