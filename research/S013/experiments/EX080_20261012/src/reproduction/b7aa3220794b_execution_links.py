"""Independent order/fill links, causal session, lot/fee, first-touch checks."""
import numpy as np
import pandas as pd

def verify(bound,result):
    run=result.runs[0].execution;orders=run.orders;fills=run.fills;decisions=run.decisions
    assert orders.order_id.is_unique and fills.fill_id.is_unique and decisions.decision_id.is_unique
    d=decisions.set_index('decision_id');o=orders.set_index('order_id')
    daily=bound.execution_data.execution_daily.set_index('dt');intra=bound.execution_data.execution_intraday
    assert intra.dt.is_unique and intra.dt.is_monotonic_increasing
    checked={'order_n':len(orders),'fill_n':len(fills),'buy_fill_n':0,'sell_fill_n':0,'open_fill_n':0,'intraday_limit_n':0,'unfilled_n':0}
    for order in orders.itertuples():
        decision=d.loc[order.decision_id]
        assert pd.Timestamp(order.signal_date)==pd.Timestamp(decision.signal_date)
        assert pd.Timestamp(order.execution_date)==pd.Timestamp(decision.valid_session)>pd.Timestamp(order.signal_date)
        assert order.side in ('BUY','SELL') and order.quantity>0 and order.quantity%100==0 and order.quantity<=1000000
        linked=fills.loc[fills.order_id.eq(order.order_id)]
        if order.status=='FILLED':assert len(linked)==1 and int(linked.quantity.sum())==order.quantity
        else:
            assert order.status=='UNFILLED' and linked.empty;checked['unfilled_n']+=1
        assert order.order_type==('LIMIT' if order.side=='BUY' else 'MARKET')
        if order.side=='BUY':assert np.isfinite(order.limit_price) and order.limit_price>0 and decision.target_position==1
        else:assert decision.target_position==0
    for fill in fills.itertuples():
        order=o.loc[fill.order_id];session=pd.Timestamp(order.execution_date)
        assert fill.decision_id==order.decision_id and fill.cycle_id==order.cycle_id and fill.side==order.side
        assert fill.signal_date==order.signal_date and pd.Timestamp(fill.fill_time).normalize()==session
        assert fill.quantity==order.quantity and np.isfinite(fill.price) and fill.price>0
        assert abs(fill.fees-fill.quantity*fill.price*bound.costs[0].one_way_cost)<1e-6
        opening=float(daily.loc[session,'open'])
        if fill.side=='SELL':
            checked['sell_fill_n']+=1;assert fill.trigger=='OPEN_MARKET' and fill.price==opening and pd.Timestamp(fill.fill_time)==session
        else:
            checked['buy_fill_n']+=1;limit=float(order.limit_price);assert fill.price<=limit
            if fill.trigger=='OPEN':
                checked['open_fill_n']+=1;assert opening<=limit and fill.price==opening and pd.Timestamp(fill.fill_time)==session
            else:
                assert fill.trigger=='INTRADAY_LIMIT' and opening>limit
                bars=intra.loc[pd.to_datetime(intra.dt).dt.normalize().eq(session)]
                crossed=bars.loc[bars.low.le(limit)];assert not crossed.empty
                first=crossed.iloc[0];assert pd.Timestamp(fill.fill_time)==pd.Timestamp(first['dt'])
                assert fill.price==min(float(first.open),limit)
                checked['intraday_limit_n']+=1
    assert len(fills)==int(orders.status.eq('FILLED').sum())
    return {'status':'PASS','scope':'Every order/fill identity, T-before-next-session, fixed side/order type,100-lot/max quantity,fee, daily opening and chronological first intraday low-touch/price; sizing cash verified separately. Does not replace platform receipt validation or repair known historical OHLC anomalies.',**checked}
