"""Publish pre-account caller identity repair, preserving original plan/source."""
import json
from pathlib import Path
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_confirm_execution as d

exp, path, plan = d.stage()
ctx = d.common().context(1)
repair = {
    'status': 'PRE_ACCOUNT_CALLER_ONLY_REPAIR', 'new_accounts': 0,
    'error': 'prepare refused before inputs: runtime binding candidate_id requires strategy.reference_id S013/C9079, not short C9079',
    'original_driver_sha256': d.digest(ROOT / '.tmp/s013_confirm_execution.py'),
    'revised_driver_sha256': d.digest(ROOT / '.tmp/s013_confirm_execution_v2.py'),
    'changed': 'Only caller binding reference_id and preserved second prepare-attempt filename',
    'unchanged': 'Strategy twofile bytes, payload/parameters, effective domains, input definitions, economic gates, scientific plan, execution data and experiment identity',
    'no_provider': True, 'no_financial_repeat': True,
}
d.write(d.OUT / 'technical_repair.json', repair)
refs = {name: d.put(ctx, exp, ROOT / p) for name, p in {
    'technical_repair.json': '.tmp/s013-confirm-net-execution-result/technical_repair.json',
    'driver_v2.py': '.tmp/s013_confirm_execution_v2.py',
    'repair.py': '.tmp/s013_confirm_repair.py',
    'prepare_attempt_v1.json': '.tmp/s013-confirm-net-execution-result/prepare_attempt.json',
}.items()}
d.write(path / 'protocols/technical_repair_references.json', refs)
print(repair['status'], flush=True)
