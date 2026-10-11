"""Preserve frozen EX081 method; correct native-price CSV column spelling."""
from pathlib import Path
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_context_driver as d

exp, plan = d.stage()
if (d.OUT / 'statistics.json').exists():
    raise ValueError('Cannot rerun completed statistics')
repair = {'status': 'PRE_STATISTICS_CALLER_ONLY_REPAIR', 'experiment': exp.to_dict(),
          'original_driver_sha256': d.digest(Path(d.__file__)),
          'revised_driver_sha256': d.digest(ROOT / '.tmp/s013_context_driver_v2.py'),
          'error': 'AttributeError: prices.Open; EX066 prices.csv native OPEN column is open',
          'changes': 'Strict lowercase open field selection and second-attempt filename only; no flexible schema fallback',
          'unchanged': 'Kernel, independent oracle, source method, labels, forecasts, statistical design, experiment and economic requirements',
          'analyze_calls_before': 0, 'new_accounts': 0, 'new_allocation': 0, 'provider': 0}
path = exp.resolve(ROOT)
d.write(path / 'protocols/caller_repair.json', repair)
ctx = d.base.common().context(1)
refs = {name: d.put(ctx, exp, source) for name, source in {
    'caller_repair.json': path / 'protocols/caller_repair.json',
    'revised_driver.py': ROOT / '.tmp/s013_context_driver_v2.py',
    'repair_driver.py': Path(__file__), 'failed_attempt.json': d.OUT / 'study_attempt.json',
}.items()}
d.write(path / 'protocols/caller_repair_references.json', refs)
with (path / 'src/driver_v2.py').open('xb') as stream:
    stream.write((ROOT / '.tmp/s013_context_driver_v2.py').read_bytes())
print(repair['status'], flush=True)
