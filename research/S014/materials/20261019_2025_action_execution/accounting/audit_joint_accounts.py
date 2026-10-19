"""EX042 independent fixed joint diagnostic audit. Never dispatches accounts."""
import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path

import audit_accounts as A
import audit_early_cycle_accounts as E

ROOT=Path.cwd()
BASE=ROOT/'research/S014/experiments/EX042_20261019'
D='2025-06-19'
T='2025-12-31'

def account_from(ex,index):
    row=A.read(ROOT/f'research/S014/experiments/{ex}/others/accounts/run-{index:03d}.json')
    A.check('referenced original arm SUCCEEDED',row['status']=='SUCCEEDED')
    result=A.published(row['evidence'])
    A.check('referenced original arm receipt hash',result['result_hash']==row['result_hash'])
    return result,row

def identity(record,account,original):
    lock=A.published(A.read(BASE/'protocols/published_lock.json'))
    row=next(r for r in lock['runs'] if r['index']==record['index'])
    for key in ['mode','parameters','candidate','runtime_sha256','payload_sha256']:
        A.check('EX042 locked '+key,record[key]==row[key])
    payload,binding=A.published(record['published_payload_ref']),A.published(record['binding_ref'])
    A.public_bytes(record['published_source_ref'])
    A.check('source SHA in lock',record['published_source_ref']['sha256']==lock['source_hashes']['src/strategy_runtime/strategies/joint_action_review.py'])
    approved=A.read(ROOT/'research/S014/materials/20261019_2025_action_execution/accounting/joint_independent_method_review.json')
    A.check('source independently reviewed',record['published_source_ref']['sha256']==approved['source_sha256'])
    A.check('locked implementation closure',record['runtime_implementation_sha256']==lock['runtime_implementation_sha256']==payload['runtime']['source_sha256'])
    A.check('immutable payload',record['payload_sha256']==record['published_payload_ref']['sha256'])
    A.check('fixed JOINT domain',payload['parameters']==record['parameters']=={'mode':record['mode'],'entry_execution_date':'2025-05-30','force_decision_date':D})
    A.check('binding payload and candidate',binding['payload']==payload and binding['candidate']==record['candidate'])
    req=account['request_identity']
    A.check('new EX042 experiment',req['experiment_id']=='EX042_20261019')
    for key in ['asset_type','benchmark','costs','data_cutoff','execution_mode','frequency_window_days','initial_cash','market_rules','metric_semantics_version','price_basis','pricing','symbol','windows']:
        A.check('same original contract '+key,req[key]==original['request_identity'][key])
    A.check('request content exact',req['content_sha256']==record['request_content_sha256'])
    A.check('runtime binding exact',account['runtime_binding_hash']==req['runtime_binding_hash']==record['runtime_binding_hash'])
    A.check('candidate result exact',account['runs'][0]['candidate_id']==record['candidate'].split('-')[-1])
    A.check('input preparation binding exact',req['input_bindings']==binding['input_bindings'])
    old=A.read(ROOT/'research/S014/materials/20261019_2025_action_method_review/method/source_bindings.json')
    for key in ['execution_requests','execution_identities','execution_prepared','execution_fingerprint']:
        A.check('original authenticated data '+key,binding[key]==old['original_'+key])
    A.check('original execution data identity',req['data_identity']==binding['execution_fingerprint']==original['request_identity']['data_identity'])
    plan,oldplan=req['input_bindings']['full']['plan'],original['request_identity']['input_bindings']['full']['plan']
    A.check('input plan schema exact',plan.keys()==oldplan.keys())
    for key in plan:
        if key!='strategy':
            A.check('original input causal clock '+key,plan[key]==oldplan[key])
    A.check('new runtime and candidate bound',plan['strategy']['runtime_sha256']==record['runtime_sha256'] and plan['strategy']['reference_id']==record['candidate'])
    A.check('new immutable strategy identity',plan['strategy']['release_hash']==account['strategy_identity']==req['strategy_identity'] and account['strategy_identity']!=original['strategy_identity'])
    return {k:record[k] for k in ['parameters','candidate','payload_sha256','runtime_implementation_sha256','runtime_sha256','published_source_ref','binding_ref']}

def lifecycle(original,hold,account,mode):
    run=account['runs'][0]
    ledgers=run['ledgers']
    decisions=ledgers['decisions']['data']
    if mode=='NOOP':
        A.noop_equivalence(original,account)
    else:
        h=hold['runs'][0]
        for name,key in [('account_daily','date'),('fills','fill_time'),('orders','execution_date')]:
            A.economic_rows(h['ledgers'][name]['data'],ledgers[name]['data'],'JOINT exact H10 economic prefix through June19',D,key)
        before='2025-06-18'
        A.economic_rows(h['ledgers']['decisions']['data'],decisions,'JOINT exact H10 prior decisions',before,'signal_date')
        A.economic_rows(h['signals']['data'],run['signals']['data'],'JOINT exact H10 prior source signals',before,'signal_date')
        old=next(r for r in h['ledgers']['decisions']['data'] if A.day(r['signal_date'])==D)
        new=next(r for r in decisions if A.day(r['signal_date'])==D)
        A.check('actual H10 June19 same-day held BUY original HOLD eligible',old['buy_filled_today'] and old['held_at_close'] and not old['exit_pending'] and not old['entry_signal'] and old['target_position']==1)
        for key,val in old.items():
            if key not in A.ID_KEYS|{'action','target_position','exit_pending'}:
                A.check('same H10 June19 state '+key,new[key]==val)
        A.check('only new next-session SELL intent',new['exit_pending'] and new['target_position']==0 and new['action']=='SELL')
    by_fill={A.day(f['fill_time']):f for f in ledgers['fills']['data']}
    targeted=False
    may_completed=False
    may_entry=may_deadline=may_reservation=-1
    force_done=force_completed=False
    force_entry=force_deadline=force_reservation=-1
    pending=False
    previous=None
    suppressed,triggered,blocked,actual_sales=[],[],[],[]
    joint=mode=='JOINT'
    for i,dec in enumerate(decisions):
        day=A.day(dec['signal_date'])
        fill=by_fill.get(day)
        if fill and fill['side']=='BUY' and day=='2025-05-30':
            targeted=True
            may_entry,may_deadline,may_reservation=i,i+9,i+10
        sale_today=bool(fill and fill['side']=='SELL')
        if sale_today:
            if targeted and not may_completed:
                may_completed=True
            if force_done and not force_completed:
                force_completed=True
                actual_sales.append(fill)
            pending=False
        protected=joint and targeted and not may_completed and bool(dec['held_at_close'])
        suppressed_expected=protected and dec['support_break'] and i<dec['deadline_index'] and not pending
        force_today=joint and day==D
        if force_today:
            force_done=True
            force_entry,force_deadline,force_reservation=i,i+9,i+10
        expected_pending=bool(dec['held_at_close']) and (pending or force_today or i>=dec['deadline_index'] or (dec['support_break'] and not protected))
        A.check('joint original support/deadline/forced pending intent',bool(dec['exit_pending'])==bool(expected_pending))
        A.check('May30 exception diagnostic mode/state',bool(dec['cycle_mode_active'])==joint and bool(dec['target_entry_seen'])==targeted and bool(dec['target_cycle_completed'])==may_completed)
        A.check('May30 protected/suppressed exact',bool(dec['protected_cycle_active'])==protected and bool(dec['support_exit_suppressed'])==bool(suppressed_expected))
        A.check('May30 absolute original clocks',dec['fixed_cycle_entry_index']==may_entry and dec['fixed_cycle_deadline_index']==may_deadline and dec['fixed_cycle_reservation_index']==may_reservation)
        A.check('May30 deadline has priority',bool(dec['deadline_exit_pending'])==bool(protected and i>=dec['deadline_index'] and expected_pending))
        A.check('joint fixed mode and causal done',bool(dec['joint_mode_active'])==joint and bool(dec['joint_trigger_today'])==force_today and bool(dec['joint_done'])==force_done)
        eligible=bool(day==D and may_completed and fill and fill['side']=='BUY' and dec['held_at_close'] and dec['entry_index']==i and dec['entry_index']!=may_entry and not dec['entry_signal'])
        A.check('actual fixed-node eligibility diagnostic',bool(dec['joint_node_eligible'])==eligible)
        A.check('fixed actual June inventory anchors',dec['joint_target_cycle_entry_index']==force_entry and dec['joint_target_deadline_index']==force_deadline and dec['joint_target_reservation_index']==force_reservation)
        was_forced=bool(joint and previous and previous['joint_done'] and not previous['joint_target_cycle_completed'] and previous['held_at_close'] and previous['entry_index']==force_entry and previous['exit_pending'])
        A.check('joint blocked sale remains pending',bool(dec['joint_sale_blocked'])==bool(was_forced and not sale_today))
        A.check('actual joint sale and completed diagnostics',bool(dec['joint_actual_sale_today'])==bool(was_forced and sale_today) and bool(dec['joint_target_cycle_completed'])==force_completed)
        if dec['support_exit_suppressed']:
            suppressed.append(day)
        if dec['joint_trigger_today']:
            triggered.append(day)
            A.check('joint forced node current real fill anchors held',dec['buy_filled_today'] and dec['held_at_close'] and dec['entry_index']==force_entry and dec['deadline_index']==force_deadline and dec['reservation_index']==force_reservation)
        if dec['joint_sale_blocked']:
            blocked.append(day)
        pending=bool(expected_pending)
        previous=dec
    A.check('one joint trigger or no NOOP trigger',triggered==([D] if joint else []))
    if joint:
        A.check('joint original-inventory sale actually completed',len(actual_sales)==1 and force_completed)
    for old,new in zip(original['runs'][0]['ledgers']['decisions']['data'],decisions,strict=True):
        for key in ['ready','support_ok','warmup_sessions','support_floor','support_break']:
            A.check('original truthful raw support '+key,old[key]==new[key])
    return {'May30_suppressed_D':suppressed,'joint_trigger_D':triggered,'joint_blocked_D':blocked,'actual_joint_inventory_sales':actual_sales,
            'May30_clocks':[may_entry,may_deadline,may_reservation],'June19_clocks':[force_entry,force_deadline,force_reservation]}

def june_disposition(account):
    run=account['runs'][0]
    days={A.day(r['date']):r for r in run['ledgers']['account_daily']['data']}
    initial,end=days[D],days[T]
    entry=next(f for f in run['ledgers']['fills']['data'] if A.day(f['fill_time'])==D and f['side']=='BUY')
    A.check('June19 actual original inventory matches D',entry['quantity']==initial['quantity'])
    sales=[f for f in run['ledgers']['fills']['data'] if f['side']=='SELL' and f['cycle_id']==entry['cycle_id'] and D<A.day(f['fill_time'])<=T]
    A.check('June19 first full sale unique',len(sales)==1)
    sale=sales[0]
    base=days[A.day(sale['fill_time'])]['cash']
    A.check('June19 full original inventory actual sale',sale['quantity']==initial['quantity'] and days[A.day(sale['fill_time'])]['quantity']==0)
    A.number('June19 actual sale cash',base,initial['cash']+sale['price']*sale['quantity']-sale['fees'],True)
    return {'D_inventory':initial['quantity'],'D_cash':initial['cash'],'actual_sale':sale,'disposition_base':base,'later_participation':end['equity']-base,'terminal_wealth':end['equity']}

def main(indexpath,out,csvpath):
    origin=A.read(ROOT/'research/S014/experiments/EX023_20261018/others/account_results.json')['records'][0]
    original=A.published(origin['evidence'])
    hold,holdref=account_from('EX041_20261019',1)
    force,forceref=account_from('EX040_20261019',5)
    index=A.read(indexpath)
    result={'original_account_ref':origin['evidence'],'H10_only_ref':holdref['evidence'],'June19_exit_only_ref':forceref['evidence'],
            'resources':{'EX042_total_dispatched_including_FAILED_UNKNOWN':len(index['records']),'status_counts':dict(Counter(r['status'] for r in index['records'])),
                         'failed_unknown_preserved':[r for r in index['records'] if r['status']!='SUCCEEDED']},
            'audited_accounts':[],'new_account_dispatches_by_auditor':0,'new_fits':0,'new_market_API_calls':0}
    completed={}
    for row in index['records']:
        if row['status']!='SUCCEEDED':
            continue
        mode=row['mode']
        A.check('fixed JOINT/NOOP unique',mode in ['NOOP','JOINT'] and mode not in completed)
        account=A.published(row['evidence'])
        A.check('actual JOINT receipt result',account['result_hash']==row['result_hash'])
        A.check('one FULL original window',len(account['runs'])==1 and account['execution_mode']=='FULL')
        A.IDENTITY_MAPS.clear()
        binding=identity(row,account,original)
        A.equal_baseline(original,account)
        accounting=A.audit_daily(account)
        if mode=='JOINT':
            A.check('fresh source NOOP independently precedes JOINT','NOOP' in completed)
        phases=lifecycle(original,hold,account,mode)
        run=account['runs'][0]
        years,bh=A.yearly(run['ledgers']['account_daily']['data']),A.yearly(run['buyhold']['account_daily']['data'])
        annual=[]
        for y,r in years.items():
            target=1.5*bh[y]['return'] if bh[y]['return']>0 else 0.
            annual.append({'year':y,**r,'buyhold_return':bh[y]['return'],'buyhold_drawdown':bh[y]['max_drawdown'],'required_return':target,
                           'return_pass':r['return']>=target if bh[y]['return']>0 else r['return']>0,'drawdown_pass':r['max_drawdown']<bh[y]['max_drawdown'],
                           '2026_role':'TECHNICAL_ONLY' if y==2026 else 'ORIGINAL_GOAL_AUDIT'})
        closed=sum(t['status']=='CLOSED' for t in run['ledgers']['trades']['data'])
        result['audited_accounts'].append({'mode':mode,'evidence':row['evidence'],'result_hash':row['result_hash'],'identity':binding,'accounting':accounting,
                                         'lifecycle':phases,'original_annual_goals':annual,'frequency_per_60':60*closed/1642,'frequency_pass':60*closed/1642>=3,
                                         'terminal_2025_asof_state':A.terminal_state(account)})
        completed[mode]=account
    maps={'ORIGINAL_R':{A.day(r['date']):r for r in original['runs'][0]['ledgers']['account_daily']['data']}}
    maps.update({mode:{A.day(r['date']):r for r in acc['runs'][0]['ledgers']['account_daily']['data']} for mode,acc in completed.items()})
    opening=maps['ORIGINAL_R']['2024-12-31']['equity']
    if 'JOINT' in completed:
        def wealth(acc):
            return next(r['equity'] for r in acc['runs'][0]['ledgers']['account_daily']['data'] if A.day(r['date'])==T)
        R,H,F,J=wealth(original),wealth(hold),wealth(force),wealth(completed['JOINT'])
        interaction=J-H-F+R
        A.number('terminal descriptive interaction identity',J-R,(H-R)+(F-R)+interaction,True)
        original_may, joint_may=E.disposition(original),E.disposition(completed['JOINT'])
        may_delta=joint_may['base_terminal_currency']-original_may['base_terminal_currency']
        later_delta=joint_may['post_disposition_participation_currency']-original_may['post_disposition_participation_currency']
        A.number('joint May30 inventory disposition plus subsequent participation',J-R,may_delta+later_delta,True)
        hold_june,joint_june=june_disposition(hold),june_disposition(completed['JOINT'])
        A.check('same H10 June19 actual existing inventory and residual cash',hold_june['D_inventory']==joint_june['D_inventory'] and hold_june['D_cash']==joint_june['D_cash'])
        conditional_base=joint_june['disposition_base']-hold_june['disposition_base']
        conditional_later=joint_june['later_participation']-hold_june['later_participation']
        A.number('conditional June19 disposition plus later participation',J-H,conditional_base+conditional_later,True)
        result['fixed2025_effects']={'T':T,'original_2025_opening':opening,'wealth_R':R,'wealth_H10':H,'wealth_FORCE':F,'wealth_JOINT':J,
                                    'delta_joint_vs_R':J-R,'delta_joint_vs_H10':J-H,'delta_joint_vs_FORCE':J-F,
                                    'joint_annual_return_difference_vs_R':(J-R)/opening,'descriptive_interaction_currency':interaction,
                                    'descriptive_interaction_annual_pp':100*interaction/opening,'original_May30_disposition':original_may,'joint_May30_disposition':joint_may,
                                    'May30_disposition_difference':may_delta,'later_participation_difference_from_May30':later_delta,
                                    'H10_June19_disposition':hold_june,'joint_June19_disposition':joint_june,
                                    'conditional_June19_disposition_difference':conditional_base,'conditional_June19_later_participation_difference':conditional_later,
                                    'interpretation':'Actual same-original-history joint path. Interaction is descriptive accounting after observed interventions, not causal alpha or general signal validity.'}
    with csvpath.open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['date',*maps])
        writer.writeheader()
        for day in maps['ORIGINAL_R']:
            if day.startswith('2025-'):
                writer.writerow({'date':day,**{mode:rows[day]['equity'] for mode,rows in maps.items()}})
    result.update(status='PASS_BOTH_FIXED_EX042_MODES' if set(completed)=={'NOOP','JOINT'} else 'PARTIAL_AUDIT',completed_modes=list(completed),
                  checks=sum(A.COUNTS.values()),check_counts=dict(A.COUNTS),arithmetic_error_bounds=A.ERRORS,
                  csv={'path':str(csvpath),'sha256':sha256(csvpath.read_bytes()).hexdigest(),'yearopening':opening},
                  source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),helper_sha256={'audit_accounts':sha256(Path(A.__file__).read_bytes()).hexdigest(),'audit_early_cycle_accounts':sha256(Path(E.__file__).read_bytes()).hexdigest()},
                  index_sha256=sha256(indexpath.read_bytes()).hexdigest())
    with out.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    print(json.dumps({'status':result['status'],'checks':result['checks'],'sha256':sha256(out.read_bytes()).hexdigest()}))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--csv',type=Path,required=True)
    args=parser.parse_args()
    main(args.index,args.output,args.csv)
