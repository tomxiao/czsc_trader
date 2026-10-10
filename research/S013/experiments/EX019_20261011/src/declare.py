"""Prospective factorial for separate and joint bull regime persistence mechanisms."""
from copy import deepcopy
from strategy_runtime import StrategyRuntime,StrategyCandidate,implementation_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import ROOT,SRC,PROTOCOLS,RUNS,EXPERIMENT,DEPENDENCIES,context,read,write,file_hash

def main():
    assert not (PROTOCOLS/'plan.json').exists()
    prior=read(ROOT/'research/S013/experiments/EX015_20261011/protocols/plan.json')
    controls=[]
    for bg in ('B0','B2'):
        origin=next(c for c in prior['cells'] if c['background']==bg and c['mechanism']=='TIME')
        cfg=deepcopy(next(c for c in prior['controls']+prior['configurations'] if c['label']==origin['label']))
        cfg.update(label=bg+'-TIME',mechanism='TIME',reuse_from='EX015_20261011',reuse_label=origin['label'],reused=True)
        controls.append(cfg)
    configurations=[]
    cells=[{k:c[k] for k in ('background','mechanism','label','candidate_id','content_sha256')} for c in controls]
    for mechanism in ('BULL_CLOSE_UP','BULL_BODY_UP'):
        for control in controls:
            p=deepcopy(control['payload'])
            p['parameters']['mechanism']=mechanism
            p['runtime'].update(module='strategy_runtime.strategies.mechanism_range',qualname='MechanismRange')
            p['runtime']['source_files'].append('strategies/mechanism_range.py')
            p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=SRC/'strategy_runtime')
            number=len(configurations)
            candidate=StrategyCandidate('S013',f'C{8800+number}',p,SRC/'strategy_runtime')
            ident=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
            cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,
                'content_sha256':ident.content_sha256,'payload':p,'source_directory':'strategy_runtime',
                'background':control['background'],'mechanism':mechanism,'mode':'M1','existing_identity':None,'reused':False}
            configurations.append(cfg)
            cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX019-bull-known-price-direction','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'hypotheses':{'BULL_CLOSE_UP':'Bull flat eligible entry additionally requires current signal Close > immediately preceding actual-session signal Close, AND original buy score.',
            'BULL_BODY_UP':'Bull flat eligible entry additionally requires current signal Close > same-session Open, AND original buy score. Intraday recovery is not identical to close-to-close recovery.'},
        'prospective_control_reuse':'Original H4 and original H3 centers reused prospectively. If any new center qualifies, original H4 EX015 32 and H3 EX017 32 parameter accounts are exactly reused before new bulk evaluation; H3 is an unqualified diagnostic control, never a registered qualifier.',
        'predeclared_selection':'All four fixed accounts reported. Every original-four-gate qualifier receives complete same-domain 13-coordinate 5%/32-point diagnostics; include matched original H3 coordinates to separate gate from H3 effect. No selected-point replacement or new economic gate.',
        'counts':{'new_business_configurations':4,'new_evaluations':5,'reused_controls':2},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'Existing S013 data, four economic gates, original execution/binary position, bear entry, original score, every holding exit and priority. Only bull eligible entry receives the explicit strict-positive direction gate.',
        'signal_units':'Both Close/Open are bound HFQ research signal prices; close-to-close uses real previous trading row from complete warmup before evaluation reindex. First evaluation day is not filled with zero/true. Equality is rejected. Body may be positive after a gap down while close-to-close is negative.',
        'limits':'EX017 two-day regime confirmation qualifies only H3 center but worsens parameter tails; EX018 majority voting fails frequency and negative-year profitability. Direct known price direction is a new falsifiable entry-information hypothesis, not proof of reversal. EX014 bear exit direction failures are not direct evidence for bull entry effectiveness. Price gate may discard profitable opportunities, miss rebounds or reduce frequency; H4/H3 both reported. Same seen S013 pool, no new numeric coordinate or searched length.' ,
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    ctx=context(1)
    refs={path.stem:publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+path.stem,path.read_bytes(),'application/json','json')).to_dict()
        for path in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')}
    write(PROTOCOLS/'plan_references.json',refs)
    validation=read(ROOT/'research/S013/assets/runs/EX014_20261011/mandate_validation.json')
    write(RUNS/'mandate_validation.json',validation)
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':4})

if __name__=='__main__':
    main()
