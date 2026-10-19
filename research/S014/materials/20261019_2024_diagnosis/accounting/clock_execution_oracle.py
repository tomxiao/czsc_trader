"""Reapply the unchanged public fill contract; require exact returned fill prices.

No audit epsilon is added. The public resolver's existing daily-range roundoff
semantics are authoritative, rather than a stricter float price<=limit shortcut.
"""
from datetime import datetime, time

import pandas as pd
from trading_execution_engine import DailyQuote, OrderSpec, SessionPriceLimits, resolve_fill

from clock_financial_audit import P

A=P.A


def exact_execution_prices(account,frames):
    ledgers=account['runs'][0]['ledgers']
    fills={r['order_id']:r for r in ledgers['fills']['data']}
    expected={}
    diagnostics=[]
    for order in ledgers['orders']['data']:
        stamp=pd.Timestamp(A.day(order['execution_date']))
        actual=fills.get(order['order_id'])
        status=frames['trading_status'].loc[stamp,'Status']
        if status=='SUSPENDED':
            A.check('exact oracle suspended unfilled',actual is None and order['status']!='FILLED')
            continue
        A.check('exact oracle known trading state',status=='TRADING')
        quote=frames['projected_execution'].loc[stamp]
        bounds=frames['price_limits'].loc[stamp]
        scale=float(quote.Close/frames['execution_daily'].loc[stamp,'Close'])
        limits=SessionPriceLimits(stamp.date(),float(bounds.DownLimit*scale),float(bounds.UpLimit*scale),float(.01*scale))
        spec=OrderSpec('BUY','LIMIT',order['quantity'],order['limit_price']) if order['side']=='BUY' else OrderSpec('SELL','MARKET',order['quantity'])
        result=resolve_fill(spec,session_open=float(quote.Open),session_time=datetime.combine(stamp.date(),time(9,30)),
                            intraday_touches=(),daily_quote=DailyQuote(float(quote.Low),float(quote.High)),session_limits=limits)
        A.check('exact oracle public availability',bool(result.filled)==bool(actual))
        if actual:
            A.check('exact oracle actual price equals original public resolver return',actual['price']==result.price)
            expected[order['order_id']]=result.price
            if order['side']=='BUY' and actual['price']>order['limit_price']:
                diagnostics.append({'order':order,'fill':actual,'public_expected_price':result.price,'public_trigger':result.trigger,
                                    'saved_limit_repr':repr(order['limit_price']),'fill_repr':repr(actual['price']),
                                    'fill_minus_saved_limit':actual['price']-order['limit_price'],
                                    'projected_E_open':float(quote.Open),'projected_E_low':float(quote.Low),'projected_E_high':float(quote.High),
                                    'existing_public_daily_quote_roundoff':max(abs(order['limit_price']),abs(float(quote.Open)),abs(float(quote.Low)),abs(float(quote.High)))*1e-12,
                                    'price_tick':limits.price_tick,'audit_added_epsilon':0})
    A.check('all actual fills have exact public price oracle',set(expected)==set(fills))
    return expected,diagnostics
