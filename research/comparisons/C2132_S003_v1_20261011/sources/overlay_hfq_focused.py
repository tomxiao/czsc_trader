"""Authorized immutable center and focused in-memory fault injection; no replay."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json

from czsc_trader.research_tools import EvidenceRef
from overlay_hfq_validation import validate_overlay_hfq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def main():
    receipts = json.loads((ROOT / 'research/comparisons/C2132_S003_v1_20261011/account_receipts.json').read_bytes())
    center = next(row for row in receipts if row['family'] == 'S003')['center']
    reference = EvidenceRef.from_dict(center)
    raw = reference.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == reference.sha256
    value = json.loads(raw)
    original = deepcopy(value)
    baseline = validate_overlay_hfq(value)
    assert baseline['status'] == 'PASS', baseline
    assert baseline['public_validation'] == 'FAIL_WITH_SUPPLEMENTAL_HFQ_PROOF'
    checks = ['CENTER_STRICT_PASS_WITH_ORIGINAL_NATIVE_FAIL', 'PUBLISHED_BYTES_AUTHENTICATED']
    refusals = []
    for field, code in [('limit', 'RAW_GRID_HFQ_LIMIT'), ('price', 'CHECKPOINT_FILL_PRICE'),
                        ('fee', 'FILL_FEE'), ('cash', 'ACCOUNT_CLOSE_STATE'),
                        ('unfilled', 'BUY_FILL_ELIGIBILITY'), ('time', 'FILL_TIME_TRIGGER')]:
        changed = deepcopy(value)
        replay = changed['runs'][0]['replay_evidence']
        if field == 'limit':
            replay['orders'][0]['limit_price'] += .01
        elif field == 'price':
            replay['fills'][0]['price'] += .01
        elif field == 'fee':
            replay['fills'][0]['fees'] += 1.
        elif field == 'cash':
            replay['account_daily'][0]['cash'] += 1.
        elif field == 'unfilled':
            next(row for row in replay['orders'] if row['status'] == 'UNFILLED')['status'] = 'FILLED'
        else:
            replay['fills'][0]['fill_time'] = replay['fills'][0]['fill_time'].replace('09:30:00', '09:30:01')
        rejected = validate_overlay_hfq(changed)
        codes = {row['code'] for run in rejected['runs'] for row in run['supplemental']['findings']}
        assert rejected['status'] == 'FAIL' and code in codes, (field, rejected)
        refusals.append({'mutation': field, 'status': rejected['status'], 'finding_codes': sorted(codes)})
    assert value == original and reference.resolve(ROOT).read_bytes() == raw
    checks.append('ORIGINAL_VALUE_AND_PUBLISHED_BYTES_UNCHANGED')
    result = {'status': 'PASS', 'checks': checks, 'refusals': refusals,
              'source_sha256': sha256((HERE / 'overlay_hfq_validation.py').read_bytes()).hexdigest(),
              'test_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'reference': center, 'native_public_audit': baseline['runs'][0]['native_public_audit'],
              'read_scope': 'Only already authenticated S003 center and receipts; mutations only deepcopied memory',
              'new_evaluations': 0, 'new_preparations': 0, 'financial_replays': 0}
    (HERE / 'overlay_hfq_focused.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'checks': len(checks), 'refusals': len(refusals)}))


if __name__ == '__main__':
    main()
