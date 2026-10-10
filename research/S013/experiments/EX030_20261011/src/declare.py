"""Prospective two-held-close bull protection with original and one-day controls."""
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
    old2=read(ROOT/'research/S013/experiments/EX017_20261011/protocols/plan.json')
    two=deepcopy(next(c for c in old2['configurations'] if c['label']=='N4'))
    two.update(label='E2-EXIT',reuse_from='EX017_20261011',reuse_label='N4',reused=True)
    old3=read(ROOT/'research/S013/experiments/EX024_20261011/protocols/plan.json')
    majority=deepcopy(next(c for c in old3['configurations'] if c['label']=='N0'))
    majority.update(label='R3-ALL',reuse_from='EX024_20261011',reuse_label='N0',reused=True)
    controls=[time,two,majority]
    configurations=[]
    cells=[{k:c[k] for k in ('background','mechanism','label','candidate_id','content_sha256')} for c in controls]
    for number,control in enumerate([time,time]):
        p=deepcopy(control['payload'])
        p['parameters']['mechanism']=('BULL_EXIT_BEAR3' if number==0 else 'BULL_EXIT_BEAR_MAJORITY3')
        p['runtime'].update(module='strategy_runtime.strategies.exit_confirmed_range',qualname='ExitConfirmedRange')
        for filename in ('strategies/exit_confirmed_range.py','strategies/__init__.py'):
            if filename not in p['runtime']['source_files']:
                p['runtime']['source_files'].append(filename)
        source=SRC/'strategy_runtime'
        p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=source)
        candidate=StrategyCandidate('S013',f'C{6900+number}',p,source)
        identity=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
        cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,
            'content_sha256':identity.content_sha256,'payload':p,'source_directory':'strategy_runtime',
            'background':'B0','mechanism':p['parameters']['mechanism'],'mode':'M1','existing_identity':None,'reused':False,
            'parent_control':control['label']}
        configurations.append(cfg)
        cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX030-isolated-bull-regime-exit','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'hypotheses':{'continuous':'Only active bull route holding regime exit requires all last3 finite raw states bear; raw current entryroute and all entry gates unchanged.',
            'majority':'Only active bull route holding regime exit requires at least2 of last3 finite raw states bear; includes prior states before entry, can fire on current rawbull if prior2bear. Flat entry still current rawroute, no waiting latch or entryfilter.'},
        'prospective_control_reuse':'3 exact immutable centers: originalTIME EX015, old2day bullEXIT_CONFIRM EX017N4 and fullroute majority3 EX024N0. Old2day not a new candidate/re-evaluation. If either new center qualifies, BOTH new centers each32 new full accounts, originalEX01532 exact reused, unqualified center diagnosticonly. No old2day/route-majority parameter supplements.',
        'predeclared_selection':'2new/3old center accounts complete; originalfour economic gates only. All13 numeric centers and all32 coordinates exactly same as original. Same complete domains/radius/seed/integer mapping; no outcome replacements or narrowing.',
        'counts':{'new_business_configurations':2,'new_evaluations':3,'reused_controls':3},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'Original rawregime/current flatentry, buyconfirmation, bearACF.1/H4, bullH8, range, stop/trail, cooldown, binarytarget and fixed execution remain. Only bull holding regimeexit condition changes; bearholding rawbull exit immediate; exit_on_regime_change False disables newcondition; loss>trailing>range>time>regime priority unchanged.',
        'signal_units':'Full causal HFQ rawmomentum Close_t/Close_(t-W)-1; equality>=threshold rawbull. Rolling3 requires allfinite before reindex; count includes pre-entry market states, no holding-only reset. Fixed3 structuralchoice no new numericcoordinate. Warmupmax(parent,W+3), center180/min60/W60minimum63.',
        'information_hypothesis':'Original32 firstdivergence27holding exits versus5entry;18firstdifferences involve time, others include rawregime. Jointperturbation doesnot isolate causalparameter. EX024 majority changed both routes andexit andfailed; EX017 old2dayEXIT_CONFIRM alreadytested andfailed. Isolate exit-only sustained3 versus majority3 as mechanism countertest, not repeatold2 as newtrial.',
        'selection_history':'Alreadyseen S013EX012..29 andold32 descriptivepaths; fixed3 chosen followingold2 failure andEX024confounding. No2024rule, price/year/trade patch or infiniteextension; original timecaps stillbind. Repeated developmentpool, not independentvalidation.',
        'limits':'Exit delay may prolong losses, majority may exit on rebounded rawbull, time/range may prevent any benefit, alter fees/re-entry anderase2023profit. Morepersistent states neednot imply economics or better tails. Centerpass and relative shrinkage alone not success. No phase4/newdata/platform/dependencies/PTE.',
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    refs={path.stem:publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+path.stem,path.read_bytes(),'application/json','json')).to_dict() for path in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')}
    write(PROTOCOLS/'plan_references.json',refs)
    write(RUNS/'mandate_validation.json',read(ROOT/'research/S013/assets/runs/EX014_20261011/mandate_validation.json'))
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':2})

if __name__=='__main__':
    main()
