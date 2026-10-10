"""Prospective finite three-day regime majority mechanism and matched timers."""
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
    for number,control in enumerate(controls):
        payload=deepcopy(control['payload'])
        payload['parameters']['mechanism']='REGIME_MAJORITY3'
        payload['runtime'].update(module='strategy_runtime.strategies.regime_majority_range',qualname='RegimeMajorityRange')
        payload['runtime']['source_files'].append('strategies/regime_majority_range.py')
        payload['runtime']['source_files'].append('strategies/__init__.py')
        payload['runtime']['source_sha256']=implementation_sha256(payload['runtime']['source_files'],source_root=SRC/'strategy_runtime')
        candidate=StrategyCandidate('S013',f'C{9904+number}',payload,SRC/'strategy_runtime')
        identity=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
        cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,'content_sha256':identity.content_sha256,
            'payload':payload,'source_directory':'strategy_runtime','background':control['background'],
            'mechanism':'REGIME_MAJORITY3','mode':'M1','existing_identity':None,'reused':False,'parent_control':control['label']}
        configurations.append(cfg)
        cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX024-finite-regime-majority','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'hypotheses':{'regime_majority':'Raw m_t=Close_t/Close_(t-W)-1, equality>=threshold rawbull. Effective regime bull iff at least2 of last3 finite raw states arebull. Full daily before session reindex, no missing tobear. Original route selection and regime exits both use effective regime.'},
        'prospective_control_reuse':'Original H4/H3 centers exactly reused. All new original-four-gate qualifiers full32points with originalH4 EX01532 and originalH3 EX01732 if newH3qualifies; H3 control unqualified, diagnostic only. Matching controls/points predeclared before new metrics; no retrospective supplement.',
        'predeclared_selection':'Both fixed centers and all qualifiers reported. All13original full domains, width-normalized totalL2=.05,32points,seed13. All compared mechanism and matched TIME points exactly same numeric coordinates. Original H4 always overallbaseline if anyqualifier; no outcome-filtered replacement or narrowed domain.',
        'counts':{'new_business_configurations':2,'new_evaluations':3,'reused_controls':2},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'Bull H8, bear ACF.1/H4orH3, original buy confirmation, two-route range gates, exit priority and binary signal/execution contract unchanged. Only route state becomes finite3-day majority. No price direction gate, no fractional vote account, no early or unbounded timer.',
        'signal_units':'Full causal HFQ daily; warmup max(parent,W+3), W60requires63. Finite memory, no assumed initial state or carry from asset origin. Missing/nonfinite any3raw rejects, equality to threshold rawbull.',
        'information_hypothesis':'Original32 accounts allfailed2023positive; retained descriptive attribution places large2023loss in bull route/regime exits. Majority suppresses isolated one-day raw switching while retaining W/threshold numeric coordinates. Tests state churn rather than average referenceprice or independent strategy-target ensemble.',
        'selection_history':'Uses exposed EX016 full-account description and EX017..23 counterevidence. EX021 smoothed historical-price denominator failed all4; EX023 bullH8to4 increased cycles but damaged2023anddrawdown. Fixed3 majority kernel is prospective, not metric-selected after alternatives.',
        'limits':'Delay can prolong wrong route, alter forced exits/reentries/cash/fees and distort useful fast bear recovery. Existing ACF/H sensitivity may remain; smooth state alone does not imply economic robustness. Same repeatedly searched S013 pool, no independent validation/newdata/deps/phase4advance.',
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    refs={p.stem:publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+p.stem,p.read_bytes(),'application/json','json')).to_dict() for p in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')}
    write(PROTOCOLS/'plan_references.json',refs)
    write(RUNS/'mandate_validation.json',read(ROOT/'research/S013/assets/runs/EX014_20261011/mandate_validation.json'))
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':2})

if __name__=='__main__':
    main()
