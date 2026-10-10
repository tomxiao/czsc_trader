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
    body_prior=read(ROOT/'research/S013/experiments/EX020_20261011/protocols/plan.json')
    body=deepcopy(next(c for c in body_prior['configurations'] if c['label']=='N2'))
    body.update(label='B0-BODY',background='B0',reuse_from='EX020_20261011',reuse_label='N2',reused=True)
    one_prior=read(ROOT/'research/S013/experiments/EX025_20261011/protocols/plan.json')
    one_controls=[]
    for number in range(2):
        cfg=deepcopy(next(c for c in one_prior['configurations'] if c['label']==f'N{number}'))
        cfg.update(label=f'D{number}-ONE',reuse_from='EX025_20261011',reuse_label=f'N{number}',reused=True)
        one_controls.append(cfg)
    controls=[time,body,*one_controls]
    configurations=[]
    cells=[{k:c[k] for k in ('background','mechanism','label','candidate_id','content_sha256')} for c in controls]
    for number,control in enumerate(one_controls):
        p=deepcopy(control['payload'])
        p['parameters']['mechanism']=('BULL_ANCHOR_LOSS2' if number==0 else 'NEW_BULL_BODY_ANCHOR_LOSS2')
        p['runtime'].update(module='strategy_runtime.strategies.mechanism_range',qualname='MechanismRange')
        for filename in ('strategies/mechanism_range.py','strategies/__init__.py'):
            if filename not in p['runtime']['source_files']:
                p['runtime']['source_files'].append(filename)
        source=SRC/'strategy_runtime'
        p['runtime']['source_sha256']=implementation_sha256(p['runtime']['source_files'],source_root=source)
        candidate=StrategyCandidate('S013',f'C{9780+number}',p,source)
        identity=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES)
        cfg={'label':f'N{number}','index':number,'candidate_id':candidate.candidate_id,
            'content_sha256':identity.content_sha256,'payload':p,'source_directory':'strategy_runtime',
            'background':'B0','mechanism':p['parameters']['mechanism'],'mode':'M1','existing_identity':None,'reused':False,
            'parent_control':control['label']}
        configurations.append(cfg)
        cells.append({k:cfg[k] for k in ('background','mechanism','label','candidate_id','content_sha256')})
    plan={'name':'S013-EX026-bull-signal-anchor-protection','configurations':configurations,'controls':controls,'cells':cells,
        'mandate':prior['mandate'],'authorization':prior['authorization'],
        'hypotheses':{
            'bull_protection':'Active holding route bull, signal age>=2, current and previous HFQ Close both strictly below this holding entry signal Close => bull_anchor_loss2. Age>=2 ensures both closes belong to current holding. Equality either day rejects. Original loss/trailing precede protection, then range/time/raw regime.',
            'boundary_body':'Optional exact EX020 raw bear-to-bull flat eligible Close>Open AND original score; stablebull/bear unchanged. Compare pure/combo at identical 13 numeric centers.'},
        'prospective_control_reuse':'Original TIME, original BODY and EX025 one-day pure/BODY protection centers exact full native reuse, 4 controls. If any new qualifier original TIME EX01532 exact native parameters reused. Every new qualifier full32; if N1 alone qualifies N0 full32 as prospectively declared unqualified diagnostic, not promoted/registered. No one-day unqualified parameter supplements.',
        'predeclared_selection':'Both new centers and all4 controls fully reported. Original four gates only. Original C2132 and both new centers all13 numeric centers and all32 point coordinates exactly same. N1vsN0 isolates BODY incremental conditional on two-day protection. No outcome point replacement/domain narrowing/extra eligibility gate.',
        'counts':{'new_business_configurations':2,'new_evaluations':3,'reused_controls':4},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'preserved':'BullH8, bearACF.1/H4, original raw fast regime, original confirmation, ranges and original holding exits. Binary position and fixed execution/economic/data contracts unchanged. Only fixed persistent two-close bull anchor protection and optional existing BODY structure; no new numeric coordinate/variable confirmation length.',
        'signal_units':'Same positive finite HFQ current and previous signal Close from full daily shift1 before reindex. Anchor initially0 finite, updated only signal entry, flat retains latest anchor. No actual-fill reset. Two held closes must be strictly below same anchor; no infinite extension, no previous unrelated holding counted.',
        'information_hypothesis':'EX025 immediate signal-anchor protection produced50/47 protective signals and133/130closed but2023 losses. A single-day break can be a short fluctuation; require persistence of two held closes while retaining original fast raw-regime exits. Tests noise sensitivity of protection rather than selecting time cap.',
        'selection_history':'Uses already exposed S013 EX016 attribution and EX020..25 development evidence. Fixed2 consecutive closes chosen after failed single-day evidence, selection bias disclosed; not independent validation. No grid of persistence lengths, no threshold/age/window selected to patch one trade.',
        'limits':'Delay can prolong actual losses, still truncates rebounds and changes fees/cash/entries; H2/3/4 discrete jumps and ACF/regime thresholds remain. Anchor is not actual breakeven due1%buy premium,T+1execution and fees. Center qualification, less churn or relative degradation alone cannot prove economic robustness. No new data/dependencies/platform/phase4advance.',
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    refs={path.stem:publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+path.stem,path.read_bytes(),'application/json','json')).to_dict() for path in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')}
    write(PROTOCOLS/'plan_references.json',refs)
    write(RUNS/'mandate_validation.json',read(ROOT/'research/S013/assets/runs/EX014_20261011/mandate_validation.json'))
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':2})

if __name__=='__main__':
    main()
