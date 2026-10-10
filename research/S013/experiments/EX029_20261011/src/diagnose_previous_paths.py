"""Descriptive exact-account path audit; no new market account evaluation."""
from collections import Counter
from hashlib import sha256
import numpy as np
import pandas as pd
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence,validate_evaluation_evidence
from common import ROOT,RUNS,PROTOCOLS,EXPERIMENT,context,read,write,cache_read
from run_parameters import resolve_center,get_path


def main():
    assert not (PROTOCOLS/'previous_path_diagnosis_reference.json').exists()
    previous=read(ROOT/'research/S013/experiments/EX027_20261011/protocols/plan.json')
    config=next(c for c in previous['controls'] if c['label']=='B0-TIME')
    bound,result=resolve_center(config)
    center_ref=EvidenceRef.from_dict(read(ROOT/'research/S013/assets/runs/EX027_20261011/account_references.json')['B0-TIME'])
    assert sha256(center_ref.resolve(ROOT).read_bytes()).hexdigest()==center_ref.sha256
    assert read(center_ref.resolve(ROOT))==serialize_evaluation_evidence(bound,result)
    frame=result.runs[0].execution.decisions
    p=config['payload']['parameters']
    geometry=read(ROOT/'research/S013/experiments/EX027_20261011/protocols/geometry.json')
    analysis=read(ROOT/'research/S013/assets/runs/EX015_20261011/parameter_analysis.json')
    matrix=read(ROOT/'research/S013/assets/runs/EX015_20261011/parameter_matrix.json')
    entries=sorted((r for r in matrix['rows'] if r['center']=='B0-TIME'),key=lambda r:r['point_index'])
    assert len(entries)==32
    facts={r['point_index']:r for r in analysis['points']['B0-TIME']}
    paths=[]
    causes=Counter()
    input_refs={'center':center_ref.to_dict()}
    target=frame.target_position.to_numpy()
    years=pd.to_datetime(frame.signal_date).dt.year.to_numpy()
    for item in entries:
        key=item['point_index']
        ref=EvidenceRef.from_dict(item['reference'])
        assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest()==ref.sha256
        actual=read(ref.resolve(ROOT))
        validate_evaluation_evidence(actual)
        other,account=cache_read(ROOT/'.tmp/s013-mechanism-EX015/parameters'/(item['label']+'.pkl.gz'))
        assert serialize_evaluation_evidence(other,account)==actual
        assert other.lineage.parameter_binding.point.point_index==key
        native=account.runs[0].execution.decisions
        np.testing.assert_array_equal(native.signal_date,frame.signal_date)
        np.testing.assert_array_equal(native.acf1,frame.acf1)
        np.testing.assert_array_equal(native.close,frame.close)
        mask=native.target_position.to_numpy()!=target
        indexes=np.flatnonzero(mask)
        assert len(indexes)>0
        first=int(indexes[0])
        held=first>0 and target[first-1]==1.
        cause='holding_exit' if held else 'flat_entry'
        causes[cause]+=1
        q=other.strategy.payload['parameters']
        changes={name:{'before':get_path(p,name),'after':get_path(q,name)}
            for name,*_ in geometry['coordinates'] if get_path(p,name)!=get_path(q,name)}
        raw_gate_change=int(np.count_nonzero(frame.acf1.ge(p['bear']['acf_min']).to_numpy()!=native.acf1.ge(q['bear']['acf_min']).to_numpy()))
        paths.append({'point_index':key,'candidate_id':item['candidate_id'],'changes':changes,
            'first_target_divergence':{'date':str(frame.signal_date.iloc[first]),'category':cause,
                'center_reason':str(frame.signal_reason.iloc[first]),'point_reason':str(native.signal_reason.iloc[first]),
                'center_regime':str(frame.regime.iloc[first]),'point_regime':str(native.regime.iloc[first])},
            'different_target_days':int(mask.sum()),'different_target_days_2023':int(mask[years==2023].sum()),
            'different_regime_days':int(np.count_nonzero(native.regime.to_numpy()!=frame.regime.to_numpy())),
            'raw_bear_threshold_decision_changed_days':raw_gate_change,
            'y2023_return':facts[key]['annual']['2023']['return'],'net_cagr':facts[key]['net_cagr']})
        input_refs[item['label']]=ref.to_dict()
    binding=next(iter(bound.input_bindings.values()))
    fetched=context(1).data.fetch(binding.plan.requests['daily'],prepared=binding.prepared)
    assert fetched.ready
    bars=fetched.dataframe.copy()
    bars.index=pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
    returns=bars.Close.astype(float).pct_change(fill_method=None)
    def acf(values):
        centered=values-values.mean()
        variance=np.mean(centered**2)
        return np.nan if np.isclose(variance,0) else float(np.dot(centered[1:],centered[:-1])/19/variance)
    raw=returns.rolling(20).apply(acf,raw=True)
    dates=pd.DatetimeIndex(pd.to_datetime(frame.signal_date)).normalize()
    np.testing.assert_array_equal(raw.reindex(dates),frame.acf1)
    L=p['confirmation']['lookback']
    rolling=raw.shift(1).rolling(L,min_periods=L)
    baselines={'MEDIAN':rolling.median(),'MEAN':rolling.mean()}
    base=frame.regime.eq('bear').to_numpy() & ~frame.target_position.shift(1,fill_value=0.).eq(1.).to_numpy() & frame.bear_range_position.le(p['bear']['entry']).to_numpy()
    absolute=raw.reindex(dates).ge(p['bear']['acf_min']).to_numpy()
    contexts={}
    for name,baseline in baselines.items():
        values=baseline.reindex(dates).to_numpy()
        assert np.isfinite(values).all()
        centered=(raw-baseline).reindex(dates).ge(p['bear']['acf_min']).to_numpy()
        contexts[name]={'past_baseline_min':float(values.min()),'past_baseline_median':float(np.median(values)),
            'past_baseline_max':float(values.max()),'absolute_fixed_state_bear_opportunities':int((base & absolute).sum()),
            'centered_fixed_state_bear_opportunities':int((base & centered).sum()),
            'added_fixed_state_days':int((base & centered & ~absolute).sum()),
            'removed_fixed_state_days':int((base & absolute & ~centered).sum()),
            'not_causal_returns':'Uses original flat/route state only; does not replay changed trading/cash/exits or imply incremental profit.'}
    output={'status':'PASS','new_account_evaluations':0,'input_accounts':input_refs,'first_divergence_counts':dict(causes),
        'mean_target_difference_days':float(np.mean([r['different_target_days'] for r in paths])),
        'mean_2023_target_difference_days':float(np.mean([r['different_target_days_2023'] for r in paths])),
        'mean_raw_bear_gate_difference_days':float(np.mean([r['raw_bear_threshold_decision_changed_days'] for r in paths])),
        'all_32_points':paths,'lagged_baseline_context':contexts,
        'interpretation':'Joint perturbations change several coordinates; first divergent action class and gate counts are descriptive, not isolated causal parameter attribution or profits. Full replay is required for new centering mechanisms.',
        'selection_history':'Posthoc S013 already exposed original32/EX027 negative centers. Existing account identities and every serialized native account exactly verified; no extra parameter scenarios or data.'}
    write(RUNS/'previous_path_diagnosis.json',output)
    ref=publish_evidence(context(1),MaterialEvidenceWrite(EXPERIMENT,'previous-path-diagnosis',(RUNS/'previous_path_diagnosis.json').read_bytes(),'application/json','json'))
    write(PROTOCOLS/'previous_path_diagnosis_reference.json',ref.to_dict())
    print({k:output[k] for k in ('status','new_account_evaluations','first_divergence_counts','mean_target_difference_days','mean_2023_target_difference_days','mean_raw_bear_gate_difference_days','lagged_baseline_context')})


if __name__=='__main__':
    main()
