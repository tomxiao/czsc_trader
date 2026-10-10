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
    for mechanism in ('LAG3_MEAN','LAG5_MEAN'):
        for control in controls:
            p=deepcopy(control['payload'])
            p['parameters']['mechanism']=mechanism
            p['runtime'].update(module='strategy_runtime.strategies.mechanism_range',qualname='MechanismRange')
            p['runtime']['source_files'].append('strategies/mechanism_range.py')
            p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=SRC/'strategy_runtime')
            number=len(configurations)
            candidate=StrategyCandidate('S013',f'C{9300+number}',p,SRC/'strategy_runtime')
            ident=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
            cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,
                'content_sha256':ident.content_sha256,'payload':p,'source_directory':'strategy_runtime',
                'background':control['background'],'mechanism':mechanism,'mode':'M1','existing_identity':None,'reused':False}
            configurations.append(cfg)
            cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX021-smoothed-lag-reference','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'hypotheses':{'LAG3_MEAN':'Regime R=Close_t/mean(Close at lags W-1,W,W+1)-1; original current price, threshold, confirmation, entries and exits remain.',
            'LAG5_MEAN':'Same replacement with lags W-2 through W+2; fixed mean kernel, no searched new numeric coordinate.'},
        'prospective_control_reuse':'Original H4/H3 centers reused. Every qualified new center gets full 32-point diagnostics plus exact reuse of original H4 EX015/H3 EX017 32 points each; H3 diagnostic control is unqualified and not promoted.',
        'predeclared_selection':'All four fixed centers reported, all original-four-gate qualifiers get full same-domain 13-coordinate 5%/32-point diagnostics, all matched coordinates retained. No metric-selected samples or added economic gate.',
        'counts':{'new_business_configurations':4,'new_evaluations':5,'reused_controls':2},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'S013 existing data, four economic gates, original execution and binary position. Original buy score, bull/bear range/ACF gates and all holding exits/priority remain original TIME. Only regime reference changes, including its use in route selection and forced regime exit.',
        'signal_units':'Same bound positive finite HFQ signal Close; reference computed on full daily before session reindex. W=5..60, k=1 or2, every reference at least3sessions old; warmup max(parent,W+k+1). No filling missing reference; equality to original threshold is bull.',
        'information_hypothesis':'Single lagged price carries weight1 in original regime denominator, so a window shift can switch route because one old price rolls out. A fixed local reference average reduces that single-price weight to1/3 or1/5, while retaining unsmoothed current Close and original threshold units. Algebraic smoothing does not prove economically useful information or smoother portfolio outcomes.',
        'limits':'EX017 two-day state confirmation worsened matched parameter tails; EX018 voting failed frequency; EX019 all-bull price gates lost trade frequency; EX020 boundary-only H4 improved center return/drawdown but108/109closed<110, H3 failed2023profit. This structurally changes the reference rather than tuning gate thresholds around seen losses. It can cause new state flips, reduce useful responsiveness or fail original trade/return gates; bear ACF/H4 fragility remains. Both fixed kernels and both old holding backgrounds prospectively reported in the repeatedly seen S013 pool; no independent validation or new searched numeric parameter.',
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
