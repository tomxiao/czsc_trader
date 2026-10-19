"""Successor EX045 gate-clock audit with exact original public fill-price comparator. No policy replay, prepare or dispatch."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path

import clock_financial_audit_v2 as F
import clock_execution_oracle as O

ROOT=Path.cwd()
OUT=Path(__file__).resolve().parent
BASE=ROOT/'research/S014/experiments/EX045_20261019'
HELPER=ROOT/'research/S014/materials/20261019_exante_hold_exit/accounting/audit_policy_accounts.py'
H=F.P.H
A=H.A
FIXED=[{'clock_profile':x} for x in A.read(OUT.parent/'clock_followup_design.json')['fixed_profiles']]
EVENTS=['entry_guard_blocked','selected_shock_exit','selected_cost_exit','selected_risk_exit',
        'shock_exit_added_vs_positive','cost_exit_added_vs_baseline','risk_exit_added_vs_baseline',
        'cost_support_overlap','cost_grace_override','entry_grace_applied','support_exit_suppressed','gate_slot_consumed']


def origin(index):
    receipt=A.read(ROOT/f'research/S014/experiments/EX043_20261019/others/accounts/run-{index:03d}.json')
    account=A.published(receipt['evidence'])
    A.check('authenticated prior actual result',account['result_hash']==receipt['result_hash'])
    return account,receipt


def clock_origin():
    receipt=A.read(ROOT/'research/S014/experiments/EX044_20261019/others/accounts/run-001.json')
    account=A.published(receipt['evidence'])
    design=A.read(OUT.parent/'clock_followup_design.json')
    A.check('strict correct frozen clock control',receipt['evidence']==design['control_account'] and account['result_hash']==receipt['result_hash']==design['control_result_hash'])
    return account,receipt


def hashes_for(account,control):
    hashes=H.econ_hashes(account,control)
    keys=['date','cash','cash_before','equity','quantity','quantity_before']
    projection=[{k:r[k] for k in keys} for r in account['runs'][0]['ledgers']['account_daily']['data']]
    hashes['funded_wealth_sha256']=H.hash_value(projection)
    return hashes


def identity(record,account,frozen,prior_receipt):
    review=A.read(OUT/'clock_source_pre_review.json')
    A.check('independent source review PASS',review['status']=='PASS')
    source_sha=review['source_sha256']
    runner_review=A.read(OUT/'clock_runner_pre_review.json')
    A.check('independent final runner review PASS',runner_review['status']=='PASS' and runner_review['source_sha256']==source_sha)
    public_gate=A.read(BASE/'others/gate_source_review.json')
    A.check('published final review gate bound current lock',public_gate['status']=='PASS' and public_gate['source_lock_sha256']==sha256((BASE/'protocols/execution_lock.json').read_bytes()).hexdigest())
    A.check('public final review bytes exact independent original',A.public_bytes(public_gate['review_ref'])==(OUT/'clock_runner_pre_review.json').read_bytes())
    lock=A.published(A.read(BASE/'protocols/published_lock.json'))
    row=next(x for x in lock['runs'] if x['index']==record['index'])
    for key in ['mode','parameters','candidate','runtime_sha256','payload_sha256']:
        A.check('locked immutable '+key,record[key]==row[key])
    A.check('fixed two clock profiles',record['parameters']==FIXED[record['index']])
    payload,binding=A.published(record['published_payload_ref']),A.published(record['binding_ref'])
    A.public_bytes(record['published_source_ref'])
    A.check('independently reviewed source exact',record['published_source_ref']['sha256']==source_sha)
    A.check('implementation closure',record['runtime_implementation_sha256']==lock['runtime_implementation_sha256']==payload['runtime']['source_sha256'])
    A.check('payload immutable and exact',record['payload_sha256']==record['published_payload_ref']['sha256'] and payload==binding['payload'])
    A.check('parameters payload exact',record['parameters']==payload['parameters'] and set(payload['parameters'])=={'clock_profile'})
    A.check('candidate binding',binding['candidate']==record['candidate'])
    req=account['request_identity']
    A.check('new experiment identity',req['experiment_id']=='EX045_20261019')
    for key in ['asset_type','benchmark','costs','data_cutoff','execution_mode','frequency_window_days','initial_cash','market_rules','metric_semantics_version','price_basis','pricing','symbol','windows']:
        A.check('unchanged original contract '+key,req[key]==frozen['request_identity'][key])
    A.check('request content identity',req['content_sha256']==record['request_content_sha256'])
    A.check('runtime binding identity',account['runtime_binding_hash']==req['runtime_binding_hash']==record['runtime_binding_hash'])
    A.check('actual candidate',account['runs'][0]['candidate_id']==record['candidate'].split('-')[-1])
    A.check('full causal plan binding',req['input_bindings']==binding['input_bindings'])
    oldbinding=A.published(prior_receipt['binding_ref'])
    for key in ['execution_requests','execution_prepared','execution_identities','execution_fingerprint']:
        A.check('same existing authenticated prepared inputs '+key,binding[key]==oldbinding[key])
    A.check('account data fingerprint',req['data_identity']==binding['execution_fingerprint']==frozen['request_identity']['data_identity'])
    plan,oldplan=req['input_bindings']['full']['plan'],frozen['request_identity']['input_bindings']['full']['plan']
    A.check('same causal plan schema',plan.keys()==oldplan.keys())
    for key in plan:
        if key!='strategy':
            A.check('unchanged original causal clock '+key,plan[key]==oldplan[key])
    A.check('new strategy identity binding',plan['strategy']['reference_id']==record['candidate'] and plan['strategy']['runtime_sha256']==record['runtime_sha256'] and plan['strategy']['release_hash']==account['strategy_identity']==req['strategy_identity'] and account['strategy_identity']!=frozen['strategy_identity'])
    return binding,source_sha,{'payload_sha256':record['payload_sha256'],'runtime_sha256':record['runtime_sha256'],
                              'implementation_sha256':record['runtime_implementation_sha256'],'strategy_identity':account['strategy_identity']}


def lifecycle(account,frozen,parameters):
    profile=parameters['clock_profile']
    params={'entry_guard':'BLOCK_SHOCK','exit_domain':'POSITIVE_P','cost_stop':'BASE'}
    ledgers=account['runs'][0]['ledgers']
    rows=ledgers['decisions']['data']
    daily={A.day(x['date']):x for x in ledgers['account_daily']['data']}
    fills={A.day(x['fill_time']):x for x in ledgers['fills']['data']}
    old={A.day(x['signal_date']):x for x in frozen['runs'][0]['ledgers']['decisions']['data']}
    anchor=account['request_identity']['pricing']['anchor_factor']
    entry=peak=None
    previous=None
    annual=defaultdict(Counter)
    cycles=defaultdict(lambda:defaultdict(set))
    events=[]
    gate_sequence=0
    reservation=-1
    planned_until=-1
    for i,row in enumerate(rows):
        D=A.day(row['signal_date'])
        fill=fills.get(D)
        bought=bool(fill and fill['side']=='BUY')
        sold=bool(fill and fill['side']=='SELL')
        held=bool(D in daily and daily[D]['quantity']>0)
        for key,value in [('held_at_close',held),('buy_filled_today',bought),('sell_filled_today',sold)]:
            A.check('real funded D state '+key,bool(row[key])==value)
        failed=bool(previous and previous['entry_signal'] and not bought)
        A.check('failedBUY only actual preceding BUY intent without real fill',bool(row['failed_buy_reset'])==failed)
        for key in ['ready','support_ok','support_floor','support_break','warmup_sessions',
                    'ma20_prior','ma20_prior_lag5','atr20_prior','ret5_log','sigma20_pre5','z5',
                    'ma_known','atr_known','atr_positive','sigma20_known','sigma20_positive','shock_known']:
            A.check('unchanged market-only feature '+key,row[key]==old[D][key])
        inherited=bool(held and previous and previous['exit_pending'] and not sold)
        expired=bool(held and row['warmup_sessions']>=row['deadline_index'])
        eligible=held and not inherited and not expired
        expected={'pending_inherited':inherited,'deadline_exit':expired,'profit_exit_eligible':eligible,
                  'entry_guard_active':params['entry_guard']=='BLOCK_SHOCK','exit_domain_any':params['exit_domain']=='ANY_P',
                  'cost_stop_active':params['cost_stop']=='NET_LOSS_1ATR'}
        # Independently reconstruct eligibility from actual current inventory and original clock.
        if bought:
            reservation=i+10
            planned_until=-1
        reservation_before_gate=reservation
        candidate=not held and not row['failed_buy_reset'] and bool(row['ready']) and bool(row['support_ok']) and i>=reservation_before_gate
        candidate_shock=bool(candidate and row['shock_known'] and row['z5']>2)
        blocked=candidate_shock and params['entry_guard']=='BLOCK_SHOCK'
        consumed=blocked and profile=='KEEP_PLANNED_SLOT'
        if consumed:
            reservation=i+11
            planned_until=i+11
        A.check('independent post-gate reservation',row['reservation_index']==reservation)
        A.check('independent pre-gate reservation',row['reservation_before_gate']==reservation_before_gate)
        A.check('independent planned slot boundary',row['planned_slot_until']==planned_until)
        expected.update(original_entry_candidate=candidate,candidate_shock=candidate_shock,entry_guard_blocked=blocked,
                        gate_slot_consumed=consumed,clock_keep_planned_slot=profile=='KEEP_PLANNED_SLOT',
                        planned_slot_active=not held and planned_until>=0 and i<planned_until)
        A.check('only eligible unblocked candidate submits BUY',bool(row['entry_signal'])==bool(candidate and not blocked))
        if blocked:
            gate_sequence+=1
            A.check('gate has no phantom inventory/anchor',row['target_position']==0 and not row['failed_buy_reset'] and row['entry_index']==-1 and row['deadline_index']==-1)
            A.check('gate modifies only declared virtual reservation',row['reservation_index']==(i+11 if consumed else reservation_before_gate))
        else:
            gate_sequence=0
        if bought:
            entry=fill['price']*anchor
            peak=None
        if sold:
            entry=peak=None
        if held:
            close=daily[D]['close']*anchor
            peak=close if bought else max(peak,close)
            net=close*.999/(entry*1.001)-1
            loss=entry*1.001-close*.999
            A.number('actual entry cost in runtime HFQ',row['entry_fill_price'],entry,True)
            A.number('actual close-only peak',row['peak_close'],peak,True)
            A.number('fee-adjusted current P',row['net_profit'],net)
            A.number('actual peak net gain price',row['peak_net_gain_price'],peak*.999-entry*1.001,True)
            A.number('actual gross giveback',row['giveback_price'],peak-close,True)
            A.number('actual NET cost-loss price',row['cost_loss_price'],loss,True)
            if row['atr_positive']:
                A.number('rolling priorATR NET loss ratio',row['cost_loss_atr'],loss/row['atr20_prior'])
            else:
                A.check('unknown/nonpositive ATR remains unknown ratio',row['cost_loss_atr'] is None)
            shock=bool(eligible and row['shock_known'] and net>0 and row['z5']>2)
            accel=bool(eligible and row['shock_known'] and row['z5']>2)
            chosen_shock=accel and (params['exit_domain']=='ANY_P' or net>0)
            cost_condition=bool(eligible and row['atr_positive'] and loss>=row['atr20_prior'])
            chosen_cost=params['cost_stop']=='NET_LOSS_1ATR' and cost_condition
            risk=chosen_shock or chosen_cost
            grace=bool(eligible and bought and row['support_break'])
            ordinary=bool(eligible and row['support_break'] and not grace)
            suppressed=bool(eligible and row['support_break'] and grace and not risk)
            expected.update(shock_condition=shock,selected_profit_exit=shock,acceleration_condition=accel,
                            selected_shock_exit=chosen_shock,selected_cost_exit=chosen_cost,selected_risk_exit=risk,
                            cost_stop_condition=cost_condition,shock_exit_added_vs_positive=chosen_shock and not shock,
                            cost_exit_added_vs_baseline=chosen_cost and not (shock or ordinary),
                            risk_exit_added_vs_baseline=risk and not (shock or ordinary),
                            cost_support_overlap=chosen_cost and bool(eligible and row['support_break']),cost_grace_override=chosen_cost and grace,
                            entry_grace_eligible=grace,entry_grace_applied=grace and not risk,
                            support_exit_suppressed=suppressed,support_protection_applied=suppressed,
                            original_support_exit=bool(eligible and row['support_break']),ordinary_support_exit=ordinary,peak_known=True)
            A.check('pending/deadline > risk > grace > support',bool(row['exit_pending'])==bool(inherited or expired or risk or ordinary))
            A.check('entry-only H10 age',row['holding_age']==row['warmup_sessions']-row['entry_index'])
            A.check('never trend protection in fixed grace family',not row['trend_cycle_active'] and not row['trend_cycle_activated'])
            if bought:
                A.check('entryD Close-only giveback zero',row['giveback_price']==0)
        else:
            A.check('flat clears actual cost/peak/loss',all(row[x] is None for x in ['entry_fill_price','peak_close','net_profit','cost_loss_price','cost_loss_atr']) and not row['peak_known'])
        for key,value in expected.items():
            A.check('independent decision rule '+key,bool(row[key])==bool(value))
        if '2020-01-01'<=D<='2025-12-31':
            y=D[:4]
            annual[y]['D_rows']+=1
            annual[y]['actual_held_D']+=held
            for key in ['original_entry_candidate','candidate_shock','acceleration_condition','cost_stop_condition',*EVENTS]:
                annual[y][key]+=int(bool(row[key]))
                if held and row[key]:
                    cycles[y][key].add(row['entry_index'])
            if held:
                cycles[y]['actual_cycles'].add(row['entry_index'])
            if any(row[x] for x in EVENTS):
                events.append({'D':D,'E':A.day(row['valid_session']),'entry_index':row['entry_index'],
                               'holding_age':row['holding_age'],'z5':row['z5'],'net_profit':row['net_profit'],
                               'cost_loss_atr':row['cost_loss_atr'],'gate_consecutive_candidate_D':gate_sequence,
                               'reservation_before_gate':reservation_before_gate,'reservation_after_gate':reservation,
                               'planned_slot_until':planned_until,
                               **{key:row[key] for key in EVENTS}})
        previous=row
    return {'annual_D_counts':dict(annual),'annual_distinct_held_cycles':{y:{k:len(v) for k,v in x.items()} for y,x in cycles.items()},
            'events':events,'actual_vs_runtime_D_alignment':'EXACT_ALL1642_D','zero_shadow_affordability_assumptions':True}


def prefix(account,frozen):
    old,new=frozen['runs'][0]['ledgers'],account['runs'][0]['ledgers']
    differences=[A.day(y['signal_date']) for x,y in zip(old['decisions']['data'],new['decisions']['data'],strict=True)
                 if any(y[k]!=v for k,v in x.items() if k not in A.ID_KEYS)]
    target_differences=[A.day(y['signal_date']) for x,y in zip(old['decisions']['data'],new['decisions']['data'],strict=True) if x['target_position']!=y['target_position']]
    if not differences:
        A.noop_equivalence(frozen,account)
        return {'first_clock_state_divergence_D':None,'first_target_divergence_D':None,'old_observation_state_equals_control':True}
    D=differences[0]
    before=max(A.day(x['signal_date']) for x in new['decisions']['data'] if A.day(x['signal_date'])<D)
    for name,key,cut in [('decisions','signal_date',before),('orders','signal_date',before),('account_daily','date',D),('fills','fill_time',D)]:
        A.economic_rows(old[name]['data'],new[name]['data'],'exact original funded prefix '+name,cut,key)
    return {'first_clock_state_divergence_D':D,'first_target_divergence_D':target_differences[0] if target_differences else None,
            'old_observation_state_equals_control':False,'unchanged_funded_prefix_includes_first_clock_change_D':True,
            'metadata_difference_is_not_economic_difference':True}


def audit_one(index):
    destination=OUT/f'clock_account_{index:03d}_independent_review_v2.json'
    A.check('refuse overwrite review',not destination.exists())
    record=A.read(BASE/f'others/accounts/run-{index:03d}.json')
    A.check('actual successful account',record['status']=='SUCCEEDED')
    A.check('executor technical audit passed',bool(record['audit']) and record['audit']['status']=='PASS')
    account=A.published(record['evidence'])
    A.check('actual result hash',account['result_hash']==record['result_hash'])
    A.check('one full account',len(account['runs'])==1 and account['execution_mode']=='FULL')
    frozen,prior_receipt=clock_origin()
    prior_frozen,_=origin(4)
    original,_=origin(0)
    binding,source_sha,immutable=identity(record,account,frozen,prior_receipt)
    A.equal_baseline(frozen,account)
    frames=H.fetch_execution(binding,account['request_identity']['pricing'])
    approved_prices,boundaries=O.exact_execution_prices(account,frames)
    accounting=F.audit_daily(account,record['parameters']['clock_profile']=='KEEP_PLANNED_SLOT',approved_prices)
    if index==0:
        A.noop_equivalence(frozen,account)
    else:
        gate=A.read(OUT/'clock_account_000_independent_review.json')
        A.check('fresh current-source control passed',gate['status']=='PASS' and gate['source_sha256']==source_sha)
    prefix_result=prefix(account,frozen) if index else {'first_clock_state_divergence_D':None,'first_target_divergence_D':None,'old_observation_state_equals_control':True}
    state=lifecycle(account,frozen,record['parameters'])
    H.execution_constraints(account,frames)
    annual,summary=H.annual_and_summary(account,original)
    frozen_year=A.yearly(prior_frozen['runs'][0]['ledgers']['account_daily']['data'])
    clock_year=A.yearly(frozen['runs'][0]['ledgers']['account_daily']['data'])
    for row in annual:
        row['return_difference_vs_frozen']=row['return']-frozen_year[row['year']]['return']
        row['return_difference_vs_clock_control']=row['return']-clock_year[row['year']]['return']
    hashes=hashes_for(account,frozen)
    control_hashes=hashes_for(frozen,frozen)
    result={'status':'PASS','index':index,'policy_id':record['mode'],'parameters':record['parameters'],'candidate':record['candidate'],
            'account_ref':record['evidence'],'result_hash':record['result_hash'],'source_sha256':source_sha,
            'baseline_ref':prior_receipt['evidence'],'immutable_identity':immutable,'accounting':accounting,
            'lifecycle':state,'prefix':prefix_result,'original_annual_goal_audit':annual,'summary':summary,
            'terminal2025_asof':A.terminal_state(account),'economic_path_hashes':hashes,
            'economic_path_equals_clock_control':hashes['execution_economics_sha256']==control_hashes['execution_economics_sha256'],
            'funded_wealth_path_equals_clock_control':hashes['funded_wealth_sha256']==control_hashes['funded_wealth_sha256'],
            'funded_wealth_hash_fields':['date','cash','cash_before','equity','quantity','quantity_before'],
            'source_NOOP_exact_EX044001':index==0,'checks':sum(A.COUNTS.values()),'check_counts':dict(A.COUNTS),
            'maximum_arithmetic_error':A.ERRORS,'derived_currency_absolute_tolerance':A.MONEY_TOLERANCE,
            'derived_ratio_absolute_tolerance':A.RATIO_TOLERANCE,'NOOP_economic_projection_tolerance':0,
            'automatic_tolerance_expansion':False,'audit_implementation_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
            'frozen_execution_helper_sha256':sha256(HELPER.read_bytes()).hexdigest(),
            'ledger_helper_sha256':sha256(H.HELPER.read_bytes()).hexdigest(),
            'clock_financial_helper_sha256':sha256((OUT/'clock_financial_audit_v2.py').read_bytes()).hexdigest(),
            'exact_public_fill_oracle':{'all_actual_prices_equal_original_resolver_return':len(approved_prices),'float_price_above_saved_limit_boundaries':boundaries,'added_epsilon':0,'source_sha256':sha256((OUT/'clock_execution_oracle.py').read_bytes()).hexdigest()},
            'audit_successor':{'predecessor_failure_sha256':sha256((OUT/'clock_account_001_independent_failure.json').read_bytes()).hexdigest(),'predecessor_helper_sha256':sha256((OUT/'clock_financial_audit.py').read_bytes()).hexdigest(),'boundary_investigation_sha256':sha256((OUT/'clock_limit_boundary_investigation.json').read_bytes()).hexdigest(),'account_reruns':0,'reason':'Replace overstrong float<=limit with exact original public resolver return, no new epsilon.'},
            'source_lock_sha256':sha256((BASE/'protocols/execution_lock.json').read_bytes()).hexdigest(),
            'new_fits':0,'new_strategy_replays':0,'new_dispatches_by_auditor':0,'new_supplier_calls':0,'new_preparations':0,
            'limits':['Seen2020-25 development;2026 technical audit only.','Prepared fetch reads only existing authenticated assets; no market data export.',
                      'Two clock profiles are an adaptive shared-history contrast, not independent statistical samples.','Cost mark signal is not a guaranteed executable price/loss cap.']}
    H.write(destination,result)
    print(json.dumps({'index':index,'status':'PASS','checks':result['checks'],'review_sha256':sha256(destination.read_bytes()).hexdigest()}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index',required=True,type=int,choices=(1,))
    args=parser.parse_args()
    try:
        audit_one(args.index)
    except Exception as exc:
        failure=OUT/f'clock_account_{args.index:03d}_independent_failure_v2.json'
        if not failure.exists():
            H.write(failure,{'status':'FAIL','index':args.index,'exception':repr(exc),'check_counts':dict(A.COUNTS),
                             'no_tolerance_expansion':True,'audit_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest()})
        raise


if __name__=='__main__':
    main()
