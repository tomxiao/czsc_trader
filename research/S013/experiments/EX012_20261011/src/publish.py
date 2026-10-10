"""Publish all final accounts, counterevidence, reproducible sources and stage-three report."""
# ruff: noqa: E402
import os
for variable in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[variable]='1'
from importlib.metadata import version
import subprocess
from czsc_trader.application import (publish_evidence,publish_evidence_many,assemble_delivery,validate_delivery)
from czsc_trader.research_tools import MaterialEvidenceWrite,EvaluationEvidenceWrite
from czsc_trader.research_tools import delivery as d
from strategy_manager import CandidateKey
from common import (ROOT,SRC,PROTOCOLS,RUNS,CACHE,EXPERIMENT,WORKERS,
                    read,write,context,cache_read,file_hash)

def main():
    research=context()
    analysis=read(RUNS/'analysis.json')
    assert analysis['status']=='PASS'
    assert all(r['account_audit']['known_low_error_potential_orders']==0 for r in analysis['rows'])
    final_plan=read(PROTOCOLS/'plan_r2.json')
    requests=[]
    for config in final_plan['configurations']:
        label=config['background']+'-'+config['mode']
        bound,result=cache_read(CACHE/(label+'.pkl.gz'))
        assert result.runs[0].identity.content_sha256==config['content_sha256']
        requests.append(EvaluationEvidenceWrite(EXPERIMENT,'mechanism-final-account-'+label.lower(),bound,result))
    outcomes=publish_evidence_many(research,tuple(requests))
    assert all(p.status.value=='PUBLISHED' for p in outcomes),[(p.status,p.error) for p in outcomes]
    account_refs={config['background']+'-'+config['mode']:p.reference
                  for config,p in zip(final_plan['configurations'],outcomes,strict=True)}
    write(RUNS/'account_references.json',{k:v.to_dict() for k,v in account_refs.items()})
    materials={}
    paths=list(PROTOCOLS.glob('*.json'))+[RUNS/name for name in (
        'synthetic_check.json','precheck.json','matrix.json','analysis_r1.json',
        'exact_tie_precheck.json','numeric_correction.json','analysis.json','account_references.json')]
    for path in paths:
        name='mechanism-'+path.stem.replace('_','-')
        materials[name]=publish_evidence(research,MaterialEvidenceWrite(EXPERIMENT,name,
            path.read_bytes(),'application/json','json'))
    previous_path=ROOT/'research/S013/deliveries/CANDIDATES/6/receipt.json'
    materials['prior-candidates-receipt']=publish_evidence(research,MaterialEvidenceWrite(EXPERIMENT,
        'mechanism-prior-candidates-exact-receipt',previous_path.read_bytes(),'application/json','json'))
    reproduction={'files':{p.relative_to(SRC).as_posix():{
        'sha256':file_hash(p),'source':p.read_text(encoding='utf-8')} for p in SRC.rglob('*.py')},
        'versions':{name:version(name) for name in ('numpy','pandas','optuna','czsc-strategy-runtime')},
        'baseline_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'resources':{'max_workers':WORKERS,'native_threads':1,'request_workers':1,'seed':13},
        'retention':'Retain S013 native assets/data, formal evaluations, source snapshots and exact input bindings. .tmp is only a regenerable working cache.',
        'counts':{'business_matrix_configurations':12,'technical_content_identities':18,
                  'actual_strategy_account_evaluations':21,'serial_spawn_precheck':4,
                  'fixed_matrix_new_evaluations':11,'tie_correction_replays':6},
        'technical_attempts':['Public atomic hard links required elevated sandbox execution.',
            'Historical schema-6 mandate not re-signed; new schema-7 mandate independently restates authorized targets with exact prior bytes.',
            'Control comparison corrected to public signals.decisions and buyhold.execution fields; retained serial/spawn pair checked without further replay.',
            'Change-score floating ties corrected by exact units; six prior account attempts formally retained; exact delta source kept in a separate strategy_runtime package.'],
        'lint_scope':'New experiment scripts and both runtime source trees; copied parent unused import suppressed only in generated score_change_range.py. No full repository regression.',
        'authorization':'approved twelve business configurations; no adaptive search, external data/dependencies, phase advancement, freeze, PTE, production or remote Git actions'}
    write(RUNS/'reproduction.json',reproduction)
    materials['reproduction']=publish_evidence(research,MaterialEvidenceWrite(EXPERIMENT,
        'mechanism-reproduction',(RUNS/'reproduction.json').read_bytes(),'application/json','json'))
    # C2132 is an existing qualified control; no new change-gate strategy qualified.
    center=next(r for r in analysis['rows'] if r['background']=='B0' and r['mode']=='M1')
    assert center['qualified'] and all(not r['qualified'] for r in analysis['rows'] if r['mode'] in ('M2','M3'))
    report=(SRC.parent/'others/report.md').read_text(encoding='utf-8').rstrip()+'\n\n## 正式证据\n\n'
    for label,ref in account_refs.items():
        report+=f'- [{label}完整账户](../../../assets/deliveries/CANDIDATES/7/{ref.path})\n'
    for name,ref in sorted(materials.items()):
        report+=f'- [{name}](../../../assets/deliveries/CANDIDATES/7/{ref.path})\n'
    prior_numeric=read(RUNS/'numeric_r1_references.json')
    from czsc_trader.research_tools.evidence import EvidenceRef
    numeric_refs=tuple(EvidenceRef.from_dict(x) for x in prior_numeric)
    for ref in numeric_refs:
        report+=f'- [数值等值修正前账户：{ref.name}](../../../assets/deliveries/CANDIDATES/7/{ref.path})\n'
    entry=d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S013','C2132'),center['content_sha256']),
        '获批新执行合同下的原水平确认控制；本轮不改变候选内容',
        '原四门保持通过；未缓解已知下跌过滤和退出脆弱性，当前不投入PTE的用户决定保持。',
        (d.EvaluationEvidenceRef(account_refs['B0-M1']),))
    summary=d.SearchSummary('S013-EX012-mechanism-matrix',
        'Optuna前瞻固定3×4队列、TDR FULL账户、8进程×1原生线程；数学等值技术修正独立留证',
        '原S013开发池、统一1%合同、单侧10bp、四项原目标；不开展新阈值或权重搜索',
        21,18,'无新达标变化门；原关闭/开启确认控制不是新发现。保留全部12最终账户及6份技术原尝试。',
        ('开发池反复使用，非样本外证据','两个定向背景不是完整参数稳健性自检','正向优于反向不等于满足经济目标'),
        (materials['mechanism-analysis'],materials['mechanism-numeric-correction']))
    payload=d.CandidateSet((entry,),(),(summary,),
        '原水平门有收益作用但没有直接拦截本轮下跌状态机会；变化门损失机会且未形成新达标机制。'
        '原CANDIDATES/6交接保持；本轮不追加阶段四候选，不进入阶段四、阶段五或PTE。')
    mandate=d.DeliveryReference.from_dict(read(PROTOCOLS/'mandate_reference.json'))
    receipt=assemble_delivery(research.repository,
        d.DeliveryDefinition(research.batch,d.DeliveryStage.CANDIDATES,7,(mandate,)),
        d.DeliveryContent(payload,d.DeliveryStatus.COMPLETE,(),(),report=report,
            evidence=tuple(account_refs.values())+tuple(materials.values())+numeric_refs))
    validation=validate_delivery(research.repository,receipt.reference,scope=d.DeliveryValidationScope.FULL)
    assert validation.status is d.ValidationStatus.PASS,validation.to_dict()
    write(RUNS/'delivery_validation.json',{'status':'PASS','reference':receipt.reference.to_dict(),
        'validation':validation.to_dict(),'final_accounts':12,'retained_numeric_attempts':6,
        'new_candidate_registrations':0,'new_qualified_change_gates':0})
    write(PROTOCOLS/'delivery_reference.json',receipt.reference.to_dict())
    print({'publication':'PASS','delivery':receipt.reference.to_dict(),'full_validation':validation.to_dict()},flush=True)

if __name__=='__main__':
    main()
