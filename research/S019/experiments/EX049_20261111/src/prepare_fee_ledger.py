"""Reuse authenticated account-ledger arithmetic with explicit fee-scenario inputs."""
import ast
from hashlib import sha256
from pathlib import Path

ROOT = Path.cwd()
source = ROOT/'research/S019/experiments/EX047_20261111/src/analyze_search.py'
text = source.read_text(encoding='utf-8')
node = next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name == 'ledger')
function = ast.get_source_segment(text,node)
old = "    assert request['fee_rate'] == .001 and request['scenario_id'] == 'STANDARD'\n    assert request['window_id'] == 'FULL' and request['measurement_tier'] == 'FORMAL'"
new = """    fee = spec['fee_rate']
    assert fee in (.001,.002)
    assert request['fee_rate'] == fee
    assert request['scenario_id'] == ('STANDARD' if fee == .001 else 'STRESS')
    assert request['window_id'] == 'FULL'
    assert request['measurement_tier'] == ('FORMAL' if fee == .001 else 'STRESS')"""
assert function.count(old) == 1
function = function.replace(old,new)
old = "    measured = metrics(run, bh['metrics']['daily_max_drawdown'])\n    assert measured == row['candidate']"
new = """    full_metrics = metrics(run, bh['metrics']['daily_max_drawdown'])
    allowed = set(full_metrics) if fee == .001 else set(full_metrics)-{'gates','eligible'}
    assert set(row['candidate']) == allowed
    measured = {key:full_metrics[key] for key in allowed}
    assert measured == row['candidate']"""
assert function.count(old) == 1
function = function.replace(old,new)
old = "                       'actual_fill_count': len(fills)})"
new = "                       'gross_turnover_over_entry_equity': sum(f['quantity']*f['price'] for f in fills)/capital,\n                       'actual_fill_count': len(fills)})"
assert function.count(old) == 1
function = function.replace(old,new)
prefix = f'''"""Ledger arithmetic copied from EX047; fee contract explicit, performance formulas unchanged.
Original source SHA256: {sha256(source.read_bytes()).hexdigest()}.
"""
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path
import sys
import numpy as np

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
sys.path.insert(0,str(ROOT/'research/S019/experiments/EX013_20261110/src'))
from runner import metrics, read_account  # noqa: E402

'''
output = ROOT/'.tmp/s019-stage3-20261111/fee_ledger.py'
assert not output.exists()
output.write_bytes((prefix+function+'\n').encode())
print('FEE_LEDGER_READY')
