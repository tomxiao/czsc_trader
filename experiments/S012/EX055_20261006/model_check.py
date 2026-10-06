"""Focused source-bound synthetic model extension check; no real prices/features."""
from pathlib import Path
from hashlib import sha256
import importlib.util,sys
import pandas as pd
from strategy_runtime import ParameterSet
from .factory_contract import MODEL_SHA,ORIGINAL_MODEL_SHA,FEATURE_SHA,require

def check(current,original):
    current=Path(current);original=Path(original)
    old=original.read_bytes();new=current.read_bytes()
    before=b'self.hold_days = _integer(values, "hold_days", 1, 60)'
    after=b'self.hold_days = _integer(values, "hold_days", 1, 120)'
    require(sha256(old).hexdigest()==ORIGINAL_MODEL_SHA and sha256(new).hexdigest()==MODEL_SHA
            and old.count(before)==1 and new==old.replace(before,after),'exact one-guard source byte difference required')
    modules=[]
    for label,path in [('original',original),('extended',current)]:
        name='s012_hold_extension_synthetic_'+label
        spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
        sys.modules[name]=module;spec.loader.exec_module(module);modules.append(module)
    dates=pd.bdate_range('2020-06-05',periods=155)
    features=pd.DataFrame({'Date':dates,**{c:[c.endswith('_valid') or c in ('o01','n09','m05','own_positive','mom_high','mom3_positive')]*len(dates) for c in modules[0].BOOLEAN_COLUMNS}})
    execution=pd.DataFrame({'Date':dates,'Close':[1+i*.002+(i%7)*.001 for i in range(len(dates))]})
    inputs={'features':features,'execution':execution}
    common={'confirm_o01':False,'cooldown':0,'risk_gate':'none','risk_exit':False,'trailing_stop':0.,'allocation':1.,
            'exit_policy':'fixed','min_hold':1,'risk_unknown_policy':'block',
            'rule':{'data_source':{'package':'strategy_runtime','path':'resources/features.csv','sha256':FEATURE_SHA}}}
    results=[]
    for route,lookback,premium in [('all_union',3,-.005),('momentum_union',5,.005)]:
        params=dict(common,opportunity=route,momentum_lookback=lookback,entry_premium=premium,hold_days=60)
        old_impl=modules[0].S012PlannedCycle(ParameterSet(params));new_impl=modules[1].S012PlannedCycle(ParameterSet(params))
        pd.testing.assert_frame_equal(old_impl.calculate_window_history(inputs,dates),new_impl.calculate_window_history(inputs,dates),check_exact=True)
        require(old_impl.definition.execution==new_impl.definition.execution,'h60 public execution changed')
        for hold in (80,120):
            impl=modules[1].S012PlannedCycle(ParameterSet(dict(params,hold_days=hold)))
            history=impl.calculate_window_history(inputs,dates)
            require(history.decision_reason.iloc[hold]=='EXIT_AGE' and history.planned_age.iloc[hold]==hold
                    and history.target_position.iloc[hold]==0,'new hold age/flat exit changed')
        try:modules[1].S012PlannedCycle(ParameterSet(dict(params,hold_days=121)))
        except ValueError:pass
        else:raise ValueError('hold121 must fail')
        try:modules[0].S012PlannedCycle(ParameterSet(dict(params,hold_days=80)))
        except ValueError:pass
        else:raise ValueError('original80 must fail')
        results.append({'route':route,'h60_all_signals_exact':True,'same_public_execution':True,'allowed':[80,120],'rejected':[121]})
    return {'status':'PASS_SOURCE_EXTENSION_SYNTHETIC_ONLY','source_diff_guards':1,'cases':results,'real_prices_or_features_used':False}
