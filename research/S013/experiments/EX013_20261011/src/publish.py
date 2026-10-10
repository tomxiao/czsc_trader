"""Publish fixed-account outcomes and immutable stage-three successor report."""
# ruff: noqa: E402
import os
for variable in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[variable]='1'
import subprocess
from importlib.metadata import version
from czsc_trader.application import publish_evidence,publish_evidence_many,assemble_delivery,validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite,EvaluationEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools import delivery as d
from strategy_manager import CandidateKey
from common import ROOT,SRC,PROTOCOLS,RUNS,CACHE,EXPERIMENT,WORKERS,read,write,cache_read,context,file_hash

def main():
    ctx=context()
    analysis=read(RUNS/'analysis.json')
    assert analysis['status']=='PASS'
    plan=read(PROTOCOLS/'plan.json')
    assert not any(analysis['rows'][c['label']]['qualified'] for c in plan['configurations'])
    for path,digest in plan['source_files'].items():
        assert file_hash(SRC/path)==digest
    requests=[]
    for config in plan['configurations']:
        bound,result=cache_read(CACHE/(config['label']+'.pkl.gz'))
        requests.append(EvaluationEvidenceWrite(EXPERIMENT,'ablation-account-'+config['label'].lower(),bound,result))
    outcomes=publish_evidence_many(ctx,tuple(requests))
    assert all(o.status.value=='PUBLISHED' for o in outcomes),[(o.status,o.error) for o in outcomes]
    refs={c['label']:o.reference for c,o in zip(plan['configurations'],outcomes,strict=True)}
    for label,reuse in analysis['control_reuse'].items():
        refs[label]=EvidenceRef.from_dict(reuse['reference'])
    write(RUNS/'account_references.json',{label:ref.to_dict() for label,ref in refs.items()})
    reproduction={'baseline_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'files':{p.relative_to(SRC).as_posix():{'sha256':file_hash(p),'source':p.read_text(encoding='utf-8')} for p in SRC.rglob('*.py')},
        'versions':{name:version(name) for name in ('numpy','pandas','optuna','czsc-strategy-runtime')},
        'resources':{'max_workers':WORKERS,'native_threads':1,'request_workers':1,'seed':13},
        'counts':{'new_business_configurations':5,'new_account_evaluations':6,'historical_controls_reused':3,'shown_cells':12,'content_identities':8},
        'retention':'Retain S013 native data/prepared input bindings, original EX012 accounts, EX013 full accounts and source/evidence. .tmp caches are regenerable transport only.',
        'technical_notes':['Analysis caller initially compared frozen tuples directly to JSON lists; normalized to canonical JSON and repeated summaries without replay.',
            'No unknown minutes reconstructed; known low discrepancy potential orders zero for all eight accounts.'],
        'method':'Public typed prepare, serial/spawn exact full-account preflight; fixed Optuna queue and public FULL evaluate_many; no adaptive parameter search.'}
    write(RUNS/'reproduction.json',reproduction)
    material_paths=list(PROTOCOLS.glob('*.json'))+[RUNS/name for name in (
        'mandate_validation.json','synthetic_check.json','precheck.json','matrix.json','analysis.json',
        'interaction.json','helper_provenance.json','account_references.json','reproduction.json')]
    materials={}
    for path in material_paths:
        name='ablation-'+path.stem.replace('_','-')
        assert name not in materials
        materials[name]=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,name,path.read_bytes(),'application/json','json'))
    report=(SRC.parent/'others/report.md').read_text(encoding='utf-8')
    report+='\n## 正式证据引用\n\n'
    for label,ref in refs.items():
        report+=f'- [{label}完整账户](../../../assets/deliveries/CANDIDATES/8/{ref.path})\n'
    for name,ref in materials.items():
        report+=f'- [{name}](../../../assets/deliveries/CANDIDATES/8/{ref.path})\n'
    center=analysis['rows']['B0-M1']
    entry=d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013','C2132'),center['content_sha256']),
        '原机制的不可变完整账户控制，本轮核对后复用。',
        '原四门通过；当前不投入PTE的决定保持。五个删项机制未达标，未新增登记或阶段四交接。',
        (d.EvaluationEvidenceRef(refs['B0-M1']),))
    summary=d.SearchSummary(plan['name'],
        'Optuna前瞻固定五配置；TDR FULL；公开准备、串行/spawn精确预检、4个批量新账户，3个原对照完整序列化精确核对后复用。',
        'S013既有开发池、统一1%执行合同、单侧10bp、原四项经济目标；关闭参数事前归一，不新增阈值或期限。',
        6,5,'五个新配置全量完成，无新增四门达标配置；另有3个原控制、12展示格和8个内容身份。',
        ('已见开发池，非独立验证','两条局部参数交互，不替代全部参数32点自检','关闭坐标失效不构成稳健性证据'),
        (materials['ablation-analysis'],materials['ablation-interaction'],materials['ablation-precheck']))
    payload=d.CandidateSet((entry,),(),(summary,),
        '过滤和定时退出各有价值，路径交互明确；取消后收益/风险/频率存在代价，五新配置未同时达标。'
        '原交接和历史排序保持；继续阶段三，条件退出是下一轮待评审假说，未批准阶段四、选型或PTE。')
    mandate=d.DeliveryReference.from_dict(plan['mandate'])
    receipt=assemble_delivery(ctx.repository,d.DeliveryDefinition(ctx.batch,d.DeliveryStage.CANDIDATES,8,(mandate,)),
        d.DeliveryContent(payload,d.DeliveryStatus.COMPLETE,(),(),report=report,
            evidence=tuple(refs.values())+tuple(materials.values())))
    validation=validate_delivery(ctx.repository,receipt.reference,scope=d.DeliveryValidationScope.FULL)
    assert validation.status is d.ValidationStatus.PASS,validation.to_dict()
    write(PROTOCOLS/'delivery_reference.json',receipt.reference.to_dict())
    write(RUNS/'delivery_validation.json',{'status':'PASS','reference':receipt.reference.to_dict(),'validation':validation.to_dict(),
        'new_accounts':5,'reused_controls':3,'new_candidate_registrations':0,'new_qualified_configurations':0})
    print({'delivery':receipt.reference.to_dict(),'full_validation':'PASS','new_qualified':0},flush=True)

if __name__=='__main__':
    main()
