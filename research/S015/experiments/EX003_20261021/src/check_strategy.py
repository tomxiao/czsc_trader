"""Focused causal and state checks; no provider calls or account simulation."""
import importlib.util
from types import SimpleNamespace
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from run_strategy_study import EROOT, save


def main():
    path=EROOT/'src/strategy_runtime/strategies/range_gate_reversal.py'
    spec=importlib.util.spec_from_file_location('s015_research_strategy',path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p={'entry':.005,'exit':0.,'max_days':3,'range_cap':0.}
    algorithm=mod.RangeGateReversal(ParameterSet(p))
    dates=pd.bdate_range('2024-11-01',periods=100)
    pressure=np.full(100,-.01)
    close=100*(1+pressure)
    market=pd.DataFrame({'Date':dates,'Open':100.,'Close':close,'High':102.,'Low':98.,'Volume':1000.,'Amount':100000.})
    sessions=dates[dates>='2024-12-31']
    full=algorithm.calculate_context_history({'market':market},SimpleNamespace(sessions=sessions))
    assert list(full.target_position.iloc[:8])==[1.,1.,1.,0.,1.,1.,1.,0.]
    changed=market.copy()
    split=sessions[20]
    changed.loc[changed.Date>split,['Close','High','Low']]*=1.7
    a=algorithm.calculate_context_history({'market':changed},SimpleNamespace(sessions=sessions))
    pd.testing.assert_frame_equal(full.loc[:split],a.loc[:split])
    prefix=algorithm.calculate_context_history({'market':market[market.Date<=split]},SimpleNamespace(sessions=sessions[sessions<=split]))
    pd.testing.assert_frame_equal(full.loc[:split],prefix)
    # Pressure recovery exits even before the maximum signal age; same day cannot re-enter.
    recovery=market.copy()
    recovery.loc[recovery.Date==sessions[1],'Close']=101.
    r=algorithm.calculate_context_history({'market':recovery},SimpleNamespace(sessions=sessions))
    assert list(r.target_position.iloc[:3])==[1.,0.,1.]
    risk=mod.RangeGateReversal(ParameterSet({**p,'range_cap':1.5}))
    shock=market.copy()
    shock.loc[shock.Date>=sessions[0],'High']=120.
    shock.loc[shock.Date>=sessions[0],'Low']=80.
    g=risk.calculate_context_history({'market':shock},SimpleNamespace(sessions=sessions))
    assert g.target_position.iloc[0]==0 and set(g.target_position)<= {0.,1.}
    for bad in ({**p,'max_days':0},{**p,'max_days':True},{**p,'entry':float('nan')},{**p,'extra':1}):
        try:
            mod.RangeGateReversal(ParameterSet(bad))
        except (ValueError,RuntimeError):
            pass
        else:
            raise AssertionError('invalid parameter accepted')
    save(EROOT/'others/strategy_checks.json',{'status':'PASS','checks':[
        'maximum signal age and one flat signal before re-entry','early pressure exit',
        'prefix invariance','future input perturbation invariance','binary range-entry filter',
        'invalid parameters rejected'],'scope':'synthetic signal logic, not economic acceptance'})
    print('focused strategy checks PASS')


if __name__=='__main__':
    main()
