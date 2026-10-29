"""Independent synthetic checks; no historical data or governance writes."""
from math import fsum
from statistics import median
import sys

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
from signals import NAMES, compute, predicates, scalar_at  # noqa: E402


ZONE = 'America/New_York'


def fixture(days=35, *, one_slot=False):
    """Synthetic weekdays deliberately span DST; day 8 has a half-day shape."""
    rows = []
    for day_no, day in enumerate(pd.bdate_range('2020-10-05', periods=days)):
        start = pd.Timestamp(f'{day.date()} 09:30', tz=ZONE)
        count = 1 if one_slot else (7 if day_no == 8 else 13)
        for slot in range(count):
            if not one_slot and day_no == 12 and slot == 2:
                continue
            at = start + pd.Timedelta(minutes=30*slot)
            rows.append({'BarStart':at.tz_convert('UTC'),
                'Date':(at+pd.Timedelta(minutes=30)).tz_convert('UTC'),
                'Open':100., 'High':101., 'Low':99., 'Close':100.,
                'Volume':float(100+day_no*10+slot)})
    return pd.DataFrame(rows)


def set_prices(frame, index, *, close, high=None, low=None):
    frame.loc[index,['Open','Close']] = close
    frame.loc[index,'High'] = close+1 if high is None else high
    frame.loc[index,'Low'] = close-1 if low is None else low


def historical_volumes(frame, i):
    """Independent date/clock selection, with explicit distinct prior dates."""
    now = frame.BarStart.iloc[i].tz_convert(ZONE)
    selected = []
    seen = set()
    for j in reversed(range(i)):
        at = frame.BarStart.iloc[j].tz_convert(ZONE)
        day = at.date()
        if day < now.date() and at.strftime('%H:%M') == now.strftime('%H:%M'):
            assert day not in seen
            seen.add(day)
            selected.append(j)
            if len(selected) == 20:
                break
    return selected


def independent_flags(frame, i):
    """Direct arithmetic oracle, separate from vector feature construction."""
    volumes = historical_volumes(frame, i)
    if i < 77 or len(volumes) < 20:
        return None
    vol_median = median(float(frame.Volume.iloc[j]) for j in volumes)
    if vol_median <= 0:
        return None
    closes = [float(x) for x in frame.Close]
    def mean(end):
        return fsum(closes[end-64:end+1])/65
    def atr(end, n):
        return fsum(max(float(frame.High.iloc[j]-frame.Low.iloc[j]),
            abs(float(frame.High.iloc[j])-closes[j-1]),
            abs(float(frame.Low.iloc[j])-closes[j-1]))
            for j in range(end-n+1,end+1))/n
    a = closes[i] > max(float(x) for x in frame.High.iloc[i-65:i])
    return {'A':a,
        'B':mean(i)>mean(i-13) and closes[i-1]<=mean(i-1) and closes[i]>mean(i),
        'C':closes[i-1]<=mean(i-1)-2*atr(i-1,13) and closes[i]>float(frame.High.iloc[i-1]),
        'AC':a and atr(i-1,13)<=.7*atr(i-1,65),
        'AV':a and float(frame.Volume.iloc[i])>=1.5*vol_median}


def check_fixture(frame, expected_name):
    flags,ready,_ = compute(frame)
    i = len(frame)-1
    assert ready.iloc[i]
    expected = independent_flags(frame,i)
    actual = {k:bool(flags[k].iloc[i]) for k in NAMES}
    assert expected == actual == scalar_at(frame,i)
    assert actual[expected_name], (expected_name,actual)


def run_checks():
    checks = []
    # Direct predicate probes isolate every strict/inclusive inequality.
    values = dict(close=110., previous_close=99., previous_high=100., mean=100.,
        previous_mean=101., lag_mean=99., previous_atr=1., previous_high65=109.,
        previous_atr13=7., previous_atr65=10., volume=150., volume_median=100.)
    assert all(predicates(**values).values())
    probes = [
        ('A', 'close', 109., False), ('A','close',109.01,True),
        ('B','mean',99.,False), ('B','previous_close',101.,True),
        ('B','previous_close',101.01,False), ('B','close',100.,False),
        ('C','previous_close',99.,True), ('C','previous_close',99.01,False),
        ('C','close',100.,False), ('C','close',100.01,True),
        ('AC','previous_atr13',7.,True), ('AC','previous_atr13',7.01,False),
        ('AV','volume',150.,True), ('AV','volume',149.99,False),
    ]
    for name,key,value,expected in probes:
        assert bool(predicates(**{**values,key:value})[name]) is expected,(name,key,value)
    absent = predicates(**{**values,'close':109.})
    assert not absent['A'] and not absent['AC'] and not absent['AV']
    checks.append('five_predicates_positive_negative_strict_and_inclusive_boundaries')

    base = fixture()
    i = len(base)-1
    sample = base.copy(deep=True)
    set_prices(sample,i,close=103.)
    check_fixture(sample,'A')
    sample.loc[i,'Volume'] = 1.5*median(float(sample.Volume.iloc[j])
        for j in historical_volumes(sample,i))
    check_fixture(sample,'AV')
    sample = base.copy(deep=True)
    sample.loc[i-65:i-14,['High','Low']] = [105.,95.]
    set_prices(sample,i,close=106.)
    check_fixture(sample,'AC')
    sample = base.copy(deep=True)
    for j,close in zip(range(i-100,i-1),np.linspace(80.,100.,99),strict=True):
        set_prices(sample,j,close=float(close))
    set_prices(sample,i-1,close=80.)
    set_prices(sample,i,close=105.)
    check_fixture(sample,'B')
    sample = base.copy(deep=True)
    set_prices(sample,i-1,close=70.)
    set_prices(sample,i,close=72.)
    check_fixture(sample,'C')
    flat,ready,_ = compute(base)
    assert ready.iloc[i] and not flat.iloc[i].any()
    checks.append('each_expression_has_a_positive_price_fixture_and_flat_negative_control')

    _,_,features = compute(sample)
    changed = sample.copy(deep=True)
    changed.loc[i,['High','Low','Volume']] = [1000.,1.,1e8]
    _,_,after = compute(changed)
    prior = ['previous_close','previous_high','previous_mean','lag_mean',
        'previous_atr','previous_high65','previous_atr13','previous_atr65','volume_median']
    pd.testing.assert_series_equal(features.loc[i,prior],after.loc[i,prior])
    checks.append('current_bar_excluded_from_prior_high_atr_and_volume_baselines')

    local = base.BarStart.dt.tz_convert(ZONE)
    days = sorted(set(local.dt.date))
    target = next(j for j,at in enumerate(local)
                  if at.date()==days[24] and at.strftime('%H:%M')=='09:30')
    indices = historical_volumes(base,target)
    assert len(indices)==20 and len({local.iloc[j].date() for j in indices})==20
    assert len({base.BarStart.iloc[j].hour for j in indices})==2
    _,ready,features = compute(base)
    assert ready.iloc[target]
    assert features.volume_median.iloc[target] == median(float(base.Volume.iloc[j]) for j in indices)
    changed = base.copy(deep=True)
    same_day = local.dt.date.eq(local.iloc[target].date())
    changed.loc[same_day,'Volume'] = 1e9
    _,_,after = compute(changed)
    assert after.volume_median.iloc[target]==features.volume_median.iloc[target]
    checks.append('volume_uses_twenty_prior_distinct_local_sessions_across_dst_and_excludes_today')

    target = next(j for j,at in enumerate(local)
                  if at.date()==days[21] and at.strftime('%H:%M')=='15:00')
    indices = historical_volumes(base,target)
    assert len(indices)==20 and local.iloc[indices[-1]].date()==days[0]
    assert days[8] not in {local.iloc[j].date() for j in indices}
    assert features.volume_median.iloc[target] == median(float(base.Volume.iloc[j]) for j in indices)
    checks.append('half_day_missing_slot_is_not_zero_filled_or_shortened_to_nineteen_days')

    early = next(j for j,at in enumerate(local)
                 if at.date()==days[19] and at.strftime('%H:%M')=='09:30')
    assert early>78 and len(historical_volumes(base,early))==19
    assert not ready.iloc[early] and scalar_at(base,early) is None
    zero = base.copy(deep=True)
    zero['Volume'] = 0.
    _,zero_ready,_ = compute(zero)
    assert not zero_ready.any() and scalar_at(zero,i) is None
    checks.append('nineteen_prior_days_or_zero_volume_baseline_are_explicitly_not_ready')

    # Sparse but valid chronological input exposes the exact earliest feature boundary.
    sparse = fixture(85,one_slot=True)
    _,sparse_ready,_ = compute(sparse)
    assert not sparse_ready.iloc[76] and sparse_ready.iloc[77]
    assert scalar_at(sparse,76) is None
    assert scalar_at(sparse,77)==independent_flags(sparse,77)
    checks.append('exact_77_index_warmup_boundary_agrees_between_vector_and_scalar')

    variable = fixture()
    rng = np.random.default_rng(20)
    closes = 100*np.exp(np.cumsum(rng.normal(0,.018,len(variable))))
    variable['Open'] = closes
    variable['Close'] = closes
    variable['High'] = closes*(1+rng.uniform(.001,.02,len(variable)))
    variable['Low'] = closes*(1-rng.uniform(.001,.02,len(variable)))
    variable['Volume'] *= rng.uniform(.5,2.5,len(variable))
    flags,ready,features = compute(variable)
    for j in range(len(variable)):
        expected = independent_flags(variable,j)
        assert bool(ready.iloc[j]) == (expected is not None),j
        assert scalar_at(variable,j)==expected,j
        if expected is not None:
            assert {k:bool(flags[k].iloc[j]) for k in NAMES}==expected,j
    assert (flags.AC <= flags.A).all() and (flags.AV <= flags.A).all()
    checks.append('independent_scalar_and_vector_agree_for_every_synthetic_row_and_condition_subsets')

    cut = 330
    changed = variable.copy(deep=True)
    changed.loc[cut:,['Open','High','Low','Close']] *= 7
    changed.loc[cut:,'Volume'] *= 10
    f2,r2,x2 = compute(changed)
    pd.testing.assert_frame_equal(flags.iloc[:cut],f2.iloc[:cut])
    pd.testing.assert_series_equal(ready.iloc[:cut],r2.iloc[:cut])
    pd.testing.assert_frame_equal(features.iloc[:cut],x2.iloc[:cut])
    fp,rp,xp = compute(variable.iloc[:cut].copy())
    pd.testing.assert_frame_equal(flags.iloc[:cut],fp)
    pd.testing.assert_series_equal(ready.iloc[:cut],rp)
    pd.testing.assert_frame_equal(features.iloc[:cut],xp)
    checks.append('future_suffix_and_truncated_prefix_leave_all_prior_flags_and_features_unchanged')

    bad = base.copy(deep=True)
    bad.loc[1,'BarStart'] = bad.loc[0,'BarStart']
    try:
        compute(bad)
    except ValueError as exc:
        assert 'Duplicate session' in str(exc)
    else:
        raise AssertionError('Duplicate local session-slot was accepted')
    checks.append('duplicate_local_session_slot_rejected')
    return checks


if __name__=='__main__':
    result = run_checks()
    print('PASS',len(result),*result,sep='\n',flush=True)
