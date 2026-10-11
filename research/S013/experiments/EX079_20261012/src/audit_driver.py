"""Run frozen independent EX079 reconstruction once; no new account/model study."""
from hashlib import sha256
import importlib.util
from pathlib import Path
import sys
import pandas as pd
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_net_research as driver

WORK = driver.OUT
AUDIT = ROOT / '.tmp/s013-base-net-audit'
plan = driver.read(WORK / 'plan.json')
driver.check(plan)
exp = ExperimentRef.from_dict(plan['experiment'])
refs = driver.read(exp.resolve(ROOT) / 'protocols/result_references.json')
for value in refs.values():
    driver.public(value)
freeze = driver.read(AUDIT / 'freeze.json')
for name, expected in freeze['files'].items():
    if sha256((AUDIT / name).read_bytes()).hexdigest() != expected:
        raise ValueError('Frozen independent audit drift')
bound, result = driver.common.cache_read(ROOT / '.tmp/s013-mechanism-EX058/N0.pkl.gz')
if serialize_evaluation_evidence(bound, result) != driver.read(driver.public(plan['input_references']['native'])):
    raise ValueError('Full native public identity differs')
old = driver.frame(plan['input_references']['features.csv'])
features, labels, auxiliary, history = [driver.frame(refs[name]) for name in ('features.csv', 'labels.csv', 'auxiliary.csv', 'original_history.csv')]
labels['label_end_return_4'] = pd.to_datetime(labels.label_end_return_4).dt.as_unit('ns')
native_history = result.runs[0].execution.decisions.set_index('signal_date')[['target_position', 'entry_eligible', 'confirmation_opportunity']].copy()
native_history.index = pd.to_datetime(native_history.index).as_unit('ns')
history['target_position'] = history.target_position.astype(float)
pd.testing.assert_frame_equal(history, native_history, check_exact=True, check_names=False)
prices = bound.execution_data.execution_daily.set_index('dt')[['open', 'close']].copy()
prices.index = pd.to_datetime(prices.index).as_unit('ns')
old_prices = driver.frame(plan['input_references']['prices.csv'])
pd.testing.assert_frame_equal(prices, old_prices[['open', 'close']], check_exact=True, check_names=False)
spec = importlib.util.spec_from_file_location('s013_net_independent_audit', AUDIT / 'audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
input_check = audit.verify_inputs(old, prices.rename(columns={'open': 'Open', 'close': 'Close'}), history, features, labels, auxiliary.iloc[:, 0])
prior = driver.read(driver.public(plan['input_references']['statistics.json']))['scopes']['all']['labels']['return_4']['walk_forward']['prediction_records']['controls']
statistics_check = audit.verify_statistics(features, labels, auxiliary.iloc[:, 0], driver.read(driver.public(refs['statistics.json'])), prior)
if driver.common.SOURCE_CALLS:
    raise ValueError('No provider calls allowed')
verification = {'status': 'PASS', 'input_audit': input_check, 'statistics_audit': statistics_check, 'native_exact': True, 'audit_freeze': freeze, 'actual_evidence_references': refs, 'input_references': plan['input_references'], 'new_accounts': 0, 'new_main_statistics': 0, 'provider_calls': 0}
driver.write(WORK / 'verification.json', verification)
ctx = driver.common.context(1)
audit_refs = {'verification.json': driver.put(ctx, exp, WORK / 'verification.json')}
for path in sorted(AUDIT.iterdir()):
    if path.suffix in ('.json', '.py'):
        audit_refs['audit_' + path.name] = driver.put(ctx, exp, path)
        if path.suffix == '.py':
            (exp.resolve(ROOT) / 'src' / ('independent_' + path.name)).write_bytes(path.read_bytes())
audit_refs['audit_driver.py'] = driver.put(ctx, exp, Path(__file__))
(exp.resolve(ROOT) / 'src' / 'audit_driver.py').write_bytes(Path(__file__).read_bytes())
driver.write(exp.resolve(ROOT) / 'protocols/audit_references.json', audit_refs)
print({'status': 'PASS', 'input_audit': input_check, 'statistics_audit': statistics_check}, flush=True)
