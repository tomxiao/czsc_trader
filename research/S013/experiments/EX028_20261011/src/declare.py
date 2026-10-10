"""Prospective fixed three-day bear ACF aggregation versus original and long mean."""
from copy import deepcopy
from strategy_runtime import StrategyRuntime,StrategyCandidate,implementation_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import ROOT,SRC,PROTOCOLS,RUNS,EXPERIMENT,DEPENDENCIES,context,read,write,file_hash

def main():
    assert not (PROTOCOLS/'plan.json').exists()
    prior=read(ROOT/'research/S013/experiments/EX015_20261011/protocols/plan.json')
    origin=next(c for c in prior['cells'] if c['background']=='B0' and c['mechanism']=='TIME')
    time=deepcopy(next(c for c in prior['controls']+prior['configurations'] if c['label']==origin['label']))
    time.update(label='B0-TIME',mechanism='TIME',background='B0',reuse_from='EX015_20261011',reuse_label=origin['label'],reused=True)
    short_plan=read(ROOT/'research/S013/experiments/EX027_20261011/protocols/plan.json')
    shorts=[]
    for index,label in enumerate(('B0-SHORT_MEDIAN','B0-SHORT_MEAN')):
        cfg=deepcopy(next(c for c in short_plan['configurations'] if c['label']==f'N{index}'))
        cfg.update(label=label,background='B0',reuse_from='EX027_20261011',reuse_label=f'N{index}',reused=True)
        shorts.append(cfg)
    controls=[time,*shorts]
    configurations=[]
    cells=[{k:c[k] for k in ('background','mechanism','label','candidate_id','content_sha256')} for c in controls]
    for number,control in enumerate([time,time]):
        p=deepcopy(control['payload'])
        p['parameters']['mechanism']=('BEAR_ACF_CENTER_MEDIAN' if number==0 else 'BEAR_ACF_CENTER_MEAN')
        p['runtime'].update(module='strategy_runtime.strategies.acf_range',qualname='AcfRange')
        for filename in ('strategies/acf_range.py','strategies/__init__.py'):
            if filename not in p['runtime']['source_files']:
                p['runtime']['source_files'].append(filename)
        source=SRC/'strategy_runtime'
        p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=source)
        candidate=StrategyCandidate('S013',f'C{8700+number}',p,source)
        identity=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
        cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,
            'content_sha256':identity.content_sha256,'payload':p,'source_directory':'strategy_runtime',
            'background':'B0','mechanism':p['parameters']['mechanism'],'mode':'M1','existing_identity':None,'reused':False,
            'parent_control':control['label']}
        configurations.append(cfg)
        cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX028-bear-lagged-acf-centering','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'previous_path_diagnosis':read(PROTOCOLS/'previous_path_diagnosis_reference.json'),
        'hypotheses':{'median':'Only bear entry ACF value becomes current originalACF20 minus median of strictly previous L=confirmation.lookback finite originalACF20 estimates. Keep current value unsmoothed; compare same original bear.acf_min in correlation-difference units.',
            'mean':'Same strictly lagged L-mean baseline as paired counterexample: distinguish recent baseline adaptation from outlier resistance. No new numerical coordinate, threshold or reference-length search.'},
        'prospective_control_reuse':'Original TIME and EX027 shortmedian/shortmean native complete centers exact reuse. If any new qualifier original EX01532 native parameters reuse and bothnew centers all32; unqualified one prospectively symmetric diagnostic only, no registration. No qualifiers => zero new parameters.',
        'predeclared_selection':'Two new centers plus3 old controls allreported. Original fourgates only. All13 numericcenters and32pointcoordinates identical. Full domains, no outcome point replacement, narrowing or new economic gate.',
        'counts':{'new_business_configurations':2,'new_evaluations':3,'reused_controls':3},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'OriginalbullH8/bearH4, bear threshold.1, original rawregime/confirmation/bullACF/ranges/exits, binarypositions, costs/window/benchmark. Only bear ACF input centered against causal past baseline. All13original coordinates active.',
        'information_hypothesis':'Absolute ACF cutoff may conflate varying recent level with current departure. EX027 short smoothing failed and can delay actual state changes. Centering retains current estimate instead of smoothing it; local reference uses existing confirmation lookback, not a result-selected new window.',
        'selection_history':'Already exposed S013 EX012..27 evidence. Plan formed after negative short smoothing, before new accounts. Previous account path diagnostic is descriptive, joint perturbations cannot isolate individual parameter causality. Repeated seen development pool, no independentvalidation.',
        'new_coupling':'confirmation.lookback controls both original confirmation normalization and laggedACF baseline. Same configurable coordinate, no redundant dimension; extra interaction and changed gate interpretation disclosed. bear.acf_min compares current-minusbaseline ACF units instead of raw absolute ACF units.',
        'warmup':'L preceding complete ACF20 estimates plus current requires L+21 prices; max(parent,L+21). Center still180; full numericdomain may add1 warmup vsparent. Public existing-only binding must fail clearly if not reusable, no download/fallback.',
        'limits':'Reference can adapt to genuine persistent signal and admit poor opportunities, subtractingbaseline can worsen integerH/regime coupling. Same-coordinate perturbations compare mechanisms, not identical semantic thresholds or futureprobability. Stronger center, smoother gate or weakerrelative degradation alone cannot prove economicrobustness.',
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    refs={path.stem:publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+path.stem,path.read_bytes(),'application/json','json')).to_dict() for path in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')}
    write(PROTOCOLS/'plan_references.json',refs)
    write(RUNS/'mandate_validation.json',read(ROOT/'research/S013/assets/runs/EX014_20261011/mandate_validation.json'))
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':2})

if __name__=='__main__':
    main()
