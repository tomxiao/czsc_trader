from pathlib import Path
import csv
import json
from hashlib import sha256

BASE = Path('.tmp/s001-v4-correction')
def read(path):
    return json.loads(path.read_text(encoding='utf-8'))
def project(rows, fields):
    return [{k:r[k] for k in fields} for r in rows]
def compare(a,b):
    fields = {
        'account_daily': ('session','cash','quantity','close','equity','receivable'),
        'fills': ('side','quantity','price','fees','interval_start','interval_end'),
        'orders': ('side','quantity','limit_price','order_type','status','reason','valid_start','valid_end'),
        'trades': ('entry_at','exit_at','cost','income','net_pnl','net_return','status'),
    }
    result = {}
    for name,keys in fields.items():
        left,right=project(a[name],keys),project(b[name],keys)
        assert left == right, (name,left,right)
        result[name]={'status':'EXACT','rows':len(left),'fields':keys}
    assert a['metrics']==b['metrics']
    result['metrics']='EXACT'
    return result

actual=read(BASE/'pte_actual.json')
signals=read(BASE/'signals/summary.json')
result={'schema':'s001-completed-week-forward-comparison-v1',
    'observation_window':['2026-09-03','2026-11-05'],
    'execution_window':['2026-09-04','2026-11-05'],
    'initial_cash':100000,'fee_per_side':0.0005,
    'scope':'Retained canonical input counterfactual and separately extracted actual PTE ledger; no production mutation',
    'signal_summary':signals,'versions':{},
    'limitations':actual['interpretation_limits']+[
        'Canonical retained input prefixes do not reproduce every historical provider snapshot.',
        'No inference of all-history equivalence from this observation window.',
        'Actual recorded drawdown is omitted because early v2 daily valuations used adjusted marks.',
        'Model fills use daily BAR_RANGE; actual fills have broker timestamps and prices.',
        'Historical source bindings must be replaced with supported continuous sources before future production deployment.']}
for version in ['v1','v2']:
    payload=read(BASE/f'accounts/{version}-native-account.json')
    native=payload['runs']['candidate']
    complete=read(BASE/f'controls/{version}-complete/account.json')
    partial=read(BASE/f'controls/{version}-partial/account.json')
    p=actual['accounts']['s001-'+version]
    with (BASE/f's001-{version}_fills.csv').open(encoding='utf-8-sig',newline='') as f: fills=list(csv.DictReader(f))
    fill_pairs=[]
    assert len(fills)==len(native['fills'])
    for model,real in zip(native['fills'],fills):
        assert model['side']==real['side'] and model['quantity']==int(real['quantity'])
        assert model['interval_start'][:10]==real['occurred_at_shanghai'][:10]
        fill_pairs.append({'date':model['interval_start'][:10],'side':model['side'],'quantity':model['quantity'],
            'controlled_price':model['price'],'actual_price':float(real['price']),
            'controlled_fee':model['fees'],'actual_fee':float(real['fee']),
            'actual_execution_time':real['occurred_at_shanghai']})
    net=native['account_daily'][-1]['equity']
    actual_net=float(p['current_account']['total_assets'])
    value={'native_identity':payload['evaluation_identity'],
        'complete_control_reference':complete['reference'],'partial_control_reference':partial['reference'],
        'native_vs_old_formula_complete':compare(native,complete['run']),
        'old_formula_partial_vs_complete':compare(partial['run'],complete['run']),
        'controlled_metrics':native['metrics'],'controlled_final_equity':net,
        'actual_final_equity':actual_net,'actual_total_return':float(p['total_return_to_last_settlement']),
        'actual_total_costs':float(p['total_recorded_costs']),
        'actual_minus_controlled_equity':actual_net-net,
        'actual_vs_controlled_fills':fill_pairs,
        'actual_ledger_reconciliation':p['ledger_reconciliation'],
        'conclusion':'No weekly-policy effect in this window; actual difference is execution and recorded-cost difference, not a signal change.'}
    # Exact cash identity isolates execution price and recorded costs, with both accounts flat.
    gross_delta=sum((1 if x['side']=='SELL' else -1)*x['quantity']*(x['actual_price']-x['controlled_price']) for x in fill_pairs)
    fee_delta=value['actual_total_costs']-native['metrics']['fees']
    assert abs(gross_delta-fee_delta-value['actual_minus_controlled_equity'])<1e-7
    value['cash_difference_identity']={'actual_minus_controlled_gross':gross_delta,'actual_minus_controlled_cost':fee_delta}
    result['versions'][version]=value
result['inputs']={str(p.relative_to(BASE)):{'sha256':sha256(p.read_bytes()).hexdigest()} for p in [BASE/'pte_actual.json',BASE/'inputs/input_identity.json',BASE/'signals/summary.json']}
(BASE/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for v,data in result['versions'].items():
    print(v,'PASS',data['controlled_final_equity'],data['actual_final_equity'],data['cash_difference_identity'])
