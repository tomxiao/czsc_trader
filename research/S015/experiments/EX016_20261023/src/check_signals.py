"""Focused mechanism, prefix and future-invariance checks on synthetic inputs."""
import importlib.util
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from suite import HOME,save


def main():
    path=Path(__file__).parent/'strategy_runtime/strategies/pressure_path.py'
    spec=importlib.util.spec_from_file_location('checked_pressure_path',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dates=pd.bdate_range('2024-09-09',periods=150)
    close=100*np.exp(np.cumsum(np.sin(np.arange(150))*.01))
    pressure=np.sin(np.arange(150)*.7)*.01
    market=pd.DataFrame({'Date':dates,'Open':close,'Close':close,'High':close*1.02,'Low':close*.98,
        'Volume':1000.,'Amount':1000.*close/(1+pressure)})
    sessions=dates[dates>='2024-12-31']
    tested=[]
    for mode,extra in module.EXTRAS.items():
        p={'mode':mode,'entry':0.,'exit':.005,'hold':3}
        p.update({k:20 if k=='lookback' else 2 if k=='extension' else .02 if k=='risk_budget' else .5 for k in extra})
        algo=module.PressurePath(ParameterSet(p))
        full=algo.calculate_context_history({'market':market},SimpleNamespace(sessions=sessions))
        assert full.target_position.between(0,1).all()
        cut=sessions[25]
        prefix=algo.calculate_context_history({'market':market[market.Date<=cut]},SimpleNamespace(sessions=sessions[sessions<=cut]))
        pd.testing.assert_frame_equal(full.loc[:cut],prefix)
        future=market.copy()
        future.loc[future.Date>cut,['Close','High','Low']]*=1.7
        changed=algo.calculate_context_history({'market':future},SimpleNamespace(sessions=sessions))
        pd.testing.assert_frame_equal(full.loc[:cut],changed.loc[:cut])
        tested.append(mode)
    controlled=market.copy()
    controlled['Close']=100.
    controlled['High']=102.
    controlled['Low']=98.
    controlled['Amount']=100000/(1-.01)
    staged=module.PressurePath(ParameterSet({'mode':'staged','entry':0.,'exit':.005,'hold':3,'probe':.5}))
    second=sessions[1]
    controlled.loc[controlled.Date==second,'Amount']=100000/(1-.005)
    out=staged.calculate_context_history({'market':controlled},SimpleNamespace(sessions=sessions))
    assert list(out.target_position.iloc[:4])==[.5,1.,1.,0.]
    for bad in ({'mode':'base','entry':0.,'exit':.005,'hold':True},
                {'mode':'base','entry':float('nan'),'exit':.005,'hold':3},
                {'mode':'base','entry':0.,'exit':.005,'hold':3,'extra':1}):
        try:
            module.PressurePath(ParameterSet(bad))
        except (ValueError,RuntimeError):
            pass
        else:
            raise AssertionError('invalid parameter accepted')
    save(HOME/'others/signal_checks.json',{'status':'PASS','modes':tested,
        'checks':['prefix invariance','future perturbation invariance','target bounds','staged commitment and forced flat','invalid parameters'],
        'scope':'synthetic signal semantics only, not economic acceptance'})
    print('SIGNAL_CHECKS_PASS',flush=True)


if __name__=='__main__':
    main()
