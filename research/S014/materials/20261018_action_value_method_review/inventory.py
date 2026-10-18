"""Offline evidence inventory; no action-value labels, prices fetched, or models."""
from pathlib import Path
from hashlib import sha256
import io
import json
import socket

import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
EX19 = ROOT / 'research/S014/experiments/EX019_20261017'
EX33 = ROOT / 'research/S014/experiments/EX033_20261018'


def main():
    def blocked(*args, **kwargs):
        raise RuntimeError('Metadata-only inventory: network forbidden')
    socket.socket.connect = blocked
    socket.create_connection = blocked
    sources = {}

    def local(path):
        raw = path.read_bytes()
        sources[path.relative_to(ROOT).as_posix()] = {'sha256': sha256(raw).hexdigest()}
        return raw

    manifests = {EX19: json.loads(local(EX19 / 'others/result.json')),
                 EX33: json.loads(local(EX33 / 'others/result.json'))}

    def published(folder, path, name, columns=None):
        raw = local(folder / path)
        refs = [v for v in manifests[folder]['evidence'].values() if v['name'] == name]
        assert len(refs) == 1, name
        ref = EvidenceRef.from_dict(refs[0])
        immutable = ref.resolve(ROOT).read_bytes()
        assert immutable == raw and sha256(raw).hexdigest() == ref.sha256
        sources[(folder / path).relative_to(ROOT).as_posix()]['public_ref'] = refs[0]
        if columns is None:
            return json.loads(raw)
        return pd.read_csv(io.BytesIO(raw), usecols=columns)

    records = published(EX19, 'others/comparison_accounts.json', 'ex019-others-comparison_accounts-json')['records']
    base = next(r for r in records if r['variant'] == 'baseline_H3')
    assert base['candidate'] == 'S014-C0011' and base['status'] == 'SUCCEEDED'
    ref = EvidenceRef.from_dict(base['evidence'])
    account_raw = ref.resolve(ROOT).read_bytes()
    assert sha256(account_raw).hexdigest() == ref.sha256
    account = json.loads(account_raw)
    assert account['result_hash'] == base['result_hash'] and len(account['runs']) == 1
    sources['public_account_C0011'] = {'sha256': ref.sha256, 'public_ref': base['evidence'], 'result_hash': base['result_hash']}
    ledgers = account['runs'][0]['ledgers']
    # Returns and historical P/D states are deliberately never extracted.
    trades = pd.DataFrame(ledgers['trades']['data'])[['cycle_id', 'entry_date', 'exit_date', 'quantity', 'status']]
    daily = pd.DataFrame(ledgers['account_daily']['data'])[['date', 'cash', 'quantity', 'close', 'equity']]
    fills = pd.DataFrame(ledgers['fills']['data'])[['cycle_id', 'fill_time', 'side', 'quantity', 'price', 'fees']]
    member_columns = ['cycle_id', 'original_status', 'entry_date', 'entry_year', 'quantity',
                      'decision_date', 'original_target_exit', 'extended_target_exit',
                      'original_actual_exit', 'extended_actual_exit']
    members = published(EX19, 'others/state_diagnostics_v2_members.csv',
                        'ex019-others-state_diagnostics_v2_members-csv', member_columns)
    attempts = published(EX19, 'others/state_diagnostics_v2_fill_attempts.csv',
                         'ex019-others-state_diagnostics_v2_fill_attempts-csv',
                         ['cycle_id', 'horizon', 'day', 'filled', 'price'])
    calendar = published(EX33, 'others/calendar.csv', 'ex033-others-calendar-csv', ['date'])
    dates = calendar.date.tolist()
    assert len(dates) == 1642 and len(set(dates)) == 1642 and dates == sorted(dates)
    daily['date'] = pd.to_datetime(daily.date).dt.strftime('%Y-%m-%d')
    daily = daily.set_index('date')
    assert daily.index.tolist() == dates and daily.notna().all().all()
    trades['entry_date'] = pd.to_datetime(trades.entry_date).dt.strftime('%Y-%m-%d')
    trades['exit_date'] = pd.to_datetime(trades.exit_date).dt.strftime('%Y-%m-%d')
    fills['day'] = pd.to_datetime(fills.fill_time).dt.strftime('%Y-%m-%d')
    assert len(members) == len(trades) == 147
    assert members.cycle_id.is_unique and trades.cycle_id.is_unique
    assert set(members.cycle_id) == set(trades.cycle_id)
    trade_lookup = trades.set_index('cycle_id')
    inventory = []

    def date_or_none(value):
        return None if pd.isna(value) else str(value)

    for row in members.itertuples():
        trade = trade_lookup.loc[row.cycle_id]
        assert row.entry_date == trade.entry_date and row.quantity == trade.quantity
        assert row.original_status == trade.status
        pos = dates.index(row.entry_date)
        ds = {f'E{k}': dates[pos+k] if pos+k < len(dates) else None for k in (2, 3, 6, 9)}
        assert ds['E2'] == date_or_none(row.decision_date)
        assert ds['E3'] == date_or_none(row.original_target_exit)
        assert ds['E6'] == date_or_none(row.extended_target_exit)
        actual3, actual6 = date_or_none(row.original_actual_exit), date_or_none(row.extended_actual_exit)
        assert actual3 == date_or_none(trade.exit_date)
        event_fills = fills.loc[fills.cycle_id.eq(row.cycle_id)]
        buy, sell = event_fills.loc[event_fills.side.eq('BUY')], event_fills.loc[event_fills.side.eq('SELL')]
        assert len(buy) == 1 and len(sell) <= 1
        assert int(buy.iloc[0].quantity) == row.quantity
        if actual3:
            assert len(sell) == 1 and sell.iloc[0].day == actual3
        else:
            assert len(sell) == 0
        hx = attempts.loc[attempts.cycle_id.eq(row.cycle_id) & attempts.horizon.eq(6) & attempts.filled.eq(True)]
        assert len(hx) == int(actual6 is not None)
        if actual6:
            assert hx.iloc[0].day == actual6 and pd.notna(hx.iloc[0].price)
        decision_known = ds['E2'] is not None
        if decision_known:
            assert daily.loc[ds['E2'], 'quantity'] == row.quantity
        e6_known = ds['E6'] is not None
        h6_by_e6 = bool(e6_known and actual6 is not None and actual6 <= ds['E6'])
        h3_by_e6 = bool(e6_known and actual3 is not None and actual3 <= ds['E6'])
        same_day_buy = None if actual3 is None else bool(fills.loc[fills.day.eq(actual3) & fills.side.eq('BUY')].shape[0])
        inventory.append({'cycle_id': row.cycle_id, 'entry_date': row.entry_date, 'entry_year': int(row.entry_year),
                          'decision_year': int(ds['E2'][:4]) if decision_known else None,
                          'original_status': row.original_status, **ds,
                          'original_actual_exit': actual3, 'same_quantity_H6_actual_exit': actual6,
                          'original_sell_delayed': bool(actual3 > ds['E3']) if actual3 and ds['E3'] else None,
                          'H6_sell_delayed': bool(actual6 > ds['E6']) if actual6 and ds['E6'] else None,
                          'original_sold_by_E6': h3_by_e6 if e6_known else None,
                          'H6_sold_by_E6': h6_by_e6 if e6_known else None,
                          'original_sale_day_has_new_buy': same_day_buy,
                          'D_cash_quantity_known': decision_known,
                          'X_E6_cash_quantity_close_equity_known': e6_known,
                          'H_E6_same_quantity_exit_known': h6_by_e6,
                          'C_original_sale_cash_fields_known': bool(decision_known and h3_by_e6 and sell[['quantity', 'price', 'fees']].notna().all().all()),
                          'E6_comparable': bool(decision_known and e6_known and h6_by_e6 and h3_by_e6)})

    annual = []
    for year in range(2020, 2027):
        entry_rows = [r for r in inventory if r['entry_year'] == year]
        decision_rows = [r for r in inventory if r['decision_year'] == year]
        annual.append({'year': year, 'entries': len(entry_rows),
                       'E2_available_by_entry_year': sum(r['E2'] is not None for r in entry_rows),
                       'E3_available_by_entry_year': sum(r['E3'] is not None for r in entry_rows),
                       'E6_available_by_entry_year': sum(r['E6'] is not None for r in entry_rows),
                       'E9_available_by_entry_year': sum(r['E9'] is not None for r in entry_rows),
                       'E6_comparable_by_entry_year': sum(r['E6_comparable'] for r in entry_rows),
                       'E6_comparable_by_decision_year': sum(r['E6_comparable'] for r in decision_rows)})
    result = {'status': 'PASS', 'scope': 'Evidence field/date inventory only; no action-value returns computed',
              'new_calls': 0, 'new_fits': 0, 'new_labels': 0, 'new_account_runs': 0,
              'source_script_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'sources': sources, 'calendar': {'sessions': len(dates), 'start': dates[0], 'end': dates[-1]},
              'counts': {'entries': len(inventory), 'closed': sum(r['original_status'] == 'CLOSED' for r in inventory),
                         **{k+'_available': sum(r[k] is not None for r in inventory) for k in ('E2', 'E3', 'E6', 'E9')},
                         'E6_comparable': sum(r['E6_comparable'] for r in inventory)},
              'annual': annual,
              'delayed_or_unsold': [r for r in inventory if r['original_sell_delayed'] or r['H6_sell_delayed'] or r['original_sold_by_E6'] is not True or r['H6_sold_by_E6'] is not True],
              'field_sufficiency': {
                  'D': 'C11 account_daily cash/quantity/close at E2; exact existing entry quantity cross-checked',
                  'X': 'C11 account_daily cash/quantity/close/equity at E6; subsequent residual position must remain marked, with no invented sale fee',
                  'H': 'Original C11 quantity plus published EX019 horizon=6 fill-attempt price/date, existing 0.1% sell fee and D residual cash',
                  'C': 'D cash plus original sell quantity/price/fee; preserve cash thereafter. Do not use original daily cash after later reentry.',
                  'status': 'All 146 E6-observable events have complete fields; terminal event retained as missing/censored'},
              'limits': ['This inventory does not compute H-X, H-C or X-C outcomes.',
                         'E6 close is a fixed common valuation endpoint; no account strategy has been run.',
                         'Observed dates and execution availability must not be used as contemporaneous predictive signals.',
                         'Annual cohort counts are by entry or decision year, never annual account returns.',
                         'Missing terminal dates are null; no zero imputation or forced terminal exit.',
                         'Existing H3 and H6 results are reused; no independently unseen sample is claimed.'],
              'events': inventory}
    assert result['counts']['E6_comparable'] == 146
    (OUT / 'inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'counts': result['counts'], 'annual': annual,
                      'delayed_or_unsold': result['delayed_or_unsold']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
