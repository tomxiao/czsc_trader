"""Reuse four authenticated funded policy cells; controls add no independent sample."""
import json
from pathlib import Path

import consolidate_interaction_audit as S


def main():
    prior = S.ROOT / 'research/S014/materials/20261020_preentry_diagnosis/accounting'
    specifications = [
        ('SHOCK_ON', 'BASE', prior / 'pause_account_000_independent_review.json', '6b18343c78a5a87636fc182472b32d193e644b2720e885cbafc282172dc3deaf'),
        ('SHOCK_ON', 'AFTER_NET_LOSS_SKIP1', prior / 'pause_account_001_independent_review.json', 'aa8c448637c66ee42fd3882f7bb009f74a884e0c14ad8bf3579df2a887e05ce3'),
        ('SHOCK_OFF', 'AFTER_NET_LOSS_SKIP1', S.OUT / 'interaction_account_000_independent_review.json', None),
        ('SHOCK_OFF', 'BASE', S.OUT / 'interaction_account_001_independent_review.json', None),
    ]
    annual, policies, sources = [], [], []
    for shock, pause, path, expected in specifications:
        if expected:
            S.A.check('immutable prior independent audit exact SHA', S.ref(path)['sha256'] == expected)
        report = S.A.read(path)
        account = S.A.published(report['account_ref'])
        S.A.check('four actual funded PASS results exact', report['status'] == 'PASS' and report['result_hash'] == account['result_hash'])
        S.A.check('four cells canonical pause identities', report['parameters']['pause_profile'] == pause)
        cell = {'shock_profile': shock, 'pause_profile': pause, 'diagID': report.get('diagID', 'S014-' + account['runs'][0]['candidate_id']),
                'source_experiment': account['request_identity']['experiment_id']}
        sources.append({**cell, 'independent_review': S.ref(path), 'account_ref': report['account_ref'], 'result_hash': report['result_hash']})
        rows = report['original_annual_goal_audit']
        S.A.check('seven original hardgate rows reused', [r['year'] for r in rows] == list(range(2020, 2027)))
        annual.extend({**cell, **{k: r[k] for k in ['year', 'opening_equity', 'closing_equity', 'return', 'max_drawdown', 'buyhold_return', 'buyhold_drawdown', 'required_return', 'return_pass', 'drawdown_pass']},
                       'original_partial2026_hard_gate': r['year'] == 2026} for r in rows)
        policies.append({**cell, 'nannual_return_pass': sum(r['return_pass'] for r in rows), 'nannual_drawdown_pass': sum(r['drawdown_pass'] for r in rows),
                         'original_frequency': report['summary']['frequency_full_contract'], 'original_frequency_pass': report['summary']['original_frequency_pass'],
                         'terminal_original_cutoff_equity': account['runs'][0]['ledgers']['account_daily']['data'][-1]['equity']})
    interactions = []
    for year in range(2020, 2027):
        values = {(r['shock_profile'], r['pause_profile']): r['return'] for r in annual if r['year'] == year}
        off = values[('SHOCK_OFF', 'BASE')] - values[('SHOCK_OFF', 'AFTER_NET_LOSS_SKIP1')]
        on = values[('SHOCK_ON', 'BASE')] - values[('SHOCK_ON', 'AFTER_NET_LOSS_SKIP1')]
        interactions.append({'year': year, 'BASE_minus_LOSS_at_fixed_SHOCK_OFF_pp': 100 * off,
                             'BASE_minus_LOSS_at_fixed_SHOCK_ON_pp': 100 * on, 'descriptive_difference_of_annual_policy_return_differences_pp': 100 * (off - on)})
    S.A.check('exact four policies and28 annual rows', len(policies) == 4 and len(annual) == 28)
    outputs = [S.csv_output('interaction_four_cell_yearly.csv', annual), S.csv_output('interaction_four_cell_summary.csv', policies),
               S.csv_output('interaction_descriptive_yearly_contrast.csv', interactions)]
    result = {'status': 'PASS_AUTHENTICATED_ACTUAL_REUSE', 'sources': sources, 'outputs': outputs,
              'implementation': S.ref(Path(__file__).resolve()), 'checks': sum(S.A.COUNTS.values()),
              'limits': ['Four economic policies, not six independent strategy trials; exact fresh controls do not increase independent evidence.',
                         'Each policy uses its own continuous money, completion feedback and annual opening. Difference of annual returns is descriptive policy interaction, not same-inventory local causal PnL.',
                         'All seven years have been seen; no fixed forecast, fitted coefficient, scan or holdout claim.',
                         'Old2026 audit technical label is not reused to delete the original2026 hard goal; original numeric return/DD/frequency counts retained.',
                         'No new source history replay, supplier call or actual account dispatch by this auditor.']}
    path = S.OUT / 'interaction_four_cell_review.json'
    S.H.write(path, result)
    print(json.dumps({'review': S.ref(path), 'outputs': outputs}))


if __name__ == '__main__':
    main()
