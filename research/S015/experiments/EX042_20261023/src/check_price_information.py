"""Focused runtime contract checks on authenticated prior inputs; no accounts."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from datetime import date
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from strategy_runtime import ParameterSet, TradableWindow

ROOT=Path(__file__).resolve().parents[5]
HERE=Path(__file__).resolve().parents[1]
BASE=HERE.parent
def read(p):return json.loads(p.read_bytes())
def module(p,name):
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def main():
    source=HERE/'src/strategy_runtime/strategies/price_information.py';m=module(source,'price_runtime_check')
    r=EvidenceRef.from_dict(read(BASE/'EX026_20261023/others/protocol_refs.json')['study.py'])
    oldpath=BASE/'EX026_20261023/src/study.py'
    assert oldpath.read_bytes()==r.resolve(ROOT).read_bytes()
    old=module(oldpath,'authenticated_prior_inputs');oldrefs=old.sources();adj,raw,bars,rules,ids=old.inputs(oldrefs)
    for f in (adj,raw,bars):f.attrs={}
    refs=read(BASE/'EX036_20261023/others/published_refs.json')['materials']
    priorref=EvidenceRef.from_dict(refs['others/model_features.csv']);prior=pd.read_csv(priorref.resolve(ROOT))
    x=m.causal_features(adj,raw,bars);actual=x.loc['2025-01-02':]
    assert len(x)==435 and len(actual)==434 and not bool(x.feature_ready.iloc[0]) and actual.feature_ready.all()
    assert actual.index.strftime('%Y-%m-%d').tolist()==prior.date.tolist()
    np.testing.assert_allclose(actual[list(m.COLUMNS)],prior[list(m.COLUMNS)],rtol=1e-11,atol=1e-12)
    errors=(actual[list(m.COLUMNS)].to_numpy()-prior[list(m.COLUMNS)].to_numpy())
    checks=['all_434_by_13_features_match_authenticated_EX036','canonical_seed_cash_only']
    # Recompute six complete prefixes, including the first and last decision.
    for position in (0,39,99,183,351,433):
        xx=m.causal_features(adj.iloc[:76+position],raw.iloc[:76+position],bars.iloc[:8*(position+1)])
        pd.testing.assert_frame_equal(xx,x.iloc[:position+2],check_exact=True)
    checks.append('six_full_prefixes_exact')
    one={'columns':['r1'],'center':[0.],'scale':[1.],'beta':[1.,0.]}
    risk={'columns':['r1'],'center':[0.],'scale':[1.],'beta':[0.,0.],'threshold':.1}
    schedule=[{'date':'2025-01-02','train_known_max':'2024-12-31','models':{'path':one,'risk':risk}}]
    params={'family':'A','mode':'and','hold':3,'exposure':1.,'schedule':schedule}
    out=m.intentions(x,params)
    assert out.target_position.iloc[:10].tolist()==[0.,1.,1.,1.,0.,1.,1.,1.,0.,1.]
    assert out.intent_age.iloc[:10].tolist()==[0,1,2,3,0,1,2,3,0,1]
    assert m.intentions(x,{**params,'schedule':[]}).target_position.eq(0).all()
    checks.extend(['fixed_three_signal_day_cycle_no_same_day_reentry','empty_model_schedule_stays_cash'])
    changed=deepcopy(params)
    update=deepcopy(schedule[0]);update['date']='2025-01-06';update['train_known_max']='2025-01-03';update['models']['path']['beta']=[-1.,0.]
    changed['schedule'].append(update)
    later=m.intentions(x,changed)
    assert later.target_position.iloc[:6].tolist()==[0.,1.,1.,1.,0.,0.]
    assert later.path_prediction.loc['2025-01-03']==1 and later.path_prediction.loc['2025-01-06']==-1
    pd.testing.assert_frame_equal(later.loc[:'2025-01-03'],out.loc[:'2025-01-03'])
    checks.extend(['future_model_never_used_early','prediction_change_does_not_exit_active_cycle'])
    highrisk=deepcopy(params);highrisk['schedule'][0]['models']['risk']['beta']=[.2,0.]
    assert m.intentions(x,{**highrisk,'mode':'path'}).target_position.sum()>0
    assert m.intentions(x,{**highrisk,'mode':'risk'}).target_position.eq(0).all()
    assert m.intentions(x,{**highrisk,'mode':'and'}).target_position.eq(0).all()
    checks.append('three_permission_modes_use_their_declared_predictors')
    bads=[]
    z=deepcopy(params);z['schedule'][0]['train_known_max']='2025-01-02';bads.append(z)
    z=deepcopy(params);z['schedule'][0]['models']['path']['beta'][0]=float('nan');bads.append(z)
    z=deepcopy(params);z['schedule'][0]['models']['path']['scale'][0]=0;bads.append(z)
    z=deepcopy(params);z['schedule'][0]['models']['path']['columns']=['unknown'];bads.append(z)
    z=deepcopy(params);z['schedule'].append(deepcopy(z['schedule'][0]));bads.append(z)
    z=deepcopy(params);z['hold']=True;bads.append(z)
    z=deepcopy(params);z['exposure']=1.1;bads.append(z)
    for p in bads:
        try:m.validate_parameters(p)
        except ValueError:pass
        else:raise AssertionError('invalid model parameters accepted')
    checks.append('seven_invalid_parameter_boundaries_rejected')
    runtime=m.PriceInformation(ParameterSet(params));days=tuple(pd.Timestamp(d).date() for d in adj.Date)
    scopes=[]
    for start in (date(2025,1,2),date(2025,2,6)):
        window=TradableWindow(start,date(2026,10,21));runtime.calendar_request(window)
        scope=runtime.derive_calculation_scope(window,days);scopes.append(scope)
        assert scope.calculation_dates[0]==date(2024,12,31)
        assert scope.inputs['intraday'].coverage.minimum_sessions==0
        assert scope.inputs['intraday'].coverage.observations_through>= '2025-01-02'
        truncated={
            'market':adj[pd.to_datetime(adj.Date)<=pd.Timestamp(scope.inputs['market'].end)],
            'execution':raw[pd.to_datetime(raw.Date)<=pd.Timestamp(scope.inputs['execution'].end)],
            'intraday':bars[pd.to_datetime(bars.Date).dt.normalize()<=pd.Timestamp(scope.inputs['intraday'].end)]}
        computed=runtime.calculate_context_history(truncated,SimpleNamespace(sessions=pd.DatetimeIndex(scope.calculation_dates)))
        pd.testing.assert_frame_equal(computed,out.reindex(pd.DatetimeIndex(scope.calculation_dates)))
    checks.append('two_window_scope_contracts_construct')
    policy=runtime.definition.execution.settings['capital']
    assert policy['mode']=='available_cash_fraction' and policy['target_scope']=='entry_cycle' and policy['allocation_fraction']==1.
    checks.append('entry_cycle_available_cash_contract')
    result={'status':'PASS','source_sha256':sha256(source.read_bytes()).hexdigest(),'feature_rows':434,'feature_columns':list(m.COLUMNS),'maximum_absolute_feature_difference':float(np.abs(errors).max()),'checks':checks,'future_coefficient_guard':'Strictly earlier train_known_max and latest schedule date <= each signal date','input_loader':r.to_dict(),'prior_features':priorref.to_dict(),'data_identities':ids,'accounts_created':0}
    (HERE/'others/runtime_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
