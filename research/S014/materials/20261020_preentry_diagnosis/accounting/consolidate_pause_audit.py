"""Consolidate all three already audited EX046 outcomes; no new economic runs."""
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import io
import json
from pathlib import Path

import audit_pause_accounts as Q

ROOT, OUT, EX, A, H = Q.ROOT, Q.OUT, Q.EX, Q.A, Q.H


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def csv_output(name, rows, columns=None):
    columns = columns or list(dict.fromkeys(k for r in rows for k in r))
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    path = OUT / name
    with path.open('xb') as target:
        target.write(stream.getvalue().encode('utf-8'))
    return {**ref(path), 'rows': len(rows)}


def main():
    snapshot_ref = A.read(EX / 'others/accounts_index_ref.json')
    snapshot = A.published(snapshot_ref)
    records = snapshot['records']
    status_counts = Counter(r['status'] for r in records)
    dispatches = sorted((EX / 'others/dispatches').glob('*.json'))
    A.check('every dispatched receipt accounted', len(dispatches) == len(records))
    A.check('fixed three actual resource identities', len(records) == 3 and sorted(r['index'] for r in records) == [0, 1, 2])
    reviews, reports = [], []
    for index, params in enumerate(Q.FIXED):
        record = next(r for r in records if r['index'] == index)
        path = OUT / f'pause_account_{index:03d}_independent_review.json'
        report = A.read(path)
        A.check('all three actual successful and independent PASS', record['status'] == 'SUCCEEDED' and report['status'] == 'PASS')
        A.check('per-account exact formal identity', report['account_ref'] == record['evidence'] and report['result_hash'] == record['result_hash'] and report['parameters'] == params)
        _, actual_lock_ref = Q.run_lock(record)
        A.check('review same frozen source and own dispatch lock', report['source_sha256'] == Q.SOURCE_SHA and report['source_lock_sha256'] == actual_lock_ref['sha256'])
        A.check('per-review source helper bytes frozen', report['audit_implementation_sha256'] == ref(OUT / 'audit_pause_accounts.py')['sha256'] and report['financial_helper_sha256'] == ref(OUT / 'pause_financial_audit.py')['sha256'])
        reviews.append(ref(path))
        reports.append(report)
    yearly, policies, events, completed = [], [], [], []
    classes = defaultdict(list)
    economic_classes = defaultdict(list)
    for report in reports:
        profile = report['parameters']['pause_profile']
        meta = {'policy_id': report['policy_id'], 'hold_rule': 'ENTRY_GRACE', 'exit_rule': 'SHOCK_PROFIT',
                'entry_guard': 'BASE', 'exit_domain': 'POSITIVE_P', 'cost_stop': 'NET_LOSS_1ATR', 'pause_profile': profile}
        annual = [r for r in report['original_annual_goal_audit'] if 2020 <= r['year'] <= 2025]
        A.check('six complete natural years', len(annual) == 6)
        for row in annual:
            yearly.append({**meta, **{k: v for k, v in row.items() if k not in {'sessions', 'technical_only'}}})
        policies.append({**meta, **{k: v for k, v in report['summary'].items() if k != 'without2025_role'},
                         'nannual_joint_pass_2020_25': sum(r['return_pass'] and r['drawdown_pass'] for r in annual),
                         'nannual_return_pass_development2020_24': sum(r['return_pass'] for r in annual if r['year'] < 2025),
                         'nannual_drawdown_pass_development2020_24': sum(r['drawdown_pass'] for r in annual if r['year'] < 2025)})
        for event in report['lifecycle']['events']:
            events.append({**meta, **event})
        for event in report['lifecycle']['actual_completed_cycles']:
            completed.append({**meta, **event})
        classes[report['economic_path_hashes']['funded_wealth_2020_25_sha256']].append(profile)
        economic_classes[report['economic_path_hashes']['execution_economics_sha256']].append(profile)
    A.check('18 yearly and3 policy rows', len(yearly) == 18 and len(policies) == 3)
    outputs = [csv_output('pause_policy_yearly_summary.csv', yearly), csv_output('pause_policy_summary.csv', policies),
               csv_output('pause_policy_trigger_events.csv', events), csv_output('pause_actual_completed_cycles.csv', completed)]
    failures = [ref(path) for path in sorted(OUT.glob('pause_account_*_independent_failure*.json'))]
    successor = snapshot.get('control_supplement_ref')
    A.check('retained internal correction publicly supplemented', successor is not None)
    successor_result = A.published(successor)
    result = {'status': 'PASS', 'experiment': 'EX046_20261020', 'source_sha256': Q.SOURCE_SHA,
              'source_lock_ref': A.read(EX / 'protocols/published_lock_v2.json'),
              'original_BASE_dispatch_source_lock_ref': A.read(EX / 'protocols/published_lock.json'), 'formal_accounts_index_ref': snapshot_ref,
              'internal_control_correction_ref': successor, 'internal_control_correction': successor_result,
              'account_reports': reviews, 'outputs': outputs, 'policy_summary': policies,
              'resource_accounting': {'actual_dispatched': len(dispatches), 'SUCCEEDED': status_counts['SUCCEEDED'],
                                      'FAILED': status_counts['FAILED'], 'UNKNOWN': status_counts['UNKNOWN'],
                                      'other_status': {k: v for k, v in status_counts.items() if k not in {'SUCCEEDED', 'FAILED', 'UNKNOWN'}},
                                      'retries': len(records) - len({r['index'] for r in records}), 'source_specific_NOOP_accounts': 1,
                                      'new_active_profiles': 2, 'independent_audit_failure_records': failures,
                                      'original_internal_audit_expression_incidents': sum(r['executor_original_internal_audit_status'] != 'PASS' for r in reports),
                                      'fits': 0, 'new_supplier_calls': 0},
              'independent_actual_checks': sum(r['checks'] for r in reports), 'consolidation_checks': sum(A.COUNTS.values()),
              'original_economic_goal': 'Return and MDD each of2020-25 plus original fullwindow frequency; no added gate.',
              'funded_path_equivalence_classes_2020_25': [{'sha256': k, 'profiles': v} for k, v in classes.items()],
              'full_execution_economic_equivalence_classes': [{'sha256': k, 'profiles': v} for k, v in economic_classes.items()],
              'profile_lifecycle_counts': {r['policy_id']: r['lifecycle']['annual_D_counts'] for r in reports},
              'four_divergence_dates': {r['policy_id']: r['prefix'] for r in reports},
              'terminal2025_asof': {r['policy_id']: r['terminal2025_asof'] for r in reports},
              'implementation': ref(Path(__file__).resolve()),
              'interpretation_limits': ['All2020-25 previously seen development; without2025 is shared-seen aggregation.',
                                        'Positive/negative feedback pauses evolve their own entry/population/capital; not equal-dose randomized timing controls.',
                                        'Repeated armed days/slots are not independent trades; only actual positive-funded completed cycles count frequency.',
                                        '2026 original contract audit is technical tail, never selected economic endpoint.']}
    destination = OUT / 'independent_pause_audit_summary.json'
    H.write(destination, result)
    print(json.dumps({'summary': ref(destination), 'resources': result['resource_accounting'], 'checks': result['independent_actual_checks'], 'outputs': outputs}))


if __name__ == '__main__':
    main()
