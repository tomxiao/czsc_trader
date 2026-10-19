"""Independently reconstruct all21 modelled OFF labels and frozen summaries."""
import csv
import json
from pathlib import Path

import pandas as pd

import authenticate_shock_population as P
import local_cycle_oracle as O
import local_input_reader as I

ROOT, OUT = P.ROOT, P.OUT
EX = ROOT / 'research/S014/experiments/EX049_20261020'
STATES = ['PRIOR_TREND_ESTABLISHED', 'NON_FINAL_DAY_DOMINATED']


def summarize(rows, state, year=None, age_kind=None, remaining=None):
    group = [r for r in rows if (year is None or int(r['year_of_D']) == year)
             and (age_kind is None or (int(float(r['holding_age_D'])) == 0) == (age_kind == 'age0'))
             and (remaining is None or int(float(r['remaining_D_sessions_to_deadline'])) == remaining)]
    cells = []
    for value in [True, False, None]:
        selected = [r for r in group if r[state] is value]
        valid = [r['advantage'] for r in selected if r['advantage'] is not None]
        cells.append({'state_value': value, 'N': len(selected), 'closed_label_n': len(valid), 'censored_n': sum(r['censored'] for r in selected),
                      'positive_n': sum(v > 0 for v in valid), 'zero_n': sum(v == 0 for v in valid), 'negative_n': sum(v < 0 for v in valid),
                      'mean_advantage': sum(valid) / len(valid) if valid else None, 'median_advantage': float(pd.Series(valid).median()) if valid else None})
    common = [r for r in group if r[state] is not None and r['advantage'] is not None]
    return {'state': state, 'year': year, 'age_kind': age_kind, 'exact_remaining': remaining, 'N': len(group), 'cells': cells,
            'same_closed_known_cohort_reference': {'N': len(common), 'always_exit_mean': 0. if common else None,
                'always_hold_mean': sum(r['advantage'] for r in common) / len(common) if common else None,
                'frozen_true_hold_false_exit_mean': sum(r['advantage'] if r[state] else 0. for r in common) / len(common) if common else None}}


def main():
    review = P.read(OUT / 'local_on_independent_review.json')
    lock_ref = P.read(EX / 'protocols/published_lock.json')
    on_ref = P.read(EX / 'others/on_controls_ref.json')
    P.check('A original21 exact ON current identity passed', review['status'].startswith('PASS') and review['source_lock_sha256'] == lock_ref['sha256'] and review['ON_ref'] == on_ref)
    gate = P.read(EX / 'others/gate_ON_independent.json')
    P.check('paired source/ON gate current identities', gate['status'] == 'PASS' and gate['source_lock_sha256'] == lock_ref['sha256'] and gate['ON_ref'] == on_ref and {v['reviewer'] for v in gate['reviews']} == {'A', 'B'})
    for value in gate['reviews']:
        certificate = P.published(value['ref'])
        P.check('public independent gate exact ON/lock', certificate['status'].startswith('PASS') and certificate['source_lock_sha256'] == lock_ref['sha256'] and certificate['ON_ref'] == on_ref)
    lock = P.published(lock_ref)
    for name, digest in lock['source_hashes'].items():
        P.check('same locked component bytes ' + name, P.ref(EX / name)['sha256'] == digest)
    off_ref = P.read(EX / 'others/off_labels_ref.json')
    document = P.published(off_ref)
    original = P.published(on_ref)
    P.check('public OFF identity tied to exact ON', document['source_lock_sha256'] == lock_ref['sha256'] and document['origin_ON_control_ref'] == on_ref and document['N'] == 21 and document['new_funded_accounts'] == document['new_fits'] == 0)
    P.check('local OFF exact public bytes', P.ref(EX / 'others/off_labels.json')['sha256'] == off_ref['sha256'])
    account, frames, input_proof = I.load()
    for key, value in input_proof['content_identities'].items():
        P.check('independent pinned source and execution input exact ' + key, original['prepared_content_identities'][key] == value)
    decisions, _ = O.original_maps(account)
    with (OUT / 'original_shock_population.csv').open(encoding='utf-8', newline='') as stream:
        events = list(csv.DictReader(stream))
    results = []
    keys = ['D', 'valid_E', 'entry_index', 'deadline_index', 'reservation_index', 'holding_age', 'target_position', 'exit_pending',
            'pending_inherited', 'deadline_exit', 'profit_exit_eligible', 'shock_condition', 'selected_shock_exit', 'selected_cost_exit',
            'selected_risk_exit', 'ordinary_support_exit', 'entry_grace_eligible', 'entry_grace_applied', 'net_profit', 'cost_loss_price']
    for event, supplied in zip(events, document['rows'], strict=True):
        P.check('all original21 events no matching filter', supplied['origin_actual_event'] == event)
        independent = O.reconstruct(event, account, frames, 'OFF_LOCAL_CYCLE')
        modeled = supplied['alternative_MODELLED_POSTHOC']
        P.check('independent owncycle exact same liquidation/censor', independent['censored'] == (modeled['status'] == 'CENSORED'))
        P.check('complete independent OFF ownstate path', len(independent['trace']) == len(modeled['trace']))
        for ours, theirs in zip(independent['trace'], modeled['trace'], strict=True):
            for key in keys:
                P.check('independent OFF original-entry state ' + key, ours[key] == theirs[key])
        P.check('independent OFF public attempts same count', len(independent['attempts']) == len(modeled['attempts']))
        for ours, theirs in zip(independent['attempts'], modeled['attempts'], strict=True):
            for key in ['D', 'E', 'filled', 'price', 'trigger', 'reason']:
                P.check('independent public OFF attempt ' + key, ours[key] == theirs[key])
        if not independent['censored']:
            sale = independent['sale']
            P.check('independent OFF exact price quantity and fee', sale['E'] == modeled['exit_E'] and sale['price'] == modeled['exit_price_ledger'] and sale['quantity'] == modeled['quantity'] and sale['fee'] == modeled['exit_fee'])
            precision = 'TIMESTAMP' if sale['trigger'] == 'OPEN_MARKET' else 'SESSION' if sale['trigger'] == 'DAILY_OPEN_PLUS_TICK' else None
            P.check('original modeled public time semantics exact', precision is not None and modeled['exit_time_precision'] == precision and pd.Timestamp(modeled['exit_fill_time']) == pd.Timestamp(sale['E'] + 'T09:30:00'))
            P.check('no original post-sale close or later source decision', not modeled['post_sale_close_evaluated'] and all(r['D'] < sale['E'] for r in modeled['trace']))
        label = supplied['label_POSTHOC']
        P.check('strict original Q netproceeds normalization and sign exact', independent['incremental_liquidation_cash'] == label['delta_net_proceeds'] and independent['incremental_liquidation_normalized'] == label['advantage'] and independent['advantage_sign'] == label['sign'])
        state = O.causal_states(event['D'], decisions[event['D']], frames)
        for key in STATES + ['r1_log', 'r4_log']:
            P.check('firstD causal state fixed and retained', state[key] == supplied['D_known_states'][key])
        for key in STATES:
            choice = label['advantage'] if state[key] else 0. if state[key] is not None else None
            P.check('frozen truehold falseexit choice exact', choice == supplied['frozen_local_choices_POSTHOC'][key + '_TRUE_HOLD_FALSE_EXIT'])
        results.append({**event, **{k: state[k] for k in STATES}, 'r1_log': state['r1_log'], 'r4_log': state['r4_log'],
                        'r1_positive': state['r1_log'] > 0 if state['r1_log'] is not None else None,
                        'modeled_OFF_exit_D': independent['sale']['D'] if independent['sale'] else None, 'modeled_OFF_exit_E': modeled['exit_E'],
                        'modeled_OFF_price_ledger': modeled['exit_price_ledger'], 'modeled_OFF_fee': modeled['exit_fee'],
                        'modeled_OFF_exit_trigger': modeled['exit_trigger'], 'modeled_OFF_public_attempts': len(modeled['attempts']),
                        'censored': independent['censored'], 'entry_total_cost': independent['entry_total_cost'],
                        'delta_net_proceeds': independent['incremental_liquidation_cash'], 'advantage': independent['incremental_liquidation_normalized'],
                        'advantage_sign': independent['advantage_sign'], 'component_only_not_actual_trade_or_policy_return': True})
    summaries = []
    for supplied in document['summaries']:
        result = summarize(results, supplied['state'], supplied['year'], supplied['age_kind'], supplied['exact_remaining'])
        P.check('complete independent group/empty/unknown/censor/reference summary exact', result == supplied)
        summaries.append(result)
    flat = [{**{k: group[k] for k in ['state', 'year', 'age_kind', 'exact_remaining']}, **cell,
             **{key: value for key, value in group['same_closed_known_cohort_reference'].items() if key != 'N'}}
            for group in summaries for cell in group['cells']]
    outputs = [P.save('local_event_labels.csv', results, True), P.save('local_state_summary.csv', flat, True)]
    report = {'status': 'PASS_INDEPENDENT21_MODELLED_LOCAL_LABELS', 'reviewer': 'A', 'source_lock_sha256': lock_ref['sha256'], 'ON_ref': on_ref, 'OFF_ref': off_ref,
              'N': len(results), 'closed_labels': sum(not r['censored'] for r in results), 'censored_labels': sum(r['censored'] for r in results),
              'sign_counts': {name: sum(r['advantage_sign'] == value for r in results) for name, value in [('positive', 1), ('zero', 0), ('negative', -1)]},
              'outputs': outputs, 'summaries': summaries, 'independent_original_input_proof': input_proof,
              'checks': dict(P.CHECKS), 'check_count': sum(P.CHECKS.values()), 'primary_label_tolerance': 0, 'state_threshold_epsilon': 0,
              'implementation': P.ref(Path(__file__).resolve()), 'independent_oracle': P.ref(Path(O.__file__).resolve()), 'independent_reader': P.ref(Path(I.__file__).resolve()),
              'resources': {'unique_original_component_events': 21, 'independent_OFF_reconstructions': 21, 'new_funded_accounts': 0, 'new_fits': 0, 'new_supplier_calls': 0, 'new_preparations': 0, 'prepared_public_fetches': 5},
              'limits': ['OFF outcomes are modeled component fills, never actual new funded trades.', 'All old entry quantities and opportunities fixed; their overlapping alternatives cannot be summed into policy wealth or original annual gates.', 'Every year/event/state/age/remaining retained, no filtered downD or new threshold, direction, sample-count or stability veto.', 'See all21 and peryear/age/remaining counterexamples before considering any whole-policy trial.']}
    print(json.dumps({'review': P.save('local_off_independent_review.json', report), 'checks': report['check_count'], 'N': report['N'], 'signs': report['sign_counts'], 'tables': outputs}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        path = OUT / 'local_off_independent_failure.json'
        if not path.exists():
            P.save(path.name, {'status': 'TECHNICAL_INDEPENDENT_OFF_AUDIT_FAILURE', 'exception': repr(exc), 'checks': dict(P.CHECKS), 'implementation': P.ref(Path(__file__).resolve()), 'new_funded_accounts': 0})
        raise
