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
    for mechanism in ('NEW_BULL_CLOSE_UP','NEW_BULL_BODY_UP'):
        for control in controls:
            p=deepcopy(control['payload'])
            p['parameters']['mechanism']=mechanism
            p['runtime'].update(module='strategy_runtime.strategies.mechanism_range',qualname='MechanismRange')
            p['runtime']['source_files'].append('strategies/mechanism_range.py')
            p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=SRC/'strategy_runtime')
            number=len(configurations)
            candidate=StrategyCandidate('S013',f'C{9100+number}',p,SRC/'strategy_runtime')
            ident=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
            cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,
                'content_sha256':ident.content_sha256,'payload':p,'source_directory':'strategy_runtime',
                'background':control['background'],'mechanism':mechanism,'mode':'M1','existing_identity':None,'reused':False}
            configurations.append(cfg)
            cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX020-new-bull-known-price-direction','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'hypotheses':{'NEW_BULL_CLOSE_UP':'Only a raw bear-to-bull transition entry additionally requires current signal Close > preceding actual-session signal Close, AND original buy score. Stable bull entry unchanged.',
            'NEW_BULL_BODY_UP':'Same new-bull entry scope with current signal Close > same-session Open. Stable bull entry unchanged; intraday recovery differs from close-to-close recovery.'},
        'prospective_control_reuse':'Original H4/H3 centers reused. Every qualified new center gets full 32-point diagnostics plus exact reuse of original H4 EX015/H3 EX017 32 points each; H3 diagnostic control is unqualified and not promoted.',
        'predeclared_selection':'All four fixed centers reported, all original-four-gate qualifiers get full same-domain 13-coordinate 5%/32-point diagnostics, all matched coordinates retained. No metric-selected samples or added economic gate.',
        'counts':{'new_business_configurations':4,'new_evaluations':5,'reused_controls':2},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'S013 existing data, four economic gates, original execution and binary position. Bear and stable bull entry, original score, all holding exits/priority remain original TIME. Direction rejects only eligible flat entry at raw bear-to-bull transition.',
        'signal_units':'Same bound HFQ signal prices and raw regime definition. Momentum first computed on full warmup daily then shifted(1) before session reindex; warmup max(parent,regime_window+2). Current and previous raw state equality are bull; missing prior state/close not filled.',
        'information_hypothesis':'Rolling-window momentum can cross threshold because its old reference price rolls out, while current close is falling. A known same-day price-direction check only at new-bull entry may distinguish this boundary-switch mechanism without filtering every stable bull pullback. It does not assert all transitions are spurious or prove price recovery predicts return.',
        'limits':'EX017 two-day state confirmation qualified only H3 but worsened parameter tails; EX018 voting failed frequency; EX019 all-bull price gates failed four gates, H4 reduced drawdown but only97/99closed. Conditional scope is a new falsifiable structural information hypothesis after those counterexamples, not a tuned time/spacing threshold. It may merely do fewer trades, retain losing stable-bull entries, or buy later; price and raw state can be mechanically correlated. Same already seen S013 development pool; no independent data or new tunable numeric coordinate.',
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
