"""Finish prospective metadata from pure proof and frozen source metadata only."""
from hashlib import sha256
from pathlib import Path
import json

ROOT = Path.cwd()
HERE = ROOT / '.tmp/ex053-analysis-repair'
method = json.loads((HERE / 'method_draft.json').read_text(encoding='utf-8'))
proof = json.loads((HERE / 'focused.json').read_text(encoding='utf-8'))
assert proof['status'] == 'PASS' and proof['ast_added_literal_only']
method['status'] = 'PURE_READY_TECHNICAL_ANALYSIS_REPAIR'
names = ['analysis_reference_corrected.py', 'run_analysis_corrected.py', 'focused.py',
         'original_analysis_reference.py', 'build.py']
method['repair_source_files'] = {name: sha256((HERE / name).read_bytes()).hexdigest() for name in names}
method['repair_source_contents'] = {name: (HERE / name).read_text(encoding='utf-8') for name in names}
method['ast_added_literal_only'] = True
method['pure_proof'] = proof
method['pure_proof_sha256'] = sha256((HERE / 'focused.json').read_bytes()).hexdigest()
failure = HERE / 'analysis_failure.json'
method['failure_sha256'] = sha256(failure.read_bytes()).hexdigest()
method['original_failure'] = json.loads(failure.read_text(encoding='utf-8'))
plan_path = ROOT / 'research/S013/experiments/EX053_20261011/protocols/plan.json'
plan = json.loads(plan_path.read_text(encoding='utf-8'))
assert len(plan['source_files']) == 22
method['frozen_all22_source_files'] = plan['source_files']
method['original_method_reference'] = plan['method_reference']
for name, digest in plan['source_files'].items():
    assert sha256((plan_path.parent.parent / 'src' / name).read_bytes()).hexdigest() == digest
method['ruff_status'] = 'PASS current corrected helper, wrapper, focused source and builder'
method['reproduction_entrypoint'] = 'run_analysis_corrected.py; optional argument is exact EvidenceRef.to_dict JSON reference; default protocols/analysis_repair_method_reference.json'
method['method_reference_schema'] = 'Exact public EvidenceRef.to_dict object, no outer wrapper'
(HERE / 'method.json').write_text(json.dumps(method, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
print(json.dumps({'status': method['status'], 'method_sha256': sha256((HERE / 'method.json').read_bytes()).hexdigest(),
                  'corrected_helper_sha256': method['repair_source_files']['analysis_reference_corrected.py'],
                  'wrapper_sha256': method['repair_source_files']['run_analysis_corrected.py'],
                  'pure_proof_sha256': method['pure_proof_sha256'],
                  'failure_sha256': method['failure_sha256']}, indent=2))
