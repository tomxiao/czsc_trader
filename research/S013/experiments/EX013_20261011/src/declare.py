"""Prospectively bind the approved five new accounts and three exact controls."""
from copy import deepcopy
from strategy_runtime import StrategyRuntime, StrategyCandidate, implementation_sha256
from czsc_trader.application import publish_evidence, validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d
from common import ROOT,SRC,PROTOCOLS,RUNS,EXPERIMENT,DEPENDENCIES,read,write,context,file_hash

def main():
    assert not (PROTOCOLS/'plan.json').exists()
    ctx=context(1)
    review=ROOT/'research/S013/materials/path_ablation_review_20261011'
    approved=read(review/'proposal.json')
    prior=read(ROOT/'research/S013/experiments/EX012_20261011/protocols/plan_r2.json')
    controls=[]
    for background in ('B0','B1','B2'):
        config=deepcopy(next(c for c in prior['configurations'] if c['background']==background and c['mode']=='M1'))
        config.update(label=background+'-M1',mechanism='ORIGINAL',source_directory='original/strategy_runtime',reused=True)
        identity=StrategyRuntime().identify(StrategyCandidate('S013',config['candidate_id'],config['payload'],SRC/config['source_directory']),dependencies=DEPENDENCIES)
        assert identity.content_sha256==config['content_sha256']
        controls.append(config)
    configurations=[]
    for cell in approved['cells']:
        if cell['reuse_existing_ex012'] or any(c['key']==cell['unique_configuration'] for c in configurations):
            continue
        p=deepcopy(controls[0]['payload'])
        p['parameters']['bear'].update(acf_min=cell['bear_acf_min'],max_hold=cell['bear_max_hold'])
        source_directory='original/strategy_runtime' if cell['bear_max_hold'] is not None else 'strategy_runtime'
        source=SRC/source_directory
        p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=source)
        identifier=f'C{7200+len(configurations)}'
        assert not (ROOT/f'research/registrations/S013/candidates/{identifier}.json').exists()
        identity=StrategyRuntime().identify(StrategyCandidate('S013',identifier,p,source),dependencies=DEPENDENCIES)
        configurations.append({'index':len(configurations),'label':f'N{len(configurations)}',
            'key':cell['unique_configuration'],'mechanism':cell['mechanism'],'background':cell['background'],
            'mode':'M1','candidate_id':identifier,'content_sha256':identity.content_sha256,
            'existing_identity':None,'source_directory':source_directory,'payload':p,'reused':False})
    assert len(configurations)==len({c['content_sha256'] for c in configurations})==5
    cells=[]
    for cell in approved['cells']:
        config=next(c for c in controls if c['background']==cell['background']) if cell['reuse_existing_ex012'] else next(c for c in configurations if c['key']==cell['unique_configuration'])
        cells.append({**cell,'label':config['label'],'candidate_id':config['candidate_id'],'content_sha256':config['content_sha256']})
    auth={'source':'direct human answer to the review question in this conversation',
        'date':'2026-10-11','answer':'批准按此方案执行',
        'question':'是否批准下一轮最小删项实验：保留原买入确认与其他规则，分别取消下跌自相关过滤、取消下跌定时退出，以及同时取消两者？复用3个已有对照，仅运行5个新完整账户；沿用S013数据和四项经济目标。取消定时退出可能延长亏损持仓，结果将完整呈现。等待评审依据是你此前“先评审方案再启动新实验”的要求。',
        'approved_proposal_sha256':file_hash(review/'proposal.json')}
    write(PROTOCOLS/'authorization.json',auth)
    mandate=d.DeliveryReference.from_dict(read(ROOT/'research/S013/experiments/EX012_20261011/protocols/mandate_reference.json'))
    validation=validate_delivery(ctx.repository,mandate,scope=d.DeliveryValidationScope.FULL)
    assert validation.status is d.ValidationStatus.PASS
    write(RUNS/'mandate_validation.json',validation.to_dict())
    plan={'name':'S013-EX013-bear-rule-ablation','status':'APPROVED_PROSPECTIVE',
        'configurations':configurations,'controls':controls,'cells':cells,'mandate':mandate.to_dict(),
        'approved_proposal':approved,'authorization':auth,
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'counts':{'new_business_accounts':5,'existing_controls':3,'matrix_cells':12,
            'serial_spawn_duplicate_for_preflight':1,'planned_new_account_evaluations':6},
        'preflight':'Synthetic semantics, original integer timer equivalence, causal prefixes; one new account serial and spawn for exact signals and five ledgers; serial result reused as first of five business outcomes.',
        'identity':'Disabled parameters are normalized to None before content identity; repeat cells share one identity. Nullable timer sources are separate from unchanged original sources.',
        'stop':'Complete fixed five, retain failures and all outcomes, explain four original economic gates and local interactions. No adaptive search, no joint32-point inspection or stage advancement.',
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    refs={}
    for name,path in [('authorization',PROTOCOLS/'authorization.json'),('prospective-plan',PROTOCOLS/'plan.json'),
                      ('approved-proposal',review/'proposal.json'),('review-diagnostic',review/'diagnostic.json')]:
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'ablation-'+name,path.read_bytes(),'application/json','json')).to_dict()
    write(PROTOCOLS/'plan_references.json',refs)
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':len(configurations),'control_reuse':len(controls),'mandate_validation':'PASS'})

if __name__=='__main__':
    main()
