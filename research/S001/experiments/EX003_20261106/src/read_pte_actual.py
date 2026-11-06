"""Bounded read-only production ledger extraction; no PTE API or credentials."""
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from hashlib import sha256
from collections import Counter
import csv
import json
import re
import sqlite3

ROOT = Path.cwd()
OUT = ROOT/'.tmp/s001-v4-correction'
PROD = Path('D:/CZSC-PTE')
DB = PROD/'shared/state/runtime.db'
OUT.mkdir(parents=True,exist_ok=True)
ZONE = ZoneInfo('Asia/Shanghai')
ACCOUNTS = ('s001-v1','s001-v2')

def fingerprint(path):
    content = path.read_bytes()
    stat = path.stat()
    return {'path':str(path),'bytes':len(content),'sha256':sha256(content).hexdigest(),
            'mtime_ns':stat.st_mtime_ns}

def tag(value):
    return None if value is None else sha256(str(value).encode()).hexdigest()[:16]

def local(value):
    return datetime.fromisoformat(value).astimezone(ZONE).isoformat() if value else None

def safe_text(value):
    if not isinstance(value,str):
        return value
    value = re.sub(r'PTE-[A-F0-9]+',lambda m:'intent#'+tag(m.group()),value)
    value = re.sub(r'(?i)(token|password|api_key|secret)\s*[=:]\s*[^,;\s]+',r'\1=[REDACTED]',value)
    return value[:700]

artifacts = []
def write_csv(name,rows):
    path = OUT/name
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('w',encoding='utf-8',newline='') as file:
        writer = csv.DictWriter(file,fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    artifacts.append({'path':name,'rows':len(rows),'sha256':sha256(path.read_bytes()).hexdigest()})

started = datetime.now(timezone.utc).isoformat()
before = [fingerprint(path) for path in (DB,Path(str(DB)+'-wal')) if path.exists()]
active_path = PROD/'shared/config/active-release.json'
active = json.loads(active_path.read_text(encoding='utf-8'))
prices = {}
price_sources = []
for kind,name in (('HFQ','588080_daily_2026.csv'),('RAW','588080_execution_daily_2026.csv')):
    path = PROD/'shared/data'/name
    with path.open(encoding='utf-8-sig',newline='') as file:
        rows = list(csv.DictReader(file))
    prices[kind] = {row['date'][:10]:row['close'] for row in rows}
    price_sources.append({**fingerprint(path),'role':kind,'first':min(prices[kind]),'last':max(prices[kind])})

connection = sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True)
connection.row_factory = sqlite3.Row
connection.execute('PRAGMA query_only=ON')
assert connection.execute('PRAGMA query_only').fetchone()[0] == 1
connection.execute('BEGIN')
version = connection.execute('PRAGMA data_version').fetchone()[0]
summaries = {}
queries = []

def query(sql,parameters):
    queries.append({'sql':sql,'parameters':list(parameters)})
    return [dict(row) for row in connection.execute(sql,parameters)]

try:
    for account in ACCOUNTS:
        rows = query('SELECT account_id,strategy_id,strategy_version,initial_cash,cash,frozen_cash,total_assets,quantity,average_cost,realized_pnl,observation_start,last_settlement_session,created_at,updated_at,run_state,health,release_hash,selection_data_cutoff FROM virtual_accounts WHERE account_id=?',(account,))
        assert len(rows)==1
        current = rows[0]
        frozen_path = PROD/'releases'/active['release_id']/'strategies/S001/versions'/(current['strategy_version']+'.json')
        frozen = json.loads(frozen_path.read_text(encoding='utf-8'))
        assert frozen['release_hash']==current['release_hash']
        decisions = query('SELECT decision_id,signal_date,valid_session,generated_at,legacy_status,superseded_by,payload FROM decisions WHERE account_id=? ORDER BY signal_date,generated_at,decision_id',(account,))
        decoded = []
        for row in decisions:
            data = json.loads(row.pop('payload'))
            decoded.append({'decision_ref':tag(row['decision_id']),'signal_date':row['signal_date'],
                'valid_session':row['valid_session'],'generated_at_utc':row['generated_at'],
                'generated_at_shanghai':local(row['generated_at']),'stored_status':row['legacy_status'],
                'superseded_by_ref':tag(row['superseded_by']),
                **{key:data.get(key) for key in ('action','actual_quantity','target_quantity','cycle_target_quantity','delta_quantity','fee_rate','signal_reference_price','execution_reference_price','data_cutoff')},
                'release_hash':data.get('strategy',{}).get('release_hash')})
        fills = query('SELECT fill_id,order_id,decision_id,side,quantity,price,fee,realized_pnl,occurred_at FROM fills WHERE account_id=? ORDER BY occurred_at,fill_id',(account,))
        for row in fills:
            for key in ('fill_id','order_id','decision_id'):
                row[key.replace('_id','_ref')] = tag(row.pop(key))
            row['occurred_at_shanghai'] = local(row['occurred_at'])
            row['gross_amount'] = str(Decimal(row['price'])*row['quantity'])
        ledger = query('SELECT entry_type,order_id,fill_id,cash_delta,frozen_cash_delta,quantity_delta,fee,balance_after,quantity_after,occurred_at FROM account_ledger WHERE account_id=? ORDER BY occurred_at,ledger_entry_id',(account,))
        for row in ledger:
            row['order_ref']=tag(row.pop('order_id'));row['fill_ref']=tag(row.pop('fill_id'))
            row['occurred_at_shanghai']=local(row['occurred_at'])
        orders = query('SELECT channel_order_id,intent_id,decision_id,cumulative_filled_quantity,created_at,updated_at,payload FROM orders WHERE account_id=? ORDER BY created_at,channel_order_id',(account,))
        clean_orders=[]
        for row in orders:
            payload=json.loads(row['payload'])
            clean_orders.append({'order_ref':tag(row['channel_order_id']),'intent_ref':tag(row['intent_id']),
                'decision_ref':tag(row['decision_id']),'created_at':row['created_at'],'updated_at':row['updated_at'],
                **{key:payload.get(key) for key in ('side','quantity','limit_price','order_type','status','cumulative_filled_quantity','average_fill_price')},
                'last_error':safe_text(payload.get('last_error'))})
        intents=query('SELECT intent_id,decision_id,order_sequence,side,quantity,limit_price,valid_session,status,attention_required,attention_reason,resolved_at,resolution_note,created_at,updated_at,payload FROM intents WHERE account_id=? ORDER BY created_at,intent_id',(account,))
        clean_intents=[]
        for row in intents:
            payload=json.loads(row.pop('payload'))
            row['intent_ref']=tag(row.pop('intent_id'));row['decision_ref']=tag(row.pop('decision_id'))
            row['fee_rate']=payload.get('fee_rate');row['order_type']=payload.get('order_type')
            row['resolution_note']=safe_text(row['resolution_note'])
            clean_intents.append(row)
        snapshots=query('SELECT session,created_at,payload FROM account_snapshots WHERE account_id=? ORDER BY session',(account,))
        daily=[];peak=Decimal(current['initial_cash']);max_dd=Decimal(0)
        for row in snapshots:
            payload=json.loads(row['payload']);equity=Decimal(payload['total_assets'])
            peak=max(peak,equity);dd=equity/peak-1;max_dd=min(max_dd,dd)
            day=row['session'];close=Decimal(payload['close'])
            matches=[kind for kind,values in prices.items() if day in values and Decimal(values[day])==close]
            daily.append({'session':day,'recorded_at_utc':row['created_at'],
                **{key:payload.get(key) for key in ('cash','frozen_cash','quantity','close','market_value','total_assets')},
                'nav':str(equity/Decimal(current['initial_cash'])),'drawdown_recorded':str(dd),
                'legacy_hfq_close':prices['HFQ'].get(day),'legacy_raw_close':prices['RAW'].get(day),
                'close_matches_legacy_cache':'|'.join(matches) if matches else 'OUTSIDE_CACHE_OR_DIFFERENT',
                'decision_ref':tag(payload.get('decision_id'))})
        events=query("SELECT id,created_at,occurred_at,event_type,severity,outcome,payload FROM events WHERE account_id=? OR (json_valid(payload) AND json_extract(payload,'$.account_id')=?) OR (event_type IN ('SCHEDULER_OPERATION_FAILED','SCHEDULER_OPERATION_RECOVERED') AND payload LIKE ?) ORDER BY id",(account,account,'%'+account+'%'))
        allowed=('error','error_type','original_error','reason','intent_status','adjustment','modeled_fee','actual_fee','fill_count','treatment','operation','previous_version','target_version','previous_release_hash','migration','side','quantity')
        relevant=[]
        for row in events:
            data=json.loads(row.pop('payload'))
            if (row['severity'] in ('ERROR','WARNING') or row['event_type'] in ('BROKER_FEE_RECONCILED','ACCOUNT_PAUSED','ACCOUNT_RESUMED','ACCOUNT_STRATEGY_BOUND','SCHEDULER_OPERATION_RECOVERED')):
                relevant.append({**row,'occurred_at_shanghai':local(row['occurred_at'] or row['created_at']),
                    'details':json.dumps({key:safe_text(data[key]) for key in allowed if key in data},ensure_ascii=False,sort_keys=True)})
        for suffix,values in (('decisions',decoded),('fills',fills),('ledger',ledger),('orders',clean_orders),('intents',clean_intents),('daily_snapshots',daily),('exception_events',relevant)):
            write_csv(account+'_'+suffix+'.csv',values)
        fees=sum((Decimal(row['fee']) for row in fills),Decimal(0))
        reconciled=sum((Decimal(row['fee']) for row in ledger if row['entry_type']=='BROKER_FEE_RECONCILIATION'),Decimal(0))
        cash=Decimal(current['initial_cash'])+sum((Decimal(row['cash_delta']) for row in ledger),Decimal(0))
        frozen_cash=sum((Decimal(row['frozen_cash_delta']) for row in ledger),Decimal(0))
        quantity=sum(row['quantity_delta'] for row in ledger)
        assert cash==Decimal(current['cash']) and frozen_cash==Decimal(current['frozen_cash']) and quantity==current['quantity']
        summaries[account]={'current_account':current,'created_at_shanghai':local(current['created_at']),
            'production_frozen_metadata':{key:frozen.get(key) for key in ('release_id','release_hash','selection_data_cutoff','forward_start','source_candidate')},
            'frozen_metadata_file':fingerprint(frozen_path),
            'boundaries':{'snapshot_first':daily[0]['session'],'snapshot_last':daily[-1]['session'],
                'first_signal':min(r['signal_date'] for r in decoded),'last_signal':max(r['signal_date'] for r in decoded),
                'first_valid_session':min(r['valid_session'] for r in decoded),'last_valid_session':max(r['valid_session'] for r in decoded),
                'first_decision_generated_at':min(r['generated_at_utc'] for r in decoded),
                'first_fill_shanghai':fills[0]['occurred_at_shanghai'],'last_fill_shanghai':fills[-1]['occurred_at_shanghai']},
            'counts':{'daily_snapshots':len(daily),'decisions_including_historical_invalidated':len(decoded),'unique_signal_dates':len({r['signal_date'] for r in decoded}),'fills':len(fills),'orders':len(clean_orders),'intents':len(clean_intents),'ledger':len(ledger)},
            'modeled_fee_rates':sorted({str(r['fee_rate']) for r in decoded if r['fee_rate'] is not None}),
            'actual_fill_fees':str(fees),'broker_fee_reconciliation':str(reconciled),'total_recorded_costs':str(fees+reconciled),
            'total_return_to_last_settlement':str(Decimal(daily[-1]['total_assets'])/Decimal(current['initial_cash'])-1),
            'max_drawdown_as_recorded_not_uniform_price_basis':str(max_dd),
            'ledger_reconciliation':'EXACT_CURRENT_CASH_FROZEN_QUANTITY',
            'event_type_counts':dict(Counter(row['event_type'] for row in events)),
            'decision_release_hashes':dict(Counter(r['release_hash'] for r in decoded)),
            'intent_terminal_states':dict(Counter(r['status'] for r in clean_intents))}
finally:
    connection.rollback()
    connection.close()

after=[fingerprint(path) for path in (DB,Path(str(DB)+'-wal')) if path.exists()]
summary={'schema_version':1,'scope':'RSCH production read-only evidence extraction; no strategy, experiment, account run or production mutation',
    'extracted_started_utc':started,'extracted_finished_utc':datetime.now(timezone.utc).isoformat(),
    'database':{'uri_mode':'ro','query_only':True,'single_read_transaction':True,'data_version_at_snapshot':version,
        'physical_files_before':before,'physical_files_after':after,
        'note':'Physical file hashes describe observed files, not an SQLite logical-snapshot hash; CSV hashes identify the selected read-transaction outputs.'},
    'production_active_release':active,'active_release_file':fingerprint(active_path),'price_crosscheck_files':price_sources,
    'queries':queries,'accounts':summaries,'artifacts':artifacts,
    'recommended_comparison_window':{'timezone':'Asia/Shanghai','performance_baseline_date':'2026-09-03','initial_cash':'100000.0000','initial_quantity':0,
        'first_decision_signal_date':'2026-09-03','first_executable_session':'2026-09-04','last_completed_valuation_session':'2026-11-05',
        'exclude_unsettled_valid_session':'2026-11-06','note':'Use the actual recorded observation baseline, not frozen forward_start or first fill; permitting a Sep3 open trade using Sep2 signals introduces an additional startup difference.'},
    'interpretation_limits':[
        'S001-v2 first exit was rejected for an out-of-limit price, operator confirmed absent broker order, then a replacement sell filled on Sep11 14:23 Shanghai. This execution-path effect is separate from weekly-signal logic.',
        'S001-v2 broker-fee reconciliation deducted 104.3977 on Sep11; fill-level modeled fees alone do not explain final cash.',
        'S001-v2 holding snapshots Sep8-Sep10 use HFQ closes matching production adjusted cache, while Sep17 onward matches RAW where crosscheck data exists. As-recorded drawdown is not a uniform-RAW reconstruction.',
        'Both accounts had historical release rebindings, pauses and data/decision failures. An ideal replay versus actual PTE difference cannot all be attributed to weekly construction.',
        'Stored decisions include invalidated and superseded history. Use actual fills and ledger for executed performance, and explicit decision status/release lineage when comparing signals.',
        'This extraction does not query credentials or broker services. Broker/order/decision identifiers in CSVs are pseudonymized; account ids are retained only as strategy/version labels.']}
target=OUT/'pte_actual.json'
target.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'pte_actual.sha256').write_text(sha256(target.read_bytes()).hexdigest()+'  pte_actual.json\n',encoding='ascii')
print(json.dumps({'path':str(target),'sha256':sha256(target.read_bytes()).hexdigest(),
                 'accounts':{key:{'fills':value['counts']['fills'],'return':value['total_return_to_last_settlement'],'costs':value['total_recorded_costs']} for key,value in summaries.items()}},ensure_ascii=False))
