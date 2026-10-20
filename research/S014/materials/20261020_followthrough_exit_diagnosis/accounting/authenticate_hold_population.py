"""Read-only C9502 population and first post-SHOCK decision clock census."""
from collections import Counter
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import socket
from uuid import UUID

import pandas as pd
import requests
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools import ResearchBatchRef
from dataflows import DataRequest, Dataset, PreparedDataRef, ProviderConfig

ROOT = Path.cwd()
EX = ROOT / 'research/S014/experiments/EX050_20261020'
OUT = Path(__file__).resolve().parent


def deny(*args, **kwargs):
    raise RuntimeError('Only original PreparedDataRef assets; no network/supplier')


socket.socket.connect = deny
socket.create_connection = deny
requests.sessions.Session.request = deny


def load_ref(value):
    ref = EvidenceRef.from_dict(value)
    raw = ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == ref.sha256 and ref.experiment.strategy_id == 'S014'
    return json.loads(raw)


def main():
    receipt = json.loads((EX / 'others/accounts/run-002.json').read_bytes())
    review_path = ROOT / 'research/S014/materials/20261020_shock_state_diagnosis/accounting/policy_account_002_independent_review.json'
    review = json.loads(review_path.read_bytes())
    assert receipt['candidate'] == 'S014-C9502' and receipt['status'] == 'SUCCEEDED'
    assert receipt['parameters'] == {'policy_profile': 'FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD'}
    assert review['status'] == 'PASS' and review['account_ref'] == receipt['evidence'] and review['result_hash'] == receipt['result_hash']
    account = load_ref(receipt['evidence'])
    assert account['result_hash'] == receipt['result_hash']
    binding = load_ref(receipt['binding_ref'])
    source = binding['input_bindings']['full']
    query, pin = source['plan']['requests']['market'], source['prepared']
    assert not query.get('parameters')
    request = DataRequest(Dataset(query['dataset']), query['symbol'], query['start'], query['end'], query['required_cutoff'], query['frequency'])
    prepared = PreparedDataRef(UUID(pin['space_id']), UUID(pin['preparation_id']), pin['manifest_sha256'])
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'), providers=ProviderConfig(bindings={}))
    fetched = ctx.data.fetch(request, prepared=prepared)
    assert fetched.ready and fetched.identity.content_sha256 == review['independent_state_input_proof']['content_identities']['source_market']
    market = fetched.dataframe.copy(deep=True)
    market.index = pd.DatetimeIndex(pd.to_datetime(market.Date))
    assert not market.index.has_duplicates
    ledger = account['runs'][0]['ledgers']
    rows = ledger['decisions']['data']
    daily = {r['date'][:10]: r for r in ledger['account_daily']['data']}
    fills = {r['cycle_id']: {} for r in ledger['fills']['data']}
    for fill in ledger['fills']['data']:
        fills[fill['cycle_id']][fill['side']] = fill
    buy_by_day = {p['BUY']['fill_time'][:10]: (key, p) for key, p in fills.items()}
    cycle_entry = {}
    for r in rows:
        if r['buy_filled_today']:
            cycle_entry[r['entry_index']] = buy_by_day[r['signal_date'][:10]]
    flags = ['pending_inherited', 'deadline_exit', 'selected_cost_exit', 'ordinary_support_exit', 'selected_shock_exit', 'exit_pending']
    records = []
    all_first = [r for r in rows if r['first_shock_today']]
    for pos, row in enumerate(rows):
        if not (row['first_shock_today'] and row['first_shock_hold_decision']):
            continue
        D = row['signal_date'][:10]
        assert row['holding_age'] >= 1 and row['shock_disable_latched'] and row['held_at_close'] and daily[D]['quantity'] > 0
        cycle, pair = cycle_entry[row['entry_index']]
        buy, sale = pair['BUY'], pair.get('SELL')
        nxt = rows[pos + 1] if pos + 1 < len(rows) else None
        postD = nxt['signal_date'][:10] if nxt else None
        exitD = sale['signal_date'][:10] if sale else None
        exitstate = next((r for r in rows if r['signal_date'][:10] == exitD), None)
        close, postclose = daily[D]['close'], daily[postD]['close'] if postD in daily else None
        samecycle = bool(nxt and nxt['held_at_close'] and nxt['entry_index'] == row['entry_index'])
        prior_sell_pending = bool(row['exit_pending'])
        source_close = float(market.loc[pd.Timestamp(D), 'Close'])
        post_source_close = float(market.loc[pd.Timestamp(postD), 'Close']) if postD else None
        lower = post_source_close < source_close if post_source_close is not None else None
        assert lower == (postclose < close if postclose is not None else None)
        records.append({'cycle_id': cycle, 'year': int(D[:4]), 'actual_entry_D': buy['signal_date'][:10],
                        'actual_entry_E': buy['fill_time'][:10], 'actual_entry_order_id': buy['order_id'], 'actual_entry_fill_id': buy['fill_id'],
                        'actual_quantity': buy['quantity'], 'shock_D': D, 'shock_valid_E': row['valid_session'][:10],
                        'entry_index': row['entry_index'], 'shock_index': row['warmup_sessions'], 'shock_age': row['holding_age'],
                        'deadline_index': row['deadline_index'], 'reservation_index': row['reservation_index'],
                        'remaining_deadline_at_shock': row['deadline_index'] - row['warmup_sessions'],
                        'shock_close_ledger_same_representation': close,
                        'shock_close_runtime_HFQ': source_close,
                        **{'shock_' + k: row[k] for k in flags},
                        'first_post_D': postD, 'first_post_valid_E': nxt['valid_session'][:10] if nxt else None,
                        'first_post_close_ledger_same_representation': postclose,
                        'first_post_close_runtime_HFQ': post_source_close,
                        'first_post_close_below_shock_anchor_known_only_at_post_D': lower,
                        'first_post_same_actual_cycle_held': samecycle,
                        'first_post_target': nxt['target_position'] if nxt else None,
                        'first_post_remaining_deadline': row['deadline_index'] - nxt['warmup_sessions'] if nxt else None,
                        **{'first_post_' + k: nxt[k] if nxt else None for k in flags},
                        'first_post_already_pending_before_new_D_decision': prior_sell_pending and samecycle,
                        'first_post_anchor_action_has_distinct_target_from_original': bool(samecycle and lower and not nxt['exit_pending']),
                        'original_actual_exit_D': exitD, 'original_actual_exit_E': sale['fill_time'][:10] if sale else None,
                        'original_actual_exit_order_id': sale['order_id'] if sale else None, 'original_actual_exit_fill_id': sale['fill_id'] if sale else None,
                        **{'original_exit_' + k: exitstate[k] if exitstate else None for k in flags}})
    assert len(records) == len({r['cycle_id'] for r in records})
    summary = {'status': 'AUTHENTICATED_ACTUAL_POPULATION_ONLY_NO_ALTERNATIVE_RETURNS',
               'account_ref': receipt['evidence'], 'result_hash': receipt['result_hash'], 'binding_ref': receipt['binding_ref'],
               'actual_review': {'path': review_path.relative_to(ROOT).as_posix(), 'sha256': sha256(review_path.read_bytes()).hexdigest()},
               'source_sha256': receipt['published_source_ref']['sha256'], 'execution_lock_ref': receipt['execution_source_lock_ref'],
               'all_first_SHOCK_actual_cycles': len(all_first), 'selected_hold_age_ge1_cycles': len(records),
               'year_counts': {str(year): sum(r['year'] == year for r in records) for year in range(2020, 2027)},
               'first_post_same_cycle': sum(r['first_post_same_actual_cycle_held'] for r in records),
               'first_post_lower_anchor': sum(r['first_post_close_below_shock_anchor_known_only_at_post_D'] is True for r in records),
               'first_post_lower_existing_other_exit': sum(r['first_post_same_actual_cycle_held'] and r['first_post_close_below_shock_anchor_known_only_at_post_D'] and r['first_post_exit_pending'] for r in records),
               'first_post_lower_distinct_action': sum(r['first_post_anchor_action_has_distinct_target_from_original'] for r in records),
               'original_actual_exit_reason_overlap': dict(Counter(tuple(k for k in flags[:-1] if r['original_exit_' + k]) for r in records)),
               'input_proof': {'source_prepared': pin, 'source_market_request': query, 'source_market_content_sha256': fetched.identity.content_sha256,
                               'prepared_only_public_fetches': 1, 'new_preparations': 0, 'raw_market_exports': 0},
               'implementation_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
               'new_fits': 0, 'new_supplier_calls': 0, 'new_accounts': 0, 'new_counterfactual_outcomes': 0,
               'scope': 'Existing actual D/nextD observations only. nextDclose is known at nextD close, never at original SHOCK D. No replacement fill/profit or future labels computed.'}
    summary['original_actual_exit_reason_overlap'] = {'|'.join(k): v for k, v in summary['original_actual_exit_reason_overlap'].items()}
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(records[0]))
    writer.writeheader()
    writer.writerows(records)
    with (OUT / 'original_hold_population.csv').open('x', encoding='utf-8', newline='') as output:
        output.write(stream.getvalue())
    with (OUT / 'original_hold_population_review.json').open('x', encoding='utf-8') as output:
        output.write(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False))
    print(json.dumps([r for r in records if r['first_post_close_below_shock_anchor_known_only_at_post_D']], ensure_ascii=False))


if __name__ == '__main__':
    main()
