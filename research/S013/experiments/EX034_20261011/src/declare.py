"""Prospective single-mechanism bear TIME entry-opportunity refresh contrast."""
from copy import deepcopy
from strategy_runtime import StrategyRuntime, StrategyCandidate, implementation_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from common import ROOT, SRC, PROTOCOLS, EXPERIMENT, DEPENDENCIES, context, read, write, file_hash


def configuration():
    old = read(ROOT/'research/S013/experiments/EX032_20261011/protocols/plan.json')
    control = deepcopy(next(c for c in old['controls'] if c['label']=='B0-TIME'))
    payload = deepcopy(control['payload'])
    files = ['strategies/'+name+'.py' for name in (
        'range_reversion','adaptive_range','confirmed_range','reentry_confirmed_range','entry_refresh_range','__init__')]
    payload['parameters']['mechanism'] = 'BEAR_TIME_ENTRY_REFRESH'
    payload['runtime'].update(module='strategy_runtime.strategies.entry_refresh_range',qualname='EntryRefreshRange',
                              source_files=files,source_sha256=implementation_sha256(files,source_root=SRC/'strategy_runtime'))
    strategy = StrategyCandidate('S013','C6100',payload,SRC/'strategy_runtime')
    identity = StrategyRuntime().identify(strategy,dependencies=DEPENDENCIES)
    new = {'label':'N0','index':0,'candidate_id':'C6100','content_sha256':identity.content_sha256,
           'payload':payload,'source_directory':'strategy_runtime','background':'B0','mechanism':'BEAR_TIME_ENTRY_REFRESH',
           'mode':'M1','existing_identity':None,'reused':False,'parent_control':'B0-TIME'}
    params=deepcopy(payload['parameters'])
    del params['mechanism']
    assert params==control['payload']['parameters']
    return control,new


def main():
    assert not (PROTOCOLS/'plan.json').exists()
    ctx=context(1)
    assert not (ctx.repository.research_registry_root/'S013/candidates/C6100.json').exists(), 'Candidate id already registered'
    assert not (ROOT/'research/S013/assets/candidates/C6100').exists(), 'Candidate id has retained assets'
    control,new=configuration()
    prior=read(ROOT/'research/S013/experiments/EX033_20261011/protocols/plan.json')
    references={name:read(ROOT/'research/S013/experiments/EX033_20261011/protocols'/filename)
                for name,filename in (('paths','diagnosis_reference.json'),('refresh','refresh_reference.json'))}
    for value in references.values():
        ref=EvidenceRef.from_dict(value)
        assert file_hash(ref.resolve(ROOT))==ref.sha256
    plan={'name':'S013-EX034-bear-time-entry-refresh','controls':[control],'configurations':[new],
          'cells':[{k:c[k] for k in ('background','mechanism','label','candidate_id','content_sha256')} for c in (control,new)],
          'mandate':prior['mandate'],'authorization':prior['authorization'],'diagnosis_references':references,
          'previous_delivery':read(ROOT/'research/S013/experiments/EX033_20261011/protocols/delivery_reference.json'),
          'hypothesis':'Repeated bear reentry during one persistent range-entry opportunity resets H and can amplify parameter-driven timing differences. A memory requiring opportunity refresh after bear TIME exit may reduce this path amplification.',
          'mechanism':'Set pending only when active bear final original reason TIME and current rawbear and bear range<=entry. While flat release on rawroute!=bear or bear range>entry, before original eligibility check; release day may enter. While pending reject bear entry otherwise passing original eligibility+score. Equality to entry retains pending. NonTIME exits and bull untouched.',
          'preserved':'All13 original numeric centers/full domains, original H8/H4 signal-session units, entry age0/no entry-day exit, ACF20, raw regime, confirmation score, ranges, loss>trailing>range>time>regime priority, execution and benchmark. New entry memory, not just an exit change; no fixed wait/new threshold/position smoothing.',
          'predeclared_selection':'One new center, one old original native center exact reuse, 2actual evaluations including serial/spawn duplicate. If new center qualifies all4 original gates, run32 new complete-domain parameter accounts with32 original EX015 exactreuse, 33actual new parameter evaluations. Otherwise zero new parameter accounts. No point deletion, shrinking, replacement or economic gate added.',
          'counts':{'new_business_configurations':1,'new_evaluations':2,'reused_controls':1},
          'resources':{'max_workers':8,'native_threads':1,'request_workers':1,'seed':13},
          'strongest_counterevidence':'Original112 closed trades barely exceed110; blocking profitable repetitions may harm return or frequency. Descriptive27/38 repeat events do not establish intervention profit. Inherited-state local classification is not isolated parameter causality.',
          'selection_history':'Repeatedly seen S013 EX012..33. Mechanism selected from EX033 whole-account/state diagnosis, not from a specific year/trade/date; no external data or independent verification claimed.',
          'boundaries':'S013 stage3 only, no newdata/dependencies/platform/phase4 handoff/freeze/PTE/production; no merge/tag/push.',
          'source_files':{p.relative_to(SRC).as_posix():file_hash(p) for p in SRC.rglob('*.py') if 'strategy_runtime' in p.parts}}
    write(PROTOCOLS/'plan.json',plan)
    write(PROTOCOLS/'authorization.json',prior['authorization'])
    refs={path.stem:publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'mechanism-'+path.stem,path.read_bytes(),'application/json','json')).to_dict()
          for path in (PROTOCOLS/'plan.json',PROTOCOLS/'authorization.json')}
    write(PROTOCOLS/'plan_references.json',refs)
    print({'declared':EXPERIMENT.experiment_id,'new_configurations':1,'identity':new['content_sha256']},flush=True)


if __name__=='__main__':
    main()
