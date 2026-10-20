"""Freeze only the already-audited EX052 accounting family; no economic replay."""
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
NAMES = [
    'permission_method_review.json', 'permission_evaluation_protocol.json',
    'review_permission_source.py', 'permission_source_review.json',
    'review_permission_runner.py', 'permission_runner_pre_review.json',
    'review_permission_public_lock.py', 'permission_public_lock_review.json',
    'permission_account_common.py', 'permission_lifecycle.py',
    'audit_permission_accounts.py', 'consolidate_permission_audit.py',
    'permission_account_000_independent_review.json',
    'permission_account_001_independent_review.json',
    'independent_permission_audit_summary.json',
    'permission_policy_yearly_summary.csv', 'permission_policy_summary.csv',
    'permission_policy_trigger_events.csv',
    'permission_policy_actual_completed_cycles.csv',
    'permission_policy_actual_suppressed_rows.csv',
    'permission_policy_2026_daily_atoms.csv',
    'permission_policy_2026_phase_summary.csv',
    'permission_policy_2026_phase_direction.csv',
    'permission_policy_2026_phase.csv',
    'permission_policy_2026_calendar_cycle_contributions.csv',
    'permission_policy_2026_actual_exit_decisions.csv',
    'permission_policy_2026_flat_D_states.csv',
    'permission_policy_2026_flat_reason_summary.csv',
    'permission_policy_2026_opening_ending.csv',
    'permission_policy_first_SHOCK_actual_cycles.csv',
    'permission_actual_events.csv', 'finalize_permission_delivery.py',
]


def reference(path):
    return {'path': path.relative_to(ROOT).as_posix(),
            'sha256': sha256(path.read_bytes()).hexdigest()}


def main():
    summary = json.loads((OUT / 'independent_permission_audit_summary.json').read_bytes())
    assert summary['status'] == 'PASS'
    assert len(NAMES) == len(set(NAMES))
    files = [reference(OUT / name) for name in NAMES]
    recorded = summary['outputs'] + summary['account_reports']
    actual = {r['path']: r['sha256'] for r in files}
    assert all(actual[r['path']] == r['sha256'] for r in recorded)
    result = {
        'status': 'COMPLETE', 'experiment': 'EX052_20261020',
        'files': files,
        'source_lock_ref': summary['source_lock_ref'],
        'formal_accounts_index_ref': summary['formal_accounts_index_ref'],
        'account_reports': summary['account_reports'],
        'resource_accounting': summary['resource_accounting'],
        'independent_actual_checks': summary['independent_actual_checks'],
        'independent_phase_checks': summary['independent_phase_checks'],
        'consolidation_checks': summary['consolidation_checks'],
        'conclusion': {
            'C9521_all_original_economic_goals_pass': True,
            'original_annual_return_pass': '7/7',
            'original_annual_drawdown_pass': '7/7',
            'original_frequency': 92 / 1642 * 60,
            'year2025_return': 0.47024043600024457,
            'year2026_partial_cutoff_return_not_annualized': 2.1162502188950367,
            'year2021_return': 1.5073896123091757,
            'year2021_control_return': 1.99385691516098,
            'terminal_equity': 1522765.4949999992,
            'control_terminal_equity': 1638378.7509999992,
        },
        'limits': [
            'Historical adaptive/shared-seen research; not untouched validation or independent S1 factor confirmation.',
            'Original seven annual gates include partial2026 through10/15 without annualization; no new buffer or non-harm gate.',
            '2021 opportunity cost and lower continuous terminal wealth than C9502 remain disclosed.',
            'No automatic candidate registration, stage transition, old eligibility edit, or production activation.',
            'EX051 negative accounts and original inline audit exception/correction remain in their separate immutable delivery.',
        ],
        'scope': 'Only EX052 two fixed actual accounts and existing independent source/control/economic evidence; no new accounts or labels.',
        'implementation': reference(Path(__file__).resolve()),
    }
    path = OUT / 'permission_final_accounting_delivery.json'
    with path.open('x', encoding='utf-8', newline='\n') as target:
        json.dump(result, target, ensure_ascii=False, indent=2)
        target.write('\n')
    print(json.dumps({'delivery': reference(path), 'files': len(files),
                      'including_delivery': len(files) + 1}, ensure_ascii=False))


if __name__ == '__main__':
    main()
