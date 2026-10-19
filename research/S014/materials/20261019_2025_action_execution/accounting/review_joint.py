"""Independent fixed-joint source/method toy review, no actual branch outcomes."""
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
from strategy_runtime import ObservedSeries, ParameterSet

from review_early_cycle import load, check, CHECKS

ROOT=Path.cwd()
BASE=ROOT/'research/S014/materials/20261019_2025_action_execution/joint_method'

def main():
    planpath=BASE/'method_plan.json'
    plan=json.loads(planpath.read_bytes())
    paths={}
    for key in ['source','precheck','synthetic_receipt','predecessor_H10_source','original_EX023_source','conditional_joint_design','original_cycle_method']:
        value=plan['bindings'][key]
        path=ROOT/value['path']
        check('bound SHA '+key,sha256(path.read_bytes()).hexdigest()==value['sha256'])
        paths[key]=path
    receipt=json.loads(paths['synthetic_receipt'].read_bytes())
    check('upstream actual numeric boundary and pure toy scope',receipt['checks_count']==73 and receipt['actual_SRT_observation_materializations']==264 and receipt['new_account_dispatches']==0 and not receipt['real_market_inputs_read'])
    old=load('J_A_original',paths['original_EX023_source'])
    predecessor=load('J_A_predecessor',paths['predecessor_H10_source'])
    new=load('J_A_new',paths['source'])
    # Reuse only the predecessor's pure toy dates; modify prices independently below.
    fixture=load('J_A_fixture',ROOT/'research/S014/materials/20261019_2025_action_execution/early_cycle_method/precheck.py').fixture
    args=fixture()
    for i,frame in enumerate(args):
        extra=pd.concat([frame.iloc[[-1]].copy()]*6,ignore_index=True)
        extra['Date']=pd.to_datetime(['2025-07-01','2025-07-02','2025-07-03','2025-07-04','2025-07-07','2025-07-08'])
        args[i]=pd.concat([frame,extra],ignore_index=True)
    for frame in args[:2]:
        frame.loc[frame.Date.eq(pd.Timestamp('2025-06-16')),['Close','Low']]=[8.,7.9]
        frame.loc[frame.Date.eq(pd.Timestamp('2025-06-17')),['Close','Low']]=[7.,6.9]
    def config(mode):
        return new.JointConfig.parse(dict(mode=mode,entry_execution_date='2025-05-30',force_decision_date='2025-06-19'))
    tables={mode:new.history(*args,config(mode)) for mode in ['NOOP','HOLD_ORIGINAL_CYCLE_H10','JOINT']}
    baseline=old.history(*args,'support_exit_reserve_H10')
    prior=predecessor.history(*args,predecessor.EarlyCycleConfig.parse(dict(mode='HOLD_ORIGINAL_CYCLE_H10',entry_execution_date='2025-05-30')))
    pd.testing.assert_frame_equal(tables['NOOP'][baseline.columns],baseline,check_exact=True)
    check('new source NOOP every old column exact on toy',True)
    pd.testing.assert_frame_equal(tables['HOLD_ORIGINAL_CYCLE_H10'][prior.columns],prior,check_exact=True)
    check('new retained H10 every predecessor column exact',True)
    D=pd.Timestamp('2025-06-19')
    pd.testing.assert_frame_equal(tables['JOINT'].loc[:'2025-06-18',prior.columns],prior.loc[:'2025-06-18'],check_exact=True)
    check('joint before June19 every H10 predecessor column exact',True)
    held,joint=tables['HOLD_ORIGINAL_CYCLE_H10'].loc[D],tables['JOINT'].loc[D]
    check('fixed node real same-day bought original HOLD',held.buy_filled_today and held.held_at_close and held.target_position==1 and not held.exit_pending)
    for key in prior.columns:
        if key not in ['target_position','exit_pending']:
            check('June19 old state unchanged '+key,joint[key]==held[key])
    check('one fixed joint next-session SELL intent',joint.joint_trigger_today and joint.joint_done and joint.exit_pending and joint.target_position==0 and tables['JOINT'].joint_trigger_today.sum()==1)
    check('actual June20 sale',tables['JOINT'].loc['2025-06-20','joint_actual_sale_today']==1 and tables['JOINT'].loc['2025-06-20','joint_target_cycle_completed']==1)
    for key in ['entry_index','deadline_index','reservation_index']:
        check('actual June original anchor retained '+key,joint[key]==held[key])
    blocked=[frame.copy(deep=True) for frame in args]
    dates=pd.to_datetime(blocked[3].Date)
    blocked[3].loc[dates.between(pd.Timestamp('2025-06-20'),pd.Timestamp('2025-07-03')),'Status']='SUSPENDED'
    prolonged=new.history(*blocked,config('JOINT'))
    check('pending survives deadline and expired reservation',prolonged.loc['2025-07-03','exit_pending']==1 and prolonged.loc['2025-07-03','joint_sale_blocked']==1 and prolonged.loc['2025-07-03','held_at_close']==1)
    check('first legal sale after prolonged block',prolonged.loc['2025-07-04','joint_actual_sale_today']==1 and prolonged.loc['2025-07-04','joint_target_cycle_completed']==1)
    for label,change in [('missing_current_BUY','suspend'),('older_held_inventory','older')]:
        altered=[frame.copy(deep=True) for frame in args]
        if change=='suspend':
            altered[3].loc[altered[3].Date.eq(D),'Status']='SUSPENDED'
        else:
            for frame in altered[:2]:
                frame.loc[frame.Date.isin(pd.to_datetime(['2025-06-16','2025-06-17'])),['Close','Low']]=[10.,9.8]
        try:
            new.history(*altered,config('JOINT'))
        except new.UnsupportedJointNodeError:
            check('unsupported fixed node '+label,True)
        else:
            raise AssertionError('must reject unavailable fixed node '+label)
    accepted=0
    for mode in ['NOOP','JOINT']:
        impl=new.JointActionStrategy(ParameterSet(dict(mode=mode,entry_execution_date='2025-05-30',force_decision_date='2025-06-19')))
        original=old.RepairStrategy(ParameterSet({'variant':'support_exit_reserve_H10'}))
        for key in ['tradable_symbol','inputs','decision','execution','monitoring','capabilities']:
            check('original economic definition '+mode+' '+key,getattr(impl.definition,key)==getattr(original.definition,key))
        out=impl.calculate_history(dict(zip(['market','raw','limits','status'],args)),list(pd.to_datetime(args[0].Date)))
        for row in out.to_dict('records'):
            for field in impl.definition.observation.series:
                ObservedSeries(field.key,field.label,row[field.value_field],())
                accepted+=1
    result=dict(status='PASS_METHOD_AND_INDEPENDENT_SYNTHETIC_ONLY',checks=len(CHECKS),check_names=CHECKS,
                actual_numeric_values=accepted,source_sha256=sha256(paths['source'].read_bytes()).hexdigest(),
                plan_sha256=sha256(planpath.read_bytes()).hexdigest(),bindings=plan['bindings'],
                independent_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                actual_new_accounts=0,actual_new_branch_histories=0,market_API_calls=0,fits=0,
                mandatory_actual_gates=['Fresh source NOOP exact original R economics and one-to-one IDs.',
                'Joint economic prefix through DJune19 and decisions before it exact H10-only full-history account.',
                'June19 current real inventory/price/fee/cash equal H10; only next-session SELL intent changes, reservation/pending retained.',
                'Fixed2025 T wealth and original annual goal audit, actual accounting interaction; no additive prediction.',
                'Preserve FAILED/UNKNOWN and stop on technical failure; no date or parameter replacement.'])
    out=Path(__file__).with_name('joint_independent_method_review.json')
    with out.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    print(json.dumps({'status':result['status'],'checks':len(CHECKS),'numeric_values':accepted,'review_sha256':sha256(out.read_bytes()).hexdigest()}))

if __name__=='__main__':
    main()
