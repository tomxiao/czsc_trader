"""Independent first-news reconstruction from pinned EX036 market snapshots.

Does not import information_math/event_label or run accounts, models or searches.
Order amounts and fees are derived with Decimal; fills use the public TXE API.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import json
import math
from pathlib import Path
import socket

import pandas as pd

from trading_execution_engine import DailyQuote, OrderSpec, SessionPriceLimits, resolve_fill

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OLD = ROOT / "research/S014/experiments/EX036_20261019"


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def decimal(value):
    return Decimal(str(value))


def tick_floor(value):
    return (value / Decimal("0.01")).to_integral_value(rounding=ROUND_FLOOR) * Decimal("0.01")


def blocked(*_args, **_kwargs):
    raise RuntimeError("EX037 first-news audit is strictly offline")


def main():
    output = EX / "others/first_news_audit.json"
    if output.exists():
        raise FileExistsError("Existing first-news audit protected against replacement")
    socket.socket.connect = blocked
    socket.create_connection = blocked
    source_results = EX / "others/information_results.json"
    existing = read(source_results)
    guidance_path = EX / "others/guidance_facts.json"
    formal_path = EX / "others/formal_report_ledger.json"
    guidance = read(guidance_path)["facts"]
    formal = read(formal_path)["reports"]
    market_manifest = OLD / "others/market_inputs.json"
    frames = {}
    input_hashes = []
    for item in read(market_manifest)["native_identities"]:
        path = ROOT / item["snapshot_path"]
        assert digest(path) == item["snapshot_sha256"]
        frame = pd.read_csv(path).set_index("Date")
        assert len(frame) == item["rows"] and not frame.index.duplicated().any()
        frames[item["name"]] = frame
        input_hashes.append(
            {
                "name": item["name"],
                "path": item["snapshot_path"],
                "sha256": digest(path),
                "prepared": item["prepared"],
                "content_sha256": item["content_sha256"],
            }
        )
    assert set(frames) == {
        "stock_hfq",
        "stock_raw",
        "market",
        "sector",
        "calendar",
        "limits",
        "status",
    }
    sessions = frames["calendar"].loc[frames["calendar"].IsOpen.eq(1)].index.tolist()
    assert sessions == frames["stock_raw"].index.tolist()
    raw, adjusted, sector, statuses, limits = [
        frames[k] for k in ("stock_raw", "stock_hfq", "sector", "status", "limits")
    ]
    failures = []
    check_count = 0

    def check(name, actual, expected, period=None, tolerance=1e-9):
        nonlocal check_count
        check_count += 1
        if isinstance(actual, (float, Decimal)) and isinstance(expected, (float, int, Decimal)):
            passed = math.isclose(float(actual), float(expected), rel_tol=1e-11, abs_tol=tolerance)
        else:
            passed = actual == expected
        if not passed:
            failures.append(
                {"check": name, "period": period, "computed": actual, "recorded": expected}
            )
        return passed

    def public_fill(side, order_type, quantity, limit_price, session):
        if statuses.loc[session, "Status"] != "TRADING":
            return None
        quote = raw.loc[session]
        bounds = limits.loc[session]
        return resolve_fill(
            OrderSpec(side, order_type, quantity, float(limit_price)),
            session_open=float(quote.Open),
            session_time=datetime.fromisoformat(session + "T09:30:00"),
            intraday_touches=(),
            daily_quote=DailyQuote(float(quote.Low), float(quote.High)),
            session_limits=SessionPriceLimits(
                date.fromisoformat(session), float(bounds.DownLimit), float(bounds.UpLimit), 0.01
            ),
        )

    # Reconstruct the earliest same-period source universe before looking at its
    # ensuing prices. Unknown/ambiguous sources would remain represented.
    universe = []
    for report in formal:
        earlier = [
            g
            for g in guidance
            if g["period"] == report["period"] and g["source_day"] < report["source_day"]
        ]
        if earlier:
            first_day = min(g["source_day"] for g in earlier)
            first = [g for g in earlier if g["source_day"] == first_day]
            universe.append(
                {
                    "period": report["period"],
                    "source_day": first_day,
                    "first_doc_ids": sorted(g["doc_id"] for g in first),
                    "formal_source_day": report["source_day"],
                    "formal_event_id": report["event_id"],
                }
            )
    observed = {item["period"]: item for item in existing["first_news"]}
    check(
        "complete_unfiltered_first_news_period_universe",
        sorted(observed),
        sorted(x["period"] for x in universe),
    )
    audited = []
    for news in universe:
        period = news["period"]
        recorded = observed[period]
        check(
            "earliest_doc_identity",
            sorted(recorded["first_doc_ids"]),
            news["first_doc_ids"],
            period,
        )
        check("source_day", recorded["source_day"], news["source_day"], period)
        decision = next((session for session in sessions if session > news["source_day"]), None)
        label = recorded["label"]
        check("strict_next_session_decision", decision, label["decision_date"], period)
        di = sessions.index(decision)
        ei = di + 1
        end_i = ei + 19
        exit_i = ei + 20
        assert exit_i < len(sessions)
        entry, price_end, planned_exit = sessions[ei], sessions[end_i], sessions[exit_i]
        check("entry_date_after_decision", entry, label["entry_date"], period)
        check("twenty_session_price_end", price_end, label["price_end_date"], period)
        check(
            "exit_after_twenty_holding_sessions", planned_exit, label["planned_exit_date"], period
        )
        check("complete_price_status", "COMPLETE", label["status"], period)
        held = sessions[ei : end_i + 1]
        assert len(held) == 20
        prices = adjusted.loc[held]
        stock_return = (
            decimal(adjusted.loc[price_end, "Close"]) / decimal(adjusted.loc[entry, "Open"]) - 1
        )
        sector_return = (
            decimal(sector.loc[price_end, "Close"]) / decimal(sector.loc[entry, "Open"]) - 1
        )
        excursion = min(decimal(v) for v in prices.Low) / decimal(adjusted.loc[entry, "Open"]) - 1
        computed = {
            "decision_date": decision,
            "entry_date": entry,
            "price_end_date": price_end,
            "planned_exit_date": planned_exit,
            "stock_return20": stock_return,
            "sector_return20": sector_return,
            "sector_excess_return20": stock_return - sector_return,
            "mae20": excursion,
        }
        for field in ("stock_return20", "sector_return20", "sector_excess_return20", "mae20"):
            check(field, computed[field], label[field], period)
        previous_close = decimal(raw.loc[decision, "Close"])
        requested_limit = tick_floor(previous_close * Decimal("1.01"))
        guard = tick_floor(previous_close * Decimal("1.10")) - Decimal("0.01")
        limit_price = min(requested_limit, guard)
        quantity = (
            int(
                (Decimal("100000") / (limit_price * Decimal("1.001") * 100)).to_integral_value(
                    rounding=ROUND_FLOOR
                )
            )
            * 100
        )
        check(
            "previous_close_one_percent_floor_tick_limit",
            limit_price,
            label["buy_limit_raw"],
            period,
        )
        check("whole_lot_fee_reserved_quantity", quantity, label["order_quantity"], period)
        assert quantity <= 100000
        assert quantity * limit_price * Decimal("1.001") <= Decimal("100000")
        assert (quantity + 100) * limit_price * Decimal("1.001") > Decimal("100000")
        buy = public_fill("BUY", "LIMIT", quantity, limit_price, entry)
        check(
            "entry_public_fill_reason",
            buy.reason if buy else "SUSPENDED",
            label["buy_fill_reason"],
            period,
        )
        execution = {
            "previous_raw_close": str(previous_close),
            "limit_raw": str(limit_price),
            "quantity": quantity,
            "entry_status": statuses.loc[entry, "Status"],
            "buy_fill": {"filled": buy.filled, "price": buy.price, "reason": buy.reason}
            if buy
            else None,
        }
        if buy is None or not buy.filled:
            computed.update(
                execution_status="NO_TRADE",
                filled_quantity=0,
                cash_leftover=Decimal("100000"),
                net_position_return=None,
                event_cash_equity_return=Decimal(0),
            )
            for field in (
                "execution_status",
                "filled_quantity",
                "cash_leftover",
                "net_position_return",
                "event_cash_equity_return",
            ):
                check(field, computed[field], label[field], period)
        else:
            purchase = decimal(buy.price) * quantity
            buy_fee = purchase * Decimal("0.001")
            cost = purchase + buy_fee
            cash = Decimal("100000") - cost
            assert cash >= 0
            factor_in = decimal(adjusted.loc[entry, "Close"]) / decimal(raw.loc[entry, "Close"])
            computed.update(
                entry_price_raw=decimal(buy.price),
                buy_cost_including_fee=cost,
                cash_leftover=cash,
                filled_quantity=quantity,
                entry_factor=factor_in,
            )
            for field in (
                "entry_price_raw",
                "buy_cost_including_fee",
                "cash_leftover",
                "filled_quantity",
                "entry_factor",
            ):
                check(field, computed[field], label[field], period)
            exit_attempts = []
            for index in range(exit_i, len(sessions)):
                session = sessions[index]
                sell = public_fill(
                    "SELL",
                    "MARKET",
                    quantity,
                    decimal(raw.loc[sessions[index - 1], "Close"]),
                    session,
                )
                exit_attempts.append(
                    {
                        "date": session,
                        "reason": sell.reason if sell else "SUSPENDED",
                        "filled": bool(sell and sell.filled),
                    }
                )
                if sell and sell.filled:
                    factor_out = decimal(adjusted.loc[session, "Close"]) / decimal(
                        raw.loc[session, "Close"]
                    )
                    gross_sale = decimal(sell.price) * quantity * factor_out / factor_in
                    sell_fee = gross_sale * Decimal("0.001")
                    proceeds = gross_sale - sell_fee
                    computed.update(
                        execution_status="CLOSED",
                        actual_exit_date=session,
                        exit_delay_sessions=index - exit_i,
                        exit_price_raw=decimal(sell.price),
                        net_position_return=proceeds / cost - 1,
                        event_cash_equity_return=(cash + proceeds) / Decimal("100000") - 1,
                    )
                    execution.update(
                        buy_fee_cny=str(buy_fee),
                        sell_fee_adjusted_cny=str(sell_fee),
                        raw_sale_price=sell.price,
                        factor_in=str(factor_in),
                        factor_out=str(factor_out),
                        adjusted_sale_proceeds_cny=str(proceeds),
                        exit_attempts=exit_attempts,
                    )
                    for field in (
                        "execution_status",
                        "actual_exit_date",
                        "exit_delay_sessions",
                        "exit_price_raw",
                        "net_position_return",
                        "event_cash_equity_return",
                    ):
                        check(field, computed[field], label[field], period)
                    break
            else:
                computed.update(
                    execution_status="OPEN_AT_CUTOFF",
                    actual_exit_date=None,
                    net_position_return=None,
                    event_cash_equity_return=None,
                )
                for field in (
                    "execution_status",
                    "actual_exit_date",
                    "net_position_return",
                    "event_cash_equity_return",
                ):
                    check(field, computed[field], label.get(field), period)
        preformal = max(d for d in sessions if d < news["formal_source_day"])
        assert decision <= preformal < news["formal_source_day"]
        stock_path = (
            decimal(adjusted.loc[preformal, "Close"]) / decimal(adjusted.loc[decision, "Close"]) - 1
        )
        sector_path = (
            decimal(sector.loc[preformal, "Close"]) / decimal(sector.loc[decision, "Close"]) - 1
        )
        check("strict_preformal_close_date", preformal, recorded["preformal_date"], period)
        check(
            "guidance_Dclose_to_preformal_close_stock",
            stock_path,
            recorded["guidance_decision_close_to_preformal_close_stock_return"],
            period,
        )
        check(
            "guidance_Dclose_to_preformal_close_sector_excess",
            stock_path - sector_path,
            recorded["guidance_decision_close_to_preformal_close_sector_excess"],
            period,
        )
        audited.append(
            {
                **news,
                "computed_label": computed,
                "execution_audit": execution,
                "preformal_path": {
                    "start": decision,
                    "end": preformal,
                    "stock_return": stock_path,
                    "sector_return": sector_path,
                    "sector_excess": stock_path - sector_path,
                },
                "price_sessions": held,
                "status": "FAIL" if any(f["period"] == period for f in failures) else "PASS",
            }
        )
    equivalence_path = EX / "others/market_contract_equivalence.json"
    equivalence = read(equivalence_path)
    check("old_contract_equivalence_status", "PASS", equivalence["status"])
    check("old_contract_equivalence_event_count", 25, len(equivalence["events"]))
    check(
        "old_contract_equivalence_all_pass",
        True,
        all(e["status"] == "PASS" for e in equivalence["events"]),
    )
    for path, expected in equivalence["source_sha256"].items():
        check("old_equivalence_source_hash", digest(ROOT / path), expected)
    result = {
        "status": "PASS" if not failures else "FAIL",
        "experiment": "EX037_20261019",
        "checks": check_count,
        "failure_count": len(failures),
        "failures": failures,
        "first_news_count": len(audited),
        "all_first_news_retained_no_return_selection": True,
        "first_news": audited,
        "execution_counts": dict(
            Counter(item["computed_label"]["execution_status"] for item in audited)
        ),
        "market_contract_roles": {
            "old_25_dates": "Compatibility of common new helper with previously published EX036 contract; no new independent outcomes or sample expansion",
            "new_five_dates": "This independent reconstruction of five earliest same-period guidance news dates; descriptive only, overlapping, seen history, no causality or additional primary tests",
        },
        "snapshot_bindings": input_hashes,
        "source_hashes": [
            {"path": relative(p), "sha256": digest(p)}
            for p in [
                source_results,
                guidance_path,
                formal_path,
                market_manifest,
                equivalence_path,
                Path(__file__),
                ROOT / "packages/trading_execution_engine/src/trading_execution_engine/fills.py",
                ROOT / "packages/trading_execution_engine/src/trading_execution_engine/market.py",
            ]
        ],
        "network": "socket connect/create_connection blocked; CSV snapshots only; no provider calls",
        "new_api_calls": 0,
        "new_model_fits": 0,
        "new_accounts": 0,
        "method_independence": "Does not import root event_label or information_math; independently reconstructs source universe, session indices, Decimal price/quantity/fees and paths; uses same required public TXE fill contract",
        "limitations": [
            "All five observed entries filled; NO_TRADE and OPEN_PENDING branches checked by semantics, not observed first-news examples",
            "Full-session low may precede an intraday fill, not a certified post-fill path",
            "HFQ relative factors give synthetic isolated-position economic labels; not a literal raw-share corporate-action cash account",
            "Five observed news paths do not prove market absorption or causal financial news returns",
            "Path ending before formal source day is descriptive, not an executable decision rule that knows a future publication date",
        ],
    }
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False, default=str)
        stream.write("\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "checks": check_count,
                "failures": len(failures),
                "first_news": len(audited),
                "execution_counts": result["execution_counts"],
            }
        )
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
