"""Synthetic EX016 contracts and retained-control equivalence; no real replay.

The calendar deliberately spans the 2019 DST change and Thanksgiving half-day.
These are finite implementation checks, not evidence of trading performance.
"""
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import json

import pandas as pd
import strategy


WORK = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[5]
ZONE = ZoneInfo('America/New_York')


def retained(name, experiment):
    path = ROOT / 'research/S017/experiments' / experiment / 'src/strategy.py'
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, sha256(path.read_bytes()).hexdigest()


def fixture(*, held=False, lite_end=100., spy_end=95., current_close=105.):
    days, day = [], date(2019, 10, 21)
    while len(days) < 30:
        if day.weekday() < 5 and day != date(2019, 11, 28):
            days.append(day)
        day += timedelta(days=1)
    rows, daily = [], []
    for day in days:
        start = datetime.combine(day, time(9, 30), ZONE)
        stop = datetime.combine(day, time(13 if day == date(2019, 11, 29) else 16), ZONE)
        first = start
        while start < stop:
            end = start + timedelta(minutes=30)
            rows.append(dict(BarStart=start, Date=end, AvailableDate=end, Open=100.,
                High=100.1, Low=99.9, Close=100., Volume=10000.))
            start = end
        daily.append(dict(BarStart=first, Date=stop, AvailableDate=stop, Open=100.,
            High=100.1, Low=99.9, Close=100., Volume=100000.))
    history, market = pd.DataFrame(rows), pd.DataFrame(daily[:-1])
    for frame in (history, market):
        for field in ('BarStart', 'Date', 'AvailableDate'):
            frame[field] = pd.to_datetime(frame[field], utc=True)
    execution = pd.Timestamp(datetime.combine(days[-1], time(15, 30), ZONE))
    history = history.loc[history.Date <= execution].copy(deep=True)
    last_daily = market.Date.iloc[-1]
    history.loc[history.Date == last_daily, ['Close', 'High', 'Low']] = [
        lite_end, max(100.1, lite_end+.1), min(99.9, lite_end-.1)]
    history.loc[history.index[-1], ['Close', 'High', 'Low']] = [
        current_close, max(100.1, current_close+.1), min(99.9, current_close-.1)]
    market.loc[market.index[-1], ['Close', 'High', 'Low']] = [
        spy_end, max(100.1, spy_end+.1), min(99.9, spy_end-.1)]
    parameters = json.loads((WORK/'protocols/configurations.json').read_text(encoding='utf-8'))['C0045']
    return SimpleNamespace(history=history, parameters=parameters,
        portfolio=SimpleNamespace(quantity=int(held)), auxiliary_histories={'market': market},
        point=SimpleNamespace(observed_through=execution.to_pydatetime(), decision_at=execution.to_pydatetime()))


def facts(decision):
    return {item.key: item.text for item in decision.explanation.basis}


def rejected(name, mutate):
    ctx = fixture()
    mutate(ctx)
    try:
        strategy.decide(ctx)
    except (ValueError, TypeError):
        return name
    raise AssertionError('invalid input accepted: '+name)


def main():
    original, source13 = retained('_ex016_original_c13', 'EX003_20261028')
    gated, source43 = retained('_ex016_original_c43', 'EX014_20261029')
    held_checks, old_gate_checks, exception_changes, total = 0, 0, 0, 0
    for held in (False, True):
        for close in (95., 99., 100., 101., 105.):
            for spy_end in (95., 100., 105.):
                for lite_end in (90., 100., 110.):
                    ctx = fixture(held=held, lite_end=lite_end, spy_end=spy_end, current_close=close)
                    before_h, before_m = ctx.history.copy(deep=True), ctx.auxiliary_histories['market'].copy(deep=True)
                    actual, old13, old43 = strategy.decide(ctx), original.decide(ctx), gated.decide(ctx)
                    actual_facts = facts(actual)
                    assert strategy.base_signal(ctx.history, held, ctx.parameters)[0] == bool(old13.target)
                    if held:
                        assert actual.target == old13.target
                        for key, value in facts(old13).items():
                            assert actual_facts[key] == value
                        held_checks += 1
                    if actual_facts['weak_market_exception'] == 'False':
                        assert actual.target == old43.target
                        for key, value in facts(old43).items():
                            assert actual_facts[key] == value
                        old_gate_checks += 1
                    exception_changes += int(not held and actual.target != old43.target)
                    assert strategy.decide(ctx) == actual
                    pd.testing.assert_frame_equal(ctx.history, before_h)
                    pd.testing.assert_frame_equal(ctx.auxiliary_histories['market'], before_m)
                    total += 1
    assert held_checks > 0 and old_gate_checks > 0 and exception_changes > 0

    ctx = fixture()
    value = facts(strategy.decide(ctx))
    assert value['weak_market_exception'] == 'True' and strategy.decide(ctx).target == 1
    assert value['relative_matched_closes'] == '20' and value['relative_close_intervals'] == '19'
    matched = ctx.auxiliary_histories['market'].iloc[-20:]
    assert matched.Date.iloc[0].tz_convert(ZONE).utcoffset() != matched.Date.iloc[-1].tz_convert(ZONE).utcoffset()
    assert matched.Date.iloc[-1].tz_convert(ZONE).hour == 13
    assert matched.Date.iloc[-1].date() == date(2019, 11, 29)
    assert ctx.point.decision_at.astimezone(ZONE).date() == date(2019, 12, 2)
    # The first current-session point uses the same prior twenty complete closes.
    ctx.history = ctx.history.loc[ctx.history.Date <= matched.Date.iloc[-1]].copy(deep=True)
    opening = datetime(2019, 12, 2, 9, 30, tzinfo=ZONE)
    ctx.point = SimpleNamespace(observed_through=matched.Date.iloc[-1].to_pydatetime(), decision_at=opening)
    first = facts(strategy.decide(ctx))
    assert first['relative_lite_ratio'] == value['relative_lite_ratio']
    assert first['relative_market_ratio'] == value['relative_market_ratio']

    equal_ctx = fixture(lite_end=95., spy_end=95.)
    assert facts(strategy.decide(equal_ctx))['relative_allowed'] == 'False'
    assert strategy.decide(equal_ctx).target == gated.decide(equal_ctx).target == 0
    market_only = fixture(lite_end=90., spy_end=105.)
    assert facts(strategy.decide(market_only))['relative_allowed'] == 'False'
    assert strategy.decide(market_only).target == gated.decide(market_only).target == 1
    negative = fixture(lite_end=95., spy_end=90., current_close=95.)
    negative_facts = facts(strategy.decide(negative))
    assert negative_facts['relative_allowed'] == 'True' and negative_facts['base_target'] == 'False'
    assert strategy.decide(negative).target == 0
    # Strict original stock-buffer equality: neither entry nor holding is allowed.
    for held in (False, True):
        constant = fixture(held=held, spy_end=105.)
        constant.history.loc[:, ['Open', 'High', 'Low', 'Close']] = 100.
        assert strategy.decide(constant).target == original.decide(constant).target == 0

    def matched_stamp(ctx, offset=8):
        return ctx.auxiliary_histories['market'].iloc[-20:].Date.iloc[offset]

    def missing(ctx):
        ctx.history = ctx.history.loc[ctx.history.Date != matched_stamp(ctx)].copy()

    def duplicate(ctx):
        ctx.history = pd.concat([ctx.history, ctx.history.loc[ctx.history.Date == matched_stamp(ctx)]]).sort_values('Date')

    def bad_close(ctx, which, value):
        frame = ctx.history if which == 'main' else ctx.auxiliary_histories['market']
        frame.loc[frame.Date == matched_stamp(ctx), 'Close'] = value

    def future(ctx, which, field):
        frame = ctx.history if which == 'main' else ctx.auxiliary_histories['market']
        frame.loc[frame.index[-1], field] = pd.Timestamp(ctx.point.decision_at)+pd.Timedelta(minutes=30)

    failures = [rejected('missing_interior_daily_close', missing), rejected('duplicate_daily_close', duplicate)]
    for which in ('main', 'aux'):
        for bad in (0., -1., float('nan'), float('inf')):
            failures.append(rejected(which+'_invalid_interior_close_'+str(bad),
                                     lambda ctx, w=which, b=bad: bad_close(ctx, w, b)))
        for field in ('Date', 'AvailableDate', 'BarStart'):
            failures.append(rejected(which+'_future_'+field, lambda ctx, w=which, f=field: future(ctx, w, f)))

    def wrong_date(ctx):
        index = ctx.history.index[ctx.history.Date == matched_stamp(ctx)][0]
        ctx.history.loc[index, 'Date'] -= pd.Timedelta(seconds=1)
    failures.append(rejected('near_but_not_exact_daily_time', wrong_date))

    def wrong_interval(ctx):
        ctx.history.loc[ctx.history.Date == matched_stamp(ctx), 'BarStart'] -= pd.Timedelta(minutes=30)
    failures.append(rejected('matched_close_not_m30', wrong_interval))

    def duplicate_aux(ctx):
        frame = ctx.auxiliary_histories['market']
        ctx.auxiliary_histories['market'] = pd.concat([frame, frame.iloc[[-2]]]).sort_values('Date')
    failures.append(rejected('duplicate_aux_completion', duplicate_aux))

    def too_short(ctx):
        ctx.auxiliary_histories['market'] = ctx.auxiliary_histories['market'].iloc[-19:]
    failures.append(rejected('only_nineteen_complete_days', too_short))

    def naive(ctx):
        ctx.history['Date'] = ctx.history.Date.dt.tz_localize(None)
    failures.append(rejected('naive_main_completion', naive))

    def overflow_ratio(ctx):
        stamp = matched_stamp(ctx, 0)
        ctx.history.loc[ctx.history.Date == stamp, 'Close'] = 1e-320
    failures.append(rejected('finite_inputs_overflow_relative_ratio', overflow_ratio))

    # Twenty complete days plus today's twelve observations fit 273; public
    # runtime retains the full causal history instead of truncating to warmup.
    ctx = fixture()
    tail = ctx.history.iloc[-273:].copy(deep=True)
    assert len(tail.loc[tail.Date.isin(ctx.auxiliary_histories['market'].iloc[-20:].Date)]) == 20
    full = strategy.decide(ctx)
    ctx.history = tail
    assert strategy.decide(ctx) == full
    print(json.dumps({'status': 'PASS', 'synthetic_states': total,
        'held_target_and_original_facts_equal_c13': held_checks,
        'no_exception_target_and_original_facts_equal_c43': old_gate_checks,
        'flat_exception_changes': exception_changes, 'rejections': failures,
        'halfday_dst_weekend_exact_alignment': True, 'first_point_same_complete_days': True,
        'strict_ratio_and_original_stock_equality': True, 'negative_relative_strength_not_entry_alone': True,
        'inputs_immutable_and_repeatable': True, 'warmup_273_covers_selected_closes': True,
        'original_c13_source_sha256': source13, 'original_c43_source_sha256': source43,
        'strategy_source_sha256': sha256((WORK/'src/strategy.py').read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
