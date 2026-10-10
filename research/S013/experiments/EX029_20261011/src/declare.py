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
    mean_plan=read(ROOT/'research/S013/experiments/EX028_20261011/protocols/plan.json')
    mean=deepcopy(next(c for c in mean_plan['configurations'] if c['label']=='N1'))
    mean['source_directory']='mean_reference/strategy_runtime'
    mean.update(label='M0-REFERENCE',background='B0',reuse_from='EX028_20261011',reuse_label='N1',reused=True)
    direction_plan=read(ROOT/'research/S013/experiments/EX020_20261011/protocols/plan.json')
    direction=[]
    for old_label,label in (('N0','B0-CLOSE'),('N2','B0-BODY')):
        cfg=deepcopy(next(c for c in direction_plan['configurations'] if c['label']==old_label))
        cfg.update(label=label,background='B0',reuse_from='EX020_20261011',reuse_label=old_label,reused=True)
        direction.append(cfg)
    controls=[time,mean,*direction]
    configurations=[]
    cells=[{k:c[k] for k in ('background','mechanism','label','candidate_id','content_sha256')} for c in controls]
    for number,control in enumerate([mean,mean]):
        p=deepcopy(control['payload'])
        p['parameters']['mechanism']=('MEAN_ACF_NEW_BULL_CLOSE' if number==0 else 'MEAN_ACF_NEW_BULL_BODY')
        p['runtime'].update(module='strategy_runtime.strategies.acf_range',qualname='AcfRange')
        for filename in ('strategies/acf_range.py','strategies/__init__.py'):
            if filename not in p['runtime']['source_files']:
                p['runtime']['source_files'].append(filename)
        source=SRC/'strategy_runtime'
        p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=source)
        candidate=StrategyCandidate('S013',f'C{8480+number}',p,source)
        identity=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
        cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,
            'content_sha256':identity.content_sha256,'payload':p,'source_directory':'strategy_runtime',
            'background':'B0','mechanism':p['parameters']['mechanism'],'mode':'M1','existing_identity':None,'reused':False,
            'parent_control':control['label']}
        configurations.append(cfg)
        cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX029-mean-acf-boundary-price-combination','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'previous_path_diagnosis':read(PROTOCOLS/'previous_path_diagnosis_reference.json'),
        'hypotheses':{'close':'Exact EX028 bear currentACF20 minus strictlypast L mean; add exactEX020 rawbear->bull flat originaleligible Close>previousClose ANDoriginalscore. No gate on stablebull/bear, no waiting latch, no holdingexit changes.',
            'body':'Same centeredmean bear gate, rawboundary Close>Open ANDoriginalscore; incremental CLOSE/BODY priceinformation at original13 numericcenters.'},
        'prospective_control_reuse':'OriginalTIME, oldEX028mean-center, oldEX020CLOSE/BODY nativecenters exactreuse. If anynewqual originalEX01532 reuse, BOTH newcenters32 plusoldunqualifiedmean-center32 as prospectivediagnostic; everynewqual retained, unqualified onlydiagnostic, no registration. No newqual=>zero newparameters.',
        'predeclared_selection':'2new/4old centers complete, originalfourgates only. All13 numericcenters/all32coordinates identical. Oldmean32 ownEX028 implementation retained, no substitution withnewpricegate source. No pointreplacement/narrowdomain/neweconomicgate.',
        'counts':{'new_business_configurations':2,'new_evaluations':3,'reused_controls':4},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'OriginalbullH8/bearH4, rangeentry/exit, bearthreshold.1, rawregime, originalconfirmation, allholdingexit priorities, binaryposition andexecution/economiccontract. Fixed strictlypast Lmean bear gate exactlyEX028; only existingboundary direction info added.',
        'information_hypothesis':'EX028mean-center has123closed andpositive2022/2023, but2024DD19.7899%>benchmark18.5736%; originalEX020BODY/CLOSE reducedDD butfreq109/108failed. Combine prospectively to test complementarity, not patch a particular 2024trade. Tradefrequency headroom is not proof old pricegates help underchanged entrypath.',
        'selection_history':'Alreadyexposed S013EX012..28. Fixed oldCLOSE/BODY gates andmeanbaseline chosen aftercenter results; no new price threshold/yearcondition/window search. Original32path diagnostic posthoc descriptive. Repeated seenpool, not independentvalidation.',
        'new_coupling':'Originalconfirmation.lookback also laggedACF baseline L; threshold current-minusmean correlationdifference, not absoluteACF. Baseline andpreviousregime/previousClose full daily before reindex. Same numericcoordinate comparisons do not make gate semantics identical.',
        'warmup':'max(parent,L+21,regime_window+2) supports LcompletepastACF andpreviousrawregime. Center180 retained. Existing-only publicbinding, missingasset explicitFAILED no download/fallback.',
        'limits':'Addinggate canremovegoodentries, erase2023profit orfrequencyheadroom; annualDD maynotimprove andparameterH/regimecouplingmayremain. Centerqualification must precede fullparametercomparison; no relative-degradation-only success.',
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    refs={path.stem:publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+path.stem,path.read_bytes(),'application/json','json')).to_dict() for path in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')}
    write(PROTOCOLS/'plan_references.json',refs)
    write(RUNS/'mandate_validation.json',read(ROOT/'research/S013/assets/runs/EX014_20261011/mandate_validation.json'))
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':2})

if __name__=='__main__':
    main()
