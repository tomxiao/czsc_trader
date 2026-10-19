"""Read authenticated EX043 accounts only; decompose actual 2020-25 wealth paths.

No strategy replay, hypothetical sale, fitting, supplier call or raw-price export.
"""
from collections import Counter, defaultdict
import csv
import io
from hashlib import sha256
import json
import math
from pathlib import Path
import socket

from czsc_trader.research_tools import EvidenceRef

ROOT=Path.cwd()
OUT=Path(__file__).resolve().parent
EX=ROOT/'research/S014/experiments/EX043_20261019'
START='2020-01-01'
END='2025-12-31'
POLICIES={0:'BASE/BASE',4:'ENTRY_GRACE/SHOCK_PROFIT'}
EPS=1e-7
CHECKS=Counter()
MAX_ERROR=0.

def prohibited(*args,**kwargs):
    raise RuntimeError('Account-only read audit: no network/supplier/dispatch')

socket.socket.connect=prohibited
socket.create_connection=prohibited

def check(name,value):
    assert value,name
    CHECKS[name]+=1

def number(name,actual,expected):
    global MAX_ERROR
    error=abs(float(actual)-float(expected))
    MAX_ERROR=max(MAX_ERROR,error)
    check(name,math.isfinite(float(actual)) and error<=EPS)

def day(value):
    return str(value)[:10]

def read(path):
    return json.loads(path.read_bytes())

def published(value):
    ref=EvidenceRef.from_dict(value)
    check('S014 scope',ref.experiment.strategy_id=='S014')
    raw=ref.resolve(ROOT).read_bytes()
    check('public SHA exact',sha256(raw).hexdigest()==ref.sha256)
    return json.loads(raw)

def write_json(name,value):
    path=OUT/name
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')
    return {'path':str(path.relative_to(ROOT)),'sha256':sha256(path.read_bytes()).hexdigest()}

def write_csv(name,rows):
    path=OUT/name
    columns=list(dict.fromkeys(key for row in rows for key in row))
    stream=io.StringIO(newline='')
    writer=csv.DictWriter(stream,fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    content=stream.getvalue().encode('utf-8')
    if path.exists():
        check('recomputed output bytes exact',path.read_bytes()==content)
    else:
        with path.open('xb') as target:
            target.write(content)
    return {'path':str(path.relative_to(ROOT)),'sha256':sha256(path.read_bytes()).hexdigest(),'rows':len(rows)}

def authenticate(index,policy):
    receipt=read(EX/f'others/accounts/run-{index:03d}.json')
    check('frozen successful policy identity',receipt['mode']==policy and receipt['status']=='SUCCEEDED')
    account=published(receipt['evidence'])
    check('actual result identity',account['result_hash']==receipt['result_hash'])
    check('frozen actual source',receipt['published_source_ref']['sha256']=='e980a552367e9354a5f2fcfcd411e5c6a64a408ecb83bed115aa9b578029e57a')
    prior=read(ROOT/f'research/S014/materials/20261019_exante_hold_exit/accounting/account_{index:03d}_independent_review.json')
    check('previous independent audited account identity',prior['status']=='PASS' and prior['account_ref']==receipt['evidence'] and prior['result_hash']==account['result_hash'])
    return account,{'policy':policy,'account_ref':receipt['evidence'],'result_hash':receipt['result_hash'],
                    'parameters':receipt['parameters'],'runtime_sha256':receipt['runtime_sha256'],
                    'original_independent_review_sha256':sha256((ROOT/f'research/S014/materials/20261019_exante_hold_exit/accounting/account_{index:03d}_independent_review.json').read_bytes()).hexdigest()}

def posture(dec):
    return 'PLAN_BUY' if dec['entry_signal'] else 'PLAN_SELL' if dec['held_at_close'] and dec['exit_pending'] else 'HOLD' if dec['held_at_close'] else 'FLAT'

def process(account,policy):
    run=account['runs'][0]
    ledgers=run['ledgers']
    daily=[r for r in ledgers['account_daily']['data'] if day(r['date'])<=END]
    fills={day(r['fill_time']):r for r in ledgers['fills']['data'] if day(r['fill_time'])<=END}
    orders=ledgers['orders']['data']
    decisions={day(r['signal_date']):r for r in ledgers['decisions']['data']}
    bh={day(r['date']):r for r in run['buyhold']['account_daily']['data'] if day(r['date'])<=END}
    check('economic1455 actual sessions only',len(daily)==1455)
    year_open={}
    bh_open={}
    prev,prev_bh,prev_close=100000.,100000.,None
    active=None
    cycle_meta={}
    atoms=[]
    for row in daily:
        E=day(row['date'])
        D=day(row['signal_date'])
        year=int(E[:4])
        year_open.setdefault(year,prev)
        bh_open.setdefault(year,prev_bh)
        dec=decisions[D]
        check('source decision clock',day(dec['valid_session'])==E)
        check('D actual holding equals runtime',bool(row['quantity_before'])==bool(dec['held_at_close']))
        fill=fills.get(E)
        entry_atom=holding_atom=exit_atom=fees=0.
        old_cycle=active
        if fill and fill['side']=='BUY':
            check('new cycle flat actual entry',active is None and row['quantity_before']==0)
            active=fill['cycle_id']
            cycle_meta[active]={'policy_id':policy,'cycle_id':active,'entry_date':E,'entry_signal_D':D,
                                'entry_price':fill['price'],'quantity':fill['quantity'],'entry_fee':fill['fees'],
                                'actual_exit_date':None,'actual_exit_price':None,'exit_fee':None}
            entry_atom=fill['quantity']*(row['close']-fill['price'])
            fees=fill['fees']
            phase='ACTUAL_BUY'
        elif fill:
            check('sale linked actual held cycle',fill['side']=='SELL' and active==fill['cycle_id'] and row['quantity_before']==fill['quantity'])
            exit_atom=fill['quantity']*(fill['price']-prev_close)
            fees=fill['fees']
            phase='ACTUAL_SELL'
            meta=cycle_meta[active]
            meta.update(actual_exit_date=E,actual_exit_price=fill['price'],exit_fee=fill['fees'],exit_signal_D=D)
        elif row['quantity_before']:
            holding_atom=row['quantity_before']*(row['close']-prev_close)
            phase='ACTUAL_CONTINUE_HOLD'
        else:
            phase='ACTUAL_CONTINUE_FLAT'
        cycle=active if active is not None else 'FLAT'
        gross=entry_atom+holding_atom+exit_atom
        net=gross-fees
        number('daily actual net atoms',net,row['equity']-prev)
        number('actual wealth cash position identity',row['equity'],row['cash']+row['quantity']*row['close'])
        if row['quantity_before']:
            check('actual held cycle exists',old_cycle is not None)
        bh_pnl=bh[E]['equity']-prev_bh
        atom={'policy_id':policy,'E':E,'D':D,'year':year,'month':E[:7],'quarter':E[:4]+'Q'+str((int(E[5:7])-1)//3+1),
              'actual_phase':phase,'D_posture':posture(dec),'cycle_id':cycle,'opening_equity':prev,'closing_equity':row['equity'],
              'cash_before':row['cash_before'],'cash_after':row['cash'],'quantity_before':row['quantity_before'],'quantity_after':row['quantity'],
              'entry_day_mark_pnl':entry_atom,'continued_holding_mark_pnl':holding_atom,'exit_to_actual_fill_pnl':exit_atom,
              'gross_mark_pnl':gross,'actual_fees':fees,'net_pnl':net,'cash_interest_pnl':0.,
              'own_year_opening':year_open[year],'net_annual_contribution_pp':100*net/year_open[year],
              'buyhold_pnl':bh_pnl,'buyhold_own_year_opening':bh_open[year],
              'buyhold_annual_contribution_pp':100*bh_pnl/bh_open[year],
              'relative_buyhold_contribution_pp':100*(net/year_open[year]-bh_pnl/bh_open[year]),
              'D_support_break':dec['support_break'],'D_entry_signal':dec['entry_signal'],'D_exit_pending':dec['exit_pending'],
              'D_pending_inherited':dec['pending_inherited'],'D_deadline_exit':dec['deadline_exit'],
              'D_selected_profit_exit':dec['selected_profit_exit'],'D_support_suppressed':dec['support_exit_suppressed'],
              'D_holding_age':dec['holding_age']}
        atoms.append(atom)
        if fill and fill['side']=='SELL':
            active=None
        prev,prev_bh,prev_close=row['equity'],bh[E]['equity'],row['close']
    days={day(r['date']):r for r in daily}
    # Complete actual-cycle facts use only already existing account outcomes through2025.
    cycle_facts=[]
    for cycle,meta in cycle_meta.items():
        entry=meta['entry_date']
        exit_date=meta['actual_exit_date']
        terminal=exit_date or END
        live_days=[r for r in daily if entry<=day(r['date'])<=terminal and (day(r['date'])!=exit_date)]
        entryD=decisions[entry]
        closing_decisions=[decisions[day(r['date'])] for r in live_days]
        peak_net=max(r['net_profit'] for r in closing_decisions)
        worst_net=min(r['net_profit'] for r in closing_decisions)
        net_return=(meta['actual_exit_price']*.999/(meta['entry_price']*1.001)-1) if exit_date else (days[END]['close']/(meta['entry_price']*1.001)-1)
        cycle_atoms=[r for r in atoms if r['cycle_id']==cycle]
        net_pnl=sum(r['net_pnl'] for r in cycle_atoms)
        if exit_date:
            number('complete actual cycle net money',net_pnl,meta['quantity']*meta['actual_exit_price']-meta['exit_fee']-meta['quantity']*meta['entry_price']-meta['entry_fee'])
        else:
            number('uncompleted inventory actual mark no sale fee',net_pnl,meta['quantity']*(days[END]['close']-meta['entry_price'])-meta['entry_fee'])
        fact={**meta,'entry_year':int(entry[:4]),'status_at2025_cap':'ACTUALLY_CLOSED' if exit_date else 'OPEN_MARK_NO_EXIT_FEE',
              'observed_cycle_net_return_to2025_cap':net_return,'actual_cycle_net_pnl_to2025_cap':net_pnl,
              'max_observed_D_net_mark_profit':peak_net,'min_observed_D_net_mark_profit':worst_net,
              'never_positive_D_mark_before_exit_or_cap':peak_net<=0,'positive_D_mark_then_ended_loss':peak_net>0 and net_return<0,
              'entryD_net_profit':entryD['net_profit'],'entryD_support_break':entryD['support_break'],
              'entryD_entry_grace_applied':entryD['entry_grace_applied'],'entryD_ma20_prior':entryD['ma20_prior'],
              'entryD_atr20_prior':entryD['atr20_prior'],'entryD_z5':entryD['z5'],'entryD_breach_atr':entryD['breach_atr'],
              'last_held_D':day(closing_decisions[-1]['signal_date']),
              'entry_day_mark_pnl':sum(a['entry_day_mark_pnl'] for a in cycle_atoms),
              'continued_holding_mark_pnl':sum(a['continued_holding_mark_pnl'] for a in cycle_atoms),
              'exit_to_actual_fill_pnl':sum(a['exit_to_actual_fill_pnl'] for a in cycle_atoms),
              'actual_fees_to_cap':sum(a['actual_fees'] for a in cycle_atoms)}
        if exit_date:
            sellD=decisions[meta['exit_signal_D']]
            planned=[o for o in orders if o['cycle_id']==cycle and o['side']=='SELL' and day(o['execution_date'])<=exit_date]
            peak_close=sellD['peak_close']/account['request_identity']['pricing']['anchor_factor']
            dec_close=days[meta['exit_signal_D']]['close']
            fact.update(exitD_posture=posture(sellD),exitD_holding_age=sellD['holding_age'],exitD_net_profit=sellD['net_profit'],
                        exitD_support_break=sellD['support_break'],exitD_deadline=sellD['deadline_exit'],
                        exitD_selected_profit=sellD['selected_profit_exit'],exitD_shock=sellD['shock_condition'],exitD_z5=sellD['z5'],
                        exitD_peak_net_gain_price=sellD['peak_net_gain_price'],exitD_giveback_price=sellD['giveback_price'],
                        exitD_atr20_prior=sellD['atr20_prior'],sell_attempts=len(planned),
                        blocked_sell_attempts=sum(o['status']!='FILLED' for o in planned),
                        first_planned_sell_E=min(day(o['execution_date']) for o in planned),
                        actual_exit_on_first_planned_E=exit_date==min(day(o['execution_date']) for o in planned),
                        peak_to_sell_decision_gross_pnl=meta['quantity']*(dec_close-peak_close),
                        sell_decision_to_actual_fill_gross_pnl=meta['quantity']*(meta['actual_exit_price']-dec_close))
            number('observed peak-to-sale two part identity',fact['peak_to_sell_decision_gross_pnl']+fact['sell_decision_to_actual_fill_gross_pnl'],meta['quantity']*(meta['actual_exit_price']-peak_close))
        cycle_facts.append(fact)
    return atoms,cycle_facts,year_open,bh_open,days,decisions

SUM_FIELDS=['entry_day_mark_pnl','continued_holding_mark_pnl','exit_to_actual_fill_pnl','gross_mark_pnl','actual_fees','net_pnl',
            'net_annual_contribution_pp','buyhold_pnl','buyhold_annual_contribution_pp','relative_buyhold_contribution_pp']

def aggregate(atoms,group_keys):
    groups=defaultdict(list)
    for row in atoms:
        groups[tuple(row[k] for k in group_keys)].append(row)
    output=[]
    for keys,rows in sorted(groups.items()):
        first,last=rows[0],rows[-1]
        value={**dict(zip(group_keys,keys)),'first_E':first['E'],'last_E':last['E'],'sessions':len(rows),
               **{key:sum(r[key] for r in rows) for key in SUM_FIELDS}}
        if 'actual_phase' not in group_keys and 'D_posture' not in group_keys and 'cycle_id' not in group_keys:
            value.update(opening_equity=first['opening_equity'],closing_equity=last['closing_equity'],
                         own_period_return=last['closing_equity']/first['opening_equity']-1)
            number('period wealth bridge',value['net_pnl'],value['closing_equity']-value['opening_equity'])
        value['actual_closed_exit_count']=sum(r['actual_phase']=='ACTUAL_SELL' for r in rows)
        value['actual_entry_count']=sum(r['actual_phase']=='ACTUAL_BUY' for r in rows)
        value['actual_held_start_days']=sum(r['quantity_before']>0 for r in rows)
        value['actual_flat_start_days']=sum(r['quantity_before']==0 for r in rows)
        output.append(value)
    return output

def main():
    all_atoms,all_cycles,refs=[],[],[]
    state={}
    for index,policy in POLICIES.items():
        account,ref=authenticate(index,policy)
        atoms,cycles,opening,bhopening,days,decisions=process(account,policy)
        refs.append(ref)
        all_atoms.extend(atoms)
        all_cycles.extend(cycles)
        state[policy]={'days':days,'decisions':decisions,'opening':opening,'bhopening':bhopening}
    annual=aggregate(all_atoms,['policy_id','year'])
    monthly=aggregate(all_atoms,['policy_id','month'])
    quarterly=aggregate(all_atoms,['policy_id','quarter'])
    cycle_year=aggregate([r for r in all_atoms if r['cycle_id']!='FLAT'],['policy_id','year','cycle_id'])
    phase_year=aggregate(all_atoms,['policy_id','year','actual_phase'])
    posture_year=aggregate(all_atoms,['policy_id','year','D_posture'])
    boundary=[]
    for policy,data in state.items():
        for year in range(2020,2026):
            dates=[d for d in data['days'] if d.startswith(str(year))]
            first,last=dates[0],dates[-1]
            before=[d for d in data['days'] if d<first]
            prev=data['days'][before[-1]] if before else {'cash':100000.,'quantity':0,'equity':100000.}
            end=data['days'][last]
            dec=data['decisions'][last]
            boundary.append({'policy_id':policy,'year':year,'first_E':first,'last_E':last,
                             'opening_equity':prev['equity'],'opening_cash':prev['cash'],'opening_quantity':prev['quantity'],
                             'closing_equity':end['equity'],'closing_cash':end['cash'],'closing_quantity':end['quantity'],
                             'year_end_D_posture':posture(dec),'year_end_pending':dec['exit_pending'],
                             'year_end_entry_index':dec['entry_index'],'year_end_deadline':dec['deadline_index'],'year_end_reservation':dec['reservation_index'],
                             'uncompleted_position_at_year_end':end['quantity']>0})
    # Matched actual entry dates are not matched capital: show both quantities and net returns.
    by_policy={policy:{r['entry_date']:r for r in all_cycles if r['policy_id']==policy} for policy in POLICIES.values()}
    base,best=list(POLICIES.values())
    matched=[]
    for date in sorted(set(by_policy[base])|set(by_policy[best])):
        left,right=by_policy[base].get(date),by_policy[best].get(date)
        value={'entry_date':date,'same_actual_entry_date':left is not None and right is not None}
        for name,row in [('BASE',left),('FROZEN',right)]:
            for key in ['quantity','entry_price','actual_exit_date','actual_exit_price','observed_cycle_net_return_to2025_cap','actual_cycle_net_pnl_to2025_cap']:
                value[name+'_'+key]=row.get(key) if row else None
        if left and right:
            value['same_actual_entry_price']=left['entry_price']==right['entry_price']
            value['different_actual_exit_date']=left['actual_exit_date']!=right['actual_exit_date']
        matched.append(value)
    outputs={
        'daily_atoms':write_csv('daily_accounting_atoms_2020_25.csv',all_atoms),
        'annual_bridge':write_csv('policy_year_accounting_bridge.csv',annual),
        'monthly_bridge':write_csv('policy_month_accounting_bridge.csv',monthly),
        'quarterly_bridge':write_csv('policy_quarter_accounting_bridge.csv',quarterly),
        'cycle_year':write_csv('actual_cycle_year_contributions.csv',cycle_year),
        'cycles':write_csv('actual_cycle_facts_2020_25.csv',all_cycles),
        'phase_year':write_csv('actual_phase_year_contributions.csv',phase_year),
        'Dposture_year':write_csv('D_posture_year_contributions.csv',posture_year),
        'boundaries':write_csv('calendar_year_boundary_positions.csv',boundary),
        'matched_actual_entry_cycles':write_csv('matched_actual_entry_cycles.csv',matched)}
    result={'status':'PASS_REAL_ACCOUNT_WEALTH_AND_CYCLE_RECONCILIATION','accounts':refs,'economic_domain':[START,END],
            '2026_role':'Account bytes retain technical tail, but no2026 prices/fills/trade outcomes enter these economic calculations.',
            'source_price_units':'Anchored HFQ_RESEARCH/RESEARCH_UNIT, original factor5.892. Runtime full-HFQ peak is divided by the anchor before ledger-money multiplication.',
            'daily_identity':'DeltaW=BUY quantity*(sameEledgerClose-fillPrice) OR held quantity*(closeE-prevLedgerClose) OR SELL quantity*(fillPrice-prevLedgerClose) minus actual fees. Flat cash interest=0.',
            'phase_and_posture':'actual_phase is ex-post accounting only. D_posture uses entry_signal, actual held state and exit_pending; a flat failed-BUY action SELL is FLAT.',
            'benchmark_relative':'Actual net PnL/own year opening minus executable BuyHold PnL/its own year opening. Phase sums describe realized timing selection; they are not feasible counterfactual trades or D-known features.',
            'cycle_years':'Calendar-year cycle contributions include only actual money/marks within that year, even when entry or exit crosses it. Whole-cycle outcomes are separately tagged by actual entry year and capped2025.',
            'peak_giveback_limit':'Peak-to-sale is observed path accounting, not proof that a peak sale was knowable/executable or that another exit policy would improve full-year wealth.',
            'outputs':outputs,'check_counts':dict(CHECKS),'checks':sum(CHECKS.values()),'maximum_currency_error':MAX_ERROR,'arithmetic_absolute_tolerance':EPS,
            'new_model_fits':0,'new_strategy_replays':0,'new_accounts':0,'new_data_supplier_calls':0,'prepared_fetches':0,'raw_market_data_exports':0,
            'source_sha256':sha256(Path(__file__).read_bytes()).hexdigest()}
    out=write_json('accounting_reconciliation_final.json',result)
    print(json.dumps({'status':result['status'],'checks':result['checks'],'max_error':MAX_ERROR,'outputs':outputs,'review':out}))

if __name__=='__main__':
    main()
