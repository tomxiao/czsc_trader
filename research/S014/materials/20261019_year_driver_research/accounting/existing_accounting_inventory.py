"""Existing C0056 daily accounting inventory; no new outcome labels or policy replay."""
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import socket

import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir', type=Path, required=True,
                    help='New output directory. Existing files and historical evidence are never overwritten.')
OUT = parser.parse_args().output_dir.resolve()
assert not OUT.exists(), 'Use a new output directory; saved results are immutable'
OUT.mkdir(parents=True)

def block(*args, **kwargs):
    raise RuntimeError('No network calls permitted')

socket.socket.connect = block
socket.create_connection = block

def load(value):
    ref = EvidenceRef.from_dict(value)
    assert ref.experiment.strategy_id == 'S014'
    data = ref.resolve(ROOT).read_bytes()
    assert sha256(data).hexdigest() == ref.sha256
    return data

record = json.loads((ROOT / 'research/S014/experiments/EX023_20261018/others/account_results.json').read_bytes())['records'][0]
account = json.loads(load(record['evidence']))
assert account['result_hash'] == record['result_hash'] and len(account['runs']) == 1
run = account['runs'][0]
publication = json.loads((ROOT / 'research/S014/materials/20261018_c0056_coverage_review/publication.json').read_bytes())
daily_ref = publication['evidence']['daily_reconciliation.csv']
old_daily = pd.read_csv(BytesIO(load(daily_ref)))
old_daily.date = pd.to_datetime(old_daily.date).dt.normalize()
d = pd.DataFrame(run['ledgers']['account_daily']['data'])
d.date = pd.to_datetime(d.date).dt.normalize()
d = d.sort_values('date').reset_index(drop=True)
b = pd.DataFrame(run['buyhold']['account_daily']['data'])
b.date = pd.to_datetime(b.date).dt.normalize()
assert d.date.tolist() == b.date.tolist() == old_daily.date.tolist()
d = d.merge(old_daily, on='date', validate='one_to_one')
d['year'] = d.date.dt.year
d['month'] = d.date.dt.strftime('%Y-%m')
d['previous_equity'] = d.equity.shift(fill_value=100000.)
d['bh_equity'] = b.equity
d['bh_previous_equity'] = b.equity.shift(fill_value=100000.)
d['bh_pnl'] = d.bh_equity - d.bh_previous_equity
assert np.allclose(d.actual_pnl, d.equity - d.previous_equity, rtol=0, atol=1e-6)
fills = pd.DataFrame(run['ledgers']['fills']['data'])
fills['date'] = pd.to_datetime(fills.fill_time).dt.normalize()
by_day = {x.date: x for x in fills.itertuples()}
active = None
cycle = []
for row in d.itertuples():
    fill = by_day.get(row.date)
    if fill is not None and fill.side == 'BUY':
        assert active is None
        active = fill.cycle_id
    cycle.append(active)
    if fill is not None and fill.side == 'SELL':
        assert active == fill.cycle_id
        active = None
d['actual_cycle_id'] = cycle
assert active is None
atoms = ['entry_mark_pnl', 'hold_mark_pnl', 'exit_mark_pnl', 'fees_pnl', 'actual_pnl', 'bh_pnl']
annual = []
for year, g in d.groupby('year'):
    opening = float(g.previous_equity.iloc[0])
    bh_opening = float(g.bh_previous_equity.iloc[0])
    d.loc[g.index, 'year_opening_equity'] = opening
    d.loc[g.index, 'bh_year_opening_equity'] = bh_opening
    for col in atoms:
        denominator = bh_opening if col == 'bh_pnl' else opening
        d.loc[g.index, col + '_year_pp'] = 100 * g[col] / denominator
    annual.append({'year': int(year), 'opening_equity': opening,
                   'return_pp': 100 * (float(g.equity.iloc[-1]) / opening - 1),
                   'buyhold_return_pp': 100 * (float(g.bh_equity.iloc[-1]) / bh_opening - 1),
                   'phase_contributions_pp': {k: float(100 * g[k].sum() / (bh_opening if k == 'bh_pnl' else opening)) for k in atoms}})
pp_cols = [col + '_year_pp' for col in atoms]
monthly = d.groupby(['year', 'month'])[pp_cols].sum().reset_index()
monthly.to_csv(OUT / 'monthly_existing_accounting.csv', index=False, lineterminator='\n')
phases = d.groupby(['year', 'phase'])[pp_cols].sum().reset_index()
phases['days'] = d.groupby(['year', 'phase']).size().to_numpy()
phases.to_csv(OUT / 'phase_existing_accounting.csv', index=False, lineterminator='\n')
cycle_year = d.dropna(subset=['actual_cycle_id']).groupby(['year', 'actual_cycle_id'])[pp_cols].sum().reset_index()
trades = pd.DataFrame(run['ledgers']['trades']['data'])
cycle_year = cycle_year.merge(trades, left_on='actual_cycle_id', right_on='cycle_id', validate='many_to_one')
cycle_year.to_csv(OUT / 'cycle_calendar_year_existing_pnl.csv', index=False, lineterminator='\n')
d.to_csv(OUT / 'daily_existing_accounting.csv', index=False, lineterminator='\n')
pd.DataFrame(run['ledgers']['orders']['data']).to_csv(OUT / 'existing_orders.csv', index=False, lineterminator='\n')
decisions = pd.DataFrame(run['ledgers']['decisions']['data'])
decisions['posture'] = decisions.apply(
    lambda row: 'PLAN_BUY' if row.entry_signal == 1 else 'PLAN_SELL'
    if row.held_at_close == 1 and row.exit_pending == 1 else 'CONTINUE_HOLD'
    if row.held_at_close == 1 else 'CONTINUE_FLAT', axis=1)
assert ((decisions.posture.isin(['PLAN_BUY', 'CONTINUE_HOLD'])).astype(float) == decisions.target_position).all()
held = decisions.held_at_close.eq(1)
assert (decisions.loc[held, 'deadline_index'] - decisions.loc[held, 'entry_index']).eq(9).all()
decisions['known_holding_age_sessions'] = None
decisions.loc[held, 'known_holding_age_sessions'] = decisions.loc[held, 'warmup_sessions'] - decisions.loc[held, 'entry_index']
decisions['known_remaining_planned_exit_sessions'] = None
decisions.loc[held, 'known_remaining_planned_exit_sessions'] = decisions.loc[held, 'entry_index'] + 10 - decisions.loc[held, 'warmup_sessions']
decisions['known_reservation_remaining_sessions'] = (decisions.reservation_index - decisions.warmup_sessions).clip(lower=0)
by_id = decisions.set_index('decision_id')
orders = pd.DataFrame(run['ledgers']['orders']['data'])
for order in orders.itertuples():
    source = by_id.loc[order.decision_id]
    assert source.signal_date == order.signal_date and source.valid_session == order.execution_date
    assert source.posture == ('PLAN_BUY' if order.side == 'BUY' else 'PLAN_SELL')
assert set(decisions.loc[decisions.posture.isin(['PLAN_BUY', 'PLAN_SELL']), 'decision_id']) == set(orders.decision_id)
quantities = {str(row.date.date()): row.quantity for row in d.itertuples()}
assert all(row.held_at_close == float(quantities.get(row.signal_date[:10], 0) > 0) for row in decisions.itertuples())
decisions.to_csv(OUT / 'causal_decision_posture_inventory.csv', index=False, lineterminator='\n')
inventory = {
    'status': 'EXISTING_ACCOUNTING_INVENTORY_ONLY', 'account_evidence': record['evidence'],
    'account_result_hash': record['result_hash'], 'daily_reconciliation_evidence': daily_ref,
    'pricing': account['request_identity']['pricing'],
    'account_price_basis': account['request_identity']['price_basis'],
    'ledger_inventory': {k: {'rows': len(v['data']), 'fields': list(v['data'][0]) if v['data'] else []}
                         for k, v in run['ledgers'].items()},
    'buyhold_inventory': {k: {'rows': len(run['buyhold'][k]['data']), 'fields': list(run['buyhold'][k]['data'][0])}
                         for k in ['account_daily', 'fills', 'orders', 'attempts']},
    'annual': annual,
    'scope': 'All seven years, fixed calendar months and saved ENTRY/HOLD/EXIT/FLAT accounting phases; existing full trade cycles attributed by actual daily calendar-year PnL',
    'limits': ['Daily phase accounting and top losing intervals are descriptive; not new predictive states or new return labels.',
               'Benchmark phase allocation is same-date historical accounting, not attainable missed profits.',
               'Trade net_return may span years; annual contribution uses only actual daily PnL inside that year.',
               'HOLD includes overnight and intraday; ENTRY is actual fill to close; EXIT is previous close to actual sell; fees separate.'],
    'new_fits': 0, 'new_return_labels': 0, 'new_accounts': 0, 'new_market_data_calls': 0}
(OUT / 'accounting_source_inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
print(json.dumps({'annual': annual, 'outputs': str(OUT.relative_to(ROOT))}, ensure_ascii=False))
