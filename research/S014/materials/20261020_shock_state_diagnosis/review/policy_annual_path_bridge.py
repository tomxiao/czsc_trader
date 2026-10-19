"""Actual account annual-mark attribution; Decimal telescoping, not causal PnL."""
import csv
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
BASE = Path('research/S014/materials/20261020_shock_state_diagnosis')
EX = Path('research/S014/experiments/EX050_20261020')
def digest(path):
    return sha256((ROOT / path).read_bytes()).hexdigest()

def dec(value):
    return Decimal(str(value))

yearly_path = BASE / 'accounting/full_policy_yearly_summary.csv'
assert digest(yearly_path) == '9cd2fa7483f68283645cf1cb31660c7a99aec74c74c36c7798aed4352db46f99'
with (ROOT / yearly_path).open(encoding='utf-8', newline='') as handle:
    official = {(r['diagID'], int(r['year'])): r for r in csv.DictReader(handle)}
outputs, annual, pause_rows, refs, bindings = [], [], [], {}, {yearly_path.as_posix(): digest(yearly_path)}
for index in range(3):
    receipt_path = EX / f'others/accounts/run-{index:03}.json'
    receipt = json.loads((ROOT / receipt_path).read_bytes())
    ref = EvidenceRef.from_dict(receipt['evidence'])
    path = ref.resolve(ROOT)
    assert digest(path.relative_to(ROOT)) == ref.sha256
    refs[str(index)] = ref.to_dict()
    bindings[receipt_path.as_posix()] = digest(receipt_path)
    bindings[path.relative_to(ROOT).as_posix()] = digest(path.relative_to(ROOT))
    account = json.loads(path.read_bytes())
    tables = {k:v['data'] for k,v in account['runs'][0]['ledgers'].items()}
    fills_by_day, cycle = {}, {}
    for fill in tables['fills']:
        fills_by_day.setdefault(fill['fill_time'][:10], []).append(fill)
        cycle.setdefault(fill['cycle_id'], {})[fill['side']] = fill
    groups, year_open, year_close = {}, {}, {}
    active = None
    previous = dec(100000)
    for row in tables['account_daily']:
        day, year = row['date'][:10], int(row['date'][:4])
        pnl = dec(row['equity']) - previous
        year_open.setdefault(year, previous)
        year_close[year] = dec(row['equity'])
        fills = fills_by_day.get(day, [])
        assert len(fills) <= 1
        scope_cycle = active
        if fills and fills[0]['side'] == 'BUY':
            assert active is None
            active = fills[0]['cycle_id']
            scope_cycle = active
        elif fills:
            assert active == fills[0]['cycle_id']
            scope_cycle = active
            active = None
        if year in (2025, 2026):
            key = (year, scope_cycle or 'FLAT')
            groups[key] = groups.get(key, Decimal(0)) + pnl
        previous = dec(row['equity'])
    cid = f'S014-C{9500+index}'
    for year in (2025, 2026):
        total = sum((value for (y,_),value in groups.items() if y == year), Decimal(0))
        assert total == year_close[year] - year_open[year]
        record = official[(cid, year)]
        assert float(record['opening_equity']) == float(year_open[year])
        assert float(record['closing_equity']) == float(year_close[year])
        annual.append({'diagID': cid, 'year': year, 'own_year_opening': float(year_open[year]),
                       'closing': float(year_close[year]), 'marked_pnl': float(total),
                       'sum_contribution': float(total / year_open[year]),
                       'official_return': float(record['return']),
                       'float_representation_residual': float(record['return']) - float(total / year_open[year]),
                       'decimal_telescoping_exact': True})
        for (scope_year, cycle_id), value in groups.items():
            if scope_year != year:
                continue
            fs = cycle.get(cycle_id, {})
            buy, sell = fs.get('BUY'), fs.get('SELL')
            completed = ((dec(sell['price'])*dec(sell['quantity'])-dec(sell['fees']))
                         - (dec(buy['price'])*dec(buy['quantity'])+dec(buy['fees']))) if buy and sell else None
            outputs.append({'diagID': cid, 'year': year, 'cycle_id': cycle_id,
                            'actual_entry_E': buy['fill_time'][:10] if buy else None,
                            'actual_exit_E': sell['fill_time'][:10] if sell else None,
                            'actual_entry_price': buy['price'] if buy else None,
                            'actual_exit_price': sell['price'] if sell else None,
                            'actual_quantity': buy['quantity'] if buy else None,
                            'closed_cycle_net_whole_scope_provenance': float(completed) if completed is not None else None,
                            'annual_marked_pnl': float(value), 'own_year_opening': float(year_open[year]),
                            'annual_marked_contribution': float(value/year_open[year]),
                            'annual_marked_pnl_decimal': str(value)})
    for row in tables['decisions']:
        if row['signal_date'].startswith('2025') and row['pause_slot_consumed']:
            source_index = row['warmup_sessions']
            source_dates = {item['warmup_sessions']: item['signal_date'][:10] for item in tables['decisions']}
            pause_rows.append({'diagID': cid, 'D': row['signal_date'][:10], 'planned_E': row['valid_session'][:10],
                               'source_index': source_index, 'reservation_until': row['planned_slot_until'],
                               'eligible_again_D': source_dates.get(row['planned_slot_until']),
                               'last_completed_sign': row['last_completed_sign']})

csv_path = BASE / 'review/policy_actual_2025_2026_cycle_bridge.csv'
with (ROOT / csv_path).open('x', encoding='utf-8', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=list(outputs[0]))
    writer.writeheader()
    writer.writerows(outputs)
bindings[csv_path.as_posix()] = digest(csv_path)
bindings[Path(__file__).resolve().relative_to(ROOT).as_posix()] = digest(Path(__file__).resolve().relative_to(ROOT))
matched = {}
for year in (2025,2026):
    for row in outputs:
        if row['year'] == year and row['diagID'] in ('S014-C9500','S014-C9502'):
            matched.setdefault((year,row['actual_entry_E']),{})[row['diagID']] = row
differences = []
for (year, entry), rows in matched.items():
    before = rows.get('S014-C9500',{}).get('annual_marked_contribution',0.)
    after = rows.get('S014-C9502',{}).get('annual_marked_contribution',0.)
    differences.append({'year':year,'entry_E':entry,'control_contribution':before,
                        'AGE_contribution':after,'AGE_minus_control_contribution':after-before})
result = {'status':'PASS_ACTUAL_YEAR_MARK_ATTRIBUTION','blocking_findings':[],'reviewer':'B',
          'reviewed_hashes':bindings,'account_refs':refs,'annual_exact_decimal_bridges':annual,
          'AGE_vs_control_by_original_entry_date_description':differences,'actual_2025_pause_slots':pause_rows,
          'method':'Each original daily equity change is assigned to the actual funded cycle carried into or entered/sold on that E. Annual scope includes marks and fees on those dates, with own year-opening equity denominator. Decimal(str(saved-equity)) differences telescope exactly; float representation residual to published return is retained, not forced to zero or used as a new tolerance.',
          'limits':'Matches by same entry date only for descriptive comparisons, not equal-Q or equal-funding causal experiments. Cross-year cycle annual marks differ from whole closed-trade net PnL. Missing cycle contribution is zero only for that actual account annual ledger; it is not an unfilled-order outcome or a counterfactual profitable trade.',
          'new_funded_accounts':0,'new_market_calls':0,'new_prepared_fetches':0,'new_fits':0}
out = ROOT / BASE / 'review/policy_actual_path_bridge_review.json'
with out.open('x',encoding='utf-8',newline='\n') as handle:
    json.dump(result,handle,ensure_ascii=False,indent=2,allow_nan=False)
    handle.write('\n')
print(json.dumps({'path':out.relative_to(ROOT).as_posix(),'sha256':digest(out.relative_to(ROOT)),'csv_rows':len(outputs),
                  'annual':annual,'AGE2025differences':[r for r in differences if r['year']==2025]}))
