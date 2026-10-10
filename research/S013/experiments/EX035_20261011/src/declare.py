"""Prospective isolated expansion of the original bear-entry refresh release guard."""
from copy import deepcopy
from strategy_runtime import StrategyRuntime, StrategyCandidate, implementation_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, DEPENDENCIES, context, read, write, file_hash


def configuration():
    old=read(ROOT/'research/S013/experiments/EX034_20261011/protocols/plan.json')
    original=deepcopy(old['controls'][0])
    refresh=deepcopy(old['configurations'][0])
    refresh.update(label='C0-RANGE_REFRESH',reused=True,reuse_from='EX034_20261011',reuse_label='N0')
    payload=deepcopy(refresh['payload'])
    files=['strategies/'+name+'.py' for name in (
        'range_reversion','adaptive_range','confirmed_range','reentry_confirmed_range','eligibility_refresh_range','__init__')]
    payload['parameters']['mechanism']='BEAR_TIME_ELIGIBILITY_REFRESH'
    payload['runtime'].update(module='strategy_runtime.strategies.eligibility_refresh_range',qualname='EligibilityRefreshRange',
        source_files=files,source_sha256=implementation_sha256(files,source_root=SRC/'strategy_runtime'))
    strategy=StrategyCandidate('S013','C6000',payload,SRC/'strategy_runtime')
    identity=StrategyRuntime().identify(strategy,dependencies=DEPENDENCIES)
    new={'label':'N0','index':0,'candidate_id':'C6000','content_sha256':identity.content_sha256,
         'payload':payload,'source_directory':'strategy_runtime','background':'B0','mechanism':'BEAR_TIME_ELIGIBILITY_REFRESH',
         'mode':'M1','existing_identity':None,'reused':False,'parent_control':'C0-RANGE_REFRESH'}
    parameters=deepcopy(payload['parameters'])
    parameters['mechanism']='BEAR_TIME_ENTRY_REFRESH'
    assert parameters==refresh['payload']['parameters']
    return [original,refresh],new,old


def main():
    assert not (PROTOCOLS/'plan.json').exists()
    ctx=context(1)
    assert not (ctx.repository.research_registry_root/'S013/candidates/C6000.json').exists()
    assert not (ROOT/'research/S013/assets/candidates/C6000').exists()
    controls,new,prior=configuration()
    references=deepcopy(prior['diagnosis_references'])
    references.update({name:read(PROTOCOLS/filename) for name,filename in (
        ('EX035-pending','pending_diagnosis_reference.json'),('EX035-pending_method','pending_method_reference.json'))})
    for value in references.values():
        ref=EvidenceRef.from_dict(value)
        assert file_hash(ref.resolve(ROOT))==ref.sha256
    plan={'name':'S013-EX035-bear-time-eligibility-refresh','controls':controls,'configurations':[new],
          'cells':[{k:c[k] for k in ('background','mechanism','label','candidate_id','content_sha256')} for c in (*controls,new)],
          'mandate':prior['mandate'],'authorization':prior['authorization'],'diagnosis_references':references,
          'previous_delivery':read(ROOT/'research/S013/experiments/EX034_20261011/protocols/delivery_reference.json'),
          'hypothesis':'EX034 range-only entry memory overblocks. Expanding release to original enabled ACF/momentum eligibility failure may distinguish a fresh original opportunity sooner while retaining memory within uninterrupted eligibility.',
          'mechanism':'ARM exactly EX034: original final bear TIME, current rawbear, bear range<=entry, without requiring ACF/momentum/score. At flat T clear first if rawregime!=bear OR bear range>entry OR enabled bear ACF<acf_min OR enabled bear momentum20<momentum_min. Strict equality retains pending. Score never clears. Release T may enter by original rules. Other state/diagnostic semantics unchanged.',
          'preserved':'All13 numeric centers/full domains and H8/H4 signal-session units, original ACF20/rawregime/ranges/score/priority/execution/benchmark. ACF threshold now also controls memory release; this categorical mechanism change and coupled threshold role are disclosed. No new numeric parameter or fixed wait.',
          'predeclared_selection':'One new center, two exact native old centers reused, two actual serial/spawn evaluations. Only new N0 all4-gate qualification triggers32 new complete-domain parameter accounts plus32 exact original EX015 reuse,33actual new evaluations. Old unqualified EX034 remains diagnostic and receives no parameter supplement. Otherwise zero new parameter accounts; no replacement or added economic gate.',
          'counts':{'new_business_configurations':1,'new_evaluations':2,'reused_controls':2},
          'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
          'strongest_counterevidence':'Range-only memory reduced112 trades to86 and made both benchmark-negative years negative. Earlier ACF release may merely restore old fragility or impair return/annual drawdown; fixed-old-path10of18 earlier intervals and25 later blocked opportunities are not propagated profit predictions.',
          'selection_history':'Repeatedly seen S013 EX012..34 development pool; structural selection follows whole-path diagnosis, no date/trade-profit exception, new data or independent validation claimed.',
          'boundaries':'S013 stage3 only; no adjacent batch bytes, newdata/dependencies/platform/freeze/PTE/production/merge/tag/push.',
          'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    refs={path.stem:publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+path.stem,path.read_bytes(),'application/json','json')).to_dict()
          for path in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')}
    write(PROTOCOLS/'plan_references.json',refs)
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':1,'identity':new['content_sha256']},flush=True)


if __name__=='__main__':
    main()
