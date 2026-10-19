"""Freeze the precise original-population/component delivery, not future policies."""
import json
from pathlib import Path

import authenticate_shock_population as P


def main():
    names = '''authenticate_shock_population.py
original_shock_population.csv
original_shock_population_yearly.csv
original_shock_population_review.json
local_cycle_method_alignment.json
local_cycle_method_review.json
local_cycle_oracle.py
local_input_reader.py
local_source_review.py
local_source_review.json
local_runner_review.py
local_runner_review.json
local_public_lock_review.py
local_public_lock_review.json
local_on_independent_audit.py
local_on_independent_failure.json
local_on_independent_audit_v2.py
local_on_independent_review.json
local_on_timestamp_correction.json
local_off_independent_audit.py
local_off_independent_review.json
local_event_labels.csv
local_state_summary.csv
local_write_findings.py
local_research_findings.json
local_readout.md
local_finalize_delivery.py'''.splitlines()
    on = P.read(P.OUT / 'local_on_independent_review.json')
    off = P.read(P.OUT / 'local_off_independent_review.json')
    assert on['status'].startswith('PASS') and off['status'].startswith('PASS')
    assert on['ON_ref'] == off['ON_ref']
    assert on['source_lock_sha256'] == off['source_lock_sha256'] == '3ce1292b28b7469a2332f268b573861f4f8364b97622d02bf6895c73b0317c90'
    checks = {name: P.read(P.OUT / name)['check_count'] for name in ['local_source_review.json', 'local_runner_review.json', 'local_public_lock_review.json', 'local_on_independent_review.json', 'local_off_independent_review.json']}
    report = {'status': 'COMPLETE', 'experiment': 'EX049_20261020', 'reviewer': 'A', 'files': [P.ref(P.OUT / name) for name in names],
              'material_count_excluding_this_manifest': len(names), 'material_count_including_this_manifest': len(names) + 1,
              'source_lock_sha256': off['source_lock_sha256'], 'ON_ref': off['ON_ref'], 'OFF_ref': off['OFF_ref'],
              'review_check_counts': checks, 'N': 21, 'closed_OFF_labels': 21, 'unknown': 0, 'censored': 0,
              'actual_funded_dispatches': 0, 'funded_success': 0, 'funded_failed': 0, 'funded_unknown': 0, 'funded_retries': 0,
              'new_fits': 0, 'new_supplier_calls': 0, 'new_preparations': 0,
              'audit_expression_corrections': 1,
              'preserved_incident': 'Original ON literal timestamp representation failure/helper plus exact Timestamp successor and correction note are all included; no component/account execution failed or was rerun.',
              'scope': 'Original21 population and same21 ON/OFF local components only. No future full-policy method/source/account material included.',
              'implementation': P.ref(Path(__file__).resolve())}
    print(json.dumps(P.save('local_final_accounting_delivery.json', report)))


if __name__ == '__main__':
    main()
