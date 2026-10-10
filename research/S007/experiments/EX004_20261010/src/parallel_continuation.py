"""Explicit disjoint continuation within the prospectively declared worker cap."""
import argparse
from hashlib import sha256

from aligned_common import ROOT, PROTOCOLS, runs, read, write, material
from czsc_trader.research_tools import EvidenceRef


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('declare', 'join'))
    args = parser.parse_args()
    root = runs('S013')
    spec = read(PROTOCOLS/'plan.json')['strategies']['S013']
    identifiers = list(dict.fromkeys(x['candidate_id'] for x in spec['cases'] if 'candidate_id' in x))
    if args.action == 'declare':
        assert not (root/'parallel_decision_reference.json').exists()
        panel = read(root/'panel_rebound.json')
        assert panel['count'] == len(panel['rows']) == 20
        assert all(x['status'] == 'SUCCEEDED' for x in panel['rows'])
        ref = material('aligned-single-queue-completed-predecessor', root/'panel_rebound.json', 'S013')
        decision = {'explicit_researcher_decision': True, 'automatic_retry_or_fallback': False,
            'predecessor': ref.to_dict(), 'completed_preserved': panel['count'],
            'reason': 'Single-queue full-account runs cost about90s per4 points. Stop identified '
                      'research parent23808 and continue exact fixed IDs in three disjoint single-worker '
                      'processes; no operating process from other tasks is changed.',
            'stopped_process_unpublished_next_ids': identifiers[20:24],
            'remaining_fixed_points': 143, 'workers_total': 3, 'original_cap': 4,
            'assignment': 'prospective unique point index modulo3; all completed IDs reused',
            'shards': {str(i): identifiers[i::3] for i in range(3)},
            'unchanged': 'All domains, point values, identities, implementations, inputs, costs, '
                         'windows and diagnostic formulas; no observed economic results select points.'}
        write(root/'parallel_decision.json', decision)
        write(root/'parallel_decision_reference.json', material('aligned-disjoint-parallel-decision',
            root/'parallel_decision.json', 'S013').to_dict())
        print({'status': 'DECLARED', 'completed_reused': 20, 'remaining': 143, 'workers': 3})
        return
    decision = read(root/'parallel_decision.json')
    assert decision['workers_total'] == 3
    rows = {}
    refs = []
    for index in range(3):
        working = root/f'shard-{index}'
        panel = read(working/'panel_rebound.json')
        assert panel['status'] == 'COMPLETE'
        assert len(panel['rows']) == len({x['candidate_id'] for x in panel['rows']}) == panel['count']
        assert {x['candidate_id'] for x in panel['rows']} == set(decision['shards'][str(index)])
        assert all(x['status'] == 'SUCCEEDED' for x in panel['rows'])
        assert not set(rows).intersection(x['candidate_id'] for x in panel['rows'])
        rows.update((x['candidate_id'], x) for x in panel['rows'])
        reference = read(working/'panel_rebound_reference.json')
        authenticated = EvidenceRef.from_dict(reference)
        assert sha256(authenticated.resolve(ROOT).read_bytes()).hexdigest() == authenticated.sha256
        assert read(authenticated.resolve(ROOT)) == panel
        refs.append(reference)
    assert set(rows) == set(identifiers) and len(rows) == 163
    for row in read(root/'panel_rebound.json')['rows']:
        assert row == rows[row['candidate_id']]
    panel = {'strategy': 'S013', 'plan': read(PROTOCOLS/'plan_reference.json'),
        'count': 163, 'total': 163, 'status': 'COMPLETE',
        'rows': [rows[k] for k in identifiers],
        'explicit_parallel_decision': read(root/'parallel_decision_reference.json'),
        'shard_complete_references': refs}
    write(root/'panel_rebound.json', panel)
    write(root/'panel_rebound_reference.json', material('aligned-complete-point-panel-rebound',
        root/'panel_rebound.json', 'S013').to_dict())
    print({'status': 'COMPLETE', 'count': 163, 'repository': ROOT.as_posix()})


if __name__ == '__main__':
    main()
