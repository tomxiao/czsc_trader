"""Independent EX043 account audit, using public immutable results and existing inputs.

No dispatch, prepare, strategy replay, fitting, or supplier/network call is permitted.
Per-account reports are exclusive-created. Final consolidation reuses audited reports.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, time
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import sys
from uuid import UUID

from dataflows import DataRequest, Dataset, PreparedDataRef
import pandas as pd
import requests
from strategy_runtime.pricing import ExecutionPricing
from trading_execution_engine import DailyQuote, OrderSpec, SessionPriceLimits, resolve_fill

ROOT=Path.cwd()
OUT=Path(__file__).resolve().parent
BASE=ROOT/'research/S014/experiments/EX043_20261019'
HELPER=ROOT/'research/S014/materials/20261019_2025_action_execution/accounting/audit_accounts.py'
spec=importlib.util.spec_from_file_location('ex043_independent_ledger_helper',HELPER)
A=importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
SOURCE_SHA='e980a552367e9354a5f2fcfcd411e5c6a64a408ecb83bed115aa9b578029e57a'
TRIGGERS=['selected_profit_exit','profit_exit_added_vs_base_support','profit_exit_added_vs_selected_hold',
          'profit_support_overlap','entry_grace_applied','trend_cycle_activated','support_exit_suppressed']
FIELDS=['shock_condition','giveback_condition','entry_grace_eligible','trend_cycle_eligible',*TRIGGERS]

def prohibit(*args,**kwargs):
    raise RuntimeError('Independent auditor prohibits network, suppliers and account dispatch')

socket.socket.connect=prohibit
socket.create_connection=prohibit
requests.sessions.Session.request=prohibit

def write(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')

def hash_value(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def original():
    row=A.read(ROOT/'research/S014/experiments/EX023_20261018/others/account_results.json')['records'][0]
    return A.published(row['evidence']),row['evidence']

def identity(record,account,origin):
    lock=A.published(A.read(BASE/'protocols/published_lock.json'))
    row=next(r for r in lock['runs'] if r['index']==record['index'])
    for key in ['mode','parameters','candidate','runtime_sha256','payload_sha256']:
        A.check('locked immutable identity '+key,record[key]==row[key])
    payload,binding=A.published(record['published_payload_ref']),A.published(record['binding_ref'])
    A.public_bytes(record['published_source_ref'])
    A.check('approved source byte identity',record['published_source_ref']['sha256']==SOURCE_SHA)
    A.check('implementation closure',record['runtime_implementation_sha256']==lock['runtime_implementation_sha256']==payload['runtime']['source_sha256'])
    A.check('public payload content',record['payload_sha256']==record['published_payload_ref']['sha256'] and payload==binding['payload'])
    A.check('parameters exact',record['parameters']==payload['parameters'] and set(payload['parameters'])=={'hold_rule','exit_rule'})
    A.check('candidate and mode',binding['candidate']==record['candidate'] and record['mode']==record['parameters']['hold_rule']+'/'+record['parameters']['exit_rule'])
    req=account['request_identity']
    A.check('new EX043 identity',req['experiment_id']=='EX043_20261019')
    for key in ['asset_type','benchmark','costs','data_cutoff','execution_mode','frequency_window_days','initial_cash','market_rules','metric_semantics_version','price_basis','pricing','symbol','windows']:
        A.check('same original account contract '+key,req[key]==origin['request_identity'][key])
    A.check('request identity receipt',req['content_sha256']==record['request_content_sha256'])
    A.check('runtime binding receipt',account['runtime_binding_hash']==req['runtime_binding_hash']==record['runtime_binding_hash'])
    A.check('actual candidate',account['runs'][0]['candidate_id']==record['candidate'].split('-')[-1])
    A.check('input binding exact',req['input_bindings']==binding['input_bindings'])
    old=A.read(ROOT/'research/S014/materials/20261019_2025_action_method_review/method/source_bindings.json')
    for key in ['execution_requests','execution_prepared','execution_identities','execution_fingerprint']:
        A.check('original authenticated input '+key,binding[key]==old['original_'+key])
    A.check('account data identity',req['data_identity']==binding['execution_fingerprint']==origin['request_identity']['data_identity'])
    plan,oldplan=req['input_bindings']['full']['plan'],origin['request_identity']['input_bindings']['full']['plan']
    A.check('causal input schema',plan.keys()==oldplan.keys())
    for key in plan:
        if key!='strategy':
            A.check('same causal clock/request '+key,plan[key]==oldplan[key])
    A.check('new source-bound strategy',plan['strategy']['reference_id']==record['candidate'] and plan['strategy']['runtime_sha256']==record['runtime_sha256'] and plan['strategy']['release_hash']==account['strategy_identity']==req['strategy_identity'] and account['strategy_identity']!=origin['strategy_identity'])
    return binding,{'payload_sha256':record['payload_sha256'],'runtime_sha256':record['runtime_sha256'],
                    'strategy_identity':account['strategy_identity'],'implementation_sha256':record['runtime_implementation_sha256'],
                    'source_sha256':SOURCE_SHA,'binding_ref':record['binding_ref']}

def fetch_execution(binding,pricing):
    sys.path.append(str(ROOT/'research/S014/experiments/EX017_20261017/src'))
    from pinned_inputs import get_context
    ref=binding['execution_prepared']
    prepared=PreparedDataRef(UUID(ref['space_id']),UUID(ref['preparation_id']),ref['manifest_sha256'])
    ctx=get_context()
    frames={}
    for key in ['execution_daily','adjusted_daily','price_limits','trading_status']:
        q=binding['execution_requests'][key]
        request=DataRequest(Dataset(q['dataset']),q['symbol'],q['start'],q['end'],q['required_cutoff'],q['frequency'])
        result=ctx.data.fetch(request,prepared=prepared)
        A.check('existing prepared input ready and exact '+key,result.ready and result.identity.content_sha256==binding['execution_identities'][key])
        frames[key]=result.dataframe.copy(deep=True)
    rename={'Date':'dt','Open':'open','High':'high','Low':'low','Close':'close','Volume':'vol'}
    raw,adj=[frames[key].rename(columns=rename) for key in ['execution_daily','adjusted_daily']]
    execution=ExecutionPricing.from_dict(pricing).apply(raw.copy(),raw_daily=raw,adjusted_daily=adj).rename(columns={v:k for k,v in rename.items()})
    frames['projected_execution']=execution
    return {key:frame.set_index(pd.to_datetime(frame.Date)) for key,frame in frames.items()}

def execution_constraints(account,frames):
    ledgers=account['runs'][0]['ledgers']
    fills={f['order_id']:f for f in ledgers['fills']['data']}
    for row in ledgers['account_daily']['data']:
        stamp=pd.Timestamp(A.day(row['date']))
        A.number('actual ledger projected close',row['close'],frames['projected_execution'].loc[stamp,'Close'],True)
    for order in ledgers['orders']['data']:
        stamp=pd.Timestamp(A.day(order['execution_date']))
        actual=fills.get(order['order_id'])
        state=frames['trading_status'].loc[stamp,'Status']
        if state=='SUSPENDED':
            A.check('suspended actual order unfilled',actual is None and order['status']!='FILLED')
            continue
        A.check('admitted trading status',state=='TRADING')
        quote=frames['projected_execution'].loc[stamp]
        bounds=frames['price_limits'].loc[stamp]
        scale=float(quote.Close/frames['execution_daily'].loc[stamp,'Close'])
        rule=SessionPriceLimits(stamp.date(),float(bounds.DownLimit*scale),float(bounds.UpLimit*scale),float(.01*scale))
        spec=OrderSpec('BUY','LIMIT',order['quantity'],order['limit_price']) if order['side']=='BUY' else OrderSpec('SELL','MARKET',order['quantity'])
        result=resolve_fill(spec,session_open=float(quote.Open),session_time=datetime.combine(stamp.date(),time(9,30)),intraday_touches=(),daily_quote=DailyQuote(float(quote.Low),float(quote.High)),session_limits=rule)
        A.check('original public fill availability',bool(result.filled)==bool(actual))
        if actual:
            A.number('actual constrained execution price',actual['price'],result.price,True)

def state_lifecycle(account,origin,parameters):
    ledgers=account['runs'][0]['ledgers']
    rows=ledgers['decisions']['data']
    days={A.day(r['date']):r for r in ledgers['account_daily']['data']}
    fills={A.day(f['fill_time']):f for f in ledgers['fills']['data']}
    old={A.day(r['signal_date']):r for r in origin['runs'][0]['ledgers']['decisions']['data']}
    anchor=account['request_identity']['pricing']['anchor_factor']
    entry_price=peak=None
    protected=False
    previous=None
    by_year=defaultdict(Counter)
    cycles=defaultdict(lambda:defaultdict(set))
    events=[]
    for row in rows:
        D=A.day(row['signal_date'])
        held=bool(row['held_at_close'])
        fill=fills.get(D)
        bought=bool(fill and fill['side']=='BUY')
        sold=bool(fill and fill['side']=='SELL')
        if bought:
            entry_price=fill['price']*anchor
            peak=None
            protected=False
        if sold:
            entry_price=peak=None
            protected=False
        # This uses the actual account snapshot at D, independently of shadow100 quantities.
        actual_held=bool(D in days and days[D]['quantity']>0)
        A.check('runtime held equals actual funded D inventory',held==actual_held)
        A.check('runtime BUY flag equals actual funded D BUY',bool(row['buy_filled_today'])==bought)
        A.check('runtime SELL flag equals actual funded D SELL',bool(row['sell_filled_today'])==sold)
        for key in ['ready','support_ok','support_floor','support_break','warmup_sessions']:
            A.check('original market-only state '+key,row[key]==old[D][key])
        inherited=bool(held and previous and previous['exit_pending'] and not sold)
        deadline=bool(held and row['warmup_sessions']>=row['deadline_index'])
        eligible=held and not inherited and not deadline
        A.check('causal inherited pending',bool(row['pending_inherited'])==inherited)
        A.check('mandatory original deadline',bool(row['deadline_exit'])==deadline)
        A.check('discretionary current funded domain',bool(row['profit_exit_eligible'])==eligible)
        if held:
            close=days[D]['close']*anchor
            peak=close if bought else max(peak,close)
            A.number('runtime actual entry price projection',row['entry_fill_price'],entry_price,True)
            A.number('actual Close-only tracked peak',row['peak_close'],peak,True)
            A.number('actual gross price giveback',row['giveback_price'],peak-close,True)
            A.number('fee-adjusted D mark profit',row['net_profit'],close*.999/(entry_price*1.001)-1)
            A.number('peak net gain runtime price units',row['peak_net_gain_price'],peak*.999-entry_price*1.001,True)
            A.check('actual entry D giveback zero',not bought or row['giveback_price']==0)
            shock=bool(eligible and row['shock_known'] and row['net_profit']>0 and row['z5']>2)
            giveback=bool(eligible and row['atr_positive'] and row['peak_net_gain_price']>=2*row['atr20_prior'] and row['giveback_price']>=row['atr20_prior'])
            selected=(parameters['exit_rule']=='SHOCK_PROFIT' and shock) or (parameters['exit_rule']=='PROFIT_GIVEBACK' and giveback)
            grace=bool(eligible and bought and row['support_break'])
            trend=bool(grace and row['ma_known'] and row['atr_positive'] and close>=row['ma20_prior'] and row['ma20_prior']>row['ma20_prior_lag5'] and row['breach_atr']<=1)
            if parameters['hold_rule']=='TREND_CYCLE' and trend:
                protected=True
            protection=(parameters['hold_rule']=='ENTRY_GRACE' and grace) or (parameters['hold_rule']=='TREND_CYCLE' and protected)
            suppressed=bool(eligible and row['support_break'] and protection and not selected)
            ordinary=bool(eligible and row['support_break'] and not protection)
            expected={'shock_condition':shock,'giveback_condition':giveback,'selected_profit_exit':selected,
                      'profit_exit_added_vs_base_support':selected and not row['support_break'],
                      'profit_exit_added_vs_selected_hold':selected and not ordinary,'profit_support_overlap':selected and row['support_break'],
                      'entry_grace_eligible':grace,'entry_grace_applied':parameters['hold_rule']=='ENTRY_GRACE' and grace and not selected,
                      'trend_cycle_eligible':trend,'trend_cycle_activated':parameters['hold_rule']=='TREND_CYCLE' and trend,
                      'trend_cycle_active':protected,'support_protection_applied':suppressed,'support_exit_suppressed':suppressed,
                      'original_support_exit':eligible and row['support_break'],'ordinary_support_exit':ordinary,'peak_known':True}
            for key,value in expected.items():
                A.check('actual funded state rule '+key,bool(row[key])==bool(value))
            A.check('actual state exit priority',bool(row['exit_pending'])==bool(inherited or deadline or selected or ordinary))
            A.check('actual holding age',row['holding_age']==row['warmup_sessions']-row['entry_index'])
        else:
            A.check('no phantom inventory peak/entry/protection',row['entry_fill_price'] is None and row['peak_close'] is None and not row['peak_known'] and not row['trend_cycle_active'])
        if '2020-01-01'<=D<='2025-12-31':
            y=D[:4]
            by_year[y]['D_rows']+=1
            by_year[y]['actual_held_D']+=int(held)
            by_year[y]['original_held_D']+=int(bool(old[D]['held_at_close']))
            by_year[y]['induced_held_when_R_flat_D']+=int(held and not old[D]['held_at_close'])
            if held:
                cycles[y]['actual_cycles'].add(row['entry_index'])
            for key in FIELDS:
                by_year[y][key]+=int(bool(row[key]))
                if row[key] and held:
                    cycles[y][key].add(row['entry_index'])
            if any(row[key] for key in TRIGGERS):
                events.append({'D':D,'E':A.day(row['valid_session']),'entry_index':row['entry_index'],'age':row['holding_age'],
                               'original_R_held':bool(old[D]['held_at_close']),'source_action':row['action'],
                               **{key:row[key] for key in FIELDS},'net_profit':row['net_profit'],'atr20_prior':row['atr20_prior'],
                               'z5':row['z5'],'peak_close':row['peak_close'],'giveback_price':row['giveback_price']})
        previous=row
    return {'annual_D_counts':dict(by_year),'annual_distinct_cycles':{y:{k:len(v) for k,v in part.items()} for y,part in cycles.items()},
            'trigger_events':events,'runtime_vs_actual_funded_holding_alignment':'EXACT_ALL1642_D','shadow_quantity_not_assumed_affordable':True}

def annual_and_summary(account,origin):
    run=account['runs'][0]
    daily=run['ledgers']['account_daily']['data']
    years,bh,old=[A.yearly(rows) for rows in [daily,run['buyhold']['account_daily']['data'],origin['runs'][0]['ledgers']['account_daily']['data']]]
    annual=[]
    for y,row in years.items():
        target=1.5*bh[y]['return'] if bh[y]['return']>0 else 0.
        annual.append({'year':y,**{k:v for k,v in row.items() if k!='sessions'},'buyhold_return':bh[y]['return'],
                       'buyhold_drawdown':bh[y]['max_drawdown'],'required_return':target,
                       'return_pass':row['return']>=target if bh[y]['return']>0 else row['return']>0,
                       'drawdown_pass':row['max_drawdown']<bh[y]['max_drawdown'],
                       'return_difference_vs_original':row['return']-old[y]['return'],'sessions':row['sessions'],'technical_only':y==2026})
    days={A.day(r['date']):r for r in daily}
    trades=run['ledgers']['trades']['data']
    fullclosed=sum(t['status']=='CLOSED' for t in trades)
    completeclosed=sum(t['status']=='CLOSED' and '2020-01-01'<=A.day(t['exit_date'])<='2025-12-31' for t in trades)
    completesessions=sum('2020-01-01'<=A.day(r['date'])<='2025-12-31' for r in daily)
    summary={'continuous2020_2025_return_from100000':days['2025-12-31']['equity']/100000-1,
             'terminal2025_equity':days['2025-12-31']['equity'],'own2025_opening':years[2025]['opening_equity'],
             'development_without2025_end2024_equity':days['2024-12-31']['equity'],
             'development_without2025_continuous_return_from100000':days['2024-12-31']['equity']/100000-1,
             'nannual_return_pass_2020_25':sum(r['return_pass'] for r in annual if r['year']<=2025),
             'nannual_drawdown_pass_2020_25':sum(r['drawdown_pass'] for r in annual if r['year']<=2025),
             'nannual_return_pass_original_full_contract':sum(r['return_pass'] for r in annual),
             'nannual_drawdown_pass_original_full_contract':sum(r['drawdown_pass'] for r in annual),
             'closed_trades_full_contract':fullclosed,'sessions_full_contract':len(daily),'frequency_full_contract':60*fullclosed/len(daily),
             'original_frequency_pass':60*fullclosed/len(daily)>=3,'closed_trades_completeyears':completeclosed,
             'sessions_completeyears':completesessions,'frequency_completeyears_diagnostic':60*completeclosed/completesessions,
             'without2025_role':'Shared-seen2020-24 development reaggregation; no reset, refit or heldout claim.'}
    return annual,summary

def econ_hashes(account,origin):
    run=account['runs'][0]
    projection={}
    for name in ['account_daily','orders','fills','trades']:
        old=origin['runs'][0]['ledgers'][name]['data']
        keys=set(old[0])-A.ID_KEYS
        projection[name]=[{k:r[k] for k in sorted(keys)} for r in run['ledgers'][name]['data']]
    return {'execution_economics_sha256':hash_value(projection),'daily_wealth_sha256':hash_value(projection['account_daily'])}

def audit_one(index):
    destination=OUT/f'account_{index:03d}_independent_review.json'
    A.check('refuse overwrite independent account audit',not destination.exists())
    record=A.read(BASE/f'others/accounts/run-{index:03d}.json')
    A.check('actual account status SUCCEEDED',record['status']=='SUCCEEDED')
    origin,originref=original()
    account=A.published(record['evidence'])
    A.check('result receipt exact',account['result_hash']==record['result_hash'])
    A.check('one FULL original account run',len(account['runs'])==1 and account['execution_mode']=='FULL')
    binding,immutable=identity(record,account,origin)
    A.equal_baseline(origin,account)
    accounting=A.audit_daily(account)
    if index==0:
        A.noop_equivalence(origin,account)
    else:
        control=A.read(OUT/'account_000_independent_review.json')
        A.check('new source NOOP independently passed',control['status']=='PASS' and control['source_sha256']==SOURCE_SHA)
    lifecycle=state_lifecycle(account,origin,record['parameters'])
    frames=fetch_execution(binding,account['request_identity']['pricing'])
    execution_constraints(account,frames)
    annual,summary=annual_and_summary(account,origin)
    result={'status':'PASS','index':index,'policy_id':record['mode'],'parameters':record['parameters'],'candidate':record['candidate'],
            'account_ref':record['evidence'],'result_hash':record['result_hash'],'original_ref':originref,'source_sha256':SOURCE_SHA,
            'immutable_identity':immutable,'accounting':accounting,'lifecycle':lifecycle,'original_annual_goal_audit':annual,'summary':summary,
            'terminal2025_asof':A.terminal_state(account),'economic_path_hashes':econ_hashes(account,origin),
            'source_NOOP_exact_original':index==0,'checks':sum(A.COUNTS.values()),'check_counts':dict(A.COUNTS),'maximum_arithmetic_error':A.ERRORS,
            'derived_currency_absolute_tolerance':A.MONEY_TOLERANCE,'derived_ratio_absolute_tolerance':A.RATIO_TOLERANCE,
            'source_NOOP_and_unchanged_economic_fields_tolerance':0,'automatic_tolerance_expansion':False,
            'source_lock_sha256':sha256((BASE/'protocols/execution_lock.json').read_bytes()).hexdigest(),
            'audit_implementation_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'ledger_helper_sha256':sha256(HELPER.read_bytes()).hexdigest(),
            'new_fits':0,'new_strategy_replays':0,'new_account_dispatches_by_auditor':0,'new_market_supplier_calls':0,'new_preparations':0,
            'limits':['Full2026 annual fields are original-contract technical audit only.','Nine configurations are seen-history structural contrasts, not nine independent validations.',
                      'Execution constraint check reapplies original public rules, not independent market authenticity validation.']}
    write(destination,result)
    print(json.dumps({'index':index,'status':'PASS','checks':result['checks'],'review_sha256':sha256(destination.read_bytes()).hexdigest()}))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index',type=int,required=True)
    args=parser.parse_args()
    try:
        audit_one(args.index)
    except Exception as exc:
        failure=OUT/f'account_{args.index:03d}_independent_failure.json'
        if not failure.exists():
            write(failure,{'status':'FAIL','index':args.index,'exception':repr(exc),'check_counts':dict(A.COUNTS),'maximum_arithmetic_error':A.ERRORS,
                           'no_tolerance_expansion':True,'source_sha256':SOURCE_SHA,'audit_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest()})
        raise

if __name__=='__main__':
    main()
