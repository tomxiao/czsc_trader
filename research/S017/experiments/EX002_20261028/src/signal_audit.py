"""Causal condition counts, not trades or independent opportunities."""
from datetime import date
from uuid import UUID
from types import SimpleNamespace
import pandas as pd
from dataflows import PreparedDataRef, EquityDataRequest, EquityQuery, EquityProduct
from run import ROOT, WORK, SOURCE, INSTRUMENT, context, configurations, save, read
from strategy import decide


def main():
    ref = read(ROOT/'research/S017/experiments/EX001_20261028/others/data_preparation_v2.json')['reference']
    prepared = PreparedDataRef(UUID(ref['space_id']), UUID(ref['preparation_id']), ref['manifest_sha256'])
    fetched = context().data.fetch(EquityDataRequest(INSTRUMENT,SOURCE,EquityQuery(EquityProduct.BARS,date(2018,11,1),date(2025,12,31))),prepared=prepared)
    assert fetched.ready, fetched.error
    frame = fetched.dataframe.reset_index(drop=True)
    assert frame.BarStatus.eq('OBSERVED').all()
    close = frame.Close
    slow = close.rolling(260).mean()
    mean = close.rolling(13).mean()
    atr = pd.concat([frame.High-frame.Low,(frame.High-close.shift(1)).abs(),(frame.Low-close.shift(1)).abs()],axis=1).max(axis=1).rolling(13).mean()
    trend = close > slow
    breakout = close > frame.High.shift(1).rolling(65).max()
    dip = close < mean-atr
    decisions = pd.DataFrame({'trend':trend.shift(1), 'breakout':breakout.shift(1), 'dip':dip.shift(1),
        'session':frame.Date.dt.tz_convert('America/New_York').dt.date.astype(str)})
    selected = decisions.loc[decisions.session.ge('2019-01-02') & decisions.session.le('2025-12-31')].copy()
    selected[['trend','breakout','dip']] = selected[['trend','breakout','dip']].astype(bool)
    tests = 0
    for index in selected.index[::401]:
        history = frame.iloc[:index]
        for key,p in configurations().items():
            result = decide(SimpleNamespace(parameters=p,history=history,portfolio=SimpleNamespace(quantity=0)))
            row = decisions.loc[index]
            expected = {'C0000':True,'C0001':row.trend,'C0002':row.breakout,
                        'C0003':row.breakout and row.trend, 'C0004':row.dip,
                        'C0005':row.dip and row.trend,'C0006':row.dip and row.trend}[key]
            assert result.target == int(expected), (key,index)
            tests += 1
    def counts(sub):
        return {'observations':len(sub), 'trend':int(sub.trend.sum()),'breakout':int(sub.breakout.sum()),
                'breakout_excluded_by_trend':int((sub.breakout & ~sub.trend).sum()),
                'dip':int(sub.dip.sum()),'dip_excluded_by_trend':int((sub.dip & ~sub.trend).sum())}
    output = {'status':'PASS', 'scope':'2019-2025 decision-time conditions, flat-portfolio counterfactual only',
        'interpretation':'Consecutive signals overlap and actual positions may already be long; counts are not trades or independent samples.',
        'causality':'Indicators calculated through previous completed visible bar, then shifted to next execution interval.',
        'source_reference':ref,'source_sha256':fetched.identity.content_sha256,
        'cross_implementation_checks':tests,'full':counts(selected),
        'annual':{year:counts(sub) for year,sub in selected.groupby(selected.session.str[:4])}}
    save(WORK/'others/signal_audit.json',output)
    print(output['full'], 'causal spot checks', tests)


if __name__ == '__main__':
    main()
