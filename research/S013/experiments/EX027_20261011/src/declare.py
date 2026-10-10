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
    smooth_cell=next(c for c in prior['cells'] if c['background']=='B0' and c['mechanism']=='SMOOTH')
    smooth=deepcopy(next(c for c in prior['configurations'] if c['label']==smooth_cell['label']))
    smooth.update(label='B0-LONG_MEAN',background='B0',reuse_from='EX015_20261011',reuse_label=smooth_cell['label'],reused=True)
    controls=[time,smooth]
    configurations=[]
    cells=[{k:c[k] for k in ('background','mechanism','label','candidate_id','content_sha256')} for c in controls]
    for number,control in enumerate([time,time]):
        p=deepcopy(control['payload'])
        p['parameters']['mechanism']=('BEAR_ACF_MEDIAN3' if number==0 else 'BEAR_ACF_MEAN3')
        p['runtime'].update(module='strategy_runtime.strategies.acf_range',qualname='AcfRange')
        for filename in ('strategies/acf_range.py','strategies/__init__.py'):
            if filename not in p['runtime']['source_files']:
                p['runtime']['source_files'].append(filename)
        source=SRC/'strategy_runtime'
        p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=source)
        candidate=StrategyCandidate('S013',f'C{8900+number}',p,source)
        identity=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
        cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,
            'content_sha256':identity.content_sha256,'payload':p,'source_directory':'strategy_runtime',
            'background':'B0','mechanism':p['parameters']['mechanism'],'mode':'M1','existing_identity':None,'reused':False,
            'parent_control':control['label']}
        configurations.append(cfg)
        cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX027-bear-short-acf-aggregation','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'hypotheses':{'median':'Only bear ACF20 used by original acf_min gate replaced with fixed trailing3 median, requiring3 finite estimates. Isolated outliers might destabilize entry gates; other routes/score/exit unchanged.',
            'mean':'Same fixed3 trailing mean as matched aggregation counterexample; identifies outlier resistance versus equal-length smoothing. All13 numeric centers identical to C2132.'},
        'prospective_control_reuse':'Original TIME and EX015 fixed20 ACFmean B0 complete accounts exact native reuse. If any new qualifier original EX01532 exact native parameters reused and both new centers get32 each; unqualified new center diagnostic only, not registered. Zero qualifiers means zero new parameters.',
        'predeclared_selection':'Two centers and2 old controls completely reported. Original four economic gates only. Original C2132 and both new centers all13numeric centers andall32 coordinates identical. No point replacement/domain narrowing/new economic gate.',
        'counts':{'new_business_configurations':2,'new_evaluations':3,'reused_controls':2},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'BullH8, bearH4/ACFthreshold.1, original raw regime, confirmation features and bull ACF, ranges, exits, binary positions and fixed execution/economic/data contracts. Only bear ACF threshold input aggregation changed, all13 numeric coordinates still active.',
        'information_hypothesis':'EX012/13 show bearACF and discrete timer sensitivity persists without original buy confirmation. EX015 long20mean failed every center. Fixed3 chosen as minimal odd causal aggregation able to reject one isolated outlier, not a length grid or result-selected threshold.',
        'selection_history':'Already exposed S013 EX012..26 development evidence, including failed20mean and bull protection. Fixed3median/mean declared prospectively before new market accounts. Repeated development pool, not independent validation.',
        'limits':'Short aggregation may merely lag genuine changes, reduce frequency or leave H integer/regime threshold sensitivity. Smooth signals or a weaker center do not prove economic robustness. No new data/dependencies/platform/phase4advance.',
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    refs={path.stem:publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+path.stem,path.read_bytes(),'application/json','json')).to_dict() for path in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')}
    write(PROTOCOLS/'plan_references.json',refs)
    write(RUNS/'mandate_validation.json',read(ROOT/'research/S013/assets/runs/EX014_20261011/mandate_validation.json'))
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':2})

if __name__=='__main__':
    main()
