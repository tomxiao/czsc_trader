"""The common typed execution boundary preserves model-specific facts."""
from dataclasses import replace
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from strategy_runtime import ExecutionPolicy, OrderSide, OrderType, PlannedOrder
from strategy_runtime.replay_contracts import ReplayPoint, ExecutionPrecision
from strategy_runtime.replay_adapters import project_window_plan
from trading_execution_engine import HistoricalExecutor
from test_historical_cycles import _plan


def test_session_projection_consumes_orders_and_preserves_idempotent_account():
    dates = pd.bdate_range("2026-09-14", periods=2)
    executor = HistoricalExecutor(strategy_reference="S999-C0001", symbol="588080.SH",
        execution_daily=pd.DataFrame({"dt":dates, "open":10., "close":10.}),
        execution_intraday=pd.DataFrame(columns=["dt","high","low"]),
        evaluation_start=dates[1], evaluation_end=dates[1], initial_cash=2000.,
        execution_policy=ExecutionPolicy("FROZEN_RULE", {"capital":{"fee_rate":.001}}),
        order_types=("MARKET",))
    native = _plan(executor, dates, 1, 1., (PlannedOrder(OrderSide.BUY,100,OrderType.MARKET,None),),.001)
    start=datetime.combine(dates[1].date(),time(),ZoneInfo("Asia/Shanghai"))
    point=ReplayPoint(datetime.combine(native.signal_date,time(15),ZoneInfo("Asia/Shanghai")),native.generated_at,start,start+timedelta(days=1),
        dates[1].date().isoformat(),ExecutionPrecision.SESSION)
    neutral=project_window_plan(native,point)
    changed=replace(neutral,orders=(replace(neutral.orders[0],quantity=200),))
    with pytest.raises(ValueError,match="orders differ"):
        executor.execute_plan(changed,native)
    result=executor.execute_plan(neutral,native)
    assert executor.execute_plan(neutral,native)==result
    assert executor.finish().fills.quantity.tolist()==[100]
