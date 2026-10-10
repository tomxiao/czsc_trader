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
    for mechanism in ('EARLY_POSITIVE','EARLY_NONPOSITIVE','NEW_BULL_BODY_EARLY_POSITIVE','NEW_BULL_BODY_EARLY_NONPOSITIVE'):
        for control in controls[:1]:
            p=deepcopy(control['payload'])
            p['parameters']['mechanism']=mechanism
            p['runtime'].update(module='strategy_runtime.strategies.mechanism_range',qualname='MechanismRange')
            p['runtime']['source_files'].append('strategies/mechanism_range.py')
            p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=SRC/'strategy_runtime')
            number=len(configurations)
            candidate=StrategyCandidate('S013',f'C{9500+number}',p,SRC/'strategy_runtime')
            ident=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
            cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,
                'content_sha256':ident.content_sha256,'payload':p,'source_directory':'strategy_runtime',
                'background':control['background'],'mechanism':mechanism,'mode':'M1','existing_identity':None,'reused':False}
            configurations.append(cfg)
            cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    body_prior=read(ROOT/'research/S013/experiments/EX020_20261011/protocols/plan.json')
    body=deepcopy(next(c for c in body_prior['configurations'] if c['label']=='N2'))
    body.update(label='B0-BODY',reuse_from='EX020_20261011',reuse_label='N2',reused=True)
    controls.append(body)
    cells.insert(2,{k:body[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX022-bounded-early-price-exit','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'hypotheses':{'EARLY_POSITIVE':'Bear signal age>=max(1,H-1) and age<H permits early exit only when current signal Close>entry signal Close; original H cap remains.',
            'EARLY_NONPOSITIVE':'Competing direction with Close<=entry signal Close; original H cap remains, equality partitions the conditions.',
            'NEW_BULL_BODY_EARLY_POSITIVE':'Same bounded positive early exit, combined with exactly EX020 boundary-only original-score AND Close>Open entry gate.',
            'NEW_BULL_BODY_EARLY_NONPOSITIVE':'Same bounded nonpositive early exit combined with that boundary-only body gate.'},
        'prospective_control_reuse':'Original H4/H3 and EX020 BODY H4 centers reused exactly. Every qualified new center gets full32points plus original H4 EX015/H3 EX01732points each; unqualified H3 only diagnostic.',
        'predeclared_selection':'All four fixed centers reported, all original-four-gate qualifiers get full same-domain13-coordinate5%/32-point diagnostics. No metric-selected point substitution or new eligibility gate.',
        'counts':{'new_business_configurations':4,'new_evaluations':5,'reused_controls':3},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'All existing S013 economic/execution/data constraints. Raw regime and original score retained; original bull timer and both routes other exits retained. Bear original H remains latest signal age; no unbounded extension. H=1 means no early exit. Higher exit priority loss>trailing>range>time(early/default)>regime.',
        'signal_units':'Anchor=current bound HFQ Close at original signal entry, not fill price or actual net PnL. Early condition strictly positive or nonpositive; latest cap uses original H. Body gate uses known same-row Open only on raw bear-to-bull eligible flat entry, prior state calculated on full daily before session reindex. No missing-price filling or actual-fill reset of original signal-state age.',
        'information_hypothesis':'Original H3/H4 sharply changes outcomes; EX016 unbounded conditional time exits lost trades/profit, so this tests a one-session information-based timing choice with a fixed original cap. Early positive is motivated by prior descriptive positive-anchor bear exits having weaker next3day mean than nonpositive exits; the reverse condition is retained as a strong competing counter. Those events are non-independent and horizon signs reverse, so this is a new full-policy test, not event-PnL arithmetic.',
        'selection_history':'EX020 BODY H4 had16.6697%CAGR/13.3493%DD/109closed and2023profit but failed110frequency. Its selected combination is informed by already seen development evidence. Original standalone early controls are included so interaction is not credited additively. No attempt to infer one extra trade from predecessor paths; same pool repeatedly searched.',
        'limits':'EX021 reference smoothing failed all four centers. Bounded early sale can truncate rebounds, induce re-entry/fees or still lose frequency; unchanged H/ACF and body-state discontinuities remain. Positive relative signal price does not imply net profitable account exit after1%entry premium and fees. A one-session cap buffer is fixed category, not searched extra coordinate; all13original numeric coordinates remain active. No independent validation or new data/dependencies.',
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
