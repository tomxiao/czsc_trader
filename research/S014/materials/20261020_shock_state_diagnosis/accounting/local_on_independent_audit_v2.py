"""Original21 ON controls independently reconstructed; no real OFF call."""
import csv
import json
from pathlib import Path

import pandas as pd

import authenticate_shock_population as P
import local_cycle_oracle as O
import local_input_reader as I

ROOT, OUT = P.ROOT, P.OUT
EX = ROOT / 'research/S014/experiments/EX049_20261020'


def main():
    proof = P.read(OUT / 'local_public_lock_review.json')
    lock_ref = P.read(EX / 'protocols/published_lock.json')
    P.check('current source lock independently reviewed', proof['status'].startswith('PASS') and proof['source_lock_ref'] == lock_ref)
    lock = P.published(lock_ref)
    for name, digest in lock['source_hashes'].items():
        P.check('frozen exact source at ON audit ' + name, P.ref(EX / name)['sha256'] == digest)
    on_ref = P.read(EX / 'others/on_controls_ref.json')
    document = P.published(on_ref)
    P.check('originalON public and local exact', P.ref(EX / 'others/on_controls.json')['sha256'] == on_ref['sha256'])
    P.check('21 originalON only exact source provenance', document['status'] == 'PASS_ORIGINAL_ON_COMPONENT_CONTROLS' and document['N'] == 21 and document['source_lock_sha256'] == lock_ref['sha256'] and document['new_OFF_labels'] == document['new_funded_accounts'] == 0)
    P.check('OFF not present before independentON gate', not (EX / 'others/off_labels.json').exists())
    population_review = P.read(OUT / 'original_shock_population_review.json')
    population_file = ROOT / population_review['outputs'][0]['path']
    P.check('original complete21 population bytes frozen', P.ref(population_file)['sha256'] == population_review['outputs'][0]['sha256'])
    with population_file.open(encoding='utf-8', newline='') as stream:
        events = list(csv.DictReader(stream))
    account, frames, inputs = I.load()
    for name, value in inputs['content_identities'].items():
        P.check('independently fetched original prepared content ' + name, value == document['prepared_content_identities'][name])
    P.check('actual original account pinned identity', document['origin_actual_account_ref'] == inputs['original_account_ref'] and document['origin_actual_result_hash'] == account['result_hash'])
    decisions, fills = O.original_maps(account)
    keys = ['entry_index', 'deadline_index', 'reservation_index', 'holding_age', 'target_position', 'exit_pending', 'pending_inherited',
            'deadline_exit', 'profit_exit_eligible', 'shock_condition', 'selected_shock_exit', 'selected_cost_exit', 'selected_risk_exit',
            'ordinary_support_exit', 'entry_grace_eligible', 'entry_grace_applied', 'net_profit', 'cost_loss_price']
    certificates = []
    for event, supplied in zip(events, document['rows'], strict=True):
        P.check('all original events not reselected', event == supplied['origin_actual_event'])
        expected = O.reconstruct(event, account, frames, 'ON')
        result = supplied['original_ON_MODELLED_control']
        sale = fills[event['actual_exit_fill_id']]
        P.check('independent ON final same actual public price and fee exact', expected['sale']['E'] == O.day(sale['fill_time']) == result['exit_E'] and expected['sale']['price'] == sale['price'] == result['exit_price_ledger'] and expected['sale']['quantity'] == sale['quantity'] == result['quantity'] and expected['sale']['fee'] == sale['fees'] == result['exit_fee'])
        P.check('ON normalized proceeds advantage exactzero', expected['incremental_liquidation_cash'] == expected['incremental_liquidation_normalized'] == expected['advantage_sign'] == 0)
        P.check('ON complete originalD interval no postsaleDclose', [r['D'] for r in expected['trace']] == [r['D'] for r in result['trace']] == sorted(d for d in decisions if event['actual_entry_fill_E'] <= d < event['actual_exit_fill_E']) and not result['post_sale_close_evaluated'])
        for ours, theirs in zip(expected['trace'], result['trace'], strict=True):
            old = decisions[ours['D']]
            P.check('ON valid nextE exact original', ours['valid_E'] == theirs['valid_E'] == O.day(old['valid_session']))
            for key in keys:
                P.check('independent ON original-entry state ' + key, ours[key] == theirs[key] == old[key])
        P.check('ON exact attempts cover original filled SELL', len(expected['attempts']) == len(result['attempts']) == 1)
        attempt = result['attempts'][0]
        P.check('ON attempt original order/fill clock and precision', attempt['D'] == sale['signal_date'][:10] and attempt['E'] == O.day(sale['fill_time']) and attempt['trigger'] == sale['trigger'] and pd.Timestamp(attempt['filled_at']) == pd.Timestamp(sale['fill_time']) and attempt['time_precision'] == sale['time_precision'])
        state = O.causal_states(event['D'], decisions[event['D']], frames)
        for key in ['PRIOR_TREND_ESTABLISHED', 'NON_FINAL_DAY_DOMINATED', 'r1_log', 'r4_log']:
            P.check('independent originalD known state ' + key, state[key] == supplied['D_known_states'][key])
        seed = supplied['seed']
        P.check('actual funded entry and original runtime checkpoint exact', seed['quantity'] == fills[event['actual_entry_fill_id']]['quantity'] and seed['runtime_entry_price'] == decisions[event['actual_entry_fill_E']]['entry_fill_price'] and seed['ledger_entry_price'] == fills[event['actual_entry_fill_id']]['price'] and seed['actual_buy_fee'] == fills[event['actual_entry_fill_id']]['fees'])
        certificates.append({'event_id': event['event_id'], 'D': event['D'], 'cycle_id': event['cycle_id'], 'original_ON_exit_E': event['actual_exit_fill_E'],
                             'original_actual_quantity': sale['quantity'], 'independent_price_exact': expected['sale']['price'], 'independent_fee_exact': expected['sale']['fee'],
                             'independent_ON_trace_D': len(expected['trace']), 'independent_D_states': state, 'strict_ON_advantage': expected['incremental_liquidation_normalized']})
    P.check('all21 ON actualfunded cycles independently controlled', len(certificates) == 21)
    result = {'status': 'PASS_INDEPENDENT_ORIGINAL21_ON_EXACT', 'reviewer': 'A', 'source_lock_sha256': lock_ref['sha256'], 'source_lock_ref': lock_ref,
              'ON_ref': on_ref, 'N': len(certificates), 'checks': dict(P.CHECKS), 'check_count': sum(P.CHECKS.values()),
              'exact_ON_price_fee_state_tolerance': 0, 'timestamp_comparison': 'Exact pd.Timestamp nanosecond equality, no truncation or tolerance',
              'retained_prior_failure': P.ref(OUT / 'local_on_independent_failure.json'),
              'retained_prior_implementation': P.ref(OUT / 'local_on_independent_audit.py'), 'original_input_proof': inputs, 'certificates': certificates,
              'implementation': P.ref(Path(__file__).resolve()), 'independent_oracle': P.ref(Path(O.__file__).resolve()), 'independent_reader': P.ref(Path(I.__file__).resolve()),
              'resources': {'independent_original_ON_reconstructions': 21, 'new_real_OFF_labels': 0, 'new_funded_accounts': 0, 'fits': 0, 'new_supplier_calls': 0, 'new_preparations': 0, 'prepared_public_fetches': 5},
              'limits': ['ON is checked against original actual funded fill and sourceD state, independently of C simulator outputs.', 'D-known states carry no new future outcome in this audit; OFF still requires the separate paired reviewer gate.', 'Local ON exits at actual SELL_E fill; no post-sale Eclose original fullaccount target is simulated or required.']}
    print(json.dumps({'review': P.save('local_on_independent_review.json', result), 'checks': result['check_count'], 'N': len(certificates)}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        destination = OUT / 'local_on_independent_failure_v2.json'
        if not destination.exists():
            P.save(destination.name, {'status': 'TECHNICAL_INDEPENDENT_ON_AUDIT_FAILURE', 'exception': repr(exc), 'checks': dict(P.CHECKS), 'implementation': P.ref(Path(__file__).resolve()), 'new_OFF_labels': 0, 'new_funded_accounts': 0})
        raise
