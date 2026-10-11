"""Metadata/source-only build; no native account or market access."""
from pathlib import Path
import json
from hashlib import sha256

ROOT = Path.cwd()
BASE = ROOT / 'research/S013/experiments/EX053_20261011/src'
TARGET = ROOT / '.tmp/ex053-analysis-repair'
source = (BASE / 'analysis_reference.py').read_text(encoding='utf-8')
old = "'MEAN_FIXED120_BEAR_TIME_BELOW_CLOSE', 'MEAN_BEAR_TIME_BELOW_SEGMENT_CLOSE'):"
new = "'MEAN_FIXED120_BEAR_TIME_BELOW_CLOSE', 'MEAN_BEAR_TIME_BELOW_SEGMENT_CLOSE', 'RAW_BEAR_TIME_BELOW_CLOSE'):"
assert source.count(old) == 1 and 'RAW_BEAR_TIME_BELOW_CLOSE' not in source
(TARGET / 'analysis_reference_corrected.py').write_text(source.replace(old, new), encoding='utf-8')
(TARGET / 'original_analysis_reference.py').write_bytes((BASE / 'analysis_reference.py').read_bytes())

def digest(path):
    return sha256(path.read_bytes()).hexdigest()


inputs = [BASE / 'analysis_reference.py', BASE / 'analyze.py', BASE / 'common.py', BASE / 'precheck.py',
          BASE.parent / 'protocols/plan.json', ROOT / 'research/S013/assets/runs/EX053_20261011/precheck.json']
metadata = {'status': 'PROSPECTIVE_TECHNICAL_ANALYSIS_REPAIR_ONLY',
            'problem': 'Frozen summarize gate enum list omits RAW_BEAR_TIME_BELOW_CLOSE; original theoretical entry assertion ignores true additional direction gate. Native evaluation is unchanged.',
            'change': 'One added enum literal in existing classified bear TIME direction-gate branch only',
            'immutable_frozen_inputs': {str(path.relative_to(ROOT)).replace('\\', '/'): digest(path) for path in inputs},
            'limits': 'No altered economics, qualification criteria, ledgers, native runtime, evaluation or parameter coordinates. Corrected wrapper reanalyzes the same existing evaluation only.',
            'native_reads_at_declaration': 0, 'market_reads': 0, 'new_evaluations': 0,
            'failure_preserved': 'Original frozen helper copied verbatim; root retains original failed command output; source failure is not evidence of an account result error.'}
(TARGET / 'method_draft.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
