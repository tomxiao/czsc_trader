"""Fixed base-rule equivalence and strict gate boundaries on synthetic facts."""
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import strategy


def main():
    root=Path(__file__).resolve().parents[5]
    spec=spec_from_file_location('_retained_c0013',root/'research/S017/experiments/EX003_20261028/src/strategy.py')
    old=module_from_spec(spec)
    spec.loader.exec_module(old)
    p=dict(trend_bars=260,vol_bars=13,entry_atr=2.,exit_atr=2.,context_sessions=20,context_mode='BOTH')
    dates=pd.date_range('2018-11-01',periods=320,freq='30min',tz='UTC')
    h=pd.DataFrame(dict(Date=dates,Open=100.,Close=100.,High=100.1,Low=99.9,Volume=10000.))
    for held in (False,True):
        for close in (95.,99.,100.,101.,105.):
            h.loc[h.index[-1],['Close','High','Low']]=[close,max(100.1,close+.1),min(99.9,close-.1)]
            ctx=SimpleNamespace(history=h,portfolio=SimpleNamespace(quantity=int(held)),parameters=p)
            actual=strategy.base_signal(h,held,p)[0]
            assert actual==bool(old.decide(ctx).target)
    market=pd.DataFrame(dict(Date=pd.date_range('2018-11-01',periods=20,freq='B',tz='UTC'),Open=100.,Close=100.))
    industry=market.copy(deep=True)
    ctx=SimpleNamespace(history=h,portfolio=SimpleNamespace(quantity=0),parameters=p,
        auxiliary_histories={'market':market,'industry':industry})
    assert strategy.base_signal(h,False,p)[0]
    assert strategy.decide(ctx).target==0
    market.loc[market.index[-1],'Close']=101.
    assert strategy.decide(ctx).target==0
    industry['Close']=100.1
    assert strategy.decide(ctx).target==1
    # Rescale one whole daily bar as a split would: within-session C/O is invariant.
    before=strategy.decide(ctx)
    industry.loc[industry.index[-1],['Open','Close']]/=2
    assert strategy.decide(ctx)==before
    print('EX010 base parity, strict gates and same-session scale invariance PASS')


if __name__=='__main__':
    main()
