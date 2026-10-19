import json
from pathlib import Path
from collections import defaultdict
from decimal import Decimal, localcontext, ROUND_FLOOR
from datetime import date, datetime
from hashlib import sha256
import numpy as np
import pandas as pd
from trading_execution_engine import DailyQuote, OrderSpec, SessionPriceLimits, resolve_fill

BASE = Path("research/S014/experiments/EX036_20261019")
READY = Path("research/S014/materials/20261019_financial_readiness")
OUT = BASE / "others"
accepted = json.loads((READY / "others/accepted_financial_inputs.json").read_bytes())
lineage = json.loads((OUT / "financial_features_lineage.json").read_bytes())
assert (
    lineage["accepted_manifest_sha256"]
    == sha256((READY / "others/accepted_financial_inputs.json").read_bytes()).hexdigest()
)
facts = {(f["kind"], f["period"], f["field"]): f for f in accepted["facts"]}
features = pd.read_csv(
    OUT / "financial_features.csv", dtype={"report_period": str, "joint_report_periods": str}
)
clusters = defaultdict(set)
for f in accepted["facts"]:
    if f["period"] >= "20191231" and f["state"] == "PUBLIC_ORIGINAL_VALUE_RECONCILED":
        clusters[f["decision_available_at"]].add(f["period"])


def close(a, b):
    if a is None:
        assert pd.isna(b), (a, b)
    else:
        assert np.isclose(float(a), float(b), rtol=2e-12, atol=2e-12), (a, b)


with localcontext() as ctx:
    ctx.prec = 50
    for row, (ts, periods) in zip(
        features.to_dict("records"), sorted(clusters.items()), strict=True
    ):
        assert row["decision_available_at"] == ts
        assert row["report_period"] == max(periods)
        assert row["joint_report_periods"].split("|") == sorted(periods)
        p = pd.Period(pd.Timestamp(max(periods)), freq="Q-DEC")
        used = set()

        def v(kind, period, field):
            key = (kind, period.end_time.strftime("%Y%m%d"), field)
            used.add(key)
            f = facts[key]
            if f["state"] != "PUBLIC_ORIGINAL_VALUE_RECONCILED":
                return None
            assert f["decision_available_at"] <= ts
            return Decimal(str(f["value"]))

        def q(kind, period, field):
            cur = v(kind, period, field)
            if period.quarter == 1:
                return cur
            prev = v(kind, period - 1, field)
            return None if cur is None or prev is None else cur - prev

        def quality(period):
            cash = q("cashflow", period, "n_cashflow_act")
            profit = q("income", period, "n_income")
            begin = v("balancesheet", period - 1, "total_assets")
            end = v("balancesheet", period, "total_assets")
            assert begin > 0 and end > 0
            return (cash - profit) * 2 / (begin + end)

        rev, oldrev = [q("income", per, "revenue") for per in (p, p - 4)]
        cost, oldcost = [q("income", per, "oper_cost") for per in (p, p - 4)]
        gm, oldgm = (rev - cost) / rev, (oldrev - oldcost) / oldrev
        qs, oldqs = quality(p), quality(p - 4)
        parent = q("income", p, "n_income_attr_p") - q("income", p - 4, "n_income_attr_p")
        deducted = q("fina_indicator", p, "profit_dedt") - q("fina_indicator", p - 4, "profit_dedt")
        assets, oldassets = [v("balancesheet", per, "total_assets") for per in (p, p - 4)]
        expected = dict(
            quarter_revenue=rev,
            quarter_prior_year_revenue=oldrev,
            quarter_gross_margin=gm,
            quarter_prior_year_gross_margin=oldgm,
            revenue_yoy_difference=rev - oldrev,
            gross_margin_yoy_difference=gm - oldgm,
            cash_support=qs,
            prior_year_cash_support=oldqs,
            cash_support_yoy_difference=qs - oldqs,
            parent_profit_yoy_difference=parent,
            deducted_profit_yoy_difference=deducted,
            F1=int(rev > oldrev and gm > oldgm),
            F2=int(qs > oldqs),
            PARENT=int(parent > 0),
        )
        for field, column in [
            ("accounts_receiv", "receivables_asset_ratio_yoy_difference"),
            ("inventories", "inventory_asset_ratio_yoy_difference"),
        ]:
            cur, old = [v("balancesheet", per, field) for per in (p, p - 4)]
            expected[column] = (
                None if cur is None or old is None else cur / assets - old / oldassets
            )
        for field, value in expected.items():
            close(value, row[field])
        trace = next(e for e in lineage["events"] if e["decision_date"] == row["decision_date"])[
            "input_lineage"
        ]
        assert {(e["kind"], e["period"], e["field"]) for e in trace} == used
        for e in trace:
            f = facts[e["kind"], e["period"], e["field"]]
            assert e["eligible_observation_ids"] == f["eligible_observation_ids"]
            assert e["available_at"] == f.get("decision_available_at")

frames = {
    name: pd.read_csv(OUT / f"{name}_market.csv").set_index("Date")
    for name in ["stock_raw", "stock_hfq", "sector", "market", "limits", "status", "calendar"]
}
sessions = frames["calendar"].loc[frames["calendar"].IsOpen.eq(1)].index.tolist()
raw, hfq = frames["stock_raw"], frames["stock_hfq"]
aligned = hfq.loc[raw.index]
factors = aligned.Close / raw.Close
for col in ["Open", "High", "Low", "Close"]:
    np.testing.assert_allclose(raw[col] * factors, aligned[col], rtol=1e-10, atol=1e-8)
labels = pd.read_csv(OUT / "market_event_labels.csv", dtype={"report_period": str})


def fill(side, typ, qty, limit, ds):
    if frames["status"].loc[ds, "Status"] != "TRADING":
        return None
    r, b = raw.loc[ds], frames["limits"].loc[ds]
    return resolve_fill(
        OrderSpec(side, typ, qty, limit),
        session_open=float(r.Open),
        session_time=datetime.fromisoformat(ds + "T09:30:00"),
        intraday_touches=(),
        daily_quote=DailyQuote(float(r.Low), float(r.High)),
        session_limits=SessionPriceLimits(
            date.fromisoformat(ds), float(b.DownLimit), float(b.UpLimit), 0.01
        ),
    )


for r in labels.to_dict("records"):
    di = sessions.index(r["decision_date"])
    ei = di + 1
    pi = ei + 19
    xi = ei + 20
    e, pe, xe = [sessions[i] for i in [ei, pi, xi]]
    assert r["entry_date"] == e and r["price_endpoint_date"] == pe and r["planned_exit_date"] == xe
    for name, df in [("stock", hfq), ("market", frames["market"]), ("sector", frames["sector"])]:
        close(df.loc[pe, "Close"] / df.loc[e, "Open"] - 1, r[name + "_return20"])
        close(
            df.loc[r["decision_date"], "Close"] / df.loc[sessions[di - 20], "Close"] - 1,
            r[name + "_trailing20"],
        )
    close(r["stock_return20"] - r["sector_return20"], r["sector_excess_return20"])
    close(r["stock_return20"] - r["market_return20"], r["market_excess_return20"])
    close(hfq.loc[sessions[ei : pi + 1], "Low"].min() / hfq.loc[e, "Open"] - 1, r["mae20"])
    assert hfq.loc[sessions[ei : pi + 1], "Low"].idxmin() == r["mae_low_date"]
    limit = (
        Decimal(str(raw.loc[r["decision_date"], "Close"])) * Decimal("1.01") * 100
    ).to_integral_value(rounding=ROUND_FLOOR) / 100
    qty = (
        int(
            (Decimal("100000") / (limit * Decimal("1.001") * 100)).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        * 100
    )
    close(limit, r["buy_limit_raw"])
    assert qty == r["order_quantity"]
    buy = fill("BUY", "LIMIT", qty, float(limit), e)
    if buy is None or not buy.filled:
        assert r["execution_status"] == "NO_TRADE" and pd.isna(r["net_position_return"])
        assert (
            r["actual_quantity"] == 0
            and r["cash_leftover_raw"] == 100000
            and r["event_cash_equity_return"] == 0
        )
        continue
    assert r["execution_status"] == "CLOSED"
    close(buy.price, r["buy_price_raw"])
    assert qty == r["actual_quantity"]
    bi = qty * buy.price
    bf = bi * 0.001
    cash = 100000 - bi - bf
    close(bi, r["buy_notional_raw"])
    close(bf, r["buy_fee_raw"])
    close(cash, r["cash_leftover_raw"])
    for sj in range(xi, len(sessions)):
        sell = fill("SELL", "MARKET", qty, None, sessions[sj])
        if sell is not None and sell.filled:
            break
    assert sessions[sj] == r["actual_exit_date"]
    close(sell.price, r["exit_price_raw"])
    sale = qty * sell.price * factors.loc[sessions[sj]] / factors.loc[e]
    close(sale * 0.999 / (bi + bf) - 1, r["net_position_return"])
    close((cash + sale * 0.999) / 100000 - 1, r["event_cash_equity_return"])
    close(qty * sell.price * 0.001, r["sell_fee_raw"])
    close(sale * 0.001, r["sell_fee_hfq_research_adjusted"])
    assert r["dependency_endpoint_date"] == max(pe, xe, sessions[sj])

print(
    json.dumps(
        {
            "financial_events": len(features),
            "report_periods": int(features.joint_report_count.sum()),
            "flag_counts": {f: int(features[f].sum()) for f in ["F1", "F2", "PARENT"]},
            "financial_values_and_lineage": "ALL_RECOMPUTED",
            "price_labels": len(labels),
            "execution_status": labels.execution_status.value_counts().to_dict(),
            "delayed_exits": int(labels.exit_delay_sessions.gt(0).sum()),
            "factor_changes": int(
                (
                    ~np.isclose(
                        factors.to_numpy()[1:], factors.to_numpy()[:-1], rtol=1e-10, atol=1e-12
                    )
                ).sum()
            ),
            "market_price_MAE_controls_and_fees": "ALL_RECOMPUTED",
            "new_API_calls": 0,
        }
    )
)
