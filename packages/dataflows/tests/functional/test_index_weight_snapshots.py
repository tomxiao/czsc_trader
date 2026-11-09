"""The public interval API requests exact month-end snapshots, never ranges."""
import pandas as pd
import pytest

from dataflows.errors import DataContractError, IncompleteDataError, EmptyDataError
from dataflows.tushare_strategy_data import fetch_index_constituent_weight


class MonthlyPro:
    def __init__(self):
        self.calls = []
        self.missing = None
        self.mutate = lambda frame: frame

    def trade_cal(self, **kwargs):
        dates = pd.date_range(kwargs['start_date'], kwargs['end_date'])
        return pd.DataFrame({'exchange':'SSE','cal_date':dates.strftime('%Y%m%d'),
                             'is_open':(dates.dayofweek < 5).astype(int)})

    def index_weight(self, **kwargs):
        self.calls.append(kwargs)
        assert set(kwargs) == {'index_code','trade_date','fields'}
        if kwargs['trade_date'] == self.missing:
            return pd.DataFrame()
        return self.mutate(pd.DataFrame({'index_code':kwargs['index_code'],
            'trade_date':kwargs['trade_date'], 'con_code':[f'{i:06d}.SZ' for i in range(500)],
            'weight':[.2]*500}))


def test_DFLS_26_C01_original_interval_queries_each_month_end_and_500_unique_members():
    pro = MonthlyPro()
    frame, metadata = fetch_index_constituent_weight('000905.SH', '2025-09-04', '2026-11-05', pro=pro)
    expected = ['20250930', '20251031', '20251128', '20251231', '20260130',
                '20260227', '20260331', '20260430', '20260529', '20260630',
                '20260731', '20260831', '20260930', '20261030']
    assert [call['trade_date'] for call in pro.calls] == expected
    assert len(frame) == 7000
    grouped = frame.groupby('Date')
    assert grouped.size().tolist() == [500] * 14
    assert grouped.ConstituentSymbol.nunique().tolist() == [500] * 14
    assert frame.Weight.eq(.2).all()
    assert grouped.size().index.strftime('%Y%m%d').tolist() == expected
    assert all(call['index_code'] == '000905.SH' for call in pro.calls)


def test_DFLS_26_C02_calendar_holiday_moves_snapshot_to_prior_open_day():
    pro = MonthlyPro()
    original = pro.trade_cal
    def holiday(**kwargs):
        frame = original(**kwargs)
        frame.loc[frame.cal_date.eq('20260930'),'is_open'] = 0
        return frame
    pro.trade_cal = holiday
    frame, _ = fetch_index_constituent_weight('000905.SH','2026-09-01','2026-09-30',pro=pro)
    assert frame.Date.unique().tolist() == [pd.Timestamp('2026-09-29')]


def test_DFLS_26_C03_missing_expected_snapshot_fails_entire_interval():
    pro = MonthlyPro()
    pro.missing = '20261030'
    with pytest.raises(IncompleteDataError, match='snapshot is missing') as error:
        fetch_index_constituent_weight('000905.SH','2026-09-01','2026-11-05',pro=pro)
    assert error.value.context['trade_date'] == '20261030'


@pytest.mark.parametrize('kind,error,message', [
    pytest.param('wrong_date', DataContractError, 'different from requested trade_date', id='DFLS-26-C04'),
    pytest.param('duplicate', DataContractError, 'duplicate constituent symbols', id='DFLS-26-C05'),
    pytest.param('invalid_weight', DataContractError, 'invalid weights', id='DFLS-26-C06'),
    pytest.param('negative_weight', DataContractError, 'invalid weights', id='DFLS-26-C07'),
], ids=['DFLS-26-C04', 'DFLS-26-C05', 'DFLS-26-C06', 'DFLS-26-C07'])
def test_invalid_snapshot_is_rejected(kind, error, message):
    pro = MonthlyPro()
    def mutate(frame):
        if kind == 'wrong_date':
            frame['trade_date'] = '20260929'
        if kind == 'wrong_index':
            frame['index_code'] = '000300.SH'
        if kind == 'duplicate':
            frame.loc[1,'con_code'] = frame.loc[0,'con_code']
        if kind == 'short':
            frame = frame.iloc[:-1]
        if kind == 'invalid_weight':
            frame.loc[0,'weight'] = float('nan')
        if kind == 'negative_weight':
            frame.loc[0,'weight'] = -.1
        return frame
    pro.mutate = mutate
    with pytest.raises(error, match=message):
        fetch_index_constituent_weight('000905.SH','2026-09-01','2026-09-30',pro=pro)




def test_DFLS_26_C08_partial_month_without_month_end_is_not_current_day_snapshot():
    pro = MonthlyPro()
    with pytest.raises(EmptyDataError, match='no month-end'):
        fetch_index_constituent_weight('000905.SH','2026-11-01','2026-11-05',pro=pro)
    assert pro.calls == []
