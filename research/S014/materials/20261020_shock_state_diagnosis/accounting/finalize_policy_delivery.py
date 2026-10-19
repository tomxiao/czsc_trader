"""Precise EX050 accounting delivery; old EX049 files remain separate."""
import json
from pathlib import Path

import policy_account_common as C
from consolidate_policy_audit import ref


def main():
    names = '''policy_evaluation_protocol.json
review_policy_source.py
policy_source_review.json
review_policy_runner.py
policy_runner_pre_review.json
review_policy_public_lock.py
policy_public_lock_review.json
policy_account_common.py
policy_lifecycle.py
audit_policy_accounts.py
consolidate_policy_audit.py
policy_account_000_independent_review.json
policy_account_001_independent_review.json
policy_account_002_independent_review.json
independent_policy_audit_summary.json
write_policy_findings.py
policy_research_findings.json
policy_readout.md
policy_key_actual_cycles.csv
finalize_policy_delivery.py'''.splitlines()
    summary = C.A.read(C.OUT / 'independent_policy_audit_summary.json')
    assert summary['status'] == 'PASS'
    for value in summary['outputs']:
        path = C.ROOT / value['path']
        assert path.parent == C.OUT and ref(path)['sha256'] == value['sha256']
        if path.name not in names:
            names.append(path.name)
    for value in summary['account_reports']:
        assert ref(C.ROOT / value['path'])['sha256'] == value['sha256']
    result = {'status': 'COMPLETE', 'experiment': 'EX050_20261020', 'files': [ref(C.OUT / name) for name in names],
              'material_count_excluding_manifest': len(names), 'material_count_including_manifest': len(names) + 1,
              'source_sha256': C.SOURCE_SHA, 'source_lock_ref': summary['source_lock_ref'],
              'formal_accounts_index_ref': summary['formal_accounts_index_ref'], 'account_reports': summary['account_reports'],
              'resource_accounting': summary['resource_accounting'], 'independent_actual_checks': summary['independent_actual_checks'],
              'independent_phase_checks': summary['independent_phase_checks'], 'consolidation_checks': summary['consolidation_checks'],
              'reused_frozen_dependencies': [ref(C.ROOT / path) for path in [
                  'research/S014/materials/20261020_preentry_diagnosis/accounting/audit_pause_accounts.py',
                  'research/S014/materials/20261020_preentry_diagnosis/accounting/pause_financial_audit.py',
                  'research/S014/materials/20261020_shock_state_diagnosis/accounting/local_input_reader.py',
                  'research/S014/materials/20261020_shock_state_diagnosis/accounting/authenticate_shock_population.py']],
              'scope': 'Only three original-contract full funded policies. EX049 component originals and late local delivery are not overwritten or included in this family.',
              'conclusion': 'No account meets all original goals. Age policy passes2026 but fails2025 return; no registration/eligibility edit or phase advancement.',
              'implementation': ref(Path(__file__).resolve())}
    path = C.OUT / 'policy_final_accounting_delivery.json'
    C.H.write(path, result)
    print(json.dumps({'manifest': ref(path), 'files_excluding_self': len(names), 'resources': summary['resource_accounting']}))


if __name__ == '__main__':
    main()
