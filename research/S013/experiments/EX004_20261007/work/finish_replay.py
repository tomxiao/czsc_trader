"""Verify all original configurations have a successful account after explicit retry."""
import json
from common import WORK, save
from search import configuration_hash


def main():
    plan = json.loads((WORK / 'replay_plan.json').read_text(encoding='utf-8'))
    rows = json.loads((WORK / 'search_results.json').read_text(encoding='utf-8'))['rows']
    success = {r['config_hash']: r for r in rows if r['status'] == 'SUCCEEDED'}
    comparisons = []
    for config in plan['configurations']:
        row = success[configuration_hash(config['parameters'])]
        comparisons.append({'label': config['label'], 'candidate_id': row['candidate_id'],
                            'result_hash': row['result_hash'], 'search': row['search']})
    failed = [r for r in rows if r['status'] != 'SUCCEEDED']
    retries = []
    for row in failed:
        replacement = success[row['config_hash']]
        assert replacement['trial_attributes']['explicit_retry_of'] == row['candidate_id']
        retries.append({'unknown_candidate_id': row['candidate_id'],
                        'successor_candidate_id': replacement['candidate_id'],
                        'config_hash': row['config_hash'], 'original_error': row['error']})
    save('all_replay_comparisons.json', {'status': 'COMPLETE', 'comparisons': comparisons,
        'original_plan_configurations': len(plan['configurations']),
        'successful_unique_configurations': len(success), 'unknown_attempts_preserved': len(failed),
        'explicit_retry_successors': retries,
        'studies': sorted({r['search'] for r in rows if r['search'] != 'hfq_initial'})})
    print(json.dumps({'completed': len(comparisons), 'unknown_preserved': len(failed),
                      'all_explicit_retries_succeeded': True}), flush=True)


if __name__ == '__main__':
    main()
