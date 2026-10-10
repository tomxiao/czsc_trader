"""Publish full-path diagnostics with zero new account evaluations and FULL validation."""
import subprocess
from common import ROOT,SRC,PROTOCOLS,RUNS,EXPERIMENT,context,read,write,file_hash
from czsc_trader.application import publish_evidence,assemble_delivery,validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite,delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateKey


def main():
    assert not (PROTOCOLS/'delivery_reference.json').exists()
    plan=read(PROTOCOLS/'plan.json')
    correction=read(PROTOCOLS/'correction_plan.json')
    for name,digest in correction['source_files'].items():
        assert file_hash(SRC/name)==digest
    for name,digest in plan['source_files'].items():
        assert file_hash(SRC/name)==digest
    for name,digest in plan['external_source_files'].items():
        assert file_hash(ROOT/name)==digest
    report=SRC.parent/'others/report.md'
    assert report.exists()
    before=report.read_bytes()
    subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(SRC/'write_report.py')],cwd=ROOT,check=True,capture_output=True)
    assert before==report.read_bytes()
    ctx=context(1)
    materials={'plan':EvidenceRef.from_dict(read(PROTOCOLS/'plan_reference.json')),
               **{name+'-method':EvidenceRef.from_dict(value) for name,value in plan['method_references'].items()},
               **{'input-'+name:EvidenceRef.from_dict(value) for name,value in plan['input_references'].items()}}
    materials.update({name+'-method-v2':EvidenceRef.from_dict(value) for name,value in correction['method_references'].items()})
    materials.update({name:EvidenceRef.from_dict(value) for name,value in correction['proof_references'].items()})
    materials['technical-correction']=EvidenceRef.from_dict(read(PROTOCOLS/'correction_plan_reference.json'))
    for name,path in (('research-decision',PROTOCOLS/'decision.json'),
                      ('focused-original-math',ROOT/'.tmp/ex036-diagnosis/math_check.json')):
        materials[name]=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,name,path.read_bytes(),'application/json','json'))
    accounts={}
    summaries={}
    for name in ('confirmation','drawdown'):
        output=read(ROOT/'.tmp/ex036-diagnosis'/(name+'_v2.json'))
        assert output['status']=='PASS' and output['new_account_evaluations']==0
        assert output['method_reference']==correction['method_references'][name]
        for label,value in output['input_accounts'].items():
            ref=EvidenceRef.from_dict(value)
            assert ref.experiment.strategy_id=='S013' and file_hash(ref.resolve(ROOT))==ref.sha256
            accounts[name+'-'+label]=ref
        write(RUNS/(name+'_v2.json'),output)
        materials[name]=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'native-'+name+'-diagnosis-v2',
            (RUNS/(name+'_v2.json')).read_bytes(),'application/json','json'))
        summaries[name]=output['summary']
    unique={ref.repository_path:ref for ref in accounts.values()}
    assert len(unique)==34,len(unique)
    center=next(ref for ref in unique.values() if ref.sha256=='bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86')
    lint=subprocess.run([str(ROOT/'.venv/Scripts/ruff.exe'),'check',str(SRC)],cwd=ROOT,check=True,capture_output=True,text=True)
    reproduction={'source_files':{p.relative_to(SRC).as_posix():{'sha256':file_hash(p),'source':p.read_text(encoding='utf-8')} for p in SRC.glob('*.py')},
                  'external_source_files':plan['external_source_files'],'technical_correction':correction,'unique_native_accounts_reused':34,
                  'new_account_evaluations':0,'new_business_configurations':0,'report_sha256':file_hash(report),
                  'ruff':lint.stdout.strip(),'objective_achieved':False,'economic_targets':'UNCHANGED',
                  'retention':'All referenced native prepared/data/source assets remain required; Git alone is not complete data backup.'}
    write(RUNS/'reproduction.json',reproduction)
    materials['reproduction']=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'reproduction',
        (RUNS/'reproduction.json').read_bytes(),'application/json','json'))
    entries=(d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013','C2132'),
        '939e07357e59fa00b3123a5f0e775303ca1fdd9295c22bbca3f014ffda4aa8ad'),
        '原策略完整账户不可变对照','本轮只复用已有账户诊断，不新增达标配置或阶段四交接',
        (d.EvaluationEvidenceRef(center),)),)
    summary=d.SearchSummary(plan['name'],'事前冻结两项全路径方法，已有原生账户精确复用',
        '原S013数据、四项经济要求；全7年和原32点保留，零新增评价或配置',0,0,
        '34个独立原生账户复用；确认边界及年度回撤路径诊断完成，目标仍未达成',
        ('已见开发池','单步替代判断未传播状态与现金，不能作为策略收益','路线分解是描述，不是删交易后的利润'),
        (materials['confirmation'],materials['drawdown']))
    payload=d.CandidateSet(entries,(),(summary,),'本轮诊断完成；C8701保持未达标证据身份，未登记推广；总研究目标继续。')
    report_text=report.read_text(encoding='utf-8')+'\n## 正式证据引用\n\n'
    evidence={}
    for name,ref in {**accounts,**materials}.items():
        assert file_hash(ref.resolve(ROOT))==ref.sha256
        if ref.repository_path in evidence:
            assert evidence[ref.repository_path]==ref
        evidence[ref.repository_path]=ref
        report_text+=f'- [{name}](../../../assets/deliveries/CANDIDATES/32/{ref.path})\n'
    receipt=assemble_delivery(ctx.repository,d.DeliveryDefinition(ctx.batch,d.DeliveryStage.CANDIDATES,32,
        (d.DeliveryReference.from_dict(plan['mandate']),d.DeliveryReference.from_dict(plan['previous_delivery']))),
        d.DeliveryContent(payload,d.DeliveryStatus.COMPLETE,(),(),report=report_text,evidence=tuple(evidence.values())))
    validation=validate_delivery(ctx.repository,receipt.reference,scope=d.DeliveryValidationScope.FULL)
    assert validation.status.value=='PASS',validation.to_dict()
    write(PROTOCOLS/'delivery_reference.json',receipt.reference.to_dict())
    write(RUNS/'delivery_validation.json',{'status':'PASS','reference':receipt.reference.to_dict(),
        'validation':validation.to_dict(),'unique_native_accounts_reused':34,'new_account_evaluations':0,
        'objective_achieved':False})
    print({'FULL':'PASS','delivery':receipt.reference.to_dict(),'unique_reused_accounts':34,'new_evaluations':0},flush=True)


if __name__=='__main__':
    main()
