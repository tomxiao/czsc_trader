"""Immutable mechanism delivery, exact report regeneration and evidence validation."""
from common import ROOT, SRC, PROTOCOLS, RUNS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence, assemble_delivery, validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite, delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateKey
import subprocess
from importlib.metadata import version


def main():
    assert not (PROTOCOLS/'delivery_reference.json').exists()
    plan=read(PROTOCOLS/'plan.json')
    a=read(RUNS/'analysis.json')
    p=read(RUNS/'parameter_analysis.json')
    conclusion=read(RUNS/'conclusion.json')
    assert a['status']=='PASS' and p['status'] in ('PASS','NOT_APPLICABLE')
    for relative,digest in plan['source_files'].items():
        assert file_hash(SRC/relative)==digest
    report_path=SRC.parent/'others/report.md'
    before=report_path.read_bytes()
    subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(SRC/'write_report.py')],cwd=ROOT,check=True,capture_output=True)
    assert before==report_path.read_bytes()
    lint=subprocess.run([str(ROOT/'.venv/Scripts/ruff.exe'),'check',str(SRC)],cwd=ROOT,check=True,capture_output=True,text=True)
    reconstruction={'baseline_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                    'files':{f.relative_to(SRC).as_posix():{'sha256':file_hash(f),'source':f.read_text(encoding='utf-8')} for f in SRC.rglob('*.py')},
                    'versions':{name:version(name) for name in ('numpy','pandas','optuna','czsc-strategy-runtime')},
                    'resources':plan['resources'],'counts':{key:conclusion[key] for key in ('new_mechanism_business_accounts','mechanism_actual_evaluations','new_parameter_business_accounts','parameter_actual_evaluations','reused_parameter_accounts')},
                    'ruff':lint.stdout.strip(),'report_regeneration':'EXACT_EQUAL',
                    'retention':'All S013 prepared/input assets, original native accounts and source snapshots required; Git and regenerable .tmp transports alone are not a full data backup.'}
    write(RUNS/'reproduction.json',reconstruction)
    refs={label:EvidenceRef.from_dict(ref) for label,ref in read(RUNS/'account_references.json').items()}
    if p['status']=='PASS':
        refs.update({row['label']:EvidenceRef.from_dict(row['reference']) for row in read(RUNS/'parameter_matrix.json')['rows']})
    materials={name:EvidenceRef.from_dict(value) for name,value in read(PROTOCOLS/'plan_references.json').items()}
    materials['geometry']=EvidenceRef.from_dict(read(PROTOCOLS/'geometry_reference.json'))
    materials.update({'EX033-'+name:EvidenceRef.from_dict(ref) for name,ref in plan['diagnosis_references'].items()})
    primary=read(materials['EX033-paths'].resolve(ROOT))
    refs.update({'EX033-native-'+label:EvidenceRef.from_dict(ref) for label,ref in primary['input_accounts'].items()})
    ctx=context(1)
    for path in [*PROTOCOLS.glob('*.json'),*RUNS.glob('*.json')]:
        if path.name in ('plan.json','authorization.json','geometry.json','delivery_validation.json'):
            continue
        if path.name=='parameter_analysis.json' and p['status']=='PASS':
            materials['parameter-analysis']=EvidenceRef.from_dict(read(PROTOCOLS/'parameter_analysis_references.json')['analysis'])
            continue
        name='final-'+path.stem.replace('_','-')
        assert name not in materials
        materials[name]=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,name,path.read_bytes(),'application/json','json'))
    entries=[]
    for label in ('B0-TIME','N0'):
        row=a['rows'][label]
        if label=='N0' and not row['qualified']:
            continue
        entries.append(d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013',row['candidate_id']),row['content_sha256']),
            '原策略不可变对照' if label=='B0-TIME' else 'bear TIME退出后等待原范围入场机会刷新再买，原买入确认及其他规则保持',
            '原四門达标；参数诊断及负面证据保留，非正式阶段四/PTE选择',(d.EvaluationEvidenceRef(refs[label]),)))
    summary=d.SearchSummary(plan['name'],'事前固定1机制队列与公共TDR完整账户，串行/spawn预检',
        '原S013数据、四经济要求、13完整域、统一执行与基准；无固定等待天数或新数值阈值',
        conclusion['mechanism_actual_evaluations']+conclusion['parameter_actual_evaluations'],
        conclusion['new_mechanism_business_accounts']+conclusion['new_parameter_business_accounts'],
        f"1新中心完成，{conclusion['new_qualified']}新四门达标；参数新业务配置{conclusion['new_parameter_business_accounts']}",
        ('已反复使用的开发池','阻断重复入场可能损害有利反弹与交易频率','诊断不新增硬门；FULL不是收益验证'),
        (materials['final-analysis'],materials.get('parameter-analysis',materials.get('final-parameter-analysis')),materials['final-conclusion']))
    payload=d.CandidateSet(tuple(entries),(),(summary,),'完整最小机制对照与原目标判断保留；未推进正式阶段四交接、冻结或PTE。')
    report=before.decode('utf-8')+'\n## 正式证据引用\n\n'
    evidence={}
    for name,ref in {**refs,**materials}.items():
        assert file_hash(ref.resolve(ROOT))==ref.sha256
        if ref.repository_path in evidence:
            assert evidence[ref.repository_path]==ref
        evidence[ref.repository_path]=ref
        report+=f'- [{name}](../../../assets/deliveries/CANDIDATES/30/{ref.path})\n'
    receipt=assemble_delivery(ctx.repository,d.DeliveryDefinition(ctx.batch,d.DeliveryStage.CANDIDATES,30,
        (d.DeliveryReference.from_dict(plan['mandate']),d.DeliveryReference.from_dict(plan['previous_delivery']))),
        d.DeliveryContent(payload,d.DeliveryStatus.COMPLETE,(),(),report=report,evidence=tuple(evidence.values())))
    validation=validate_delivery(ctx.repository,receipt.reference,scope=d.DeliveryValidationScope.FULL)
    assert validation.status.value=='PASS',validation.to_dict()
    write(PROTOCOLS/'delivery_reference.json',receipt.reference.to_dict())
    write(RUNS/'delivery_validation.json',{'status':'PASS','reference':receipt.reference.to_dict(),'validation':validation.to_dict(),
                                         'objective_achieved':conclusion['objective_achieved'],'report_regeneration':'EXACT_EQUAL'})
    print({'delivery':receipt.reference.to_dict(),'FULL':'PASS','objective_achieved':conclusion['objective_achieved']},flush=True)


if __name__=='__main__':
    main()
