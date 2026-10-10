"""Declared supplemental one-step state/feature and persistent-opportunity checks."""
from diagnose import (
    ROOT, SRC, RUNS, PROTO, EXPERIMENT, PRIOR, context, read, write, cache_read,
    file_hash, resolve_center, state_trace, EvidenceRef, publish_evidence,
    MaterialEvidenceWrite, serialize_evaluation_evidence, validate_evaluation_evidence,
)
from collections import Counter
import numpy as np


def step(row, p, state):
    holding, route, age = state
    active = route if holding else row.regime
    rp = p[active]
    position = getattr(row, active+'_range_position')
    if holding:
        age += 1
        reason = ('range' if position >= rp['exit'] else 'time' if age >= rp['max_hold']
                  else 'regime' if row.regime != route else 'hold')
        return ((True,route,age) if reason == 'hold' else (False,None,0)), reason
    eligible = (position <= rp['entry'] and (rp['acf_min'] is None or row.acf1 >= rp['acf_min'])
                and (rp['momentum_min'] is None or row.momentum20 >= rp['momentum_min']))
    reason = 'flat' if not eligible else ('entry' if row.confirmation_score >= p['confirmation']['threshold'] else 'confirmation_rejected')
    return ((True,row.regime,0) if reason == 'entry' else (False,None,0)), reason


def classify(pp, qq, pq, qp):
    """Arguments are native p(Sp), q(Sq), p(Sq), q(Sp), each post-state."""
    if pp[0] == qq[0]:
        return 'SAME_TARGET'
    direct = (pp[0] != qp[0], pq[0] != qq[0])
    inherited = (pp[0] != pq[0], qp[0] != qq[0])
    assert any(direct) or any(inherited)
    if not any(direct):
        return 'INHERITED_STATE_ONLY'
    if not any(inherited):
        return 'CURRENT_FEATURE_RULE_ONLY'
    return 'MIXED'


def refresh_events(frame,p,before,episodes):
    reasons = frame.signal_reason.to_numpy()
    entries = np.flatnonzero(reasons=='entry')
    events=[]
    for i in np.flatnonzero(reasons=='time'):
        if before[i][1] != 'bear':
            continue
        later=entries[entries>i]
        j=int(later[0]) if len(later) else None
        until=len(frame) if j is None else j+1
        raw_bear=frame.regime.iloc[i:until].eq('bear').to_numpy()
        in_range=frame.bear_range_position.iloc[i:until].le(p['bear']['entry']).to_numpy()
        unrefreshed=bool(j is not None and (raw_bear & in_range).all())
        exit_segments=[e for e in episodes if e['start_index']<=i<=e['last_different_index']]
        segments=[e for e in exit_segments if j is not None and j<=e['last_different_index']]
        events.append({'exit_index':int(i),'next_entry_index':j,
                       'waiting_sessions':None if j is None else j-int(i),
                       'next_entry_route':None if j is None else str(frame.regime.iloc[j]),
                       'bear_range_opportunity_unrefreshed':unrefreshed,
                       'exit_inside_state_episode':bool(exit_segments),
                       'entry_after_state_resynchronization':bool(exit_segments and not segments and j is not None),
                       'inside_state_episode':bool(segments),
                       'state_episode_sessions':segments[0]['state_difference_sessions'] if segments else None,
                       'time_seeded_state_episode':segments[0]['time_in_reason_pair'] if segments else None})
    repeat=[e for e in events if e['bear_range_opportunity_unrefreshed']]
    return {'bear_time_exits':len(events),'unrefreshed_bear_reentries':len(repeat),
            'next_session_unrefreshed_bear_reentries':sum(e['waiting_sessions']==1 for e in repeat),
            'unrefreshed_reentries_inside_state_episode':sum(e['inside_state_episode'] for e in repeat),
            'unrefreshed_reentries_in_episode_at_least_8_sessions':sum(e['inside_state_episode'] and e['state_episode_sessions']>=8 for e in repeat),
            'events':events}


def main():
    assert not (PROTO/'refresh_reference.json').exists()
    diagnosis=read(RUNS/'diagnosis.json')
    assert diagnosis['status']=='PASS'
    method={'source_sha256':file_hash(SRC/'refresh_diagnosis_v2.py'),
            'primary_diagnosis_reference':read(PROTO/'diagnosis_reference.json'),
            'previous_failed_method':read(PROTO/'refresh_method_reference.json'),
            'technical_correction':'v1 stopped on valid 2019-12-31 decision for 2020-01-02 execution: assign annual decision groups to valid_session year. No native account rerun, parameter or economic change. Also require TIME exit and next entry inside the same state episode when counting within-episode reentries.',
            'new_account_evaluations':0,
            'method':'Reuse exact same 33 native accounts. Per day one-step cross-check p(features_p,state_p), q(features_q,state_q), p(features_p,state_q), q(features_q,state_p); first two must reproduce native target/state/reason. For divergent native targets, no direct difference on either fixed state => inherited-state only; no state effect under either fixed rule/features => current-rule/features only; others mixed. No off-policy state propagated or cash/profit simulated. Count bear TIME exits followed by next entry before rawbear or original range-entry opportunity refresh, inclusive exit..next-entry. Eight-session group is diagnostic center bull H8 scale, not economic gate or filtering.',
            'limits':'Fixed historical features and inherited states; joint parameter attribution remains local/descriptive, not isolated parameter causality. Range-opportunity memory is proposed only if supported; will change entry behavior and may harm frequency.'}
    write(PROTO/'refresh_method_v2.json',method)
    ref=publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'declared-refresh-method-v2',(PROTO/'refresh_method_v2.json').read_bytes(),'application/json','json'))
    write(PROTO/'refresh_method_v2_reference.json',ref.to_dict())
    original=next(c for c in read(PRIOR.parent/'protocols/plan.json')['controls'] if c['label']=='B0-TIME')
    bound,result=resolve_center(original)
    frame=result.runs[0].execution.decisions
    p=bound.strategy.payload['parameters']
    cbefore,cstates,_=state_trace(frame,p)
    center_rows=list(frame.itertuples())
    rows=[]
    total=Counter()

    def verify(binding,account,refdict):
        evidence=EvidenceRef.from_dict(refdict)
        assert file_hash(evidence.resolve(ROOT))==evidence.sha256
        formal=read(evidence.resolve(ROOT))
        validate_evaluation_evidence(formal)
        assert formal==serialize_evaluation_evidence(binding,account)

    verify(bound,result,diagnosis['input_accounts']['center'])
    for item in read(PROTO/'plan.json')['points']:
        other,account=cache_read(ROOT/'.tmp/s013-mechanism-EX015/parameters'/(item['label']+'.pkl.gz'))
        verify(other,account,diagnosis['input_accounts'][item['label']])
        native=account.runs[0].execution.decisions
        q=other.strategy.payload['parameters']
        pbefore,pstates,_=state_trace(native,q)
        classes=Counter()
        yearly={str(y):Counter() for y in range(2020,2027)}
        for i,row in enumerate(native.itertuples()):
            pp,reason_p=step(center_rows[i],p,cbefore[i])
            qq,reason_q=step(row,q,pbefore[i])
            pq,_=step(center_rows[i],p,pbefore[i])
            qp,_=step(row,q,cbefore[i])
            assert pp==cstates[i] and qq==pstates[i]
            assert reason_p==frame.signal_reason.iloc[i] and reason_q==row.signal_reason
            classification=classify(pp,qq,pq,qp)
            classes[classification]+=1
            yearly[str(int(str(row.valid_session)[:4]))][classification]+=1
        total.update(classes)
        episode=next(r['state_episodes']['episodes'] for r in diagnosis['points'] if r['point_index']==item['point_index'])
        rows.append({'point_index':item['point_index'],'one_step_classes':dict(classes),
                     'yearly_one_step_classes':{k:dict(v) for k,v in yearly.items()},
                     'center_refresh':refresh_events(frame,p,cbefore,episode),
                     'point_refresh':refresh_events(native,q,pbefore,episode)})
    summary={'one_step_classes':dict(total),
             'mean_point_unrefreshed_bear_reentries':float(np.mean([r['point_refresh']['unrefreshed_bear_reentries'] for r in rows])),
             'mean_point_bear_time_exits':float(np.mean([r['point_refresh']['bear_time_exits'] for r in rows])),
             'mean_point_unrefreshed_in_long_episode':float(np.mean([r['point_refresh']['unrefreshed_reentries_in_episode_at_least_8_sessions'] for r in rows])),
             'center_refresh':refresh_events(frame,p,cbefore,[])}
    output={'status':'PASS','new_account_evaluations':0,'input_accounts':diagnosis['input_accounts'],
            'method_reference':ref.to_dict(),'summary':summary,'points':rows,'objective_achieved':False,
            'not_proof':'Local transition decomposition and repeated-opportunity counts are descriptive, not complete-policy returns.'}
    write(RUNS/'refresh_diagnosis.json',output)
    published=publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'one-step-refresh-diagnosis-v2',(RUNS/'refresh_diagnosis.json').read_bytes(),'application/json','json'))
    write(PROTO/'refresh_reference.json',published.to_dict())
    print({k:v for k,v in summary.items() if k!='center_refresh'},flush=True)
    print({k:v for k,v in summary['center_refresh'].items() if k!='events'},flush=True)


if __name__=='__main__':
    main()
