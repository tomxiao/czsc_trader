"""Prospective fixed adverse-displacement exit; exact native predecessor reuse."""
from copy import deepcopy
from strategy_runtime import StrategyRuntime,StrategyCandidate,implementation_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from common import ROOT,SRC,PROTOCOLS,EXPERIMENT,DEPENDENCIES,context,read,write,file_hash


def configurations():
    previous=read(ROOT/'research/S013/experiments/EX037_20261011/protocols/plan.json')
    original=deepcopy(previous['controls'][0])
    mean=deepcopy(next(c for c in read(ROOT/'research/S013/experiments/EX028_20261011/protocols/plan.json')['configurations'] if c['label']=='N1'))
    body=deepcopy(next(c for c in read(ROOT/'research/S013/experiments/EX029_20261011/protocols/plan.json')['configurations'] if c['label']=='N1'))
    mean.update(label='B0-MEAN',background='MEAN',reuse_from='EX028_20261011',reuse_label='N1',reused=True)
    body.update(label='B0-BODY',background='BODY',reuse_from='EX029_20261011',reuse_label='N1',reused=True)
    risk_plan=read(ROOT/'research/S013/experiments/EX037_20261011/protocols/plan.json')
    risk_controls=[]
    for index,label in enumerate(('B1-MEAN','B1-BODY')):
        control=deepcopy(risk_plan['configurations'][index])
        control.update(label=label,reused=True,reuse_from='EX037_20261011',reuse_label=f'N{index}')
        risk_controls.append(control)
    controls=[original,mean,body,*risk_controls]
    new=[]
    for index,control in enumerate((mean,mean,body,body)):
        payload=deepcopy(control['payload'])
        payload['parameters']['mechanism']=('BEAR_MEAN_ACF_ADVERSE_TR2','BEAR_MEAN_ACF_ADVERSE_TR3','BEAR_MEAN_ACF_BODY_ADVERSE_TR2','BEAR_MEAN_ACF_BODY_ADVERSE_TR3')[index]
        files=['strategies/'+name+'.py' for name in ('range_reversion','adaptive_range','confirmed_range','reentry_confirmed_range','acf_background_range','acf_risk_one_range','acf_range','__init__')]
        payload['runtime'].update(module='strategy_runtime.strategies.acf_range',qualname='AcfRange',source_files=files,
            source_sha256=implementation_sha256(files,source_root=SRC/'strategy_runtime'))
        strategy=StrategyCandidate('S013',f'C{5700+index}',payload,SRC/'strategy_runtime')
        identity=StrategyRuntime().identify(strategy,dependencies=DEPENDENCIES)
        new.append({'label':f'N{index}','index':index,'candidate_id':strategy.candidate_id,'content_sha256':identity.content_sha256,
            'payload':payload,'source_directory':'strategy_runtime','background':control['background'],
            'mechanism':payload['parameters']['mechanism'],'mode':'M1','existing_identity':None,'reused':False,'parent_control':control['label']})
        old=deepcopy(control['payload']['parameters'])
        old['mechanism']=payload['parameters']['mechanism']
        assert old==payload['parameters']
    return controls,new,previous


def main():
    assert not (PROTOCOLS/'plan_references.json').exists()
    ctx=context(1)
    controls,new,previous=configurations()
    for cfg in new:
        assert not (ctx.repository.research_registry_root/f"S013/candidates/{cfg['candidate_id']}.json").exists()
        assert not (ROOT/f"research/S013/assets/candidates/{cfg['candidate_id']}").exists()
    delivery=read(ROOT/'research/S013/assets/deliveries/CANDIDATES/33/delivery.json')
    names={'runs-analysis','runs-conclusion'}
    diagnosis={ref['name']:ref for ref in delivery['content']['evidence'] if ref['name'] in names}
    assert set(diagnosis)==names
    for value in diagnosis.values():
        ref=EvidenceRef.from_dict(value)
        assert file_hash(ref.resolve(ROOT))==ref.sha256
    plan={'name':'S013-EX038-bear-mean-acf-adverse-tr-width','controls':controls,'configurations':new,
        'cells':[{k:c[k] for k in ('background','mechanism','label','candidate_id','content_sha256')} for c in controls+new],
        'mandate':previous['mandate'],'authorization':previous['authorization'],
        'previous_delivery':read(ROOT/'research/S013/experiments/EX037_20261011/protocols/delivery_reference.json'),
        'diagnosis_references':diagnosis,
        'hypothesis':'EX037 cutoff1 fixes annualDD but breaks2023 profit. A wider2/3-unit causal cutoff may distinguish recoverable short adverse moves from larger held losses. This is disclosed new-constant calibration, not proof of robustness.',
        'mechanism':'While already signal-held bear, anchor is HFQ signal entry Close. At T, max(anchor-Close_T,0)>=k*mean(TR_{T-20..T-1}), fixedk=2or3 sets target0, reason bear_risk, after original loss/trail and before range/time/regime. TR=max(H-L,abs(H-prevClose),abs(L-prevClose)). Current shock excluded from mean; current past20 unit updates each signal day. No entry-day exit, no waiting or date exceptions; next flat original eligibility may reenter.',
        'fixed_new_choices':'Two fixed cutoff choices2/3 and20 strictlypastTR observations are new mechanism constants. Choice formed after cutoff1 failed; both widths and both backgrounds retained. Original13-coordinate comparison excludes these constants, so success does not prove their broad sensitivity or independent validation. HFQ signal anchor is distinct from actual fill/fees; no intraday guaranteed stop price.',
        'preserved':'All13 original numeric values/domains active; H8/H4 signal-session units, original score/confirmation threshold and raw regime, centeredACF from existing L, BODY only in its declared background; stop/trail/momentum null, original binary target and T+1 execution/cost/benchmark/data/window.',
        'predeclared_selection':'Four new centers with5 actual complete evaluations (N0 serial/spawn exact and N1/N2/N3 once), five old complete centers exact reuse including both zero-risk and both cutoff1 failed backgrounds. Only new centers passing all4 original gates receive32 full13domain parameters each,33actual evaluations per selectedcenter from per-center serial/spawn technical duplication; original EX01532 exact reuse if anyqualifier. No unqualified-center parameter expansion, no outcome point replacement or new economic gate.',
        'strongest_counterevidence':'Existing daily-loss and shorter timer controls often destroyed2023 profit. Early bear exit may realize losses before recovery, increase repeat entries/fees, or reduce2022/2023 profits. Old-path risk flags and2024 attribution are not a profit forecast.',
        'selection_history':'Repeatedly seen S013 development pool EX012..37. EX036 all-year adverse/TR distributions, including2023/2024, were already seen before choosing widths2/3; choices are outcome-informed mechanism calibration. Both zero-risk backgrounds fail2024 annualDD; both cutoff1 backgrounds fail2023 profit. No date-specific execution exception or removal. BODY gives different entry context. This is mechanism research, not independent validation or future guarantee.',
        'counts':{'new_business_configurations':4,'new_evaluations':5,'reused_controls':5},
        'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
        'boundaries':'S013 stage3 only; no adjacent batch bytes/newdata/dependencies/platform/freeze/PTE/prod/merge/tag/push.',
        'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    if (PROTOCOLS/'plan.json').exists():
        assert read(PROTOCOLS/'plan.json')==plan, 'Unpublished prospective plan must remain identical'
    else:
        write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',previous['authorization'])
    write(PROTOCOLS/'plan_references.json',{p.stem:publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+p.stem,p.read_bytes(),'application/json','json')).to_dict()
        for p in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')})
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':4},flush=True)


if __name__=='__main__':
    main()
