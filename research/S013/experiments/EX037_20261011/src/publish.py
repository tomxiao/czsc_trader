"""Full native-account delivery, immutable negatives and honest diagnostic scope."""
import subprocess
from common import ROOT,SRC,PROTOCOLS,RUNS,EXPERIMENT,context,read,write,file_hash
from czsc_trader.application import publish_evidence,assemble_delivery,validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite,delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateKey


def main():
    assert not (PROTOCOLS/'delivery_reference.json').exists()
    plan=read(PROTOCOLS/'plan.json')
    analysis=read(RUNS/'analysis.json')
    parameter=read(RUNS/'parameter_analysis.json')
    conclusion=read(RUNS/'conclusion.json')
    assert analysis['status']=='PASS' and parameter['status'] in ('PASS','NOT_APPLICABLE')
    for path,digest in plan['source_files'].items():
        assert file_hash(SRC/path)==digest
    report=SRC.parent/'others/report.md'
    before=report.read_bytes()
    subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(SRC/'write_report.py')],cwd=ROOT,check=True,capture_output=True)
    assert before==report.read_bytes()
    lint=subprocess.run([str(ROOT/'.venv/Scripts/ruff.exe'),'check',str(SRC)],cwd=ROOT,check=True,capture_output=True,text=True)
    write(RUNS/'reproduction.json',{'source_files':{p.relative_to(SRC).as_posix():{'sha256':file_hash(p),'source':p.read_text(encoding='utf-8')} for p in SRC.rglob('*.py')},
        'baseline_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'resources':plan['resources'],'counts':conclusion,'report_sha256':file_hash(report),
        'report_regeneration':'EXACT_EQUAL','ruff':lint.stdout.strip(),
        'retention':'All native prepared/data/source assets remain required; Git alone is not a complete data backup.'})
    accounts={label:EvidenceRef.from_dict(value) for label,value in read(RUNS/'account_references.json').items()}
    if parameter['status']=='PASS':
        accounts.update({row['label']:EvidenceRef.from_dict(row['reference']) for row in read(RUNS/'parameter_matrix.json')['rows']})
    materials={name:EvidenceRef.from_dict(value) for name,value in read(PROTOCOLS/'plan_references.json').items()}
    materials.update({name:EvidenceRef.from_dict(value) for name,value in plan['diagnosis_references'].items()})
    materials['geometry']=EvidenceRef.from_dict(read(PROTOCOLS/'geometry_reference.json'))
    ctx=context(1)
    for directory in (PROTOCOLS,RUNS):
        for path in directory.glob('*.json'):
            if path.name in ('plan.json','authorization.json','geometry.json','delivery_validation.json'):
                continue
            name=('protocols' if directory==PROTOCOLS else 'runs')+'-'+path.stem.replace('_','-')
            assert name not in materials
            materials[name]=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,name,path.read_bytes(),'application/json','json'))
    entries=[]
    for label in ('B0-TIME','N0','N1'):
        row=analysis['rows'][label]
        if not row['qualified']:
            continue
        entries.append(d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013',row['candidate_id']),row['content_sha256']),
            '原策略完整账户不可变对照' if label=='B0-TIME' else '均值居中自相关背景中，下跌持仓逆向位移达到严格past20TR均值一个单位时退出',
            '原四门达标；参数结果及反证完整保留，未正式阶段四选择、冻结或PTE',(d.EvaluationEvidenceRef(accounts[label]),)))
    summary=d.SearchSummary(plan['name'],'事前固定两机制背景与公共TDR完整账户，串行/spawn一致预检',
        '原S013数据、四经济要求、13完整域、原执行与基准；新固定风险单位1与past20TR披露',
        conclusion['mechanism_actual_evaluations']+conclusion['parameter_actual_evaluations'],
        conclusion['new_mechanism_business_accounts']+conclusion['new_parameter_business_accounts'],
        f"2新完整中心、3旧中心复用，{conclusion['new_qualified']}新四门达标；参数新配置{conclusion['new_parameter_business_accounts']}",
        ('反复使用的已见开发池；路线诊断不能预测新收益','早退出可能卖掉恢复反弹、增加重复交易费用',
         'FULL仅证据完整性；原13扰动不包含新风险常量稳定性'),
        (materials['runs-analysis'],materials['runs-parameter-analysis'],materials['runs-conclusion']))
    payload=d.CandidateSet(tuple(entries),(),(summary,),'所有失败完整账户保留；仅四门达标新center列候选，未正式阶段四交接、冻结或生产。')
    report_text=before.decode('utf-8')+'\n## 正式证据引用\n\n'
    evidence={}
    for name,ref in {**accounts,**materials}.items():
        assert file_hash(ref.resolve(ROOT))==ref.sha256
        if ref.repository_path in evidence:
            assert evidence[ref.repository_path]==ref
        evidence[ref.repository_path]=ref
        report_text+=f'- [{name}](../../../assets/deliveries/CANDIDATES/33/{ref.path})\n'
    receipt=assemble_delivery(ctx.repository,d.DeliveryDefinition(ctx.batch,d.DeliveryStage.CANDIDATES,33,
        (d.DeliveryReference.from_dict(plan['mandate']),d.DeliveryReference.from_dict(plan['previous_delivery']))),
        d.DeliveryContent(payload,d.DeliveryStatus.COMPLETE,(),(),report=report_text,evidence=tuple(evidence.values())))
    validation=validate_delivery(ctx.repository,receipt.reference,scope=d.DeliveryValidationScope.FULL)
    assert validation.status.value=='PASS',validation.to_dict()
    write(PROTOCOLS/'delivery_reference.json',receipt.reference.to_dict())
    write(RUNS/'delivery_validation.json',{'status':'PASS','reference':receipt.reference.to_dict(),'validation':validation.to_dict(),'counts':conclusion})
    print({'FULL':'PASS','delivery':receipt.reference.to_dict(),'objective_achieved':conclusion['objective_achieved']},flush=True)


if __name__=='__main__':
    main()
