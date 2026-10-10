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
    for bg in ('B0',):
        origin=next(c for c in prior['cells'] if c['background']==bg and c['mechanism']=='TIME')
        cfg=deepcopy(next(c for c in prior['controls']+prior['configurations'] if c['label']==origin['label']))
        cfg.update(label=bg+'-TIME',mechanism='TIME',reuse_from='EX015_20261011',reuse_label=origin['label'],reused=True)
        controls.append(cfg)
    configurations=[]
    cells=[{k:c[k] for k in ('background','mechanism','label','candidate_id','content_sha256')} for c in controls]
    for mechanism in ('VOTE9','VOTE27'):
        for control in controls:
            p=deepcopy(control['payload'])
            p['parameters']['mechanism']=mechanism
            p['runtime'].update(module='strategy_runtime.strategies.mechanism_range',qualname='MechanismRange')
            p['runtime']['source_files'].append('strategies/mechanism_range.py')
            p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=SRC/'strategy_runtime')
            number=len(configurations)
            candidate=StrategyCandidate('S013',f'C{8500+number}',p,SRC/'strategy_runtime')
            ident=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
            cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,
                'content_sha256':ident.content_sha256,'payload':p,'source_directory':'strategy_runtime',
                'background':control['background'],'mechanism':mechanism,'mode':'M0','existing_identity':None,'reused':False}
            configurations.append(cfg)
            cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX018-fixed-neighbor-voting','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'hypotheses':{'VOTE9':'Cartesian product of bear ACF center and +/-0.033, bear H center and +/-1. Each original TIME signal machine independent; strict majority 5/9 generates one actual binary target.',
            'VOTE27':'Same nine members crossed with regime threshold center and +/-0.012; strict majority 14/27. Compare to VOTE9 to test whether regime boundary diversification helps.'},
        'fixed_neighbors':{'acf_offsets':[-.033,0.,.033],'bear_h_offsets':[-1,0,1],'regime_offsets':[-.012,0.,.012],
            'boundary_semantics':'H deliberately truncated to [1,60], regime threshold to [-.2,.2], repeated members retained with unchanged vote multiplicity. ACF finite source domain accepts interior neighbor offsets; center parameter domain remains [-.6,.5]. No failed member substitution.',
            'selection':'3% ACF and regime domain widths fixed before any EX018 evaluation; no weight, spacing, count or quorum search.'},
        'actual_account':'Members are virtual signal machines, not funded accounts. Original score gate applies per member; actual new entry need not satisfy a single center same-day gate. Actual fills never reset member age/anchor. T known inputs form one target, T+1 original execution and fees once. No averaged member returns or fractional position.',
        'predeclared_selection':'Report both full accounts. Register every original-four-gate qualifier, then run complete same-domain 13-coordinate 5%/32-point diagnostics for every qualifier; reuse verified original EX015 32 accounts. No outcome-based point replacement or new economic gate.',
        'counts':{'new_business_configurations':2,'new_evaluations':3,'reused_controls':1},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'Existing S013 data, four economic gates, original execution, binary position. Original TIME rules and buy score unchanged within each member; actual policy is explicitly changed to majority voting.',
        'limits':'EX017 entry confirmation center qualifies but absolute and matched-control parameter tails worsen. Voting may merely reproduce a median rule, reduce closed frequency, delay exits or miss reversals. Same repeatedly observed S013 pool, no independent data. Internal fixed neighborhood is distinct from external joint perturbation.',
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    ctx=context(1)
    refs={path.stem:publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+path.stem,path.read_bytes(),'application/json','json')).to_dict()
        for path in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')}
    write(PROTOCOLS/'plan_references.json',refs)
    validation=read(ROOT/'research/S013/assets/runs/EX014_20261011/mandate_validation.json')
    write(RUNS/'mandate_validation.json',validation)
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':2})

if __name__=='__main__':
    main()
