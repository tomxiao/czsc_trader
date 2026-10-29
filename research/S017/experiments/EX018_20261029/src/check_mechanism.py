"""Independent causal fixtures and unchanged held-position rule checks."""
from hashlib import sha256
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict
import numpy as np
import pandas as pd
import run
import strategy


def frame(rows):
    h = pd.DataFrame(rows, columns=['High', 'Low', 'Close'], dtype=float)
    h['Open'] = h.Close
    h['Volume'] = 10000.
    h['Date'] = pd.date_range('2018-11-01', periods=len(h), freq='30min', tz='UTC')
    return h


def main():
    checks = []
    base = [(10,8,9),(12,9,11),(11,7,8),(10,5,6),(12,7,11),
            (15,10,14),(12,9,10),(11,7,8),(13,8,12)]
    h = frame(base)
    assert strategy.pat_entry(h)[0]
    assert not strategy.pat_entry(h.iloc[:-1])[0]
    assert strategy.pat_entry(h)[1]['pat_l2_confirmed_at'] == h.Date.iloc[-1].isoformat()
    checks.append('right_confirmation_one_bar_and_no_backfill')
    for name, index, field, value in (
        ('trigger_equal', 8, 'Close', 11), ('higher_high_equal', 5, 'High', 12),
        ('higher_low_equal', 7, 'Low', 5), ('same_bar_breach', 8, 'Low', 4)):
        changed = h.copy(deep=True)
        changed.loc[index, field] = value
        assert not strategy.pat_entry(changed)[0], name
        checks.append(name)
    outside = frame(base[:6] + [(12,9,10),(16,4,12),(12,9,10),(11,7,8),(13,8,12)])
    signal, facts = strategy.pat_entry(outside)
    assert facts['pat_ambiguous_bars'] == 1 and facts['pat_structure'] and not facts['pat_intact'] and not signal
    checks.append('discarded_dual_pivot_does_not_erase_breach')
    same = frame([(10,8,9),(11,9,10),(10,9,9.5),(12,9,11),(11,8,10),
                  (10,5,6),(12,7,11),(15,10,14),(12,9,10),(11,7,8),(13,8,12)])
    assert strategy.pat_entry(same)[0] and strategy.pat_entry(same)[1]['pat_h1'] == 12
    checks.append('consecutive_high_keeps_more_extreme')
    equal = same.copy(deep=True)
    equal.loc[3, 'High'] = 11
    assert strategy.pat_entry(equal)[0] and strategy.pat_entry(equal)[1]['pat_h1'] == 11
    checks.append('equal_same_kind_keeps_first')
    long = frame([(1000,1,100)] * 300 + base)
    assert strategy.pat_entry(long)[0]
    first = strategy.pat_entry(long)
    long.loc[:47, ['High', 'Low', 'Close']] = [2000, .5, 50]
    assert strategy.pat_entry(long) == first
    checks.append('older_than_261_bars_ignored')
    copy = h.copy(deep=True)
    assert strategy.pat_entry(h) == strategy.pat_entry(h)
    pd.testing.assert_frame_equal(h, copy)
    checks.append('pure_repeated_evaluation_no_input_mutation')
    path = run.ROOT / 'research/S017/experiments/EX003_20261028/src/strategy.py'
    spec = spec_from_file_location('original_c13', path)
    original = module_from_spec(spec)
    spec.loader.exec_module(original)
    parameters = run.configurations()['C0047']
    rng = np.random.default_rng(17)
    held_checks = 0
    for _ in range(100):
        closes = np.exp(np.log(100) + np.cumsum(rng.normal(0, .02, 320)))
        sample = frame([(float(c+1), float(c-1), float(c)) for c in closes])
        ctx = SimpleNamespace(history=sample, parameters=parameters, portfolio=SimpleNamespace(quantity=1))
        old, new = original.decide(ctx), strategy.decide(ctx)
        assert old.target == new.target
        # Every original held explanation field is retained; next_watch is descriptive only.
        oldfacts = asdict(old.explanation)
        newfacts = asdict(new.explanation)
        for key in oldfacts:
            if key != 'next_watch':
                assert oldfacts[key] == newfacts[key], key
        held_checks += 1
    flat = frame([(100,100,100)] * 261)
    ctx = SimpleNamespace(history=flat, parameters=parameters, portfolio=SimpleNamespace(quantity=1))
    assert original.decide(ctx).target == strategy.decide(ctx).target == 0
    checks.append('held_c13_equivalence_and_strict_exit_equality')
    run.save(run.WORK / 'others/precheck_mechanism.json', {
        'status': 'PASS', 'checks': checks, 'held_random_contexts': held_checks,
        'strategy_source_sha256': sha256((run.WORK / 'src/strategy.py').read_bytes()).hexdigest(),
        'check_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'original_c13_source_sha256': sha256(path.read_bytes()).hexdigest(),
        'scope': 'Synthetic rule checks; no real prices or strategy performance'})
    print('MECHANISM PASS', len(checks), 'boundaries and', held_checks, 'held contexts', flush=True)


if __name__ == '__main__':
    main()
