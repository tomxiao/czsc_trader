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
    controls=[time]
    configurations=[]
    cells=[{k:c[k] for k in ('background','mechanism','label','candidate_id','content_sha256')} for c in controls]
    for number,control in enumerate([time,time]):
        p=deepcopy(control['payload'])
        p['parameters']['mechanism']=('BEAR_VOLATILITY_TIME' if number==0 else 'ALL_VOLATILITY_TIME')
        p['runtime'].update(module='strategy_runtime.strategies.volatility_time_range',qualname='VolatilityTimeRange')
        for filename in ('strategies/volatility_time_range.py','strategies/__init__.py'):
            if filename not in p['runtime']['source_files']:
                p['runtime']['source_files'].append(filename)
        source=SRC/'strategy_runtime'
        p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=source)
        candidate=StrategyCandidate('S013',f'C{6400+number}',p,source)
        identity=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
        cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,
            'content_sha256':identity.content_sha256,'payload':p,'source_directory':'strategy_runtime',
            'background':'B0','mechanism':p['parameters']['mechanism'],'mode':'M1','existing_identity':None,'reused':False,
            'parent_control':control['label']}
        configurations.append(cfg)
        cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX031-market-volatility-time','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'hypotheses':{'bear_clock':'Only bearholding timeexit uses accumulated relativevolatility progress >= original integer H; bulltimeexit keeps original elapsedage.',
            'all_clock':'Bothroutes timeexit use same accumulatedprogress >= own originalH; rawregime/entry and all other exits untouched.'},
        'prospective_control_reuse':'OriginalTIME EX015 exactnative center reuse only. If either new center qualifies, BOTH new centers each32 newfullaccounts andoriginalEX01532 exactreuse; unqualifiedcenter onlyprospectivediagnostic, no promotion. Noqualifiers=>zero parameteraccounts.',
        'predeclared_selection':'2new/1old completecenters, originalfour economicgates only. All13numericcenters/originalcompletedomains/32pointcoordinates exactlysame; radius.05 seed13 PCG64 HALF_EVENinteger/LINEARquantiles. No replacement/narrowing/newgate.',
        'counts':{'new_business_configurations':2,'new_evaluations':3,'reused_controls':1},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'Originalraw route/flatentry, buyconfirmation, ACF.1, range, stops/trail/regime andexitpriority loss>trailing>range>time>regime, binarytargets andexecution contract. H numeric bull8/bear4 andintegertype retained, but its selectedroute meaning changes from elapsedtradingdays to relativevolatilitybudget.',
        'signal_units':'v_t=max(High-Low,abs(High-prevClose),abs(Low-prevClose))/prevClose using HFQ. Increment=v_t/strictlyprevious20finitev mean; denominatorpositive required, no fill/clip/cap. Full daily before sessionsreindex, currentbar known atTclose. Entryclock0, eachsubsequentholdingsession adds increment, exitkeepsfinalclock/flatkeepsrecent/newentryresets, no actualfillreset. Clockdiagnostic accumulates in bothroutes; onlyselectedroute replaces timecondition.',
        'warmup':'max(parent,22) supplies 20strictlypast v pluscurrent andpreviousClose; parentmin60, center180 unchanged. Fixed20 adopts existing20component scale as newstructural role, not searched/numericaldimension. Missingexistingasset explicitFAILED no download/fallback.',
        'information_hypothesis':'Original32 firstdivergence27holdingexits/5entry,18time related, descriptive not singleparametercausal. H4->3 changesbuy/sell timing sharply andoldconfirm/delete/conditionaltimer/priceanchor/stateexit experiments failed. Test whether calendar days are a poor measure of cumulative priceactivity, with bear-only versus all-route isolation.',
        'selection_history':'Alreadyseen S013EX012..30; fixed20 relativeTrueRange chosen prospectively after calendar/exitdelay negatives. No newyearcondition or tradepatch, no window/ratio/H search. Same repeatedlyresearchedpool, noindependentvalidation.',
        'limits':'NewH units are not samephysicalquantity despite samenumericgeometry. Quiet periods can extendactual holding beyondH without calendarcap, strongvolatility can sell reboundearly, originalACF/rawroute fragility mayremain. Zero20daymean rejects ratherthan stalls silently. No newdata/dependencies/platform/phase4/PTE.',
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    refs={path.stem:publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+path.stem,path.read_bytes(),'application/json','json')).to_dict() for path in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')}
    write(PROTOCOLS/'plan_references.json',refs)
    write(RUNS/'mandate_validation.json',read(ROOT/'research/S013/assets/runs/EX014_20261011/mandate_validation.json'))
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':2})

if __name__=='__main__':
    main()
