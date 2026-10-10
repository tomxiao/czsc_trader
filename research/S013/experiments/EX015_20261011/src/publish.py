"""Publish the final reproducible stage-three mechanism and diagnostic conclusion."""
from importlib.metadata import version
import subprocess
from czsc_trader.application import publish_evidence,assemble_delivery,validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools import delivery as d
from strategy_manager import CandidateKey
from common import ROOT,SRC,PROTOCOLS,RUNS,EXPERIMENT,context,read,write,file_hash

def main():
    assert not (PROTOCOLS/'delivery_reference.json').exists()
    ctx=context(1)
    a=read(RUNS/'analysis.json')
    p=read(RUNS/'parameter_analysis.json')
    assert a['status']==p['status']=='PASS'
    plan=read(PROTOCOLS/'plan.json')
    for path,digest in plan['source_files'].items():
        assert file_hash(SRC/path)==digest
    before=(SRC.parent/'others/report.md').read_bytes()
    subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(SRC/'write_report.py')],cwd=ROOT,check=True,capture_output=True)
    assert before==(SRC.parent/'others/report.md').read_bytes()
    lint=subprocess.run([str(ROOT/'.venv/Scripts/ruff.exe'),'check',str(SRC),'--per-file-ignores','*mechanism_range.py:F401'],
        cwd=ROOT,check=True,capture_output=True,text=True)
    reconstruction={'baseline_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'files':{path.relative_to(SRC).as_posix():{'sha256':file_hash(path),'source':path.read_text(encoding='utf-8')} for path in SRC.rglob('*.py')},
        'versions':{name:version(name) for name in ('numpy','pandas','optuna','czsc-strategy-runtime')},
        'counts':{'new_mechanism_business_accounts':12,'mechanism_actual_evaluations':13,'reused_controls':4,
            'new_parameter_business_accounts':64,'parameter_actual_evaluations':p['actual_parameter_evaluations']},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'report_regeneration':'EXACT_EQUAL bytes',
        'ruff':{'status':'PASS','per_file_ignore':'mechanism_range.py:F401 only, immutable unused Mapping import retained','output':lint.stdout.strip()},
        'technical_corrections':'Analysis cache path followed reuse to the original cache, keeping original evidence reference; public candidate registration import corrected before account publication. No strategy-source correction or mechanism account replay.',
        'retention':'All formal S013 data/prepared inputs, centers, full accounts, source snapshots, public parameter bindings and candidate C7408 remain necessary; .tmp transports are regenerable, Git is not a full data backup.'}
    write(RUNS/'reproduction.json',reconstruction)
    refs={label:EvidenceRef.from_dict(ref) for label,ref in read(RUNS/'account_references.json').items()}
    parameter_refs={row['label']:EvidenceRef.from_dict(row['reference']) for row in read(RUNS/'parameter_matrix.json')['rows']}
    materials={}
    paths=list(PROTOCOLS.glob('*.json'))+[RUNS/name for name in (
        'mandate_validation.json','synthetic_check.json','precheck.json','matrix.json','analysis.json',
        'account_references.json','registration.json','center_equivalence.json','parameter_precheck.json','parameter_matrix.json',
        'parameter_analysis.json','parameter_pairs.json','conclusion.json','reproduction.json')]
    for path in paths:
        name='final-information-'+path.stem.replace('_','-')
        assert name not in materials
        materials[name]=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,name,path.read_bytes(),'application/json','json'))
    report=before.decode('utf-8')+'\n## 正式证据引用\n\n'
    for label,ref in {**refs,**parameter_refs}.items():
        report+=f'- [{label}完整账户](../../../assets/deliveries/CANDIDATES/11/{ref.path})\n'
    for name,ref in materials.items():
        report+=f'- [{name}](../../../assets/deliveries/CANDIDATES/11/{ref.path})\n'
    entries=[]
    for label in ['B0-TIME']+[c['label'] for c in plan['configurations'] if a['rows'][c['label']]['qualified']]:
        r=a['rows'][label]
        entries.append(d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013',r['candidate_id']),r['content_sha256']),
            '原中心不可变控制' if label=='B0-TIME' else '到期且原确认分仍达标退出；中心收益/回撤与原C2132相同',
            '原四门通过；完整同域32点诊断保留。不作为PTE选择或稳健性保证。',
            (d.EvaluationEvidenceRef(refs[label]),)))
    summary=d.SearchSummary(plan['name'],
        'Optuna固定12机制+64参数配置；公共TDR FULL及串行/spawn预检，全部点保留。',
        'S013既有开发池、原统一1%合同/10bp费用、四门；前瞻声明共同13维域，5%总L2、32点/中心、seed13。',
        13+p['actual_parameter_evaluations'],76,
        '12新机制完成，1新四门达标并登记；原中心和新达标机制共64参数点完整完成；技术重复不算独立发现。',
        ('已见开发池，非独立验证','新声明共同域，不能把历史退化直接当相同量尺','邻点资格是诊断，无新增经济门'),
        (materials['final-information-analysis'],materials['final-information-parameter-analysis'],materials['final-information-conclusion']))
    payload=d.CandidateSet(tuple(entries),(),(summary,),
        '完整机制及参数对照已留证。原中心与C7408均保留，未新增正式阶段四排名/交接、阶段五选择或PTE。详见报告中的改善差与绝对退化。')
    mandate=d.DeliveryReference.from_dict(plan['mandate'])
    receipt=assemble_delivery(ctx.repository,d.DeliveryDefinition(ctx.batch,d.DeliveryStage.CANDIDATES,11,(mandate,)),
        d.DeliveryContent(payload,d.DeliveryStatus.COMPLETE,(),(),report=report,
            evidence=tuple(refs.values())+tuple(parameter_refs.values())+tuple(materials.values())))
    validation=validate_delivery(ctx.repository,receipt.reference,scope=d.DeliveryValidationScope.FULL)
    assert validation.status is d.ValidationStatus.PASS,validation.to_dict()
    write(PROTOCOLS/'delivery_reference.json',receipt.reference.to_dict())
    write(RUNS/'delivery_validation.json',{'status':'PASS','reference':receipt.reference.to_dict(),
        'validation':validation.to_dict(),'new_registered_qualified_candidates':1,'new_mechanism_business_accounts':12,
        'new_parameter_business_accounts':64,'report_regeneration':'EXACT_EQUAL','replays_after_source_snapshot':0})
    print({'final_delivery':receipt.reference.to_dict(),'full_validation':'PASS','new_qualified':1},flush=True)

if __name__=='__main__':
    main()
