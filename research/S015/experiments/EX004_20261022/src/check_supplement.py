"""Synthetic causal checks for unchanged intent episodes and dynamic allocation."""
import importlib.util
from types import SimpleNamespace
import pandas as pd
from strategy_runtime import ParameterSet
from run_supplement import EROOT, save


def main():
    spec=importlib.util.spec_from_file_location('s015_weight_checks',EROOT/'src/strategy_runtime/strategies/range_weight_reversal.py')
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p={'entry':0.,'exit':.005,'max_days':3,'sizing':'absolute','threshold':.05,'low_weight':.25,'reverse':False}
    dates=pd.bdate_range('2024-11-01',periods=100)
    market=pd.DataFrame({'Date':dates,'Open':100.,'Close':99.,'High':102.,'Low':98.,'Volume':1000.,'Amount':100000.})
    sessions=dates[dates>='2024-12-31']
    market.loc[market.Date>=sessions[1],'High']=110.
    def compute(params,frame=market,selected=sessions):
        return mod.RangeWeightReversal(ParameterSet(params)).calculate_context_history({'market':frame},SimpleNamespace(sessions=selected))
    result=compute(p)
    assert result.target_position.iloc[:4].tolist()==[1.,.25,.25,0.]
    zero=compute({**p,'low_weight':0.})
    assert zero.target_position.iloc[:4].tolist()==[1.,0.,0.,0.]
    assert zero.intent_age.iloc[:8].tolist()==[1,2,3,0,1,2,3,0]
    reverse=compute({**p,'reverse':True})
    assert reverse.target_position.iloc[:4].tolist()==[.25,1.,1.,0.]
    split=sessions[20]
    changed=market.copy()
    changed.loc[changed.Date>split,['Close','High','Low']]*=1.7
    pd.testing.assert_frame_equal(result.loc[:split],compute(p,changed).loc[:split])
    pd.testing.assert_frame_equal(result.loc[:split],compute(p,market[market.Date<=split],sessions[sessions<=split]))
    cycle=compute({**p,'sizing':'cycle','threshold':0.,'low_weight':1.})
    constant=compute({**p,'sizing':'constant','threshold':0.,'low_weight':1.})
    pd.testing.assert_frame_equal(cycle,constant)
    for bad in ({**p,'low_weight':1.1},{**p,'threshold':0.},{**p,'reverse':1},{**p,'max_days':True}):
        try:
            mod.RangeWeightReversal(ParameterSet(bad))
        except (ValueError,RuntimeError):
            pass
        else:
            raise AssertionError('invalid parameters accepted')
    save(EROOT/'others/strategy_checks.json',{'status':'PASS','checks':[
        'dynamic weights while intent age unchanged','zero target does not reset intent',
        'reverse direction','full-weight intent control equivalence',
        'prefix and future perturbation invariance','invalid parameters'],
        'scope':'synthetic signals only; no return acceptance'})
    print('supplement strategy checks PASS')


if __name__=='__main__':
    main()
