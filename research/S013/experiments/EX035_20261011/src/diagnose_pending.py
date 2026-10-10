"""Declared fixed-old-path eligibility release diagnostic, zero new accounts."""
from common import ROOT, SRC, PROTOCOLS, RUNS, EXPERIMENT, context, read, write, cache_read, file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from account_reference import verify_account
import numpy as np


def main():
    assert not (PROTOCOLS/'pending_diagnosis_reference.json').exists()
    refs=read(ROOT/'research/S013/assets/runs/EX034_20261011/account_references.json')
    method={'name':'S013-EX035-fixed-old-path-pending-diagnosis','source_sha256':file_hash(SRC/'diagnose_pending.py'),
            'old_accounts':refs,'new_account_evaluations':0,
            'method':'Authenticate original C2132 and EX034 C6100 whole native accounts; in each exact old pending interval after bear TIME arm, find first flat signal with rawbear/range-entry still true but original bear ACF or momentum eligibility false. Compare that first possible additional release with old actual release and count old blocked opportunities afterward. No alternative state propagated, no new account, no inferred intervention profits.',
            'selection_history':'S013 repeated development pool EX012..34; most recent known failure motivated comparing old range-only release with existing original eligibility. No additional threshold/window/confirmation change.'}
    write(PROTOCOLS/'pending_method.json',method)
    ctx=context(1)
    mr=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'declared-pending-diagnosis',(PROTOCOLS/'pending_method.json').read_bytes(),'application/json','json'))
    write(PROTOCOLS/'pending_method_reference.json',mr.to_dict())
    oldplan=read(ROOT/'research/S013/experiments/EX034_20261011/protocols/plan.json')
    for filename,digest in oldplan['source_files'].items():
        assert file_hash(ROOT/'research/S013/experiments/EX034_20261011/src'/filename)==digest
    coarse_bound,coarse_result=cache_read(ROOT/'.tmp/s013-mechanism-EX034/N0.pkl.gz')
    # Resolve only the already-authenticated original control chain.
    config=oldplan['controls'][0]
    while config.get('reused'):
        origin=config['reuse_from']
        assert origin.startswith(('EX012_','EX013_','EX014_','EX015_'))
        cache=ROOT/'.tmp'/('s013-mechanism-'+origin[:5])/(config['reuse_label']+'.pkl.gz')
        if cache.exists():
            original_bound,original_result=cache_read(cache)
            break
        previous=read(ROOT/f'research/S013/experiments/{origin}/protocols/plan.json')
        label=config['reuse_label']
        config=next(c for c in previous.get('controls',[])+previous['configurations']
                    if c.get('label',c.get('background','')+'-'+c.get('mode',''))==label)
    else:
        raise AssertionError('Original native transport absent; no substitute/replay authorized by this diagnostic')
    audits={}
    for label,bound,result in (('B0-TIME',original_bound,original_result),('N0',coarse_bound,coarse_result)):
        ref=EvidenceRef.from_dict(refs[label])
        assert ref.experiment.strategy_id=='S013' and file_hash(ref.resolve(ROOT))==ref.sha256
        formal=read(ref.resolve(ROOT))
        validate_evaluation_evidence(formal)
        assert formal==serialize_evaluation_evidence(bound,result)
        actual=ctx.runtime.identify(bound.strategy,dependencies=bound.dependencies)
        assert actual.content_sha256==result.runs[0].identity.content_sha256
        audits[label]=verify_account(bound,result)
    frame=coarse_result.runs[0].execution.decisions
    p=coarse_bound.strategy.payload['parameters']['bear']
    held=frame.target_position.shift(1,fill_value=0.).eq(1.).to_numpy()
    acf_invalid=np.zeros(len(frame),dtype=bool) if p['acf_min'] is None else frame.acf1.lt(p['acf_min']).to_numpy()
    momentum_invalid=np.zeros(len(frame),dtype=bool) if p['momentum_min'] is None else frame.momentum20.lt(p['momentum_min']).to_numpy()
    additional=(~held & frame.refresh_pending_before.astype(bool).to_numpy() & frame.regime.eq('bear').to_numpy()
                & frame.bear_range_position.le(p['entry']).to_numpy() & (acf_invalid|momentum_invalid))
    arms=np.flatnonzero(frame.refresh_armed)
    releases=np.flatnonzero(frame.refresh_released)
    intervals=[]
    for start in arms:
        later=releases[releases>start]
        end=int(later[0]) if len(later) else len(frame)
        indexes=np.flatnonzero(additional[start+1:end])+start+1
        first=int(indexes[0]) if len(indexes) else None
        assert not held[start+1:end].any()
        intervals.append({'arm_index':int(start),'old_release_index':end if end<len(frame) else None,
                          'first_additional_release_index':first,
                          'old_wait_sessions':end-int(start),
                          'earlier_release_sessions':None if first is None else end-first,
                          'old_blocked_opportunities_after_first_release':0 if first is None else int(frame.refresh_blocked.iloc[first:end].sum())})
    changed=[r for r in intervals if r['first_additional_release_index'] is not None]
    output={'status':'PASS','new_account_evaluations':0,'input_accounts':refs,'account_audits':audits,
            'method_reference':mr.to_dict(),'intervals':intervals,
            'summary':{'old_pending_intervals':len(intervals),'intervals_with_earlier_release':len(changed),
                       'fixed_old_path_extra_release_days':int(additional.sum()),
                       'median_earlier_release_sessions':None if not changed else float(np.median([r['earlier_release_sessions'] for r in changed])),
                       'old_blocked_opportunities_after_first_extra_release':sum(r['old_blocked_opportunities_after_first_release'] for r in intervals)},
            'limits':'Counts on fixed old states/features do not forecast new trade count, profits, drawdown or later pending resets; full new account required. Original score gate not included in new release predicate.'}
    write(RUNS/'pending_diagnosis.json',output)
    ref=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'fixed-old-path-pending-diagnosis',(RUNS/'pending_diagnosis.json').read_bytes(),'application/json','json'))
    write(PROTOCOLS/'pending_diagnosis_reference.json',ref.to_dict())
    print({'pending_diagnosis':'PASS','new_accounts':0,'summary':output['summary']},flush=True)


if __name__=='__main__':
    main()
