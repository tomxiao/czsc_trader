"""Execution-aligned path attribution without a continuous strategy account."""
from datetime import datetime, time

import numpy as np
from trading_execution_engine import OrderSpec, DailyQuote, SessionPriceLimits, resolve_fill


def horizon_study(task):
    horizon, labels, prices, down, up, ticks, dates, features = task
    session_limits = [SessionPriceLimits(day.date(), float(down[i]), float(up[i]), float(ticks[i])) for i, day in enumerate(dates)]
    rows, decisions = [], []
    for record in labels:
        signal, entry, planned, quantity = (int(record[name]) for name in ("signal", "entry", "planned_exit", "quantity"))
        row = {key: record[key] for key in ("signal", "signal_date", "horizon", "status", "entry", "entry_filled", "entry_reason", "quantity", "planned_exit", "maturity", "net_return")}
        row.update(year=dates[signal].year, gap_fraction=float(prices[entry, 0] / prices[signal, 3] - 1),
                   known_uptrend=bool(features[signal, 0]), parent_ready=signal >= 60,
                   pullback_parent=bool(features[signal, 1]), pullback_confirm=bool(features[signal, 2]),
                   breakout_parent=bool(features[signal, 3]), breakout_confirm=bool(features[signal, 4]),
                   upper_limit_close=bool(features[signal, 5]))
        if record["status"] == "RIGHT_CENSORED":
            rows.append(row)
            continue
        if record["status"] == "UNFILLED":
            row.update(fees_cash=0., holding_gross_cash=0., noninvested_market_path=float(prices[planned, 0] / prices[entry, 0] - 1))
            rows.append(row)
            continue
        buy = float(record["entry_price"])
        maturity = int(record["maturity"])
        sell = float(record["exit_price"])
        cache = {}

        def next_exit(start):
            if start in cache:
                return cache[start]
            for index in range(start, maturity + 1):
                quote = prices[index]
                fill = resolve_fill(OrderSpec("SELL", "MARKET", quantity), session_open=float(quote[0]),
                    session_time=datetime.combine(dates[index].date(), time(9, 30)), intraday_touches=(),
                    daily_quote=DailyQuote(float(quote[2]), float(quote[1])), session_limits=session_limits[index])
                if fill.filled:
                    result = (index, float(fill.price))
                    cache[start] = result
                    return result
            raise AssertionError("No exit despite a closed inherited label")

        original_index, original_sell = next_exit(planned)
        if original_index != maturity or abs(original_sell - sell) > 1e-10:
            raise AssertionError("Inherited fixed sell does not replicate")
        fee = quantity * (buy + sell) * .001 / 100000
        source_move = quantity * (sell - prices[signal, 3]) / 100000
        gap = quantity * (prices[entry, 0] - prices[signal, 3]) / 100000
        entry_difference = quantity * (buy - prices[entry, 0]) / 100000
        gross = quantity * (sell - buy) / 100000
        net = float(record["net_return"])
        if not np.isclose(source_move - gap - entry_difference - fee, net, rtol=0, atol=1e-12):
            raise AssertionError("Cash identity fails")
        marks = quantity * (prices[entry:maturity, 3] * .999 - buy * 1.001) / 100000
        peak = max(0., float(marks.max()))
        best, best_index = net, maturity
        candidates = []
        for decision in range(entry, planned):
            exit_index, exit_price = next_exit(decision + 1)
            early_net = quantity * (exit_price * .999 - buy * 1.001) / 100000
            candidates.append((decision, exit_index, early_net))
            if early_net > best:
                best, best_index = early_net, exit_index
        row.update(entry_price=buy, exit_price=sell, signal_exit_same_quantity_cash=float(source_move),
            gap_cash=float(gap), intraday_entry_cash=float(entry_difference), fees_cash=float(fee), holding_gross_cash=float(gross),
            positive_close_mark_peak=peak, had_positive_mark=peak > 0, positive_mark_to_loss=peak > 0 and net <= 0,
            positive_profit_returned=max(0., peak - max(0., net)), peak_to_exit_drop=max(0., peak - net) if peak > 0 else 0.,
            earlier_hindsight_best=best, hindsight_headroom=max(0., best - net), hindsight_best_exit=best_index,
            hindsight_rescue=net <= 0 and best > 0, exit_delay=maturity - planned,
            planned_open_mark_net=quantity * (prices[planned, 0] * .999 - buy * 1.001) / 100000,
            signed_delay_proceeds_effect=quantity * (sell - prices[planned, 0]) * .999 / 100000,
            candidate_count=len(candidates))
        for checkpoint, decision in (("entry-close", entry), ("midpoint", entry + horizon // 2)):
            exit_index, exit_price = next_exit(decision + 1)
            mark = quantity * (prices[decision, 3] * .999 - buy * 1.001) / 100000
            ret1 = float(prices[decision, 3] / prices[decision - 1, 3] - 1)
            early_net = quantity * (exit_price * .999 - buy * 1.001) / 100000
            decisions.append({"signal": signal, "signal_date": dates[signal], "horizon": horizon, "checkpoint": checkpoint,
                "decision": decision, "decision_date": dates[decision], "decision_year": dates[decision].year,
                "entry": entry, "planned_exit": planned, "maturity": maturity, "earlier_exit": exit_index,
                "known_mark_net": float(mark), "known_ret1": ret1, "profitable": mark > 0, "weak": ret1 < 0,
                "selected": mark > 0 and ret1 < 0, "control": mark > 0 and ret1 >= 0,
                "earlier_net": float(early_net), "fixed_net": net, "exit_advantage": float(early_net - net),
                "strictly_earlier": exit_index < maturity})
        rows.append(row)
    return rows, decisions


def synthetic_task(delayed=False):
    import pandas as pd
    dates = pd.date_range("2020-01-01", periods=6)
    prices = np.array([[10, 10.2, 9.9, 10], [10, 10.4, 9.9, 10.2], [10.6, 11, 10.4, 10.8],
                       [11, 11.2, 10, 10.5], [9.5, 9.8, 9, 9.4], [9.6, 10, 9.3, 9.8]], dtype=float)
    down, up, ticks = np.full(6, 7.), np.full(6, 14.), np.full(6, .01)
    maturity, sell = 4, 9.5
    if delayed:
        prices[4] = [7., 7., 7., 7.]
        maturity, sell = 5, 9.6
    record = {"signal": 0, "signal_date": dates[0], "horizon": 3, "status": "CLOSED", "entry": 1,
        "entry_filled": True, "entry_reason": "synthetic", "quantity": 1000, "planned_exit": 4, "maturity": maturity,
        "entry_price": 10., "exit_price": sell, "net_return": 1000 * (sell * .999 - 10 * 1.001) / 100000}
    return 3, [record], prices, down, up, ticks, dates, np.zeros((6, 6), dtype=bool)
