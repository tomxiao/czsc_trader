"""Single policy contrast: flat decisions equal C0040; held decisions equal C0013."""
from importlib.util import spec_from_file_location, module_from_spec
from types import SimpleNamespace
import pandas as pd
import run
import strategy


def retained(name, experiment):
    path = run.ROOT / 'research/S017/experiments' / experiment / 'src/strategy.py'
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    original = retained('_retained_c0013', 'EX003_20261028')
    gated = retained('_retained_c0040', 'EX013_20261029')
    parameters = run.configurations()['C0043']
    dates = pd.date_range('2018-11-01', periods=320, freq='30min', tz='UTC')
    history = pd.DataFrame(dict(Date=dates, Open=100., Close=100., High=100.1, Low=99.9, Volume=10000.))
    market = pd.DataFrame(dict(Date=pd.date_range('2018-11-01', periods=20, freq='B', tz='UTC'),
                               Open=100., Close=100.))
    checks, changed_held = 0, 0
    for held in (False, True):
        for close in (95., 99., 100., 101., 105.):
            history.loc[history.index[-1], ['Close', 'High', 'Low']] = [
                close, max(100.1, close + .1), min(99.9, close - .1)]
            for market_close in (99., 100., 101.):
                market.loc[market.index[-1], 'Close'] = market_close
                ctx = SimpleNamespace(history=history, portfolio=SimpleNamespace(quantity=int(held)),
                    parameters=parameters, auxiliary_histories={'market': market})
                actual = strategy.decide(ctx)
                assert strategy.base_signal(history, held, parameters)[0] == bool(original.decide(ctx).target)
                assert actual.target == (original.decide(ctx).target if held else gated.decide(ctx).target)
                if not held and market_close <= 100.:
                    assert actual.target == 0
                changed_held += int(held and actual.target != gated.decide(ctx).target)
                assert 'ENTRY_ONLY' in str(actual.explanation)
                checks += 1
    assert changed_held > 0
    # Zero-range constant price puts both stock thresholds exactly at the close.
    history.loc[:, ['Open', 'High', 'Low', 'Close']] = 100.
    market.loc[market.index[-1], 'Close'] = 101.
    for held in (False, True):
        ctx = SimpleNamespace(history=history, portfolio=SimpleNamespace(quantity=int(held)),
            parameters=parameters, auxiliary_histories={'market': market})
        assert strategy.decide(ctx).target == 0
        assert strategy.decide(ctx).target == original.decide(ctx).target
    print('EX014 PASS:', checks, 'flat-C40/held-C13 contrasts; market equality/false and stock equality boundaries')


if __name__ == '__main__':
    main()
