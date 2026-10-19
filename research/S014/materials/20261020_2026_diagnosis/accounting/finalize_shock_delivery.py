"""Exact EX047 accounting manifest, separated from prior diagnosis and future work."""
import json

import consolidate_shock_audit as S


def main():
    out, A = S.OUT, S.A
    summary = A.read(out / 'independent_shock_audit_summary.json')
    pause = A.read(out / 'shock_pause_actual_review.json')
    sources = ['review_shock_source.py', 'review_shock_runner.py', 'review_shock_public_lock.py',
               'shock_account_common.py', 'shock_lifecycle.py', 'audit_shock_accounts.py', 'consolidate_shock_audit.py',
               'attribute_shock_pause_actuals.py', 'write_shock_findings.py', 'finalize_shock_delivery.py']
    records = ['shock_evaluation_protocol.json', 'shock_source_review.json', 'shock_runner_pre_review.json',
               'shock_public_lock_review.json', 'shock_account_000_independent_review.json', 'shock_account_001_independent_review.json',
               'independent_shock_audit_summary.json', 'shock_pause_actual_review.json', 'shock_research_findings.json', 'shock_readout.md']
    expected = [S.ref(out / name) for name in sources + records] + summary['outputs'] + pause['outputs']
    A.check('exact delivery has no repeated path', len(expected) == len({r['path'] for r in expected}))
    for value in expected:
        A.check('all exact delivery bytes frozen', S.ref(S.ROOT / value['path'])['sha256'] == value['sha256'])
    prior_path = out / 'actual_2026_diagnosis_delivery.json'
    prior = A.read(prior_path)
    A.check('prior frozen original diagnosis preserved', S.ref(prior_path)['sha256'] == '19f457675552e09608c207b4946d3f37c020233c47175d287f165df844417d70')
    result = {'status': 'COMPLETE', 'experiment': 'EX047_20261020', 'files': expected, 'file_count_excluding_this_manifest': len(expected),
              'prior_actual_diagnosis_delivery': S.ref(prior_path), 'prior_original_diagnosis_file_count_including_manifest': len(prior['files']) + 1,
              'summary': S.ref(out / 'independent_shock_audit_summary.json'), 'account_reports': summary['account_reports'],
              'resources': summary['resource_accounting'], 'independent_actual_checks': summary['independent_actual_checks'],
              'independent_phase_checks': summary['independent_phase_checks'],
              'all_original_goals_pass': {'SHOCK_ON': False, 'SHOCK_OFF': False},
              'original_annual_gate_counts': {'SHOCK_ON': {'return': '6/7', 'drawdown': '7/7'}, 'SHOCK_OFF': {'return': '5/7', 'drawdown': '7/7'}},
              'registration_or_activation': False, 'not_included': 'Future interaction_* files and all other material families. No glob selects publication scope.',
              'verification': 'Ruff on these explicit10 Python sources; two actual full funded audits, original exact public execution resolver, all seven years and frequency.',
              'next_question': 'Fixed SHOCK_OFF and cost with only own-loss pause switched, subject to separate source/control and whole-path audit; no expected recoverable-return claim.'}
    path = out / 'shock_final_accounting_delivery.json'
    S.H.write(path, result)
    print(json.dumps({'delivery': S.ref(path), 'files': len(expected), 'prior_count': result['prior_original_diagnosis_file_count_including_manifest']}))


if __name__ == '__main__':
    main()
