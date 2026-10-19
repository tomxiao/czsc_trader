"""Verify additive public v2 lock/control bridge without re-executing BASE."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
EX = ROOT / 'research/S014/experiments/EX046_20261020'
CHECKS = []


def check(name, value):
    assert value, name
    CHECKS.append(name)


def read(path):
    return json.loads(path.read_bytes())


def public(value):
    ref = EvidenceRef.from_dict(value)
    content = ref.resolve(ROOT).read_bytes()
    check('formal local EvidenceRef SHA', ref.experiment.strategy_id == 'S014' and sha256(content).hexdigest() == ref.sha256)
    return content


def main():
    lock_ref = read(EX / 'protocols/published_lock_v2.json')
    raw = public(lock_ref)
    check('public successor local bytes exact', raw == (EX / 'protocols/execution_lock_v2.json').read_bytes())
    child = json.loads(raw)
    parent_ref = child['parent_lock_ref']
    parent_raw = public(parent_ref)
    parent = json.loads(parent_raw)
    check('exact parent chain and unchanged implementation', parent_raw == (EX / 'protocols/execution_lock.json').read_bytes() and child['revision'] == 2 and parent['runtime_implementation_sha256'] == child['runtime_implementation_sha256'])
    for name, digest in parent['source_hashes'].items():
        check('old frozen bytes retained ' + name, sha256((EX / name).read_bytes()).hexdigest() == digest)
    for name, digest in child['source_hashes'].items():
        check('successor source bytes ' + name, sha256((EX / name).read_bytes()).hexdigest() == digest)
    for name, digest in child['external_source_hashes'].items():
        check('upstream exact ' + name, sha256((ROOT / name).read_bytes()).hexdigest() == digest)
    check('same three runtime candidates', len(child['runs']) == len(parent['runs']) == 3)
    for old, new in zip(parent['runs'], child['runs'], strict=True):
        for key in ['index', 'mode', 'parameters', 'candidate', 'runtime_sha256', 'payload_sha256']:
            check('unchanged execution identity ' + key, old[key] == new[key])
        check('same payload immutable bytes', public(old['payload_ref']) == public(new['payload_ref']))
    source_map = EX / 'protocols/published_sources_v2.json'
    check('published successor sources map exact', sha256(source_map.read_bytes()).hexdigest() == child['published_sources_sha256'])
    for value in read(source_map).values():
        if isinstance(value, dict) and value.get('type') == 'EvidenceRef':
            public(value)
    source_gate = read(EX / 'others/gate_source_review_v2.json')
    check('successor source gate lock bound', source_gate['status'] == 'PASS' and source_gate['source_lock_sha256'] == lock_ref['sha256'])
    check('source gate exact independent successor review', public(source_gate['review_ref']) == (OUT / 'pause_runner_v2_review.json').read_bytes())
    supplement_ref = read(EX / 'others/control_audit_correction_v2_ref.json')
    supplement_raw = public(supplement_ref)
    supplement = json.loads(supplement_raw)
    check('same account supplementary audit exact PASS', supplement_raw == (EX / 'others/control_audit_correction_v2.json').read_bytes() and supplement['status'] == 'PASS' and supplement['audit']['status'] == 'PASS' and supplement['audit']['checks'] == 425923)
    original = read(EX / 'others/accounts/run-000.json')
    check('old actual record engine success and internal FAIL preserved', original['status'] == 'SUCCEEDED' and original['audit']['status'] == 'FAIL' and original['evidence'] == supplement['account_ref'] and original['result_hash'] == supplement['result_hash'])
    control = read(EX / 'others/gate_control_v2.json')
    independent = read(EX / 'others/gate_control_independent_v2.json')
    check('effective current control gates PASS', control['status'] == independent['status'] == 'PASS')
    check('independent bridge lock and exact parent account', independent['source_lock_sha256'] == lock_ref['sha256'] and independent['account_ref'] == original['evidence'])
    check('independent bridge exact A BASE original bytes', public(independent['review_ref']) == (OUT / 'pause_account_000_independent_review.json').read_bytes())
    review = {'status': 'PASS', 'source_lock_ref': lock_ref, 'parent_lock_ref': parent_ref,
              'source_sha256': '5e775c5b27bfd7b1ac5bec9c2839ce24ae62f32f1829c21a13091868a174b846',
              'checks': CHECKS, 'check_count': len(CHECKS), 'implementation_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'same_actual_control_ref': original['evidence'], 'control_supplement_ref': supplement_ref,
              'scope': 'BASE actually dispatched under original v1. Active1/2 use v2 audit/runner/lock, unchanged strategy/request/parameter identities; no BASE redispatch.',
              'dispatch_authorized': 'Both fixed active profiles, contingent on their own technical validity; no economic optional stopping.',
              'new_accounts_by_auditor': 0, 'account_engine_failures': 0, 'retained_internal_expression_incidents': 1}
    destination = OUT / 'pause_public_lock_review_v2.json'
    with destination.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(review, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'review_sha256': sha256(destination.read_bytes()).hexdigest(), 'checks': len(CHECKS)}))


if __name__ == '__main__':
    main()
