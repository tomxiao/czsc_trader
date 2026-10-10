"""Prospective complete local factorial, direction countertest, no threshold search."""
from copy import deepcopy
from strategy_runtime import StrategyRuntime,StrategyCandidate,implementation_sha256
from czsc_trader.application import publish_evidence,validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d
from common import ROOT,SRC,PROTOCOLS,RUNS,EXPERIMENT,DEPENDENCIES,read,write,file_hash,context

def main():
    assert not (PROTOCOLS/'plan.json').exists()
    ctx=context(1)
    previous=read(ROOT/'research/S013/experiments/EX013_20261011/protocols/plan.json')
    controls=[]
    for c in previous['controls']:
        cfg=deepcopy(c)
        cfg.update(label=c['background']+'-TIME',mechanism='TIME',reuse_from='EX012_20261011',reuse_label=c['label'])
        controls.append(cfg)
    for label,bg in [('N1','B0'),('N3','B1')]:
        cfg=deepcopy(next(c for c in previous['configurations'] if c['label']==label))
        cfg.update(label=bg+'-NONE',background=bg,mechanism='NONE',reused=True,
            reuse_from='EX013_20261011',reuse_label=label,source_directory='no_timer/strategy_runtime')
        controls.append(cfg)
    for cfg in controls:
        ident=StrategyRuntime().identify(StrategyCandidate('S013',cfg['candidate_id'],cfg['payload'],SRC/cfg['source_directory']),dependencies=DEPENDENCIES)
        assert ident.content_sha256==cfg['content_sha256']
    configs=[]
    cells=[]
    for bg,acf,hold in [('B0',.1,4),('B1',.045,4),('B2',.1,3),('B3',.045,3)]:
        for mechanism,direction in [('TIME',None),('NONE',None),('DOWN',-1),('UP',1)]:
            if mechanism=='TIME' and bg!='B3':
                cfg=next(c for c in controls if c['background']==bg and c['mechanism']==mechanism)
            elif mechanism=='NONE':
                cfg=next(c for c in controls if c['background']==('B0' if acf==.1 else 'B1') and c['mechanism']=='NONE')
            else:
                payload=deepcopy(controls[0]['payload'])
                payload['parameters']['bear'].update(acf_min=acf,max_hold=hold)
                source_directory='original/strategy_runtime' if mechanism=='TIME' else 'strategy_runtime'
                if direction is not None:
                    payload['parameters']['exit_confirmation']={'direction':direction}
                    payload['runtime'].update(module='strategy_runtime.strategies.price_confirmed_exit',qualname='PriceConfirmedExitRange')
                    payload['runtime']['source_files'].append('strategies/price_confirmed_exit.py')
                payload['runtime']['source_sha256']=implementation_sha256(payload['runtime']['source_files'],source_root=SRC/source_directory)
                identifier=f'C{7300+len(configs)}'
                assert not (ROOT/f'research/registrations/S013/candidates/{identifier}.json').exists()
                ident=StrategyRuntime().identify(StrategyCandidate('S013',identifier,payload,SRC/source_directory),dependencies=DEPENDENCIES)
                cfg={'index':len(configs),'label':f'N{len(configs)}','background':bg,'mechanism':mechanism,'mode':'M1',
                    'candidate_id':identifier,'content_sha256':ident.content_sha256,'payload':payload,
                    'source_directory':source_directory,'existing_identity':None,'reused':False}
                configs.append(cfg)
            cells.append({'background':bg,'mechanism':mechanism,'label':cfg['label'],'candidate_id':cfg['candidate_id'],'content_sha256':cfg['content_sha256']})
    assert len(configs)==9 and len(controls)==5 and len(cells)==16
    auth={'date':'2026-10-11','source':'direct human instruction in this conversation',
        'exact_user_message':'授权你可以自主完成目标，无需评审',
        'scope':'Autonomously design and execute mechanisms and necessary parameter-sensitivity diagnostics toward the existing objective; prior per-experiment review requirement waived. Existing S013 data, contract and four economic gates remain.',
        'boundaries':'No production, PTE, freeze, new external data/dependencies, merge/tag/push or adjacent batch reads.'}
    write(PROTOCOLS/'authorization.json',auth)
    mandate=d.DeliveryReference.from_dict(previous['mandate'])
    validation=validate_delivery(ctx.repository,mandate,scope=d.DeliveryValidationScope.FULL)
    assert validation.status is d.ValidationStatus.PASS
    write(RUNS/'mandate_validation.json',validation.to_dict())
    plan={'name':'S013-EX014-price-conditioned-bear-exit','configurations':configs,'controls':controls,'cells':cells,
        'mandate':mandate.to_dict(),'authorization':auth,
        'hypotheses':{'DOWN':'At age>=H, sell only when Close(T)<=Close(previous actual trading session); let rising rebound continue.',
            'UP':'At age>=H, sell only when Close(T)>=Close(previous actual trading session); allow waiting for recovery on down days. Competing direction, not assumed inferior.',
            'TIME':'Original unconditional age exit.','NONE':'Existing no-timer account control.'},
        'preserved':'Original level buy gate, bear filter, bull route/timer, range/regime exit, priority, zero cooldown, T known/T+1 execution. Equality passes both direction tests. No extra lookback or numeric threshold.',
        'interpretation':'Complete 2x2 acf(.1,.045) x H(4,3) backgrounds avoids assuming no interaction; all directions fixed before accounts. Existing-cycle future returns are descriptive labels only.',
        'counts':{'new_business_accounts':9,'reused_controls':5,'shown_cells':16,'content_identities':14,'preflight_duplicate':1,'planned_new_evaluations':10},
        'preflight':'Synthetic causal/branch check, serial/spawn one representative new account, reuse serial result in fixed queue.',
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts},
        'acceptance':'Four original economic gates only. If a candidate improves local responses and meets gates, run necessary complete 5%/32-point parameter diagnostic with explicit preregistration, no additional economic veto.',
        'limits':'Already seen development pool. One-day price direction is not a predictive probability; extending positions can increase loss and reduce frequency. No independent validation or PTE selection.'}
    write(PROTOCOLS/'plan.json',plan)
    refs={}
    folder=ROOT/'research/S013/materials/conditional_exit_review_20261011'
    for name,path,media,suffix in [('authorization',PROTOCOLS/'authorization.json','application/json','json'),
        ('prospective-plan',PROTOCOLS/'plan.json','application/json','json'),
        ('existing-cycle-diagnostic',folder/'diagnostic.json','application/json','json'),
        ('diagnostic-source',folder/'diagnose.py','text/plain','py')]:
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'price-exit-'+name,path.read_bytes(),media,suffix)).to_dict()
    write(PROTOCOLS/'plan_references.json',refs)
    print({'declared':EXPERIMENT.experiment_id,'new_accounts':9,'controls':5,'all_cells':16},flush=True)

if __name__=='__main__':
    main()
