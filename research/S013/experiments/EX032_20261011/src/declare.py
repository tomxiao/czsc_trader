"""Prospective bear-only and both-route relative-volatility holding clocks."""
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
    clocks=[]
    oldclock=read(ROOT/'research/S013/experiments/EX031_20261011/protocols/plan.json')
    for number in range(2):
        cfg=deepcopy(next(c for c in oldclock['configurations'] if c['label']==f'N{number}'))
        cfg.update(label=f'C{number}-CLOCK',reuse_from='EX031_20261011',reuse_label=f'N{number}',reused=True)
        clocks.append(cfg)
    controls=[time,*clocks]
    configurations=[]
    cells=[{k:c[k] for k in ('background','mechanism','label','candidate_id','content_sha256')} for c in controls]
    for number,control in enumerate(clocks):
        p=deepcopy(control['payload'])
        p['runtime']['source_files']=[n.replace('volatility_time_range.py','midpoint_volatility_time_range.py') for n in p['runtime']['source_files']]
        p['parameters']['mechanism']=('BEAR_MIDPOINT_VOLATILITY_TIME' if number==0 else 'ALL_MIDPOINT_VOLATILITY_TIME')
        p['runtime'].update(module='strategy_runtime.strategies.midpoint_volatility_time_range',qualname='MidpointVolatilityTimeRange')
        for filename in ('strategies/midpoint_volatility_time_range.py','strategies/__init__.py'):
            if filename not in p['runtime']['source_files']:
                p['runtime']['source_files'].append(filename)
        source=SRC/'strategy_runtime'
        p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=source)
        candidate=StrategyCandidate('S013',f'C{6200+number}',p,source)
        identity=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
        cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,
            'content_sha256':identity.content_sha256,'payload':p,'source_directory':'strategy_runtime',
            'background':'B0','mechanism':p['parameters']['mechanism'],'mode':'M1','existing_identity':None,'reused':False,
            'parent_control':control['label']}
        configurations.append(cfg)
        cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX032-midpoint-volatility-time','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'hypotheses':{'bear_midpoint':'Exact EX031 bearclock, only selected timecondition clock+.5>=sameintegerH; unselected bull uses age>=H.',
            'all_midpoint':'Exact EX031 bothrouteclock, selected timecondition clock+.5>=sameintegerH. Fixed halfbin rounding boundary, no phase search or ratio rescaling.'},
        'synthetic_counting_reference':read(PROTOCOLS/'renewal_reference.json'),
        'prospective_control_reuse':'OriginalTIME EX015 andtwo original EX031clock nativecenters exactreuse. Parents are corresponding oldclock nativeproof, no oldunqualified registration. If either newqual BOTH new32fullaccounts, originalEX01532exactreuse, unqualdiagnosticonly. No oldclock parameter supplements.',
        'predeclared_selection':'2new/3old centers, originalfour economicgates; original13numericalcenters/full domains/same32coord/radius.05/seed13/PCG64/HALF_EVENintegers/LINEARquantiles. No substitutions or narrowedH/extraeconomicgate.',
        'counts':{'new_business_configurations':2,'new_evaluations':3,'reused_controls':3},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'OldEX031TR/past20mean/increment/clockaccumulation/fullrouteentry/ACF/buyconfirmation/range/regime/stop/trail/execution exactlypreserved; only selectedclock crossing boundary fixed+.5. loss>trailing>range>time>regime. OriginalintegerH8/H4 and1..60 domains; H denotes normalizedvolatilitybudget ratherthan originalelapsed sessioncap.',
        'signal_units':'HFQrelativeTR overstrictlypast20 mean, full daily before reindex. Entryclock0, everypostentry holdingsession increments, exit/flatretain/newentryreset. Selectedcondition clock+.5>=H, equalitytriggers; atmostone decisionperday, H1 cannotexit entryday. No actualdaycap/clip/fill or fillreset; zero reference rejects.',
        'warmup':'max(parent,22), min60/center180. Fixed20 andfixed.5 arestructure constants, no newnumericcoords or adaptivefitting. MissingexistingS013assets FAILED/no download/fallback.',
        'information_hypothesis':'EX031selectedtime conditionschange38/78days, calendarHpassedwithoutclockexit29/68days, frequencies107/101 below110 and2023loss. Synthetic iid positive mean1 lognormal sigma.3 paths show about.55day crossingovershoot atintegerH; fixedhalfbin reduces toy bias andconstantincrement1 remainsnativeequivalent. Neither iid nor exacthalfunit is established for realrollingdenominator, so this is a falsifiable timingcalibration test, not a proven economiccorrection.',
        'selection_history':'Alreadyseen S013EX012..31 andpuretoy; fixedhalfunit selected for nearestunit quantization, not searchedamong offsets. No year/tradepatch, no multiplier adjustment/pointdrop. Repeateddevelopmentpool; not independentvalidation.',
        'limits':'Correction may just shorten usefulholding, worsen2023/frequency orabsoluteparametertails; marketincrements dependent, so toybias doesnot guarantee correction. SameH numeric pairing hasdifferentphysicaltimeunits versusoriginal. Centerpass/reducedrelative degradation notgoalproof. No newdata/platform/dependency/phase4/PTE.',
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    refs={path.stem:publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+path.stem,path.read_bytes(),'application/json','json')).to_dict() for path in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')}
    write(PROTOCOLS/'plan_references.json',refs)
    write(RUNS/'mandate_validation.json',read(ROOT/'research/S013/assets/runs/EX014_20261011/mandate_validation.json'))
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':2})

if __name__=='__main__':
    main()
