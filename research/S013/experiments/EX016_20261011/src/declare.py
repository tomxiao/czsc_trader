"""Prospective complete factorial for competing entry-relative bear exits."""
from copy import deepcopy
from strategy_runtime import StrategyRuntime,StrategyCandidate,implementation_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import ROOT,SRC,PROTOCOLS,RUNS,EXPERIMENT,DEPENDENCIES,context,read,write,file_hash

def main():
    assert not (PROTOCOLS/'plan.json').exists()
    prior=read(ROOT/'research/S013/experiments/EX015_20261011/protocols/plan.json')
    controls=[]
    for bg in ('B0','B1','B2','B3'):
        origin=next(c for c in prior['cells'] if c['background']==bg and c['mechanism']=='TIME')
        cfg=deepcopy(next(c for c in prior['controls']+prior['configurations'] if c['label']==origin['label']))
        cfg.update(label=bg+'-TIME',mechanism='TIME',reuse_from='EX015_20261011',reuse_label=origin['label'],reused=True)
        controls.append(cfg)
    configurations=[]
    cells=[{k:c[k] for k in ('background','mechanism','label','candidate_id','content_sha256')} for c in controls]
    for mechanism in ('EXIT_NONPOSITIVE','EXIT_NONNEGATIVE'):
        for control in controls:
            p=deepcopy(control['payload'])
            p['parameters']['mechanism']=mechanism
            p['runtime'].update(module='strategy_runtime.strategies.mechanism_range',qualname='MechanismRange')
            p['runtime']['source_files'].append('strategies/mechanism_range.py')
            p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=SRC/'strategy_runtime')
            number=len(configurations)
            candidate=StrategyCandidate('S013',f'C{7800+number}',p,SRC/'strategy_runtime')
            ident=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
            cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,
                'content_sha256':ident.content_sha256,'payload':p,'source_directory':'strategy_runtime',
                'background':control['background'],'mechanism':mechanism,'mode':'M1','existing_identity':None,'reused':False}
            configurations.append(cfg)
            cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX016-entry-relative-timer','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'hypotheses':{'EXIT_NONPOSITIVE':'Bear time exit requires age>=H and current known close<=entry-signal close; extend positions still above the entry-signal close.',
            'EXIT_NONNEGATIVE':'Opposite direction: bear time exit requires age>=H and current close>=entry-signal close. Equality satisfies both. The anchor is a signal price, not actual fill or net profit.'},
        'predeclared_selection':'All 8 fixed configurations reported; register every four-gate qualified configuration. If qualified mechanisms improve local reactions, complete 5%/32-point all-active-coordinate diagnostics against original using prospective common domains. No new economic robustness gate.',
        'counts':{'new_business_configurations':8,'new_evaluations':9,'reused_controls':4},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'S013-only existing data, original binary FROZEN_RULE execution, original gates, bull rules, range/regime exits and original buy-score gate. No position sizing or new execution policy.',
        'limits':'Design follows EX013-EX015 negative accounts on repeatedly seen S013 pool. Entry-signal relative price is distinct from single-day direction and confirmation score. Delaying winners may reduce frequency; price direction excludes fees and actual fill premium. No new tunable numeric coordinate.',
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    ctx=context(1)
    refs={path.stem:publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+path.stem,path.read_bytes(),'application/json','json')).to_dict()
        for path in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')}
    write(PROTOCOLS/'plan_references.json',refs)
    validation=read(ROOT/'research/S013/assets/runs/EX014_20261011/mandate_validation.json')
    write(RUNS/'mandate_validation.json',validation)
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':8})

if __name__=='__main__':
    main()
