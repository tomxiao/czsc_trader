"""Exact EX051 population/audit/result delivery; no future EX052 materials."""
import json
from pathlib import Path

import anchor_account_common as C
from consolidate_anchor_audit import ref


def main():
    names = '''authenticate_hold_population.py
original_hold_population.csv
original_hold_population_review.json
population_method_review.json
anchor_method_review.json
anchor_evaluation_protocol.json
review_anchor_source.py
anchor_source_review.json
review_anchor_runner.py
anchor_runner_pre_review.json
review_anchor_public_lock.py
anchor_public_lock_review.json
anchor_account_common.py
anchor_lifecycle.py
audit_anchor_accounts.py
anchor_lifecycle_v2.py
audit_anchor_accounts_v2.py
anchor_projection_correction.json
review_anchor_revision.py
anchor_runner_v2_review.json
review_anchor_public_lock_v2.py
anchor_public_lock_review_v2.json
consolidate_anchor_audit.py
anchor_account_000_independent_review.json
anchor_account_001_independent_review.json
anchor_account_002_independent_review.json
independent_anchor_audit_summary.json
write_anchor_findings.py
anchor_research_findings.json
anchor_readout.md
anchor_actual_exit_cycles.csv
anchor_march_pause_chain.csv
finalize_anchor_delivery.py'''.splitlines()
    summary = C.A.read(C.OUT / 'independent_anchor_audit_summary.json')
    assert summary['status'] == 'PASS' and summary['resource_accounting']['actual_dispatched'] == 3
    for value in summary['outputs']:
        path = C.ROOT / value['path']
        assert path.parent == C.OUT and ref(path)['sha256'] == value['sha256']
        if path.name not in names:
            names.append(path.name)
    for value in summary['account_reports']:
        assert ref(C.ROOT / value['path'])['sha256'] == value['sha256']
    result = {'status': 'COMPLETE', 'experiment': 'EX051_20261020', 'files': [ref(C.OUT / name) for name in names],
              'material_count_excluding_manifest': len(names), 'material_count_including_manifest': len(names) + 1,
              'source_sha256': C.SOURCE_SHA, 'original_parent_source_lock_ref': summary['source_lock_ref'],
              'current_audit_revision_lock_ref': summary['current_audit_revision_lock_ref'],
              'actual_dispatch_lock_refs': summary['source_lock_refs_by_actual_dispatch'],
              'formal_accounts_index_ref': summary['formal_accounts_index_ref'], 'account_reports': summary['account_reports'],
              'resource_accounting': summary['resource_accounting'], 'independent_actual_checks': summary['independent_actual_checks'],
              'independent_phase_checks': summary['independent_phase_checks'], 'consolidation_checks': summary['consolidation_checks'],
              'technical_preservation': 'Original000 engine success/inlineKeyError/auditnull and v1 source/receipt/old Ahelpers all retained. Same original000 independent and supplemental audits pass; active1/2 actually usev2. Raw anchors reconstructed, not claimed directly observed.',
              'scope': 'Original C9502 population, fixed EX051 control/ZERO/frozen1ATR real accounts only. No future permission method/source/account or new local labels included.',
              'conclusion': 'No original full-goal pass. Both treatment2025 improve but still fail;2026 fails. Original seven-year/frequency goals unchanged.',
              'implementation': ref(Path(__file__).resolve())}
    path = C.OUT / 'anchor_final_accounting_delivery.json'
    C.H.write(path, result)
    print(json.dumps({'manifest': ref(path), 'files_excluding_self': len(names), 'actual_checks': summary['independent_actual_checks']}))


if __name__ == '__main__':
    main()
