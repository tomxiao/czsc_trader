"""Synthetic branch/boundary checks, independent of LITE performance."""
from types import SimpleNamespace
import pandas as pd
from strategy import decide
from run import configurations, candidate, save, WORK


def frame(last=100., prior=100.):
    return pd.DataFrame({'Close': [prior]*260+[last], 'High': [prior+1]*260+[last+1], 'Low': [prior-1]*260+[last-1]})


def check():
    configs = configurations()
    def target(key, hist, quantity=0, overrides=None):
        p = {**configs[key], **(overrides or {})}
        ctx = SimpleNamespace(parameters=p, history=hist, portfolio=SimpleNamespace(quantity=quantity))
        result = decide(ctx)
        assert result.explanation.case_key == ('long' if result.target else 'flat')
        return result.target
    assert target('C0000', frame()) == 1
    assert target('C0001', frame()) == 0
    assert target('C0001', frame(101)) == 1
    assert target('C0002', frame(101)) == 0  # equality with previous high: no breakout
    assert target('C0002', frame(102)) == 1  # exclude current high from threshold
    assert target('C0002', frame(99), 1) == 1  # support equality is not a break
    assert target('C0002', frame(98), 1) == 0
    h = frame(96)
    assert target('C0004', h) == 1
    assert target('C0005', h) == 0  # falling background excludes dip entry
    assert target('C0004', frame(), 1) == 0  # recovered mean
    assert target('C0005', h, 1) == 1  # entry-only filter does not force exit
    assert target('C0006', h, 1) == 0  # explicit background-invalidated exit
    bullish_dip = pd.DataFrame({'Close':[90.]*248+[100.]*12+[96.], 'High':[91.]*248+[101.]*12+[97.], 'Low':[89.]*248+[99.]*12+[95.]})
    assert target('C0005', bullish_dip) == 1
    for key,p in configs.items():
        c = candidate(key,p)
        assert c.definition.from_dict(c.definition.to_dict()) == c.definition
    save(WORK/'others/precheck.json', {'status':'PASS', 'synthetic_branch_assertions':13,
        'definition_roundtrips':7, 'market_performance_accessed':False,
        'coverage':'entry/holding/exit, threshold equality, prior-channel exclusion, entry-only versus ongoing trend filter, source identity'})
    print('synthetic precheck PASS')


if __name__ == '__main__':
    check()
