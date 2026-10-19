"""Readonly EX049 public source lock and paired reviewer gate verification."""
import json
from pathlib import Path

import authenticate_shock_population as P

ROOT, OUT = P.ROOT, P.OUT
EX = ROOT / 'research/S014/experiments/EX049_20261020'


def main():
    lock_ref = P.read(EX / 'protocols/published_lock.json')
    lock = P.published(lock_ref)
    P.check('current public source lock local bytes exact', P.ref(EX / 'protocols/execution_lock.json')['sha256'] == lock_ref['sha256'])
    for name, digest in lock['source_hashes'].items():
        P.check('all source bytes exact ' + name, P.ref(EX / name)['sha256'] == digest)
    for name, digest in lock['external_source_hashes'].items():
        P.check('all original upstream bytes exact ' + name, P.ref(ROOT / name)['sha256'] == digest)
    map_path = EX / 'protocols/published_sources.json'
    P.check('current formal source map exact', P.ref(map_path)['sha256'] == lock['published_sources_sha256'])
    sources = P.read(map_path)
    for value in sources.values():
        if isinstance(value, dict) and value.get('type') == 'EvidenceRef':
            reference = P.EvidenceRef.from_dict(value)
            P.check('source formal byte ref exact', P.ref(reference.resolve(ROOT))['sha256'] == reference.sha256)
    P.check('component only no funded identity dispatch', lock['new_funded_account_budget'] == 0 and lock['component_event_count'] == 21)
    index_ref = P.read(EX / 'others/accounts_index_ref.json')
    index = P.published(index_ref)
    P.check('empty funded resource index explicit and public', index['records'] == [] and index['dispatched_count'] == 0 and P.ref(EX / 'others/accounts_index.json')['sha256'] == index_ref['sha256'])
    gate = P.read(EX / 'others/gate_source_review.json')
    P.check('sourcegate current source lock', gate['status'] == 'PASS' and gate['source_lock_sha256'] == lock_ref['sha256'])
    reviews = gate['reviews']
    P.check('two distinct independent source reviewer proofs', len(reviews) == len({r['sha256'] for r in reviews}) == 2 and {r['reviewer'] for r in reviews} == {'A', 'B'})
    runner = 'research/S014/experiments/EX049_20261020/src/run_component.py'
    for value in reviews:
        review = P.published(value['ref'])
        P.check('public reviewer exact current runner', review['status'].startswith('PASS') and value['sha256'] == value['ref']['sha256'] and review['reviewed_hashes'][runner] == P.ref(ROOT / runner)['sha256'])
        if value['reviewer'] == 'A':
            P.check('A final runner review actual exact', value['ref']['sha256'] == P.ref(OUT / 'local_runner_review.json')['sha256'])
    P.check('final originalON before any OFF labels', not (EX / 'others/off_labels.json').exists())
    result = {'status': 'PASS_PUBLIC_COMPONENT_SOURCE_LOCK', 'reviewer': 'A', 'source_lock_ref': lock_ref, 'source_lock_sha256': lock_ref['sha256'],
              'source_gate': gate, 'funded_index_ref': index_ref, 'checks': dict(P.CHECKS), 'check_count': sum(P.CHECKS.values()),
              'implementation': P.ref(Path(__file__).resolve()), 'allowed_next': 'Only original21 ON controls and D-known states; OFF still requires A+B actualON exact currentlock/ONref gates.',
              'new_funded_accounts': 0, 'actual_prepared_fetches': 0, 'new_real_OFF_labels': 0}
    print(json.dumps({'review': P.save('local_public_lock_review.json', result), 'checks': result['check_count']}))


if __name__ == '__main__':
    main()
