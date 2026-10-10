"""Prospective two-by-two boundary-entry versus bull timer factorial."""
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
    body_prior=read(ROOT/'research/S013/experiments/EX020_20261011/protocols/plan.json')
    body=deepcopy(next(c for c in body_prior['configurations'] if c['label']=='N2'))
    body.update(label='B0-BODY',background='B0',reuse_from='EX020_20261011',reuse_label='N2',reused=True)
    controls=[time,body]
    configurations=[]
    cells=[{k:c[k] for k in ('background','mechanism','label','candidate_id','content_sha256')} for c in controls]
    for number,control in enumerate(controls):
        p=deepcopy(control['payload'])
        p['parameters']['mechanism']=('BULL_ANCHOR_LOSS' if number==0 else 'NEW_BULL_BODY_ANCHOR_LOSS')
        p['runtime'].update(module='strategy_runtime.strategies.mechanism_range',qualname='MechanismRange')
        for filename in ('strategies/mechanism_range.py','strategies/__init__.py'):
            if filename not in p['runtime']['source_files']:
                p['runtime']['source_files'].append(filename)
        source=SRC/'strategy_runtime'
        p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=source)
        candidate=StrategyCandidate('S013',f'C{9700+number}',p,source)
        identity=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
        cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,
            'content_sha256':identity.content_sha256,'payload':p,'source_directory':'strategy_runtime',
            'background':'B0','mechanism':p['parameters']['mechanism'],'mode':'M1','existing_identity':None,'reused':False,
            'parent_control':control['label']}
        configurations.append(cfg)
        cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX025-bull-signal-anchor-protection','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'hypotheses':{'bull_protection':'Holding active_route bull, age>=1, HFQClose strictly below entrysignal Close triggers bull_anchor_loss. Equality remains; bear never protected. Original loss/trailing precede newprotection, thenrange/time/regime original. Exact signal anchor, noactualfill reset.',
            'boundary_body':'Optional exact EX020 raw-bear-to-bull flat eligible Close>Open ANDoriginalscore; stablebull/bearunchanged. Same13numericcenter matched TIME and BODY controls.'},
        'prospective_control_reuse':'Original TIME and EX020 BODY centers exactly reused. If anynewqualifier originalTIME EX01532 exactnativeaccounts reused. Everynewqualifier full32. IfBODYprotection alonequalifies, pureprotection32addedaspredeclared unqualifieddiagnosticcontrol, notregistered/promoted.',
        'predeclared_selection':'Allfourcellsreported, originalfourgatequalifiersfull13domain5%32points. OriginalC2132and bothnewcenters fullnumericcenterandall32pointcoords EXACTsame; N1vsN0isolatesBODYconditionalonprotection. Nooutcome pointreplacement/narroweddomain/extraeligibilitygate.',
        'counts':{'new_business_configurations':2,'new_evaluations':3,'reused_controls':2},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'BullH8,bearACF.1/H4,raw regimefastswitch, originalscore,range and alloriginalexits/priority(exceptexplicitnewprotectioninsert) and binary/execution/economiccontract. Noearlybearorunboundedtimer, nofractionalpositions, no new numericcoordinate.',
        'signal_units':'Anchor=mostrecententrysignalHFQClose, initially0finite, flatretainslast, updatedonlysignalentry. Notactualbuyfill, notnetprofit/stopprice, account executionT+1mayrealizeadditional loss. Pricesandrawpreviousstateall causalfullhistory.',
        'information_hypothesis':'Retained2023attribution placesmuchlossinbullroute/regimeexit, notcausal. EX024state majority reducedswitchingbut worsenedreturn, so retainoriginalfastswitch and testearlier protectionofadmittedbullpositions. OriginalBODYcenterpositive2023butfrequency109failed; protectioncouldalterfullaccountpaths notpatchanoldtrade.',
        'selection_history':'DesignusesexposedEX016descriptionandEX020..24counterevidence. Bullprice-lossisfixedstrictdirectionversussignalanchorfromage1, nosearchedthreshold, ageorholdwindow. Currentnumericcentersunchanged unlikeEX023bullHhalf.',
        'limits':'Signalanchorbreak isnotactualbreakeven; T+1delay,1%buypricepremiumandfeesmatter. Frequentwhipsaw maycutrecoveries/raisefees/reshapeopportunities, BODYmayconfoundincrement unlessmatchedpureprotection. ExistingACF/Handregimefragilitymayremain. RepeatedS013developmentpool,noindependentvalidation/newdata/deps/phase4advance.',
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    refs={path.stem:publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+path.stem,path.read_bytes(),'application/json','json')).to_dict() for path in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')}
    write(PROTOCOLS/'plan_references.json',refs)
    write(RUNS/'mandate_validation.json',read(ROOT/'research/S013/assets/runs/EX014_20261011/mandate_validation.json'))
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':2})

if __name__=='__main__':
    main()
