"""EX096 driver metadata/mock checks only; no phase/provider/data/account."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch
import numpy as np
import pandas as pd
from strategy_runtime import StrategyCandidate, canonical_sha256

WORK = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('cart_driver_pure', WORK/'native_driver.py')
d = importlib.util.module_from_spec(spec)
sys.modules[spec.name]=d
spec.loader.exec_module(d)


def run():
    forbidden = AssertionError('Real/public evidence data forbidden in pure metadata check')
    with patch.object(d.g.base,'native',side_effect=forbidden), patch.object(d.g,'public',side_effect=forbidden):
        plan=d.definition()
    coords=plan['parameter_geometry']['coordinates']
    assert coords == [('confirmation_lookback',40,120,'INTEGER'),('holding_sessions',1,60,'INTEGER'),('tree_depth',1,4,'INTEGER'),('minimum_leaf',20,120,'INTEGER')]
    assert plan['payload']['parameters']=={'confirmation_lookback':120,'holding_sessions':4,'tree_depth':2,'minimum_leaf':40}
    assert 'ridge_alpha' not in plan['payload']['parameters']
    assert plan['resources']=={'maximum_native_centres':1,'new_accounts':1,'provider_calls':0,'automatic_repeat':False}
    assert plan['candidate_id']=='C9096' and plan['objective_achieved'] is False
    assert plan['parameter_geometry']['protocol']['point_count']==32
    assert plan['parameter_geometry']['protocol']['radius']==.05 and plan['parameter_geometry']['protocol']['seed']==13
    candidate=StrategyCandidate('S013','C9096',plan['payload'],d.PACKAGE)
    assert canonical_sha256(candidate.payload)==canonical_sha256(plan['payload'])
    axis=pd.bdate_range('2021-12-30',periods=10)
    scores=pd.DataFrame({'training_mean':0.,'cart_net':1.},index=axis)
    feature=pd.DataFrame({'confirmation_score':0.},index=axis)
    trace=[{'year':year,'train_n':100,'max_maturity':pd.Timestamp(year-1,12,30).isoformat()} for year in (2021,2022)]
    inputs={'daily':pd.DataFrame({'Date':axis,'Close':10.})}
    history=d.independent_policy(scores,feature,trace,inputs,4)
    assert history.signal_reason.tolist()[:6]==['entry','hold','hold','hold','expiry','entry']
    assert history.target_position.tolist()[:6]==[1.,1.,1.,1.,0.,1.]
    zero=scores.copy()
    zero.cart_net=0.
    assert d.independent_policy(zero,feature,trace,inputs,4).target_position.eq(0).all()
    absent=scores.copy()
    absent.cart_net=np.nan
    assert d.independent_policy(absent,feature,trace,inputs,4).target_position.eq(0).all()
    for field in ('target_position','net_forecast','signal_reason','train_n','positive_forecast','train_max_maturity'):
        bad=history.copy()
        bad[field]=bad[field].astype(object)
        bad.iloc[0,bad.columns.get_loc(field)]=False if field=='positive_forecast' else 'false' if field in ('signal_reason','train_max_maturity') else 999.
        try:
            d.compare_history(bad,history)
        except ValueError:
            pass
        else:
            raise AssertionError('Policy corruption accepted: '+field)
    with patch.object(d.Path,'exists',return_value=True):
        try:
            d.candidate_unoccupied()
        except ValueError:
            pass
        else:
            raise AssertionError('Candidate collision accepted')
    output={'status':'PASS','synthetic_only':True,'real_inputs_read':0,'real_inputs':0,'new_accounts':0,'experiments_allocated':0,
      'checks':['Definition reads source/registry/reference metadata only','Four effective full domains and exact centre','Standard32 fixed metadata','Candidate runtime canonical payload','Independent policy expiry/no reentry/strictpositive/missing/crossyear','Policy corruption and candidate collision refused'],
      'check_count':6,'policy_corruptions_refused':6,'candidate_collision_refused':True,
      'runtime_sha256':plan['payload']['runtime']['source_sha256'],
      'source_sha256':{name:sha256((WORK/name).read_bytes()).hexdigest() for name in ('native_driver.py','driver_checks.py','tree_kernel.py','checks.py','native_checks.py','audit_tree.py','audit_checks.py')},
      'original_parent_sha256':{name:sha256((d.PACKAGE/'strategies'/name).read_bytes()).hexdigest() for name in ('confirm_kernel.py','confirm_net.py')},
      'original14_label_oracle_sha256':sha256(d.ORACLE.read_bytes()).hexdigest(),'coordinates':coords,'candidate_id':'C9096'}
    (WORK/'driver_checks.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print({'status':'PASS','metadata_mock_checks':6,'real_inputs':0})


if __name__=='__main__':
    run()
