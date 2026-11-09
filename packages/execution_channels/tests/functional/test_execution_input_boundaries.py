"""EC12 input/time boundaries before any historical ledger mutation."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest
from execution_channels.historical import PortfolioHistoricalExecutor
from execution_channels.instruments import MarketId
from execution_channels.contracts import ReplayPoint, ExecutionPrecision
from ec_facts import fixture
from test_portfolio_parity import setup, facts, plan


def test_EC12_C01_negative_initial_cash_is_rejected():
    _, spec, _, _, _ = fixture(MarketId.US)
    with pytest.raises(ValueError, match='initial cash must be positive and finite'):
        PortfolioHistoricalExecutor(specification=spec,initial_cash=-1.,fee_rate=.001,price_basis='HFQ')


def test_EC12_C02_no_order_does_not_allow_nonfinite_ohlc():
    executor, stamp, _ = setup(MarketId.US)
    bar, rule = facts(stamp)
    bar['Close'] = float('nan')
    with pytest.raises(ValueError, match='invalid execution OHLCV'):
        executor.execute_account_plan(plan(executor,stamp),bar,constraint=rule)
    assert executor.quantity == 0 and executor.revision == 0
    assert not executor.rows['points']


def test_EC12_C03_naive_execution_time_is_rejected():
    _, _, point, _, _ = fixture(MarketId.US)
    with pytest.raises(TypeError, match='execution_start requires an aware datetime'):
        replace(point,execution_start=point.execution_start.replace(tzinfo=None))


def test_EC12_C05_dst_folds_retain_distinct_utc_intervals():
    first = datetime(2020,11,1,1,30,tzinfo=ZoneInfo('America/New_York'),fold=0)
    second = datetime(2020,11,1,1,30,tzinfo=ZoneInfo('America/New_York'),fold=1)
    first_utc, second_utc = first.astimezone(timezone.utc),second.astimezone(timezone.utc)
    a = ReplayPoint(first,first,first,first_utc+timedelta(minutes=30),'2020-11-01',ExecutionPrecision.BAR_INTERVAL)
    b = ReplayPoint(second,second,second,second_utc+timedelta(minutes=30),'2020-11-01',ExecutionPrecision.BAR_INTERVAL)
    assert second_utc-first_utc == timedelta(hours=1)
    assert a.execution_start.astimezone(timezone.utc) != b.execution_start.astimezone(timezone.utc)
    from execution_channels.serialization import to_record
    assert to_record(a,json_safe=True) != to_record(b,json_safe=True)


@pytest.mark.parametrize('field', ['observed_through','execution_start','execution_end'],
                         ids=['EC12-C06','EC12-C07','EC12-C08'])
def test_replay_point_refuses_inverted_visibility_and_execution(field):
    _, _, point, _, _ = fixture(MarketId.US)
    value = {'observed_through':point.decision_at+timedelta(seconds=1),
             'execution_start':point.decision_at-timedelta(seconds=1),
             'execution_end':point.execution_start}[field]
    with pytest.raises(ValueError,match='causal execution order'):
        replace(point,**{field:value})
