"""Focused temporal/execution/selection checks for the event diagnostic."""
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp
import numpy as np
import pandas as pd
from study import (WORK, digest, scan_chunk, label, nonoverlap, matched, price_at, save)


def fixture():
    end = pd.date_range('2020-01-01', periods=360, freq='30min', tz='UTC')
    close = 100+np.sin(np.arange(360)/3)*2+np.arange(360)*.02
    bars = pd.DataFrame({'Date':end, 'BarStart':end-pd.Timedelta(minutes=30),
        'AvailableDate':end,'Open':close, 'High':close+1,'Low':close-1,'Close':close,
        'Volume':10000.,'BarStatus':'OBSERVED','ExecutionBlocked':False})
    base = [(10,8,9),(12,9,11),(11,7,8),(10,5,6),(12,7,11),
            (15,10,14),(12,9,10),(11,7,8),(13,8,12)]
    bars.loc[260:268,['High','Low','Close']] = np.array(base,dtype=float)*10
    bars.loc[260:268,'Open'] = bars.loc[260:268,'Close']
    bars.loc[269,['Open','High','Low','Close']] = [120.,130.,110.,120.]
    constraints = pd.DataFrame({'Date':bars.BarStart,'AvailableDate':bars.BarStart,
        'Tradable':True, 'QuantityStep':1., 'PriceTick':.01})
    return bars,constraints


def main():
    checks = []
    bars, constraints = fixture()
    indices = list(range(260,320))
    serial = scan_chunk((bars,indices))
    assert dict((i,flag) for i,flag,_ in serial)[268]
    assert not dict((i,flag) for i,flag,_ in serial)[267]
    assert label(bars,constraints,268,13)['entry_price']==120.
    checks.append('positive_pat_after_confirmation_and_next_interval_entry')
    with ProcessPoolExecutor(max_workers=2,mp_context=mp.get_context('spawn')) as pool:
        parallel = sorted(sum(pool.map(scan_chunk,[(bars,indices[:30]),(bars,indices[30:])]),[]))
    assert serial == parallel
    checks.append('two_spawn_workers_equal_serial')
    changed = bars.copy(deep=True)
    changed.loc[290:,['Open','High','Low','Close']] *= 2
    assert scan_chunk((changed,indices[:30])) == serial[:30]
    checks.append('future_suffix_does_not_change_prior_signals')
    row = label(bars,constraints,270,13)
    expected = bars.iloc[284].Open*.999/(bars.iloc[271].Open*1.001)-1
    assert row['status']=='COMPLETE' and abs(row['price_net_return']-expected)<1e-14
    assert row['information_return'] == bars.iloc[283].Close/bars.iloc[270].Close-1
    checks.append('signal_then_entry_then_N_completed_bars_then_exit_and_two_fees')
    blocked = bars.copy(deep=True)
    blocked.loc[271,'ExecutionBlocked'] = True
    assert label(blocked,constraints,270,13)['status']=='NO_ENTRY'
    blocked.loc[271,'ExecutionBlocked'] = False
    blocked.loc[284,'ExecutionBlocked'] = True
    assert label(blocked,constraints,270,13)['status']=='NO_EXIT'
    checks.append('blocked_entry_and_exit_are_not_zero_returns')
    assert label(bars,constraints,len(bars)-5,13)['status']=='RIGHT_CENSORED_EXIT'
    checks.append('right_censor_never_reads_beyond_development_end')
    quote = bars.iloc[271].copy()
    quote['Open'],quote['Low'],quote['High'] = 102.,101.,103.
    assert price_at(quote,constraints.iloc[271],'BUY',101.)[0] is None
    quote['Low'] = 100.99
    assert price_at(quote,constraints.iloc[271],'BUY',101.) == (101.,'BAR_INTERVAL')
    checks.append('original_strict_limit_touch_and_interval_precision')
    assert nonoverlap([1,2,15,16,30,31],13)=={1,16,31}
    checks.append('nonoverlap_selection_uses_only_times_and_keeps_invalid_events')
    inputs = [dict(price_net_return=v,stratum=k,month='2020-01')
        for k,v in [('a',.1),('a',-.1),('b',.2),('b',.4)]]
    match,_ = matched(inputs,[inputs[0],inputs[2]])
    assert abs(match['difference']['mean'])<1e-14 and match['count']==2
    checks.append('matched_control_uses_signal_weights_and_same_complete_population')
    # No full-bar high/low enters path labels; changing highs cannot fabricate MFE.
    changed = bars.copy(deep=True)
    changed.loc[271:283,'High'] *= 10
    after = label(changed,constraints,270,13)
    assert after['close_path_max']==row['close_path_max']
    checks.append('close_path_does_not_use_pre_fill_intrabar_extremes')
    missing = bars.copy(deep=True)
    missing.loc[275,'BarStatus'] = 'MISSING'
    assert label(missing,constraints,270,13)['status']=='PATH_UNOBSERVED'
    checks.append('missing_path_does_not_shorten_horizon')
    save(WORK/'others/checks.json', {'status':'PASS', 'checks':checks,
        'study_sha256':digest(WORK/'src/study.py'), 'check_sha256':digest(WORK/'src/check.py')})
    print('PASS', len(checks), flush=True)


if __name__ == '__main__':
    main()
