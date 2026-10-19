"""Observed own-policy pause chains and months; no deleted-order wealth labels."""
from collections import defaultdict
import json
from pathlib import Path

import consolidate_shock_audit as S
import diagnose_actual_2026 as D

OUT, A = S.OUT, S.A


def main():
    reports = [A.read(OUT / f'shock_account_{i:03d}_independent_review.json') for i in (0, 1)]
    accounts = [A.published(r['account_ref']) for r in reports]
    slots, trace, monthly, transitions = [], [], [], []
    for i, report in enumerate(reports):
        A.check('already independent actual PASS', report['status'] == 'PASS')
        observed, states = D.trace_slots(accounts[i], accounts[1-i], report['actual2026_daily_atoms'])
        meta = {'shock_profile': report['policy_id'], 'diagID': report['diagID']}
        for row in observed:
            row['actual_BH_net_pp_in_observed_flat_window'] = row['actual_BH_up_contribution_pp_in_observed_flat_window'] + row['actual_BH_down_contribution_pp_in_observed_flat_window']
        slots.extend({**meta, **r} for r in observed)
        trace.extend({**meta, **r} for r in states)
        monthly.extend(D.grouped(report['actual2026_daily_atoms'], ['policy', 'month']))
        completed = report['lifecycle']['actual_completed_cycles']
        for row in observed:
            earlier = [r for r in completed if r['D'] <= row['slot_D']]
            transitions.append({**meta, 'slot_D': row['slot_D'], 'previous_completed_actual_record': earlier[-1] if earlier else None,
                                'own_last_completed_net_unit_D': row['last_completed_net_unit_known_D'],
                                'observed_next_actual_entry_E': row['next_actual_BUY_E'],
                                'only_actual_completed_history_and_observed_next_entry': True})
    outputs = [S.csv_output('shock_2026_actual_pause_slots.csv', slots), S.csv_output('shock_2026_pause_candidate_trace.csv', trace),
               S.csv_output('shock_2026_monthly.csv', monthly)]
    grouped = defaultdict(list)
    for row in slots:
        grouped[row['shock_profile']].append(row)
    result = {'status': 'PASS_ACTUAL_OBSERVED_CHAINS', 'sources': [S.ref(OUT / f'shock_account_{i:03d}_independent_review.json') for i in (0, 1)],
              'implementation': S.ref(Path(__file__).resolve()), 'frozen_trace_implementation': S.ref(Path(D.__file__).resolve()),
              'outputs': outputs, 'own_completion_to_slot_chain': transitions,
              'summary': {p: {'actual_slots': len(rows), 'right_censored_slots': sum(r['next_entry_right_censored_by_cutoff'] for r in rows),
                              'observed_full_flat_sessions_until_next_actual_entry': sum(r['observed_flat_sessions_until_next_entry_or_cutoff'] for r in rows),
                              'observed_BH_net_pp': sum(r['actual_BH_net_pp_in_observed_flat_window'] for r in rows)} for p, rows in grouped.items()},
              'new_checks': sum(A.COUNTS.values()), 'trace_checks': sum(D.CHECKS.values()),
              'limits': ['All windows start from actual consumed slots; repeated states are not independent trade events.',
                         'Other-policy sameD posture is a factual actual-state comparison, not a hypothetical skipped BUY result.',
                         'Full-flat BH up/down occurs after D and is attribution only; it cannot become a D-known rule or recoverable return.',
                         'Final slot remains right-censored at10/15; no assumed future expiry, order, fill or wealth.',
                         'No source change, new data, fitted model, action search or account dispatch.']}
    path = OUT / 'shock_pause_actual_review.json'
    S.H.write(path, result)
    print(json.dumps({'review': S.ref(path), 'summary': result['summary'], 'outputs': outputs}))


if __name__ == '__main__':
    main()
