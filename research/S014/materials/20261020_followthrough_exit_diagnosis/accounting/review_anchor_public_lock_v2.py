"""Audit-only public parent lock and same-control recovery gates, no dispatch."""
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


def read(path):
    return json.loads(path.read_bytes())


def public(value, decode=True):
    ref = EvidenceRef.from_dict(value)
    raw = ref.resolve(ROOT).read_bytes()
    check('immutable public SHA', sha256(raw).hexdigest() == ref.sha256 and ref.experiment.strategy_id == 'S014')
    return json.loads(raw) if decode else raw


def main():
    current_ref, parent_ref = [read(EX / ('protocols/' + name)) for name in ['published_lock_v2.json', 'published_lock.json']]
    current, parent = public(current_ref), public(parent_ref)
    check('original parent and exact new public lock', current['parent_source_lock_sha256'] == parent_ref['sha256'] == '31f34e87ccac549e7d82fed2ab721db55ee28ff7c3925a77721afac973e663ad' and sha256((EX / 'protocols/execution_lock_v2.json').read_bytes()).hexdigest() == current_ref['sha256'])
    check('all three immutable strategy identities unchanged', current['runs'] == parent['runs'] and current['runtime_implementation_sha256'] == parent['runtime_implementation_sha256'])
    for field, base in [('source_hashes', EX), ('external_source_hashes', ROOT)]:
        for path, digest in current[field].items():
            check('current frozen byte ' + path, sha256((base / path).read_bytes()).hexdigest() == digest)
    for path, digest in parent['source_hashes'].items():
        check('v1 bytes never overwritten ' + path, sha256((EX / path).read_bytes()).hexdigest() == digest)
    check('published revision map bound', sha256((EX / 'protocols/published_revision_sources.json').read_bytes()).hexdigest() == current['published_revision_sources_sha256'])
    for item in read(EX / 'protocols/published_revision_sources.json').values():
        if isinstance(item, dict) and item.get('type') == 'EvidenceRef':
            public(item, False)
    record = read(EX / 'others/accounts/run-000.json')
    source = read(EX / 'others/gate_source_review_v2.json')
    internal = read(EX / 'others/gate_control_v2.json')
    independent = read(EX / 'others/gate_control_independent_v2.json')
    for gate in [source, internal, independent]:
        check('all public recovery gates match current v2 parent', gate['status'] == 'PASS' and gate['source_lock_sha256'] == current_ref['sha256'] and gate['parent_source_lock_ref'] == parent_ref)
    check('source gate exact independent technical review', source['review_ref']['sha256'] == '3e20acb690c13a8b525587bcc0ff8361aa2c01ad9b674dd2795c1b9cece3f7a4' and public(source['review_ref']) == read(OUT / 'anchor_runner_v2_review.json'))
    supplement_ref = read(EX / 'others/control_supplement_ref.json')
    supplement = public(supplement_ref)
    check('same original successful engine and retained inline issue', record['status'] == 'SUCCEEDED' and record['audit'] is None and record['exception'] == "KeyError('shock_anchor_close_RUNTIME_HFQ')")
    check('same original account supplemental PASS', supplement['original_account_ref'] == record['evidence'] and supplement['audit']['status'] == 'PASS' and supplement['retained_original_inline_audit_failure'])
    check('independent gate binds original result/supplement/no redispatch', independent['account_ref'] == record['evidence'] and independent['control_supplement_ref'] == supplement_ref and independent['retained_original_inline_audit_failure'] and independent['new_control_dispatches'] == 0)
    own = public(independent['review_ref'])
    check('original A control PASS is not misrepresented as v2 execution', own['status'] == 'PASS' and own['account_ref'] == record['evidence'] and own['source_lock_sha256'] == parent_ref['sha256'] == independent['independent_review_original_dispatch_lock_sha256'])
    report = {'status': 'PASS', 'reviewer': 'A', 'source_lock_ref': current_ref, 'parent_source_lock_ref': parent_ref,
              'source_sha256': current['source_hashes']['src/strategy_runtime/strategies/followthrough_anchor.py'],
              'original_control_ref': record['evidence'], 'control_supplement_ref': supplement_ref,
              'same_original_independent_control_ref': independent['review_ref'], 'check_count': len(CHECKS), 'checks': CHECKS,
              'dispatch_authorized': 'Only original fixed active1/2 through reviewed v2 runner; no control rerun, parameter/source change or extra profile.',
              'raw_anchor_semantics': 'Reconstructed source values, not directly projected account raw fields. All actual formal flags/index/actions independently verified.',
              'original_inline_audit_failure_retained': True, 'new_accounts_by_auditor': 0,
              'implementation_sha256': sha256(Path(__file__).read_bytes()).hexdigest()}
    path = OUT / 'anchor_public_lock_review_v2.json'
    with path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest(), 'checks': len(CHECKS)}))


if __name__ == '__main__':
    main()
