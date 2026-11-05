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


def test_calendar_holiday_moves_snapshot_to_prior_open_day():
    pro = MonthlyPro()
    original = pro.trade_cal
    def holiday(**kwargs):
        frame = original(**kwargs)
        frame.loc[frame.cal_date.eq('20260930'),'is_open'] = 0
        return frame
    pro.trade_cal = holiday
    frame, _ = fetch_index_constituent_weight('000905.SH','2026-09-01','2026-09-30',pro=pro)
    assert frame.Date.unique().tolist() == [pd.Timestamp('2026-09-29')]


def test_missing_expected_snapshot_fails_entire_interval():
    pro = MonthlyPro()
    pro.missing = '20261030'
    with pytest.raises(IncompleteDataError, match='snapshot is missing') as error:
        fetch_index_constituent_weight('000905.SH','2026-09-01','2026-11-05',pro=pro)
    assert error.value.context['trade_date'] == '20261030'


@pytest.mark.parametrize('kind,error,message', [
    pytest.param('wrong_date', DataContractError, 'different from requested trade_date', id='wrong_date'),
    pytest.param('wrong_index', DataContractError, 'mixes indexes', id='wrong_index'),
    pytest.param('duplicate', DataContractError, 'duplicate constituent symbols', id='duplicate'),
    pytest.param('short', IncompleteDataError, '500 unique constituents', id='short'),
    pytest.param('invalid_weight', DataContractError, 'invalid weights', id='invalid_weight'),
])
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
            frame.loc[0,'weight'] = float('inf')
        return frame
    pro.mutate = mutate
    with pytest.raises(error, match=message):
        fetch_index_constituent_weight('000905.SH','2026-09-01','2026-09-30',pro=pro)


def test_incomplete_calendar_fails_before_vendor_snapshot_query():
    pro = MonthlyPro()
    original = pro.trade_cal
    pro.trade_cal = lambda **kwargs: original(**kwargs).iloc[1:]
    with pytest.raises(IncompleteDataError, match='calendar is incomplete'):
        fetch_index_constituent_weight('000905.SH','2026-09-01','2026-09-30',pro=pro)
    assert pro.calls == []


def test_partial_month_without_month_end_is_not_current_day_snapshot():
    pro = MonthlyPro()
    with pytest.raises(EmptyDataError, match='no month-end'):
        fetch_index_constituent_weight('000905.SH','2026-11-01','2026-11-05',pro=pro)
    assert pro.calls == []
