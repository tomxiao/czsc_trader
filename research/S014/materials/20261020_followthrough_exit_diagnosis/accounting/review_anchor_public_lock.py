"""Readonly public EvidenceRef byte and fixed-identity check, before BASE."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
EX = ROOT / 'research/S014/experiments/EX051_20261020'
CHECKS = []


def check(name, value):
    assert value, name
    CHECKS.append(name)


def public(value):
    ref = EvidenceRef.from_dict(value)
    raw = ref.resolve(ROOT).read_bytes()
    check('public immutable SHA', sha256(raw).hexdigest() == ref.sha256 and ref.experiment.strategy_id == 'S014')
    return raw


def main():
    lock_ref = json.loads((EX / 'protocols/published_lock.json').read_bytes())
    lock_bytes = public(lock_ref)
    check('public lock local exact', lock_bytes == (EX / 'protocols/execution_lock.json').read_bytes())
    lock = json.loads(lock_bytes)
    for path, digest in lock['source_hashes'].items():
        check('locked source bytes ' + path, sha256((EX / path).read_bytes()).hexdigest() == digest)
    for path, digest in lock['external_source_hashes'].items():
        check('upstream locked bytes ' + path, sha256((ROOT / path).read_bytes()).hexdigest() == digest)
    sources = json.loads((EX / 'protocols/published_sources.json').read_bytes())
    check('published source map exact', sha256((EX / 'protocols/published_sources.json').read_bytes()).hexdigest() == lock['published_sources_sha256'])
    for value in sources.values():
        if isinstance(value, dict) and value.get('type') == 'EvidenceRef':
            public(value)
    check('exact3 identities unique', len(lock['runs']) == 3 and len({r['candidate'] for r in lock['runs']}) == len({r['runtime_sha256'] for r in lock['runs']}) == 3)
    for i, profile in enumerate(('ORIGINAL_C9502_CONTROL', 'SHOCK_ANCHOR_ZERO', 'SHOCK_ANCHOR_FROZEN_1ATR')):
        row = lock['runs'][i]
        payload_bytes = public(row['payload_ref'])
        payload = json.loads(payload_bytes)
        check('payload identity parameter index', row['index'] == i and row['candidate'] == f'S014-C951{i}' and payload['parameters'] == row['parameters'] == {'anchor_profile': profile})
        check('payload/closure exact', sha256(payload_bytes).hexdigest() == row['payload_sha256'] and payload['runtime']['source_sha256'] == lock['runtime_implementation_sha256'])
    gate = json.loads((EX / 'others/gate_source_review.json').read_bytes())
    check('sourcegate current lock', gate['status'] == 'PASS' and gate['source_lock_sha256'] == lock_ref['sha256'])
    check('sourcegate actual final independent bytes', public(gate['review_ref']) == (OUT / 'anchor_runner_pre_review.json').read_bytes())
    result = {'status': 'PASS', 'source_lock_ref': lock_ref, 'source_sha256': lock['source_hashes']['src/strategy_runtime/strategies/followthrough_anchor.py'],
              'checks': CHECKS, 'check_count': len(CHECKS), 'implementation_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'dispatch_authorized': 'Fresh ORIGINAL_C9502_CONTROL only; independent actual control gate still required before active profiles.', 'new_accounts_by_auditor': 0}
    destination = OUT / 'anchor_public_lock_review.json'
    with destination.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'review_sha256': sha256(destination.read_bytes()).hexdigest(), 'checks': len(CHECKS)}))


if __name__ == '__main__':
    main()
