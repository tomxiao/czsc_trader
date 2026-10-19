"""Pure synthetic component timing, price units and local-state boundaries."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import socket

import numpy as np
import pandas as pd

from local_cycle import Action, CycleSeed, PreparedInputs, label, public_sell, simulate, state_at_D

EX = Path(__file__).resolve().parents[1]
CHECKS = []


def deny(*args, **kwargs):
    raise RuntimeError("Synthetic prechecks forbid network")


socket.socket.connect = deny
socket.create_connection = deny


def check(name, value):
    assert value, name
    CHECKS.append(name)


def fixture():
    dates = pd.bdate_range("2020-01-01", periods=20)
    prices = np.full(20, 11.0)
    prices[:3] = 10
    prices[12:] = 12
    raw = pd.DataFrame({"Date": dates, "Open": prices, "High": prices + .5,
                        "Low": prices - .5, "Close": prices}, index=dates)
    market = raw.copy(deep=True)
    for c in ("Open", "High", "Low", "Close"):
        market[c] *= 5.892
    f = pd.DataFrame({"ma20_prior": 58.0, "ma20_prior_lag5": 57.0,
                      "atr20_prior": 2.0, "shock_known": True, "atr_positive": True,
                      "z5": 0.0, "support_floor": 50.0}, index=dates)
    f.loc[dates[3], "z5"] = 3
    bounds = pd.DataFrame({"DownLimit": 1., "UpLimit": 100.}, index=dates)
    status = pd.DataFrame({"Status": "TRADING"}, index=dates)
    clock = {a.strftime("%Y-%m-%d"): b.strftime("%Y-%m-%d") for a, b in zip(dates[:-1], dates[1:], strict=True)}
    data = PreparedInputs(market, raw, bounds, status, f, raw.copy(), raw, bounds, status,
                          clock, tuple(dates.strftime("%Y-%m-%d")), dates[-1].strftime("%Y-%m-%d"))
    seed = CycleSeed("TOY", "CYCLE", str(dates[2].date()), str(dates[3].date()), 2, 11, 12,
                     100, 10., 1., 58.92)
    return seed, data, dates


def main():
    target = EX / "others/synthetic_precheck.json"
    assert not target.exists(), "Preserve completed synthetic evidence"
    seed, data, d = fixture()
    on, off = simulate(seed, data, Action.ON), simulate(seed, data, Action.OFF_LOCAL_CYCLE)
    check("ON original firstSHOCK nextE", on["exit_E"] == str(d[4].date()) and on["trace"][-1]["D"] == seed.first_shock_D)
    check("OFF latches only firstSHOCK cycle until originalH10", off["exit_E"] == str(d[12].date()) and off["trace"][-1]["deadline_exit"])
    check("fixed original entry and reservation never reset", all(r["entry_index"] == 2 and r["deadline_index"] == 11 and r["reservation_index"] == 12 for r in off["trace"]))
    check("no post-sale close or reentry", not on["post_sale_close_evaluated"] and not off["post_sale_close_evaluated"] and not any(r["D"] >= off["exit_E"] for r in off["trace"]))
    check("MODELED PUBLIC execution precision retained", on["exit_trigger"] == "OPEN_MARKET" and on["exit_time_precision"] == "TIMESTAMP")
    check("OFF rawshock retained selected suppressed", off["trace"][1]["shock_condition"] and not off["trace"][1]["selected_shock_exit"] and off["trace"][1]["shock_disable_latched"])
    advantage = label(seed, on["exit_price_ledger"], on["exit_fee"], off)
    check("same quantity total-proceeds label positive", advantage["sign"] == 1 and advantage["advantage"] > 0)
    same = dict(off, exit_price_ledger=on["exit_price_ledger"], exit_fee=on["exit_fee"])
    check("strict exact tie zero", label(seed, on["exit_price_ledger"], on["exit_fee"], same)["sign"] == 0)
    tiny = dict(same, exit_fee=same["exit_fee"] + 1e-9)
    check("strict negative no sign epsilon", label(seed, on["exit_price_ledger"], on["exit_fee"], tiny)["sign"] == -1)
    double = replace(seed, quantity=200, actual_buy_fee=2.)
    twice = dict(off, quantity=200, exit_fee=off["exit_fee"] * 2)
    check("quantity-scaled equivalent unit", label(double, on["exit_price_ledger"], on["exit_fee"] * 2, twice)["advantage"] == advantage["advantage"])
    # Never read later original held-state: inputs contain market-only arrays.
    changed_features = data.source_features.copy(deep=True)
    changed_features.loc[d[5], "support_floor"] = 100
    early = simulate(seed, replace(data, source_features=changed_features), Action.OFF_LOCAL_CYCLE)
    check("OFF after originalSELL uses own cost support state", early["exit_E"] == str(d[6].date()) and early["trace"][-1]["ordinary_support_exit"])
    cost_features = data.source_features.copy(deep=True)
    cost_market = data.source_market.copy(deep=True)
    cost_market.loc[d[5], "Close"] = 40
    cost = simulate(seed, replace(data, source_market=cost_market, source_features=cost_features), Action.OFF_LOCAL_CYCLE)
    check("OFF still exits cost independently", cost["exit_E"] == str(d[6].date()) and cost["trace"][-1]["selected_cost_exit"])
    blocked_status = data.trading_status.copy(deep=True)
    blocked_status.loc[d[4], "Status"] = "SUSPENDED"
    delayed = simulate(seed, replace(data, trading_status=blocked_status), Action.ON)
    check("SELL suspended pending continues with no new shock", delayed["exit_E"] == str(d[5].date()) and delayed["trace"][-1]["pending_inherited"] and not delayed["trace"][-1]["profit_exit_eligible"])
    check("blocked pending original anchors", delayed["trace"][-1]["deadline_index"] == 11 and len(delayed["attempts"]) == 2)
    allblocked = data.trading_status.copy(deep=True)
    allblocked.loc[d[4]:, "Status"] = "SUSPENDED"
    censored = simulate(seed, replace(data, trading_status=allblocked), Action.ON)
    check("cutoff pending not forced final mark", censored["status"] == "CENSORED" and censored["exit_price_ledger"] is None)
    off_censor = simulate(seed, replace(data, trading_status=allblocked), Action.OFF_LOCAL_CYCLE)
    check("OFF unresolved label null", label(seed, on["exit_price_ledger"], on["exit_fee"], off_censor) == {"advantage": None, "sign": None, "delta_net_proceeds": None})
    check("pending across original deadline does not reset", any(r["deadline_exit"] and r["pending_inherited"] for r in censored["trace"]))
    # Existing public DAILY_OPEN_PLUS_TICK/SESSION contract, never force OPEN.
    projected = data.projected_execution.copy(deep=True)
    projected.loc[d[4], ["Open", "Low", "High", "Close"]] = [9., 9., 9.5, 9.2]
    limits = data.price_limits.copy(deep=True)
    limits.loc[d[4], "DownLimit"] = 9.
    session = public_sell(replace(data, projected_execution=projected, raw_execution=projected.copy(), price_limits=limits), str(d[4].date()), 100)
    check("public lower-open SELL SESSION exact", session["filled"] and session["price"] == 9.01 and session["trigger"] == "DAILY_OPEN_PLUS_TICK" and session["time_precision"] == "SESSION")
    unknown = state_at_D(data, str(d[3].date()))
    check("missing5day explicit unknown", unknown["NON_FINAL_DAY_DOMINATED"] is None)
    states = state_at_D(data, str(d[6].date()))
    check("runtime source MA not anchored close", states["PRIOR_TREND_ESTABLISHED"] is True)
    check("declared log shape equality and direction", states["NON_FINAL_DAY_DOMINATED"] is True)
    infinite = data.source_market.copy(deep=True)
    infinite.loc[d[6], "Close"] = float("inf")
    check("nonfinite source price is unknown not false", state_at_D(replace(data, source_market=infinite), str(d[6].date()))["NON_FINAL_DAY_DOMINATED"] is None)
    overflow = data.source_market.copy(deep=True)
    overflow.loc[d[5], "Close"] = 1e300
    overflow.loc[d[1], "Close"] = 1e-300
    check("finite prices with nonfinite ratio unknown", state_at_D(replace(data, source_market=overflow), str(d[6].date()))["NON_FINAL_DAY_DOMINATED"] is None)
    for day in (d[3], d[6], d[10]):
        future = data.source_market.copy(deep=True)
        future.loc[future.index > day, "Close"] *= 2
        check("future close cannot change D state " + str(day.date()), state_at_D(data, str(day.date())) == state_at_D(replace(data, source_market=future), str(day.date())))
    for bad in ("ON", None, True):
        try:
            simulate(seed, data, bad)
        except ValueError:
            CHECKS.append("reject untyped action " + str(bad))
        else:
            raise AssertionError(bad)
    for bad in ({"quantity": 101}, {"deadline_index": 12}, {"runtime_entry_price": float("nan")}):
        try:
            replace(seed, **bad)
        except ValueError:
            CHECKS.append("reject bad seed " + str(bad))
        else:
            raise AssertionError(bad)
    result = {"status": "PASS_PURE_SYNTHETIC_ONLY", "checks_count": len(CHECKS), "checks": CHECKS,
              "source_hashes": {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted((EX / "src").glob("*.py"))},
              "new_market_fetches": 0, "new_actual_ON_controls": 0, "new_OFF_labels": 0, "new_funded_accounts": 0}
    with target.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    print("PURE_COMPONENT_PASS", len(CHECKS))


if __name__ == "__main__":
    main()
