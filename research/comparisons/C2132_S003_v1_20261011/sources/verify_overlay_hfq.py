"""Read-only supplemental checks of exactly the 34 authorized S003 receipts."""
from hashlib import sha256
from pathlib import Path
import json

from czsc_trader.research_tools import EvidenceRef
from overlay_hfq_validation import validate_overlay_hfq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def main():
    method = json.loads((HERE / 'overlay_hfq_method.json').read_bytes())
    for name, expected in method['files'].items():
        assert sha256((HERE / name).read_bytes()).hexdigest() == expected, name
    path = ROOT / method['receipt_path']
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == method['receipt_sha256']
    receipt = next(row for row in json.loads(raw) if row['family'] == 'S003')
    refs = [receipt['center'], receipt['stress'], *[row['reference'] for row in receipt['parameters']]]
    assert len(refs) == 34 and len({row['sha256'] for row in refs}) == 34
    rows = []
    for raw_reference in refs:
        reference = EvidenceRef.from_dict(raw_reference)
        assert reference.experiment.strategy_id == 'S003'
        source = reference.resolve(ROOT)
        payload = source.read_bytes()
        actual_sha = sha256(payload).hexdigest()
        assert actual_sha == reference.sha256
        value = json.loads(payload)
        proof = validate_overlay_hfq(value)
        rows.append({'reference': raw_reference, 'status': proof['status'],
                     'published_sha256': actual_sha, 'proof': proof})
        print('STRICT_OVERLAY', reference.name, proof['status'], flush=True)
        if proof['status'] != 'PASS':
            failure = {'status': 'FAIL', 'accounts': rows,
                       'method_sha256': sha256((HERE / 'overlay_hfq_method.json').read_bytes()).hexdigest(),
                       'new_financial_evaluations': 0, 'original_evidence_unchanged': True}
            (HERE / 's003_strict_failure.json').write_text(json.dumps(failure, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            raise AssertionError('Strict supplemental proof rejected actual evidence; no completion permitted')
    result = {'status': 'PASS', 'source_sha256': method['files']['overlay_hfq_validation.py'],
              'driver_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'method_sha256': sha256((HERE / 'overlay_hfq_method.json').read_bytes()).hexdigest(),
              'focused_sha256': method['files']['overlay_hfq_focused.json'],
              'accounts': rows, 'account_count': len(rows),
              'native_public_validation': 'FAIL_WITH_SUPPLEMENTAL_HFQ_PROOF',
              'whole_projection_proof': 's003_projection_proof.json (independent root public serializer exact equality)',
              'new_evaluations': 0, 'new_preparations': 0, 'financial_replays': 0,
              'platform_changes': 0, 'original_evidence_unchanged': True}
    (HERE / 's003_strict_proof.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('ALL_34_STRICT_PASS_NATIVE_AUDIT_FAIL_PRESERVED', flush=True)


if __name__ == '__main__':
    main()
