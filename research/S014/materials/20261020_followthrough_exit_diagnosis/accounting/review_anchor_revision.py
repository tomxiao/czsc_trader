"""Read-only audit/runner technical delta and preserved same-control proof."""
import ast
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


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def public(value):
    evidence = EvidenceRef.from_dict(value)
    raw = evidence.resolve(ROOT).read_bytes()
    check('original immutable public identity', sha256(raw).hexdigest() == evidence.sha256)
    return json.loads(raw)


def main():
    expected = {'src/audit_accounts_v2.py': 'ea8ed9add3ad66392bf9299ed09b98313d7421b3c0d2e2f156042e528974ecc4',
                'src/run_accounts_v2.py': 'cd32ae001d71e11ea4f2b5f95f298d6cdb75aff3a0e3181eec7ef250e5a54d93',
                'protocols/audit_revision.json': 'acb1409b7757f9f8bd5e4f2e26f11aabeedf4df67c2c99da3762659b67eac44e'}
    for name, digest in expected.items():
        check('exact new revision ' + name, ref(EX / name)['sha256'] == digest)
        if name.endswith('.py'):
            ast.parse((EX / name).read_text(encoding='utf-8'))
    revision = json.loads((EX / 'protocols/audit_revision.json').read_bytes())
    for item in revision.values():
        if isinstance(item, dict) and {'path', 'sha256'} <= item.keys():
            check('preserved revision byte ' + item['path'], ref(ROOT / item['path'])['sha256'] == item['sha256'])
    record = json.loads((EX / 'others/accounts/run-000.json').read_bytes())
    check('original engine success and inline failure retained', record['status'] == 'SUCCEEDED' and record['audit'] is None and record['exception'] == "KeyError('shock_anchor_close_RUNTIME_HFQ')")
    check('same account/result no control repeat', record['evidence'] == revision['same_account_ref'] and record['result_hash'] == revision['same_result_hash'])
    old_lock = public(revision['parent_source_lock_ref'])
    for name, digest in old_lock['source_hashes'].items():
        check('all v1 source bytes immutable ' + name, ref(EX / name)['sha256'] == digest)
    audit = (EX / 'src/audit_accounts_v2.py').read_text(encoding='utf-8')
    old = (EX / 'src/audit_accounts.py').read_text(encoding='utf-8')
    trees = [ast.parse(value) for value in [old, audit]]
    for name in ['sign', 'frozen_baseline', 'divergence_dates']:
        funcs = [next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name) for tree in trees]
        check('unrelated internal helper exact ' + name, ast.dump(funcs[0], include_attributes=False) == ast.dump(funcs[1], include_attributes=False))
    check('no missing raw column access', 'row["shock_anchor_close_RUNTIME_HFQ"]' not in audit and 'row["shock_anchor_ATR0_RUNTIME_HFQ"]' not in audit)
    check('prepared source only no new supplier context', 'providers=ProviderConfig(bindings={})' in audit and 'context.data.fetch(request, prepared=prepared)' in audit)
    check('direct frozen source operands and originalATR0', 'anchor_close = source[D]' in audit and 'anchor_atr = row["atr20_prior"]' in audit and '(anchor_close - source[D]) >= anchor_atr' in audit)
    runner = (EX / 'src/run_accounts_v2.py').read_text(encoding='utf-8')
    check('v2 cannot redispatch existing control', 'assert index in (1, 2)' in runner and 'choices=("batch",)' in runner)
    check('current parent/source/control recovery gates explicit', all(text in runner for text in ['parent_source_lock_sha256', 'gate_source_review_v2.json', 'gate_control_independent_v2.json', 'control_supplement_ref', 'retained_original_inline_audit_failure']))
    check('actual active receipt binds current lock and revision', '"audit_revision_ref": read(EX / "protocols/published_audit_revision.json")' in runner and '"execution_source_lock_ref": read(EX / "protocols/published_lock_v2.json")' in runner)
    supplement = json.loads((EX / 'others/control_supplement.json').read_bytes())
    own = json.loads((OUT / 'anchor_account_000_independent_review.json').read_bytes())
    check('independent same original control PASS remains v1', own['status'] == 'PASS' and own['account_ref'] == record['evidence'] and own['source_lock_sha256'] == revision['parent_source_lock_sha256'])
    check('corrected same control internal audit PASS', supplement['status'].startswith('PASS') and supplement['audit']['status'] == 'PASS' and supplement['original_account_ref'] == record['evidence'])
    result = {'status': 'PASS', 'reviewer': 'A', 'source_sha256': revision['unchanged_strategy_source']['sha256'],
              'check_count': len(CHECKS), 'checks': CHECKS, 'reviewed_files': [ref(EX / name) for name in expected],
              'parent_lock_ref': revision['parent_source_lock_ref'], 'original_control_ref': record['evidence'],
              'independent_original_control_review': ref(OUT / 'anchor_account_000_independent_review.json'),
              'manual_review': ['Only missing raw-anchor audit assumption corrected; strategy/economics/parameters and original000 all immutable.',
                                'SourceClose reconstructed from exact prepared asset; frozenATR0 uses first event original formal ATR feature whose unchanged implementation and prior independent feature verification are reused.',
                                'Original auditnull/KeyError stays in same successful engine receipt; supplement is separate, no control execution relabel or repeat.',
                                'Original price/fees/clock rules remain; active1/2 only after new public parent lock and corrected/internal plus independent original control gates.',
                                'No new epsilon, fallback, account budget, local outcome label, supplier or economic acceptance gate.'],
              'implementation': ref(Path(__file__).resolve()), 'new_accounts': 0, 'new_fits': 0, 'new_supplier_calls': 0}
    target = OUT / 'anchor_runner_v2_review.json'
    with target.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'review': ref(target), 'checks': len(CHECKS)}))


if __name__ == '__main__':
    main()
