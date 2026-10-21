"""Validate the final declared research inventory without running new accounts."""
import json
import re
import subprocess
import sys
from hashlib import sha256
from run_supplement import ROOT, EROOT, WORK, save


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    phases = ('initial', 'followup', 'boundary')
    rows = sum((read(WORK / f'{phase}_results.json') for phase in phases), [])
    a = read(WORK / 'analysis.json')
    d = read(WORK / 'account_diagnostics.json')
    regs = read(EROOT / 'others/registrations.json')
    assert a['published_snapshot_complete'] and len(rows) == 97
    assert len({r['candidate_id'] for r in rows}) == 97
    assert len({json.dumps(r['parameters'], sort_keys=True) for r in rows}) == 97
    for phase in phases:
        trials = read(WORK / f'optuna_{phase}_trials.json')
        assert len(trials) == a['source_counts'][phase]
        assert all(t['state'] == 'TrialState.COMPLETE' for t in trials)
    passed = {r['candidate_id'] for r in rows if r['passed']}
    assert len(passed) == 73
    assert {r['candidate_id'] for r in regs} == passed | set(a['frontier'])
    assert {r['candidate_id'] for r in regs if r['handoff']} == passed
    assert len(regs) == 77
    assert all(x['cashflow_reconciliation'] == 'PASS' and
               x['signal_age_independent_of_target_check'] == 'PASS' for x in d.values())
    assert all(x['status'] == 'PASS' and x['rows'] == 434 for x in a['cycle_control_continuity'])
    check = subprocess.run([sys.executable, '-m', 'ruff', 'check', str(EROOT / 'src')],
                           cwd=ROOT, capture_output=True, text=True, check=True)
    save(EROOT / 'others/final_checks.json', {
        'status': 'PASS', 'scope': 'EX004 focused research checks, not platform regression or stage-four acceptance',
        'configuration_count': len(rows), 'unique_parameter_count': 97, 'completed_optuna_trials': 97,
        'center_passed': len(passed), 'registrations': len(regs), 'cumulative_handoff': len(passed) + 25,
        'evidence_sha_and_input_binding_identity': '97 PASS (analyze_supplement)',
        'cash_and_closed_cycle_share_reconciliation': '97 PASS', 'signal_age_reconstruction': '97 PASS',
        'old_cycle_exact_economic_continuity': a['cycle_control_continuity'],
        'candidate_load_and_content_identity': '77 PASS (register_supplement)',
        'synthetic_signal_checks': read(EROOT / 'others/strategy_checks.json'),
        'daily_input_continuity': read(EROOT / 'others/input_continuity.json'),
        'ruff': check.stdout.strip(),
        'strategy_source_sha256': sha256((EROOT / 'src/strategy_runtime/strategies/range_weight_reversal.py').read_bytes()).hexdigest(),
        'read_only_method_review': '97 EvidenceRef SHA and counts checked by s015_supplement_method; limited risk improvement supported, return increment not replicated at second entry anchor; stage-three closeout justified.',
        'not_performed': ['repository_full_regression', 'stage_four', 'fee_stress', 'freeze', 'PTE', 'production_change']})
    links = re.findall(r'\]\(([^)]+)\)', (EROOT / 'report.md').read_text(encoding='utf-8'))
    assert all(not link.startswith(('http', '/', 'D:', 'C:')) and (EROOT / link.split('#')[0]).exists()
               for link in links), links
    print(json.dumps({'status': 'PASS', 'relative_report_links': len(links), 'ruff': check.stdout.strip()}))


if __name__ == '__main__':
    main()
