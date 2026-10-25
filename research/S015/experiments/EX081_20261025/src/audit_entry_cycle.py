"""Audit saved public PTE traces against the independently frozen cycle facts."""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

from strategy_manager.freeze_contracts import ResearchEvidenceRef
from strategy_runtime.entry_cycle import EntryCycleState


ROOT = Path(__file__).resolve().parents[5]
HOME = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def evidence(reference):
    ref = ResearchEvidenceRef.from_dict(reference)
    raw = ref.resolve(ROOT).read_bytes()
    if sha256(raw).hexdigest() != reference['sha256']:
        raise ValueError('Published evidence hash differs')
    return raw


def comparable(trace):
    """Ignore only channel-generated identifiers/timestamps, not cycle state."""
    result = []
    for row in trace:
        value = deepcopy(row['snapshot'])
        for order in value['channel']['orders']:
            for key in ('channel_order_id', 'remark', 'created_at', 'updated_at'):
                order.pop(key, None)
        result.append({'event_id': row['event_id'], 'snapshot': value})
    return result


def main(report_path, design_path, output):
    if output.exists():
        raise FileExistsError('Preserve existing audit; choose a new output path')
    report, design = read(report_path), read(design_path)
    cases = {x['case_id']: x for x in report['pte_runtime']['cases']}
    coverage = json.loads(evidence(cases['pte-coverage']['evidence'][0]))
    artifacts = {x['artifact_id']: x for x in coverage['artifacts']}
    results, traces, comparisons = [], {}, []
    for sid, expected in design['expected_entry_cycle_states'].items():
        for variant in ('restart', 'continuous'):
            artifact_id = f'{sid}:{variant}:trace.jsonl'
            item = artifacts[artifact_id]
            raw = evidence(item['reference'])
            if sha256(raw).hexdigest() != item['sha256']:
                raise ValueError('Artifact hash differs from its public reference')
            rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
            traces[sid, variant] = rows
            errors, seen, identities = [], [], set()
            nonempty = 0
            for row in rows:
                event = row['event_id']
                seen.append(event)
                if event not in expected:
                    errors.append(f'{event}: unexpected event')
                    continue
                desired, snapshot = expected[event], row['snapshot']
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
                if state.target_quantity != desired['target_quantity']:
                    errors.append(f'{event}: target quantity differs')
                if snapshot['cycle_target_quantity'] != state.target_quantity:
                    errors.append(f'{event}: account target differs from cycle')
                if state.phase.value != desired['phase']:
                    errors.append(f'{event}: cycle phase differs')
            duplicates = sorted({x for x in seen if seen.count(x) > 1})
            missing = sorted(set(expected) - set(seen))
            if duplicates:
                errors.append('Duplicate events: ' + ','.join(duplicates))
            if nonempty and len(identities) != 1:
                errors.append('Cycle/opening identity changed within one opportunity')
            complete = not missing and not errors
            results.append({
                'scenario_id': sid, 'variant': variant,
                'status': 'PASS' if complete else 'MISMATCH' if errors else 'INCOMPLETE',
                'official_scenario_status': cases[sid]['status'],
                'trace_reference': item['reference'], 'trace_sha256': item['sha256'],
                'expected_event_count': len(expected), 'observed_event_count': len(rows),
                'observed_nonempty_cycle_states': nonempty, 'observed_fields_match': not errors,
                'identity_pair_count': len(identities), 'missing_events': missing,
                'last_observed_event': seen[-1] if seen else None, 'errors': errors,
                'limit': None if complete else 'Only persisted events were checked. Missing events and the failure checkpoint are not accepted as passed.',
            })
        selected = [x for x in results if x['scenario_id'] == sid]
        equal = comparable(traces[sid, 'restart']) == comparable(traces[sid, 'continuous'])
        full = all(x['status'] == 'PASS' for x in selected)
        comparisons.append({
            'scenario_id': sid, 'observed_trace_business_facts_equal': equal,
            'status': 'PASS' if full and equal and cases[sid]['status'] == 'PASS' else 'INCOMPLETE',
            'full_recovery_demonstrated': full and equal and cases[sid]['status'] == 'PASS',
            'limit': None if full else 'Matching prefixes do not demonstrate the planned restart or subsequent retry/exit.',
        })
    positive = 'c9304_partial_full_cycle'
    if not all(x['status'] == 'PASS' for x in results if x['scenario_id'] == positive):
        raise AssertionError('Positive full-cycle state audit did not pass')
    if not next(x for x in comparisons if x['scenario_id'] == positive)['full_recovery_demonstrated']:
        raise AssertionError('Positive full-cycle recovery equivalence did not pass')
    result = {
        'status': 'PARTIAL_SUPPORT', 'inspection_run_id': report['run_id'],
        'report_path': report_path.relative_to(ROOT).as_posix(),
        'report_file_sha256': sha256(report_path.read_bytes()).hexdigest(),
        'design_path': design_path.relative_to(ROOT).as_posix(),
        'design_file_sha256': sha256(design_path.read_bytes()).hexdigest(),
        'method': 'Public authenticated trace artifacts; exact Decimal cycle economics and target/phase against predeclared independent expectations; full business-state restart comparison.',
        'results': results, 'restart_comparisons': comparisons,
        'supported': 'First scenario: zero fill, partial fill, repeated report/decision, locked budget/target, remaining fill, hold, EXITING, complete market exit and persisted-state recovery.',
        'not_supported': 'Second scenario stops before the failed cancellation checkpoint is persisted. Cancellation state, restart after cancellation, next-day refill, later hold and exit remain unverified.',
        'interpretation': 'This supplementary audit does not override the official PTE FAIL or grant freeze/forward-runtime approval.',
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'traces': len(results),
                      'complete_trace_passes': sum(x['status'] == 'PASS' for x in results),
                      'partial_trace_count': sum(x['status'] == 'INCOMPLETE' for x in results),
                      'observed_state_mismatches': sum(len(x['errors']) for x in results)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=HOME / 'others/inspection_report.json')
    parser.add_argument('--design', type=Path, default=HOME / 'others/pte_design.json')
    parser.add_argument('--output', type=Path, default=HOME / 'others/entry_cycle_audit_first.json')
    args = parser.parse_args()
    main(args.report.resolve(), args.design.resolve(), args.output.resolve())
