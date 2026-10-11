"""Post-closeout exact source review supplement; immutable delivery left intact."""
from pathlib import Path
from hashlib import sha256
import json
from driver_pricefix import ROOT, WORK, common, read, put
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef

old = (WORK / 'finish_reviewed_a030.py').read_bytes()
actual = (WORK / 'finish.py').read_bytes()
assert sha256(old).hexdigest() == 'a03098c4fc2330fc0d60a3855791f2345c487dcad12dd094758c53476ff05f41'
assert sha256(actual).hexdigest() == '57289c0e1db287f4dc2bc1be82929511a2428367d3131107c1c876392ce407dc'
assert actual.replace(b'        "closeout_checks.py",\n', b'') == old
exp = ExperimentRef.from_dict(read(WORK / 'experiment.json'))
final = read(exp.resolve(ROOT) / 'protocols/final_evidence_references.json')
assert final['finish.py']['sha256'] == sha256(actual).hexdigest()
assert EvidenceRef.from_dict(final['finish.py']).resolve(ROOT).read_bytes() == actual
assert read(exp.resolve(ROOT) / 'protocols/delivery_validation.json')['status'] == 'PASS'
assert final['statistics.json']['sha256'] == '764859c801574ffebad115aa4e09708b1574912a7fbd2f9d53951b5e02438dfc'
assert final['verification.json']['sha256'] == '81896b4a5970fca33ebec43ba558a5069ade0765f5fe026aeafc4a3e1f477838'
ctx = common.context(1)
refs = {'reviewed_old_finish': put(ctx, exp, WORK / 'finish_reviewed_a030.py')}
audit = {
    'type': 'RootNonFinancialSourceReviewSupplement',
    'status': 'PASS',
    'original_authorization_preserved': final['root_delivery_authorization.json'],
    'original_reviewed_sha256': sha256(old).hexdigest(),
    'actual_used_source': final['finish.py'],
    'exact_difference': 'Only add closeout_checks.py to the explicit publication materials list; no calculation, sampling, scientific judgment, assembly or validation logic changed.',
    'reason': 'Final source added the synthetic-helper source while root review and launch were concurrent. Original authorization retained its earlier hash; this explicit review records the exact actually used source.',
    'root_final_source_review': 'Approved actual57289c0e content and exact one-line evidence coverage difference; final delivery already contains the actual source and its corresponding synthetic proof.',
    'actual_delivery_reference': read(exp.resolve(ROOT) / 'protocols/delivery_reference.json'),
    'actual_FULL_validation': read(exp.resolve(ROOT) / 'protocols/delivery_validation.json'),
    'statistics_reference': final['statistics.json'],
    'verification_reference': final['verification.json'],
    'original_reviewed_source_reference': refs['reviewed_old_finish'],
    'delivery_receipt_manifest_unchanged': True,
    'financial_reruns': 0,
    'statistics_reruns': 0,
    'assembly_reruns': 0,
    'objective_achieved': False
}
dest = WORK / 'root_closeout_source_audit.json'
assert not dest.exists()
dest.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
refs['audit'] = put(ctx, exp, dest)
refs['audit_source'] = put(ctx, exp, Path(__file__))
path = exp.resolve(ROOT) / 'protocols/root_closeout_source_audit_references.json'
assert not path.exists()
path.write_text(json.dumps(refs, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
for name in ('root_closeout_source_audit.py', 'finish_reviewed_a030.py'):
    (exp.resolve(ROOT) / 'src' / name).write_bytes((WORK / name).read_bytes())
print({'status': 'PASS', 'exact_diff_lines': 1, 'reruns': 0, 'delivery_unchanged': True})
