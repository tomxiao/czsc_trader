"""Focused checks for disjoint controls, unavailable support and causal selection."""
from concurrent.futures import ProcessPoolExecutor
from datetime import date,timedelta
import multiprocessing as mp
import sys
from study import WORK,stats,context,comparison_task,save,digest


def main():
    before=sys.path.copy()
    context()
    assert sys.path==before
    days=[str(date(2020,1,1)+timedelta(days=i)) for i in range(90)]
    rows=[{'i':i,'n':65,'date':d,'month':d[:7],'stratum':d[:7]+'|10:00',
        'price_net_return':None if i==0 else (i-30)/1000,
        'status':'NO_ENTRY' if i==0 else 'COMPLETE'} for i,d in enumerate(days)]
    signals={'S017-M001':set(range(45)),'S017-M005':{0,15,70},
        'S017-M007':{0,1,15,16,70,71,89},'S017-M008':{0,2,15,20,70}}
    weights=stats.block_weights(len(days),replicates=10)[0]
    args=('S017-M007',rows,signals,days,weights)
    result=comparison_task(args)
    x=result[1]['modes']['nonoverlap']['background_adjusted']
    assert x['design']['target_indices']==[0,70]
    assert x['design']['control_indices']==[1,16,71,89]
    assert x['design']['signal_supported_indices']==[0,70]
    assert x['matched']['supported_indices']==[70]
    assert x['matched']['support']['self_in_control_events']==0
    assert x['matched']['support']['all_target_cell_events']==0
    assert abs(x['matched']['control']['mean']-.05)<1e-12
    missing_args=('S017-M008',rows,signals,days,weights)
    missing=comparison_task(missing_args)
    y=missing[1]['modes']['nonoverlap']['background_adjusted']
    assert y['design']['signal_unmatched_indices']==[70]
    assert y['matched']['unmatched_indices']==[70]
    assert y['matched']['difference']=={'count':0}
    assert y['bootstrap']['intervals']['difference']['undefined_replicates']==10
    assert y['bootstrap']['intervals']['difference']['interval_95'] is None
    # A retained target with no sampled same-cell control is undefined, not zero.
    import numpy as np
    fixed=np.zeros((1,len(days)),dtype=int)
    fixed[0,70]=1
    failed=comparison_task(('S017-M007',rows,signals,days,fixed))
    z=failed[1]['modes']['nonoverlap']['background_adjusted']['bootstrap']
    assert z['unsupported_control_replicates']==1
    assert z['intervals']['difference']['interval_95'] is None
    with ProcessPoolExecutor(max_workers=2,mp_context=mp.get_context('spawn')) as pool:
        assert list(pool.map(comparison_task,[args,missing_args]))==[result,missing]
    sources={p.name:digest(p) for p in (WORK/'src').glob('*.py') if p.stem!='render'}
    assert 'verify.py' in sources
    checks=['import_path_restoration','all_target_mechanism_excluded','nonfill_not_replaced',
        'signal_support_before_outcome_support','zero_support_not_zero_return',
        'resampled_missing_control_undefined','matched_mean_arithmetic','two_spawn_equivalence']
    save(WORK/'others/checks.json',{'status':'PASS','sources':sources,'checks':checks,'workers':2,'native_threads':1})
    print('FOCUSED_CHECKS_PASS',len(checks),flush=True)


if __name__=='__main__':
    main()
