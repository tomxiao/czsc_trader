"""Synthetic independent formulas, strict background and actual-fill clock."""
from hashlib import sha256
import json
from pathlib import Path
from statistics import fmean
from types import SimpleNamespace

import numpy as np
import pandas as pd
from strategy import NAMES, compute, decide, entry_facts

WORK = Path(__file__).resolve().parents[1]


def fixture():
    rng = np.random.default_rng(178)
    closes = 100 + np.cumsum(rng.normal(0, .5, 720))
    opening = np.r_[100., closes[:-1]]
    start = pd.date_range('2019-01-02 14:30', periods=len(closes), freq='30min', tz='UTC')
    return pd.DataFrame(dict(Open=opening, High=np.maximum(opening, closes)+rng.uniform(.01,.5,len(closes)),
        Low=np.minimum(opening, closes)-rng.uniform(.01,.5,len(closes)), Close=closes,
        BarStart=start, Date=start+pd.Timedelta(minutes=30), AvailableDate=start+pd.Timedelta(minutes=30)))


def independent(bars, i):
    previous = float(bars.Close.iloc[i-1])
    average = fmean(float(bars.Close.iloc[j]) for j in range(i-65, i))
    breakout = float(bars.Close.iloc[i]) > max(float(bars.High.iloc[j]) for j in range(i-6, i))
    low = previous < average
    return breakout, low and breakout, low


def ctx(bars, mechanism=NAMES[0], horizon=6, quantity=0, entry=None):
    return SimpleNamespace(history=bars, parameters={'entry_mechanism': mechanism, 'max_holding_bars': horizon},
        portfolio=SimpleNamespace(quantity=quantity, cycle_entry=entry, cycle_cost=100. if quantity else 0.,
                                  reference_price_scale=1.),
        point=SimpleNamespace(observed_through=bars.Date.iloc[-1], decision_at=bars.Date.iloc[-1]))


def main():
    bars = fixture()
    flags, parents, regimes = compute(bars)
    comparisons = 0
    for i in range(65, len(bars)):
        expected = independent(bars, i)
        assert tuple(bool(flags.iloc[i][name]) for name in NAMES) == expected
        for name, want in zip(NAMES, expected, strict=True):
            assert entry_facts(bars.iloc[:i+1], name)['entry_signal'] == want
            assert not want or bool(parents.iloc[i][name])
            comparisons += 1
    assert all(flags[name].any() for name in NAMES)
    assert (flags[NAMES[1]] == (flags[NAMES[0]] & flags[NAMES[2]])).all()
    future = bars.copy()
    future.loc[500:, ['Open','High','Low','Close']] *= 10
    a, b, c = compute(future)
    pd.testing.assert_frame_equal(flags.iloc[:500], a.iloc[:500])
    pd.testing.assert_frame_equal(parents.iloc[:500], b.iloc[:500])
    pd.testing.assert_series_equal(regimes.iloc[:500], c.iloc[:500])
    exact = bars.iloc[:66].copy()
    exact[['Open','High','Low','Close']] = [100., 100., 100., 100.]
    exact.loc[65, ['Open','High','Low','Close']] = [100., 102., 100., 101.]
    assert entry_facts(exact, NAMES[0])['entry_signal']
    assert not entry_facts(exact, NAMES[1])['entry_signal']
    assert not entry_facts(exact, NAMES[2])['entry_signal']
    assert compute(exact)[2].iloc[-1] == 'equal65'
    # A small decline in the previous close is strictly below its own mean.
    exact.loc[64, ['Open','High','Low','Close']] = [100., 100., 99.9, 99.9]
    assert entry_facts(exact, NAMES[1])['entry_signal']
    assert entry_facts(exact, NAMES[2])['entry_signal']
    exact.loc[65, 'Close'] = 100.
    assert not entry_facts(exact, NAMES[0])['entry_signal']
    assert not entry_facts(exact, NAMES[1])['entry_signal']
    assert entry_facts(exact, NAMES[2])['entry_signal']
    # The huge current price cannot enter the prior background average.
    exact.loc[65, ['High','Close']] = [10000., 10000.]
    assert entry_facts(exact, NAMES[2])['prior_sma65'] == fmean(exact.Close.iloc[:65])
    assert entry_facts(exact.iloc[:65], NAMES[1])['entry_ready'] is False
    for horizon in (6, 13):
        for name in NAMES:
            for count in (1, horizon-1, horizon, horizon+1, horizon+5):
                history = bars.iloc[:100+count]
                decision = decide(ctx(history, name, horizon, 1, bars.BarStart.iloc[100]))
                assert decision.target == int(count < horizon)
            # An unfilled buy does not start a fictional holding clock.
            history = bars.iloc[:100]
            assert decide(ctx(history, name, horizon)).target == int(entry_facts(history, name)['entry_signal'])
    for change in ('boolean_horizon', 'scale', 'availability', 'bad_ohlc', 'missing_cycle'):
        value = ctx(bars.iloc[:100].copy())
        if change == 'boolean_horizon':
            value.parameters['max_holding_bars'] = True
        elif change == 'scale':
            value.portfolio.reference_price_scale = 2.
        elif change == 'availability':
            value.history.loc[99, 'AvailableDate'] += pd.Timedelta(seconds=1)
        elif change == 'bad_ohlc':
            value.history.loc[99, 'High'] = .01
        else:
            value.portfolio.quantity = 1
        try:
            decide(value)
        except ValueError:
            pass
        else:
            raise AssertionError('Illegal context accepted: ' + change)
    result = {'status': 'PASS', 'scope': 'SYNTHETIC_ONLY', 'scalar_vector_comparisons': comparisons,
        'checks': ['independent_scalar_vector', 'M017_exact_intersection', 'strict_background_and_breakout',
                   'background_excludes_current_bar', 'prefix_future_invariance', 'actual_fill_clock_6_13',
                   'failed_buy_no_clock', 'blocked_exit_continues', 'illegal_context_rejected'],
        'sources': {p.name: sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), WORK/'src/strategy.py')}}
    (WORK/'others/entry_checks.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
