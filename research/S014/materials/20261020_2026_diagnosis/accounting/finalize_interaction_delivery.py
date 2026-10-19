"""Exact EX048 accounting delivery, no mixed EX047 publication scope."""
import json

import consolidate_interaction_audit as S


def main():
    out, A = S.OUT, S.A
    summary = A.read(out / 'independent_interaction_audit_summary.json')
    source_names = ['review_interaction_source.py', 'review_interaction_runner.py', 'review_interaction_public_lock.py',
                    'interaction_account_common.py', 'interaction_lifecycle.py', 'audit_interaction_accounts.py', 'consolidate_interaction_audit.py',
                    'attribute_interaction_pause_actuals.py', 'interaction_four_cell_actuals.py', 'write_interaction_findings.py', 'finalize_interaction_delivery.py']
    report_names = ['interaction_evaluation_protocol.json', 'interaction_source_review.json', 'interaction_runner_pre_review.json',
                    'interaction_public_lock_review.json', 'interaction_account_000_independent_review.json', 'interaction_account_001_independent_review.json',
                    'independent_interaction_audit_summary.json', 'interaction_pause_actual_review.json', 'interaction_four_cell_review.json',
                    'interaction_research_findings.json', 'interaction_readout.md']
    outputs = list(summary['outputs'])
    for filename in ['interaction_pause_actual_review.json', 'interaction_four_cell_review.json', 'interaction_research_findings.json']:
        outputs.extend(A.read(out / filename)['outputs'])
    expected = [S.ref(out / name) for name in source_names + report_names] + outputs
    A.check('exact new-family delivery unique files', len(expected) == len({r['path'] for r in expected}))
    for value in expected:
        A.check('all new-family delivery bytes frozen', S.ref(S.ROOT / value['path'])['sha256'] == value['sha256'])
    prior = out / 'shock_final_accounting_delivery.json'
    A.check('prior EX047 manifest byte preserved', S.ref(prior)['sha256'] == 'f31a26581747995871f9cb7f5c282ed5858f80dd26c0c00f3025084c6d4b0a90')
    result = {'status': 'COMPLETE', 'experiment': 'EX048_20261020', 'files': expected, 'file_count_excluding_this_manifest': len(expected),
              'summary': S.ref(out / 'independent_interaction_audit_summary.json'), 'account_reports': summary['account_reports'],
              'resources': summary['resource_accounting'], 'independent_actual_checks': summary['independent_actual_checks'], 'independent_phase_checks': summary['independent_phase_checks'],
              'original_annual_goal_counts': {'AFTER_NET_LOSS_SKIP1': {'return': '5/7', 'drawdown': '7/7', 'frequency': True}, 'BASE': {'return': '5/7', 'drawdown': '6/7', 'frequency': True}},
              'all_original_goals_pass': False, 'BASE_original2026_return_gate_pass': True, 'BASE2026_original_gate_margin_pp': 0.2720589690974329,
              'new_margin_hard_gate': False, 'registration_or_activation': False,
              'prior_EX047_delivery_readonly_reference_not_republished_here': S.ref(prior),
              'four_cell_reused_actuals': A.read(out / 'interaction_four_cell_review.json')['sources'],
              'verification': '11 explicit new Python sources Ruff PASS; two funded accounts independently audited at exact public resolver, own completion signs and all original7years/frequency. No warehouse export, market supplier, new model or repo-wide regression.',
              'publication_scope': 'Only listed43 files plus this manifest; EX047 shock/actual files and root report excluded. No glob expansion.',
              'next_step': 'Retain C9461 and all frozen counterexamples; complete local-public evidence and root review. No more actual accounts in this round.'}
    A.check('declared43 material files exact', len(expected) == 43)
    path = out / 'interaction_final_accounting_delivery.json'
    S.H.write(path, result)
    print(json.dumps({'delivery': S.ref(path), 'files': len(expected), 'actual_checks': result['independent_actual_checks'], 'phase_checks': result['independent_phase_checks']}))


if __name__ == '__main__':
    main()
