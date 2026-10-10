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
        p['parameters']['bull']['max_hold']=4
        source=SRC/control['source_directory']
        p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=source)
        assert p['runtime']['source_sha256']==control['payload']['runtime']['source_sha256']
        candidate=StrategyCandidate('S013',f'C{9800+number}',p,source)
        identity=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
        cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,
            'content_sha256':identity.content_sha256,'payload':p,'source_directory':control['source_directory'],
            'background':'B4','mechanism':control['mechanism'],'mode':'M1','existing_identity':None,'reused':False,
            'parent_control':control['label']}
        configurations.append(cfg)
        cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX023-bull-timer-half-boundary-body-factorial','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'hypotheses':{'timer_half':'Bull H8 versus fixed half H4, bear ACF0.1/H4 and all other values unchanged; no search to barely meet110trades.',
            'boundary_body':'Exact EX020 known Close>Open AND original score only on eligible flat raw bear-to-bull transition; compare against TIME at same bull H4 and H8.'},
        'prospective_control_reuse':'Original H8 TIME/BODY centers exactly reused. If any new center qualifies, original H8 TIME32 exact EX015 accounts reused, all new qualifying centers get full32points. If BODY4 alone qualifies, TIME4 gets full32points as unqualified same-coordinate diagnostic control, not promoted or registered.',
        'predeclared_selection':'All four cells and all original-four-gate qualifiers reported. All new qualifiers full13domain5%32points; new N0/N1 have same numerical centers and point coordinates, unlike original H8 baseline. No metric-selected replacement or extra eligibility gate.',
        'counts':{'new_business_configurations':2,'new_evaluations':3,'reused_controls':2},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'Exact original TIME and EX020 BODY sources, raw regime, full confirmation, bear ACF/H4 and all execution/economic/data contracts. Only bull H changes8to4 at new centers. Both bull/bear H still active original numeric1..60 coords in external perturbations.',
        'signal_units':'Exact original HFQ signal and original entry/holding state age; BODY applies only raw boundary flat entry, not waiting or stablebull gate. No actual-fill reset, execution-unit mixing or new feature source.',
        'information_hypothesis':'Boundary BODY H8 improved return, drawdown and2023but reduced112to109closed. EX022 bear early exit restored frequency yet damaged2023. This tests whether shorter bull exposure can reduce persistence of admitted bull positions while preserving original bear recovery horizon; same-timer TIME counterfactual separates timer effect from price-gate incremental information.',
        'selection_history':'Design uses already seen EX017..22 counterevidence. Half4 is prospective fixed structural dose, not known successful horizon. Original H8 BODY remains unqualified for frequency; registration and full diagnostics are not guessed from that near boundary.',
        'limits':'Holding bull less may simply truncate gains, release cash or raise costs; any benefit may be solely the timer, disappear at matched TIME or worsen absolute parameter tails. W/threshold/bear ACF/H remain fragile. Same repeatedly searched S013 pool; no independent validation, new data/dependencies or phase4/5 transition.',
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    refs={path.stem:publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+path.stem,path.read_bytes(),'application/json','json')).to_dict() for path in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')}
    write(PROTOCOLS/'plan_references.json',refs)
    write(RUNS/'mandate_validation.json',read(ROOT/'research/S013/assets/runs/EX014_20261011/mandate_validation.json'))
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':2})

if __name__=='__main__':
    main()
