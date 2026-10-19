"""Fixed Decimal disclosure comparisons and descriptive event calculations."""
from datetime import date, datetime
from decimal import Decimal

import numpy as np
from strategy_runtime.execution_rules import ExecutionRuleInput, build_frozen_execution_plan
from trading_execution_engine import DailyQuote, OrderSpec, SessionPriceLimits, resolve_fill

SETTINGS = {
    "instrument": {"lot_size": 100, "price_tick": 0.01, "price_limit_ratio": 0.1,
                   "maximum_order_quantity": 100000},
    "capital": {"mode": "ALL_AVAILABLE", "target_scope": "SINGLE_SYMBOL", "fee_rate": 0.001},
    "entry": {"order_type": "LIMIT", "limit_parameter": 0.01},
    "exit": {"order_type": "MARKET", "limit_ratio": 0.1},
}


def compare_amount(actual, low, high, quantum_low, quantum_high, approximate_point=False):
    """Compare whole uncertainty intervals; retain every conservative boundary."""
    a, lo, hi, qlo, qhi = map(Decimal, map(str, (actual, low, high, quantum_low, quantum_high)))
    if not all(x.is_finite() for x in (a, lo, hi, qlo, qhi)) or lo > hi or min(qlo, qhi) < 0:
        raise ValueError("Finite, ordered signed amounts and nonnegative monetary quanta required")
    result = {"actual_cny": str(a), "prior_low_cny": str(lo), "prior_high_cny": str(hi),
              "prior_quantum_low_cny": str(qlo), "prior_quantum_high_cny": str(qhi)}
    if approximate_point:
        if lo != hi:
            raise ValueError("Approximate single-point type requires one point")
        result.update(classification="approximate_point_estimate", literal_classification="approximate_point_estimate",
                      point_estimation_error_cny=str(a - lo), signed_breakout_cny=None)
        return result
    actual_lo, actual_hi = a - Decimal("0.005"), a + Decimal("0.005")
    outer_lo, outer_hi = lo - qlo / 2, hi + qhi / 2
    inner_lo, inner_hi = lo + qlo / 2, hi - qhi / 2
    if actual_lo > outer_hi:
        classification, distance = "positive_new", actual_lo - outer_hi
    elif actual_hi < outer_lo:
        classification, distance = "negative_new", actual_hi - outer_lo
    elif actual_lo >= inner_lo and actual_hi <= inner_hi:
        classification, distance = "covered", Decimal(0)
    else:
        classification, distance = "rounding_boundary_overlap", None
    result.update(classification=classification,
                  literal_classification="positive_new" if a > hi else "negative_new" if a < lo else "covered",
                  actual_interval_cny=[str(actual_lo), str(actual_hi)],
                  outer_prior_interval_cny=[str(outer_lo), str(outer_hi)],
                  inner_prior_interval_cny=[str(inner_lo), str(inner_hi)],
                  signed_breakout_cny=str(distance) if distance is not None else None)
    return result


def descriptive_comparison(panel, first, second, blocks, target="sector_excess_return20"):
    """Two fixed group means; unavailable groups never become artificial zeroes."""
    a = panel.loc[panel.classification.eq(first), target].dropna()
    b = panel.loc[panel.classification.eq(second), target].dropna()
    index_block = {identity: block["id"] for block in blocks for identity in block["event_ids"]}
    groups = []
    for name, values in ((first, a), (second, b)):
        ids = panel.loc[values.index, "event_id"].tolist()
        present = sorted({index_block[x] for x in ids})
        block_means = [float(values.loc[[i for i in values.index if index_block[panel.loc[i, "event_id"]] == block]].mean())
                       for block in present]
        groups.append({"class": name, "events": len(values), "event_ids": ids, "blocks": present,
                       "event_mean": float(values.mean()) if len(values) else None,
                       "block_mean": float(np.mean(block_means)) if block_means else None})
    result = {"target": target, "first": groups[0], "second": groups[1],
              "event_difference": float(a.mean() - b.mean()) if len(a) and len(b) else None,
              "block_difference": groups[0]["block_mean"] - groups[1]["block_mean"] if len(a) and len(b) else None,
              "requested_bootstrap_draws": 10000, "seed": 13, "actual_bootstrap_draws": 0}
    if min(len(x["blocks"]) for x in groups) < 2:
        result.update(status="INSUFFICIENT_GROUPS_FOR_DESCRIPTIVE_CI", percentile95=None,
                      bootstrap_valid=None, bootstrap_invalid=None,
                      reason="Each comparison arm requires at least2 distinct contributing blocks; no fabricated interval.")
        return result
    identities = [block["id"] for block in blocks]
    sums, counts, means, present = [], [], [], []
    for name in (first, second):
        s, n, m, has = [], [], [], []
        for block in identities:
            chosen = panel.loc[panel.classification.eq(name) & panel.event_id.map(index_block).eq(block), target].dropna()
            s.append(float(chosen.sum()))
            n.append(len(chosen))
            m.append(float(chosen.mean()) if len(chosen) else 0.0)
            has.append(int(bool(len(chosen))))
        sums.append(np.array(s))
        counts.append(np.array(n))
        means.append(np.array(m))
        present.append(np.array(has))
    draws = np.random.default_rng(13).integers(0, len(identities), size=(10000, len(identities)))
    effects, equal_effects = [], []
    for draw in draws:
        nn = [counts[j][draw].sum() for j in (0, 1)]
        if min(nn) == 0:
            continue
        effects.append(sums[0][draw].sum() / nn[0] - sums[1][draw].sum() / nn[1])
        equal_effects.append(means[0][draw].sum() / present[0][draw].sum()
                             - means[1][draw].sum() / present[1][draw].sum())
    result.update(status="AVAILABLE_DESCRIPTIVE", actual_bootstrap_draws=10000,
                  bootstrap_valid=len(effects), bootstrap_invalid=10000 - len(effects),
                  percentile95=np.quantile(effects, [.025, .975]).tolist() if effects else None,
                  block_percentile95=np.quantile(equal_effects, [.025, .975]).tolist() if effects else None)
    return result


def event_label(frames, sessions, decision):
    """Same fixed EX036 daily-range TXE contract for a new first-news date."""
    raw, hfq, sector = (frames[x] for x in ("stock_raw", "stock_hfq", "sector"))
    statuses, limits = (frames[x] for x in ("status", "limits"))
    if decision not in sessions or decision not in raw.index:
        return {"decision_date": decision, "status": "OUTSIDE_PINNED_MARKET_WINDOW"}
    di = sessions.index(decision)
    ei, pi, xi = di + 1, di + 20, di + 21
    result = {"decision_date": decision, "entry_date": sessions[ei] if ei < len(sessions) else None,
              "price_end_date": sessions[pi] if pi < len(sessions) else None,
              "planned_exit_date": sessions[xi] if xi < len(sessions) else None,
              "net_position_return": None, "event_cash_equity_return": None}
    if pi >= len(sessions):
        return dict(result, status="RIGHT_CENSORED")
    needed = sessions[ei:pi + 1]
    if not all(all(d in frame.index for d in needed) for frame in (raw, hfq, sector)):
        return dict(result, status="MISSING_REQUIRED_PRICES")
    entry, end = sessions[ei], sessions[pi]
    stock_return = float(hfq.loc[end, "Close"] / hfq.loc[entry, "Open"] - 1)
    sector_return = float(sector.loc[end, "Close"] / sector.loc[entry, "Open"] - 1)
    result.update(status="COMPLETE", stock_return20=stock_return, sector_return20=sector_return,
                  sector_excess_return20=stock_return-sector_return,
                  mae20=float(hfq.loc[needed, "Low"].min() / hfq.loc[entry, "Open"]-1))

    def fill(order, session):
        if statuses.loc[session, "Status"] != "TRADING":
            return None
        row, boundary = raw.loc[session], limits.loc[session]
        return resolve_fill(order, session_open=float(row.Open),
                            session_time=datetime.fromisoformat(session + "T09:30:00"), intraday_touches=(),
                            daily_quote=DailyQuote(float(row.Low), float(row.High)),
                            session_limits=SessionPriceLimits(date.fromisoformat(session), float(boundary.DownLimit),
                                                              float(boundary.UpLimit), .01))
    reference = float(raw.loc[decision, "Close"])
    plan = build_frozen_execution_plan(ExecutionRuleInput("FROZEN_RULE", SETTINGS, {}, 100000., 0, 1., reference, reference))
    order = plan["orders"][0]
    buy = fill(OrderSpec(order["side"], order["order_type"], order["quantity"], order["limit_price"]), entry)
    result.update(buy_limit_raw=order["limit_price"], order_quantity=order["quantity"],
                  entry_factor=float(hfq.loc[entry, "Close"] / raw.loc[entry, "Close"]),
                  buy_fill_reason=buy.reason if buy else "SUSPENDED")
    if buy is None or not buy.filled:
        return dict(result, execution_status="NO_TRADE", filled_quantity=0,
                    cash_leftover=100000., event_cash_equity_return=0.)
    quantity = order["quantity"]
    cost = quantity * buy.price * 1.001
    cash = 100000. - cost
    assert cash >= -.000001
    result.update(execution_status="OPEN_AT_CUTOFF", entry_price_raw=buy.price, buy_cost_including_fee=cost,
                  filled_quantity=quantity, cash_leftover=cash, actual_exit_date=None)
    for index in range(xi, len(sessions)):
        session = sessions[index]
        reference = float(raw.loc[sessions[index - 1], "Close"])
        sell_plan = build_frozen_execution_plan(ExecutionRuleInput("FROZEN_RULE", SETTINGS, {}, cash, quantity, 0., reference, reference))
        order = sell_plan["orders"][0]
        sell = fill(OrderSpec(order["side"], order["order_type"], order["quantity"], order["limit_price"]), session)
        if sell and sell.filled:
            exit_factor = float(hfq.loc[session, "Close"] / raw.loc[session, "Close"])
            sale = quantity * sell.price * (exit_factor / result["entry_factor"]) * .999
            result.update(execution_status="CLOSED", actual_exit_date=session, exit_delay_sessions=index-xi,
                          exit_price_raw=sell.price, net_position_return=sale / cost-1,
                          event_cash_equity_return=(cash+sale) / 100000.-1)
            break
    return result


def synthetic_precheck():
    assert compare_amount("150", "100", "200", "1", "1")["classification"] == "covered"
    assert compare_amount("200.50", "100", "200", "1", "1")["classification"] == "rounding_boundary_overlap"
    assert compare_amount("200.51", "100", "200", "1", "1")["classification"] == "positive_new"
    assert compare_amount("99.49", "100", "200", "1", "1")["classification"] == "negative_new"
    assert compare_amount("100", "100", "100", "1", "1")["classification"] == "rounding_boundary_overlap"
    assert compare_amount("-90", "-200", "-100", "1", "1")["classification"] == "positive_new"
    assert compare_amount("100", "100", "100", "1", "1", True)["classification"] == "approximate_point_estimate"
    assert compare_amount("150.000", "100.00", "200.00", "100", "100")["classification"] == "rounding_boundary_overlap"
    return {"status": "PASS", "fixed_decimal_boundary_cases": 8}
