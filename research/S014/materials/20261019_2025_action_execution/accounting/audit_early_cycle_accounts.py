"""Independent EX041 fixed original-May30 cycle accounting, no account dispatch."""
import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path

import audit_accounts as A

ROOT = Path.cwd()
BASE = ROOT / 'research/S014/experiments/EX041_20261019'
ENTRY = '2025-05-30'
T = '2025-12-31'
MODES = ['NOOP', 'HOLD_ORIGINAL_CYCLE_H10']

def identity(record, account, original):
    lock = A.published(A.read(BASE / 'protocols/published_lock.json'))
    row = next(r for r in lock['runs'] if r['index'] == record['index'])
    for key in ['mode','parameters','candidate','runtime_sha256','payload_sha256']:
        A.check('EX041 locked ' + key, record[key] == row[key])
    payload, binding = A.published(record['published_payload_ref']), A.published(record['binding_ref'])
    A.public_bytes(record['published_source_ref'])
    A.check('correct EX041 approved source', record['published_source_ref']['sha256'] == 'b18c884977580dfeace071c98bcd94fecf23a0e9369cb015f3f2e021b8f5536c')
    A.check('new source implementation closure', payload['runtime']['source_sha256'] == record['runtime_implementation_sha256'] == lock['runtime_implementation_sha256'])
    A.check('fixed same May30 parameters', record['parameters'] == payload['parameters'] == {'mode':record['mode'],'entry_execution_date':ENTRY})
    A.check('payload immutable SHA', record['payload_sha256'] == record['published_payload_ref']['sha256'])
    A.check('binding candidate and payload', binding['candidate'] == record['candidate'] and binding['payload'] == payload)
    req = account['request_identity']
    A.check('new EX041 request', req['experiment_id'] == 'EX041_20261019')
    for key in ['asset_type','benchmark','costs','data_cutoff','execution_mode','frequency_window_days','initial_cash','market_rules','metric_semantics_version','price_basis','pricing','symbol','windows']:
        A.check('unchanged original contract '+key, req[key] == original['request_identity'][key])
    A.check('content identity binds actual receipt', req['content_sha256'] == record['request_content_sha256'])
    A.check('runtime binding exact', account['runtime_binding_hash'] == req['runtime_binding_hash'] == record['runtime_binding_hash'])
    A.check('candidate in account', account['runs'][0]['candidate_id'] == record['candidate'].split('-')[-1])
    A.check('request same public binding', req['input_bindings'] == binding['input_bindings'])
    source = A.read(ROOT / 'research/S014/materials/20261019_2025_action_method_review/method/source_bindings.json')
    for key in ['execution_requests','execution_identities','execution_prepared','execution_fingerprint']:
        A.check('same original prepared '+key, binding[key] == source['original_'+key])
    A.check('same original execution data identity', req['data_identity'] == binding['execution_fingerprint'] == original['request_identity']['data_identity'])
    plan, old = req['input_bindings']['full']['plan'], original['request_identity']['input_bindings']['full']['plan']
    A.check('input plan keys', plan.keys() == old.keys())
    for key in plan:
        if key != 'strategy':
            A.check('same causal input/clock '+key, plan[key] == old[key])
    A.check('strategy identity distinct and bound', plan['strategy']['release_hash'] == req['strategy_identity'] == account['strategy_identity'] and account['strategy_identity'] != original['strategy_identity'])
    A.check('runtime hash bound', plan['strategy']['runtime_sha256'] == record['runtime_sha256'] and plan['strategy']['reference_id'] == record['candidate'])
    return {k:record[k] for k in ['parameters','candidate','payload_sha256','runtime_implementation_sha256','runtime_sha256','published_source_ref','binding_ref']}

def cycle_state(original, account, mode):
    run, base = account['runs'][0], original['runs'][0]
    tables = {k:v['data'] for k,v in run['ledgers'].items()}
    if mode == 'NOOP':
        A.noop_equivalence(original,account)
    else:
        for name,key in [('account_daily','date'),('fills','fill_time'),('orders','execution_date')]:
            A.economic_rows(base['ledgers'][name]['data'],tables[name], 'EX041 same original May30 filled prefix',ENTRY,key)
        old_dec = [x for x in base['ledgers']['decisions']['data'] if A.day(x['signal_date']) < ENTRY]
        new_dec = [x for x in tables['decisions'] if A.day(x['signal_date']) < ENTRY]
        A.economic_rows(old_dec,new_dec,'EX041 preceding decisions exact')
    # Truthful raw state is common for all full-window D, regardless of changed trading path.
    for old,new in zip(base['ledgers']['decisions']['data'],tables['decisions'],strict=True):
        for key in ['ready','support_ok','warmup_sessions','support_floor','support_break']:
            A.check('unchanged truthful original support state '+key, old[key] == new[key])
    by_fill = {A.day(f['fill_time']):f for f in tables['fills']}
    protected_mode = mode != 'NOOP'
    seen = completed = False
    fixed_entry = fixed_deadline = fixed_reservation = -1
    pending = False
    previous = None
    suppressed, protected_rows, blocked = [], [], []
    actual_sale = None
    for i,dec in enumerate(tables['decisions']):
        D = A.day(dec['signal_date'])
        fill = by_fill.get(D)
        if fill and fill['side'] == 'BUY' and D == ENTRY:
            seen = True
            fixed_entry, fixed_deadline, fixed_reservation = i,i+9,i+10
            A.check('actual targeted May30 fill once', fixed_entry == 1309)
        if fill and fill['side'] == 'SELL':
            if seen and not completed:
                completed = True
                actual_sale = fill
            pending = False
        held = bool(dec['held_at_close'])
        protected = protected_mode and held and seen and not completed
        suppressed_expected = protected and bool(dec['support_break']) and i < dec['deadline_index'] and not pending
        expected_pending = held and (pending or i >= dec['deadline_index'] or (bool(dec['support_break']) and not protected))
        A.check('independent support/deadline/pending intent', bool(dec['exit_pending']) == expected_pending)
        A.check('actual fixed cycle mode state', bool(dec['cycle_mode_active']) == protected_mode and bool(dec['target_entry_seen']) == seen and bool(dec['target_cycle_completed']) == completed)
        A.check('actual protected-cycle state', bool(dec['protected_cycle_active']) == protected)
        A.check('all and only support suppression', bool(dec['support_exit_suppressed']) == bool(suppressed_expected))
        A.check('original absolute fixed clocks recorded', dec['fixed_cycle_entry_index'] == fixed_entry and dec['fixed_cycle_deadline_index'] == fixed_deadline and dec['fixed_cycle_reservation_index'] == fixed_reservation)
        A.check('deadline wins over protection', bool(dec['deadline_exit_pending']) == bool(protected and i >= dec['deadline_index'] and expected_pending))
        blocked_expected = bool(protected_mode and previous and previous['protected_cycle_active'] and previous['exit_pending'] and not (fill and fill['side'] == 'SELL'))
        A.check('blocked actual sell pending observation', bool(dec['protected_sell_blocked']) == blocked_expected)
        if dec['support_exit_suppressed']:
            suppressed.append(D)
        if protected:
            protected_rows.append(D)
            A.check('protected original clocks never reset', dec['entry_index'] == fixed_entry and dec['deadline_index'] == fixed_deadline and dec['reservation_index'] == fixed_reservation)
        if dec['protected_sell_blocked']:
            blocked.append(D)
        pending = expected_pending
        previous = dec
    A.check('original fixed entry seen and eventually exited', seen and completed and actual_sale is not None)
    return {'all_support_exit_suppressed_D':suppressed,'all_protected_D':protected_rows,'all_blocked_exit_D':blocked,
            'fixed_entry_index':fixed_entry,'fixed_deadline_index':fixed_deadline,'fixed_reservation_index':fixed_reservation,
            'actual_original_inventory_sale':actual_sale}

def main(index_path, out, csv_path):
    index = A.read(index_path)
    origin = A.read(ROOT / 'research/S014/experiments/EX023_20261018/others/account_results.json')['records'][0]
    original = A.published(origin['evidence'])
    completed = {}
    result = {'resources':{'EX041_dispatched_including_failed_unknown':len(index['records']), 'status_counts':dict(Counter(r['status'] for r in index['records'])),
                           'FAILED_UNKNOWN_preserved':[r for r in index['records'] if r['status']!='SUCCEEDED']},
              'original_evidence':origin['evidence'],'audited_accounts':[],'terminal':T,'independent_dispatches':0,'new_fits':0,'new_market_API_calls':0}
    for record in index['records']:
        if record['status']!='SUCCEEDED':
            continue
        mode = record['mode']
        A.check('fixed unique mode', mode in MODES and mode not in completed)
        account = A.published(record['evidence'])
        A.check('actual result receipt',account['result_hash'] == record['result_hash'])
        A.check('one original full window',len(account['runs'])==1 and account['execution_mode']=='FULL')
        A.IDENTITY_MAPS.clear()
        bound = identity(record,account,original)
        A.equal_baseline(original,account)
        economics = A.audit_daily(account)
        if mode!='NOOP':
            A.check('fresh-source NOOP audited first','NOOP' in completed)
        lifecycle = cycle_state(original,account,mode)
        run=account['runs'][0]
        years,bh=A.yearly(run['ledgers']['account_daily']['data']),A.yearly(run['buyhold']['account_daily']['data'])
        annual=[]
        for y,row in years.items():
            target=1.5*bh[y]['return'] if bh[y]['return']>0 else 0.
            annual.append({'year':y,**row,'buyhold_return':bh[y]['return'],'required_return':target,
                           'return_pass':row['return']>=target if bh[y]['return']>0 else row['return']>0,
                           'drawdown_pass':row['max_drawdown']<bh[y]['max_drawdown'],'2026_technical_tail_only':y==2026})
        closed=sum(t['status']=='CLOSED' for t in run['ledgers']['trades']['data'])
        result['audited_accounts'].append({'mode':mode,'evidence':record['evidence'],'result_hash':record['result_hash'],
                                         'immutable_identity':bound,'accounting':economics,'cycle_lifecycle':lifecycle,
                                         'original_annual_goal_audit':annual,'frequency_per_60':60*closed/1642,
                                         'frequency_pass':60*closed/1642>=3,'terminal_2025_asof_state':A.terminal_state(account)})
        completed[mode]=account
    daily={'ORIGINAL_R':{A.day(r['date']):r for r in original['runs'][0]['ledgers']['account_daily']['data']}}
    daily.update({mode:{A.day(r['date']):r for r in account['runs'][0]['ledgers']['account_daily']['data']} for mode,account in completed.items()})
    opening=daily['ORIGINAL_R']['2024-12-31']['equity']
    if 'HOLD_ORIGINAL_CYCLE_H10' in completed:
        treatment=completed['HOLD_ORIGINAL_CYCLE_H10']
        base=disposition(original)
        changed=disposition(treatment)
        delta=changed['terminal_wealth']-base['terminal_wealth']
        dbase=changed['base_terminal_currency']-base['base_terminal_currency']
        residual=changed['post_disposition_participation_currency']-base['post_disposition_participation_currency']
        A.number('May30 exact terminal accounting split',delta,dbase+residual,True)
        result['fixed2025_terminal_effect']={'D':ENTRY,'T':T,'original':base,'H10':changed,'delta_wealth':delta,
                                           'original_position_disposition_difference':dbase,'later_participation_difference':residual,
                                           'original_year_opening':opening,'annual_return_difference':delta/opening,
                                           'D_original_wealth':daily['ORIGINAL_R'][ENTRY]['equity'],
                                           'D_normalized_effect':delta/daily['ORIGINAL_R'][ENTRY]['equity'],
                                           'nonadditivity':'Do not add EX040 FORCE or SKIP; different original node and later capital path.'}
    with csv_path.open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['date',*daily])
        writer.writeheader()
        for day in daily['ORIGINAL_R']:
            if day.startswith('2025-'):
                writer.writerow({'date':day,**{mode:rows[day]['equity'] for mode,rows in daily.items()}})
    result.update(status='PASS_BOTH_FIXED_EX041_MODES' if set(completed)==set(MODES) else 'PARTIAL_AUDIT',
                  completed_modes=list(completed),checks=sum(A.COUNTS.values()),check_counts=dict(A.COUNTS),
                  arithmetic_error_bounds=A.ERRORS,csv={'path':str(csv_path),'sha256':sha256(csv_path.read_bytes()).hexdigest(),'original_2025_opening':opening},
                  source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),helper_source_sha256=sha256(Path(A.__file__).read_bytes()).hexdigest(),
                  index_sha256=sha256(index_path.read_bytes()).hexdigest())
    with out.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    print(json.dumps({'status':result['status'],'checks':result['checks'],'output_sha256':sha256(out.read_bytes()).hexdigest()}))

def disposition(account):
    # Generic frozen-D inventory attribution, independent of EX040's June19 assertion.
    run=account['runs'][0]
    days={A.day(x['date']):x for x in run['ledgers']['account_daily']['data']}
    initial,end=days[ENTRY],days[T]
    buys=[f for f in run['ledgers']['fills']['data'] if A.day(f['fill_time'])==ENTRY and f['side']=='BUY']
    A.check('single original May30 existing inventory',len(buys)==1 and buys[0]['quantity']==initial['quantity'])
    sales=[f for f in run['ledgers']['fills']['data'] if f['cycle_id']==buys[0]['cycle_id'] and f['side']=='SELL' and ENTRY<A.day(f['fill_time'])<=T]
    A.check('at most one actual full original inventory sale',len(sales)<=1)
    if sales:
        sale=sales[0]
        after=days[A.day(sale['fill_time'])]
        A.check('actual full original inventory disposition',after['quantity']==0 and sale['quantity']==initial['quantity'])
        base=after['cash']
        A.number('actual original May30 inventory cash disposition',base,initial['cash']+sale['quantity']*sale['price']-sale['fees'],True)
        state='ACTUAL_ORIGINAL_INVENTORY_SALE_CASH_FROZEN'
    else:
        A.check('unsold original inventory at T',end['quantity']==initial['quantity'] and end['cash']==initial['cash'])
        base=initial['cash']+initial['quantity']*end['close']
        state='UNSOLD_MARK_NOT_CASH'
    return {'base_type':state,'base_terminal_currency':base,'post_disposition_participation_currency':end['equity']-base,
            'actual_original_inventory_sale':sales[0] if sales else None,'terminal_wealth':end['equity']}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--csv',type=Path,required=True)
    args=parser.parse_args()
    main(args.index,args.output,args.csv)
