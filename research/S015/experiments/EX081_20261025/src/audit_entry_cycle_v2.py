"""Audit complete successor traces without changing the preserved first audit."""
from __future__ import annotations

import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

from audit_entry_cycle import HOME, ROOT, comparable, evidence, read
from strategy_runtime.entry_cycle import EntryCycleState


def main(report_path, design_path, output):
    if output.exists():
        raise FileExistsError('Preserve prior audit; choose a new output path')
    report, design = read(report_path), read(design_path)
    cases = {x['case_id']: x for x in report['pte_runtime']['cases']}
    protocol = json.loads(evidence(report['protocol']))
    declared = {x['scenario_id']: x for x in protocol['pte']['scenarios']}
    expected_scenarios = design['expected_entry_cycle_states']
    if set(declared) != set(expected_scenarios):
        raise ValueError('Design and authenticated protocol scenario sets differ')
    if set(declared) != {'c9304_partial_full_cycle', 'c9304_partial_cancel_blocked'}:
        raise ValueError('Unexpected successor scenario scope')
    if any(x['restart_after'] != ['entry_partial'] for x in declared.values()):
        raise ValueError('This audit covers restart after partial fill only')
    coverage = json.loads(evidence(cases['pte-coverage']['evidence'][0]))
    artifacts = {x['artifact_id']: x for x in coverage['artifacts']}
    results, traces, comparisons = [], {}, []
    for sid, expected in expected_scenarios.items():
        checkpoints = {x['after_event_id']: x for x in declared[sid]['checkpoints']}
        if set(checkpoints) != set(expected):
            raise ValueError('Cycle expectations must cover every declared checkpoint')
        if sid == 'c9304_partial_cancel_blocked':
            if (checkpoints['entry_cancelled']['health'] != 'BLOCKED'
                    or {x['step_id'] for x in declared[sid]['decisions']} != {'enter'}):
                raise ValueError('Cancellation scope must end blocked without retry decisions')
        for variant in ('restart', 'continuous'):
            artifact = artifacts[f'{sid}:{variant}:trace.jsonl']
            raw = evidence(artifact['reference'])
            if sha256(raw).hexdigest() != artifact['sha256']:
                raise ValueError('Artifact hash differs from public reference')
            rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
            traces[sid, variant] = rows
            errors, seen, identities, nonempty = [], [], set(), 0
            for row in rows:
                event = row['event_id']
                seen.append(event)
                if event not in expected:
                    errors.append(f'{event}: unexpected event')
                    continue
                desired, snapshot = expected[event], row['snapshot']
                if snapshot['health'] != checkpoints[event]['health']:
                    errors.append(f'{event}: health differs from declared checkpoint')
                actual = snapshot['entry_cycle']
                if desired is None:
                    if actual is not None or snapshot['cycle_target_quantity'] is not None:
                        errors.append(f'{event}: expected no cycle')
                    continue
                if actual is None:
                    errors.append(f'{event}: missing cycle')
                    continue
                state = EntryCycleState.from_dict(actual)
                nonempty += 1
                identities.add((state.cycle_id, state.opening_signal_identity))
                for name in ('allocation_fraction', 'cash_budget', 'buy_cost_including_fees', 'remaining_budget'):
                    if getattr(state, name) != Decimal(desired[name]):
                        errors.append(f'{event}: {name} differs')
                if state.target_quantity != desired['target_quantity'] or snapshot['cycle_target_quantity'] != state.target_quantity:
                    errors.append(f'{event}: cycle/account target differs')
                if state.phase.value != desired['phase']:
                    errors.append(f'{event}: phase differs')
            missing = sorted(set(expected) - set(seen))
            if len(seen) != len(set(seen)):
                errors.append('Duplicate events')
            if nonempty and len(identities) != 1:
                errors.append('Cycle/opening identity changed within one opportunity')
            complete = not missing and not errors and cases[sid]['status'] == 'PASS'
            results.append({
                'scenario_id': sid, 'variant': variant,
                'status': 'PASS' if complete else 'FAIL' if errors else 'INCOMPLETE',
                'official_scenario_status': cases[sid]['status'],
                'trace_reference': artifact['reference'], 'trace_sha256': artifact['sha256'],
                'expected_event_count': len(expected), 'observed_event_count': len(rows),
                'observed_nonempty_cycle_states': nonempty, 'identity_pair_count': len(identities),
                'missing_events': missing, 'errors': errors,
                'last_observed_event': seen[-1] if seen else None,
            })
        equal = comparable(traces[sid, 'restart']) == comparable(traces[sid, 'continuous'])
        complete = all(x['status'] == 'PASS' for x in results if x['scenario_id'] == sid)
        comparisons.append({
            'scenario_id': sid, 'restart_after': declared[sid]['restart_after'],
            'observed_business_state_equality': equal,
            'status': 'PASS' if complete and equal else 'INCOMPLETE',
            'declared_recovery_scope_demonstrated': complete and equal,
        })
    passed = (report['pte_runtime']['status'] == 'PASS'
              and all(x['status'] == 'PASS' for x in results)
              and all(x['status'] == 'PASS' for x in comparisons))
    result = {
        'status': 'PASS' if passed else 'NOT_PASSED', 'inspection_run_id': report['run_id'],
        'report_path': report_path.relative_to(ROOT).as_posix(),
        'report_file_sha256': sha256(report_path.read_bytes()).hexdigest(),
        'design_path': design_path.relative_to(ROOT).as_posix(),
        'design_file_sha256': sha256(design_path.read_bytes()).hexdigest(),
        'protocol_reference': report['protocol'],
        'official_pte_status': report['pte_runtime']['status'],
        'method': 'Authenticate public trace/protocol references; check all predeclared Decimal cycle economics, target, phase, health and event completeness; compare full restart/continuous business snapshots.',
        'results': results, 'restart_comparisons': comparisons,
        'supported_if_pass': [
            'Complete positive opportunity: zero/partial/full fills, hold, EXITING, full exit and restart after partial fill.',
            'Cancellation path: restart after partial fill, then reconcile cancellation to BLOCKED while retaining actual holdings and entry-cycle budget/target.',
        ],
        'not_covered': [
            'Restart after cancellation.',
            'Operator acknowledgement, subsequent replenishment or automatic recovery from BLOCKED.',
            'Forward-date operation, independent economic validation, freeze or live deployment approval.',
        ],
        'preservation': 'The original first-run FAIL and entry_cycle_audit_first.json remain unchanged.',
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'traces': len(results),
                      'complete_trace_passes': sum(x['status'] == 'PASS' for x in results)}))
    if not passed:
        raise SystemExit('Successor audit did not meet complete official-PASS requirements')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=HOME / 'others/inspection_report_v2.json')
    parser.add_argument('--design', type=Path, default=HOME / 'others/pte_design_v2.json')
    parser.add_argument('--output', type=Path, default=HOME / 'others/entry_cycle_audit_v2.json')
    args = parser.parse_args()
    main(args.report.resolve(), args.design.resolve(), args.output.resolve())
