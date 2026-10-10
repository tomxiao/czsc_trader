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
        requests.append(EvaluationEvidenceWrite(EXPERIMENT,'price-exit-account-'+config['label'].lower(),bound,result))
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
        'counts':{'new_business_configurations':9,'new_account_evaluations':18,'historical_controls_reused':5,'shown_cells':16,'content_identities':14},
        'retention':'Retain S013 native data/prepared input bindings, original EX012 accounts, EX013 full accounts and source/evidence. .tmp caches are regenerable transport only.',
        'technical_notes':['Initial batch completed eight requests; missing optional config key in caller stopped cache writes. Exact same eight requests explicitly repeated; actual 18 evaluations includes preflight duplicate. Source-only helper corrections preserved in reproduction; strategy source unchanged.'],
        'method':'Public typed prepare, serial/spawn exact full-account preflight; fixed Optuna queue and public FULL evaluate_many; no adaptive parameter search.'}
    write(RUNS/'reproduction.json',reproduction)
    material_paths=list(PROTOCOLS.glob('*.json'))+[RUNS/name for name in (
        'mandate_validation.json','synthetic_check.json','precheck.json','matrix.json','analysis.json',
        'helper_provenance.json','account_references.json','reproduction.json')]
    materials={}
    for path in material_paths:
        name='price-exit-'+path.stem.replace('_','-')
        assert name not in materials
        materials[name]=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,name,path.read_bytes(),'application/json','json'))
    report=(SRC.parent/'others/report.md').read_text(encoding='utf-8')
    report+='\n## 正式证据引用\n\n'
    for label,ref in refs.items():
        report+=f'- [{label}完整账户](../../../assets/deliveries/CANDIDATES/10/{ref.path})\n'
    for name,ref in materials.items():
        report+=f'- [{name}](../../../assets/deliveries/CANDIDATES/10/{ref.path})\n'
    center=analysis['rows']['B0-TIME']
    entry=d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013','C2132'),center['content_sha256']),
        '原机制的不可变完整账户控制，本轮核对后复用。',
        '原四门通过；当前不投入PTE的决定保持。九个价格条件及联合背景配置未达标，未新增登记或阶段四交接。',
        (d.EvaluationEvidenceRef(refs['B0-TIME']),))
    summary=d.SearchSummary(plan['name'],
        'Optuna前瞻固定九配置；TDR FULL；公开串行/spawn预检、8个批量请求、一次相同8请求技术重复；5个历史控制完整序列化精确相等。',
        'S013既有开发池、统一1%执行合同、单侧10bp、原四项经济目标；固定两种价格方向及完整2x2背景。',
        18,9,'九个新配置全量完成，无新增四门达标；5个复用控制、16展示格、14内容身份。',
        ('已见开发池，非独立验证','两条局部交互，不替代全参数32点','初次批量结果未保存，显式重复已披露'),
        (materials['price-exit-analysis'],materials['price-exit-precheck']))
    payload=d.CandidateSet((entry,),(),(summary,),
        '价格条件退出不能同时修复原四门和参数交互；九个新配置全未达标，未新增候选登记。继续阶段三。')
    mandate=d.DeliveryReference.from_dict(plan['mandate'])
    receipt=assemble_delivery(ctx.repository,d.DeliveryDefinition(ctx.batch,d.DeliveryStage.CANDIDATES,10,(mandate,)),
        d.DeliveryContent(payload,d.DeliveryStatus.COMPLETE,(),(),report=report,
            evidence=tuple(refs.values())+tuple(materials.values())))
    validation=validate_delivery(ctx.repository,receipt.reference,scope=d.DeliveryValidationScope.FULL)
    assert validation.status is d.ValidationStatus.PASS,validation.to_dict()
    write(PROTOCOLS/'delivery_reference.json',receipt.reference.to_dict())
    write(RUNS/'delivery_validation.json',{'status':'PASS','reference':receipt.reference.to_dict(),'validation':validation.to_dict(),
        'new_accounts':9,'reused_controls':5,'new_candidate_registrations':0,'new_qualified_configurations':0})
    print({'delivery':receipt.reference.to_dict(),'full_validation':'PASS','new_qualified':0},flush=True)

if __name__=='__main__':
    main()
