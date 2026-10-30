"""Synthetic formula, boundary, causality and confirmed-cycle checks only."""
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from strategy import NAMES, compute, decide, entry_facts

WORK = Path(__file__).resolve().parents[1]


def fixture():
    rng = np.random.default_rng(178)
    closes = 100+np.cumsum(rng.normal(0, .5, 720))
    opening = np.r_[100., closes[:-1]]
    start = pd.date_range('2019-01-02 14:30', periods=len(closes), freq='30min', tz='UTC')
    return pd.DataFrame(dict(Open=opening, High=np.maximum(opening, closes)+rng.uniform(.01,.5,len(closes)),
        Low=np.minimum(opening, closes)-rng.uniform(.01,.5,len(closes)), Close=closes,
        BarStart=start, Date=start+pd.Timedelta(minutes=30), AvailableDate=start+pd.Timedelta(minutes=30)))


def independent(bars, i):
    c = bars.Close.to_numpy()
    high, low, opening = (bars[k].to_numpy() for k in ('High','Low','Open'))
    atr = sum(max(high[j]-low[j],abs(high[j]-c[j-1]),abs(low[j]-c[j-1]))
              for j in range(i-16,i-3))/13
    return (c[i] > max(high[i-6:i]),
        c[i-3]-c[i-9] >= atr and c[i-2] < c[i-3] and c[i-1] <= c[i-2] and c[i] > high[i-1],
        low[i] < min(low[i-6:i]) and c[i] > min(low[i-6:i]) and c[i] > opening[i])


def ctx(bars, quantity=0, entry=None, horizon=6, mechanism=NAMES[0]):
    return SimpleNamespace(history=bars,
        parameters=dict(entry_mechanism=mechanism,max_holding_bars=horizon),
        portfolio=SimpleNamespace(quantity=quantity,cycle_entry=entry,cycle_cost=100. if quantity else 0.,reference_price_scale=1.),
        point=SimpleNamespace(observed_through=bars.Date.iloc[-1],decision_at=bars.Date.iloc[-1]))


def target(value):
    # Public typed decision exposes a numeric target.
    return value.target


def main():
    bars=fixture()
    flags,parents,regimes=compute(bars)
    compared=0
    for i in range(17,len(bars)):
        expected=independent(bars,i)
        assert tuple(bool(flags.iloc[i][k]) for k in NAMES)==expected
        for k,want in zip(NAMES,expected,strict=True):
            assert entry_facts(bars.iloc[:i+1],k)['entry_signal']==want
            assert not want or bool(parents.iloc[i][k])
            compared+=1
    assert all(flags[k].any() for k in NAMES)
    altered=bars.copy()
    altered.loc[500:,['Open','High','Low','Close']]*=20
    a,b,c=compute(altered)
    pd.testing.assert_frame_equal(flags.iloc[:500],a.iloc[:500])
    pd.testing.assert_frame_equal(parents.iloc[:500],b.iloc[:500])
    pd.testing.assert_series_equal(regimes.iloc[:500],c.iloc[:500])
    boundary=bars.iloc[:40].copy()
    level=float(boundary.High.iloc[-7:-1].max())
    boundary.loc[boundary.index[-1],['Open','High','Low','Close']]=[level-.2,level+.1,level-.3,level]
    assert not entry_facts(boundary,NAMES[0])['entry_signal']
    boundary.loc[boundary.index[-1],'Close']=level+.01
    assert entry_facts(boundary,NAMES[0])['entry_signal']
    low6=float(boundary.Low.iloc[-7:-1].min())
    boundary.loc[boundary.index[-1],['Open','High','Low','Close']]=[low6+.05,low6+.2,low6,low6+.1]
    assert not entry_facts(boundary,NAMES[2])['entry_signal']
    boundary.loc[boundary.index[-1],'Low']=low6-.01
    assert entry_facts(boundary,NAMES[2])['entry_signal']
    pull=bars.iloc[:18].copy()
    pull[['Open','High','Low','Close']]=[100.,101.,99.,100.]
    for i, values in ((14,[100.,103.,99.,102.]),(15,[102.,103.,100.,101.]),
                      (16,[101.,102.,99.,100.]),(17,[100.,103.,99.,102.])):
        pull.loc[i,['Open','High','Low','Close']]=values
    assert not entry_facts(pull,NAMES[1])['entry_signal']  # recovery is strict
    pull.loc[17,'Close']=102.1
    assert entry_facts(pull,NAMES[1])['entry_signal']  # advance == ATR is inclusive
    pull.loc[14,'Close']=101.99
    assert not entry_facts(pull,NAMES[1])['entry_signal']
    cycle=bars.iloc[:40]
    for n in (6,13):
        for count in (1,n-1,n,n+1):
            history=bars.iloc[:40+count]
            entry=bars.BarStart.iloc[40]
            result=decide(ctx(history,quantity=1,entry=entry,horizon=n))
            assert target(result)==int(count<n)
        # A failed buy remains flat; no fictional holding clock.
        assert target(decide(ctx(cycle,horizon=n)))==int(entry_facts(cycle,NAMES[0])['entry_signal'])
    bad=ctx(cycle)
    bad.parameters['max_holding_bars']=True
    try:
        decide(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('Boolean horizon accepted')
    for field in ('reference_price_scale','unavailable'):
        bad=ctx(cycle.copy())
        if field=='reference_price_scale':
            bad.portfolio.reference_price_scale=2.
        else:
            bad.history.loc[bad.history.index[-1],'AvailableDate']+=pd.Timedelta(minutes=1)
        try:
            decide(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid runtime context accepted: '+field)
    result={'status':'PASS','scope':'SYNTHETIC_ONLY','scalar_vector_comparisons':compared,
        'checks':['independent_scalar_vector','child_parent_containment','strict_boundaries',
                  'future_suffix_invariance','actual_fill_clock_6_13','blocked_exit_latching','failed_buy_no_clock','invalid_parameters'],
        'sources':{p.name:sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),WORK/'src/strategy.py')}}
    (WORK/'others/entry_checks.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':
    main()
