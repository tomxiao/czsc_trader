"""Independently reconstruct hard/linear participation with confirmed exit state."""
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from dataflows import BarFrequency, EquityProduct
from strategy_runtime import equity_source_hash

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
sys.path.insert(0, str(ROOT / "research/S019/experiments/EX013_20261110/src"))
from runner import read_account  # noqa: E402
from data_window import load  # noqa: E402

POLICIES = {"hard", "none", "confirm", "daily_close", "rolling_atr", "ramp"}


def participation_factor(ratio, threshold, quiet, width, policy):
    if policy not in {'hard','linear'}:
        raise ValueError('Unknown participation policy')
    if not all(np.isfinite(x) for x in (ratio,threshold,quiet,width)):
        raise ValueError('Finite participation inputs required')
    if ratio < 0 or threshold <= 0 or width <= 0 or not 0 < quiet <= 1:
        raise ValueError('Invalid participation domain')
    if policy == 'hard':
        return 1.0 if ratio >= threshold else quiet
    weight = (ratio/threshold-(1-width))/(2*width)
    return quiet+(1-quiet)*max(0.,min(1.,weight))


def holding_step(p, state, price, slot, age, rolling_atr):
    """Independent arithmetic for one already-confirmed holding observation."""
    policy = p["exit_policy"]
    assert policy in POLICIES and p["exit_width"] > 0 and p["confirm_bars"] >= 1
    peak = state["peak"]
    if policy != "daily_close" or slot == 0:
        peak = max(peak, price)
    scale = rolling_atr if policy == "rolling_atr" else state["atr"]
    assert np.isfinite(scale) and scale > 0
    crossed = price <= peak - p["trail_atr"] * scale
    count = state["count"] + 1 if crossed else 0
    fraction = state["fraction"]
    if policy == "none":
        stop = False
    elif policy == "confirm":
        stop = count >= p["confirm_bars"]
    elif policy == "daily_close":
        stop = slot == 0 and crossed
    elif policy == "ramp":
        distance = (peak - price) / scale
        raw_fraction = (p["trail_atr"] + p["exit_width"] / 2 - distance) / p["exit_width"]
        fraction = min(fraction, max(0.0, min(1.0, raw_fraction)))
        stop = fraction == 0
    else:
        stop = crossed
    assert 0 <= fraction <= state["fraction"] <= 1
    exiting = state["exiting"] or stop or age >= p["hold_days"]
    updated = {**state, "peak": peak, "fraction": fraction, "count": count, "exiting": exiting}
    return (0.0 if exiting else state["base"] * fraction), updated, bool(stop)


def boundary_checks():
    cutoff, quiet = 1.175, .645
    for width in (.05,.10,.20):
        assert participation_factor(np.nextafter(cutoff,0),cutoff,quiet,width,'hard') == quiet
        assert participation_factor(cutoff,cutoff,quiet,width,'hard') == 1
        for ratio, expected in ((0.,quiet),(cutoff*(1-width),quiet),
                (cutoff,(quiet+1)/2),(cutoff*(1+width),1.),(3*cutoff,1.)):
            assert np.isclose(participation_factor(ratio,cutoff,quiet,width,'linear'),expected,atol=1e-14,rtol=0)
        factors = [participation_factor(r,cutoff,quiet,width,'linear') for r in (0.,.8,1.,1.175,1.4,2.)]
        assert all(quiet <= x <= 1 for x in factors) and factors == sorted(factors)
        a = participation_factor(0.,cutoff,quiet,width,'linear')
        b = participation_factor(2*cutoff,cutoff,quiet,width,'linear')
        assert max(a,b) == 1.
    for values in ((-1.,cutoff,quiet,.1,'linear'),(1.,0.,quiet,.1,'linear'),
            (1.,cutoff,0.,.1,'linear'),(1.,cutoff,quiet,0.,'hard'),
            (float('nan'),cutoff,quiet,.1,'linear'),(1.,cutoff,quiet,.1,'unknown')):
        try:
            participation_factor(*values)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid participation inputs accepted')
    p = {"exit_policy": "hard", "exit_width": 1., "confirm_bars": 2, "trail_atr": 2., "hold_days": 5}
    state = {"peak": 100., "atr": 2., "fraction": 1., "count": 0, "exiting": False, "base": .6}
    assert holding_step(p, state, 96., 3, 1, 3.)[0] == 0
    assert holding_step({**p, "exit_policy": "none"}, state, 90., 3, 1, 3.)[0] == .6
    assert holding_step({**p, "exit_policy": "none"}, state, 90., 3, 5, 3.)[0] == 0
    confirm = {**p, "exit_policy": "confirm"}
    target, one, _ = holding_step(confirm, state, 96., 3, 1, 3.)
    assert target == .6 and one["count"] == 1
    assert holding_step(confirm, one, 96., 4, 1, 3.)[0] == 0
    _, reset, _ = holding_step(confirm, one, 97., 4, 1, 3.)
    assert reset["count"] == 0 and holding_step(confirm, reset, 96., 5, 1, 3.)[0] == .6
    daily = {**p, "exit_policy": "daily_close"}
    assert holding_step(daily, state, 105., 1, 1, 3.)[1]["peak"] == 100.
    assert holding_step(daily, state, 105., 0, 1, 3.)[1]["peak"] == 105.
    assert holding_step(daily, state, 96., 1, 1, 3.)[0] == .6
    assert holding_step(daily, state, 96., 0, 1, 3.)[0] == 0
    assert holding_step({**p, "exit_policy": "rolling_atr"}, state, 95., 3, 1, 3.)[0] == .6
    ramp = {**p, "exit_policy": "ramp"}
    target, half, _ = holding_step(ramp, state, 96., 3, 1, 3.)
    assert target == .3 and half["fraction"] == .5
    assert holding_step(ramp, half, 105., 4, 1, 3.)[0] == .3
    assert holding_step(ramp, half, 95., 5, 1, 3.)[0] == 0
    assert holding_step(p, {**state, "exiting": True}, 110., 2, 1, 3.)[0] == 0
    print("EXIT_AND_PARTICIPATION_BOUNDARIES_PASS", flush=True)


def main(manifest, output):
    boundary_checks()
    frames, _ = load()
    data = {}
    for (instrument, frequency, product), frame in frames.items():
        if product is EquityProduct.BARS:
            frame = frame.copy()
            frame["session"] = frame.Date.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
            data[instrument.symbol, frequency] = frame
    daily = data["MU", BarFrequency.DAILY].set_index("session")
    sector = data["SOXX", BarFrequency.DAILY].set_index("session")
    assert daily.index.equals(sector.index)
    ordinals = {day: i for i, day in enumerate(daily.index)}
    fine = {day: group.reset_index(drop=True) for day, group in data["MU", BarFrequency.M30].groupby("session")}
    first = data["MU", BarFrequency.M30].groupby("session", sort=True).first().reindex(daily.index)
    sector_first = data["SOXX", BarFrequency.M30].groupby("session", sort=True).first().reindex(daily.index)
    true_range = pd.concat([daily.High-daily.Low, (daily.High-daily.Close.shift()).abs(),
                            (daily.Low-daily.Close.shift()).abs()], axis=1).max(axis=1)
    results = []
    for item in json.loads(manifest.read_bytes()):
        definition_path = ROOT / item["definition"]
        definition = json.loads(definition_path.read_bytes())
        source = ROOT / item["source_root"] if "source_root" in item else definition_path.parent.parent / "src"
        assert definition["source_sha256"] == equity_source_hash(source, tuple(definition["source_files"]))
        p = json.loads(definition["parameters_json"])
        assert p["exit_mode"] == "fixed" and not p["require_sector"] and p["down_days"] == 1 and p["confirm"]
        assert p["risk_basis"] == "daily" and p["treatment"] == "tilt" and p["information"] == "relative"
        assert p["joint_rule"] == "maximum" and p["participation_days"] == 3 and p["hold_days"] == 5
        from family_close_inputs import validate_parameters
        search_path = ROOT / item['search_protocol']
        assert sha256(search_path.read_bytes()).hexdigest() == item['search_protocol_sha256']
        search = json.loads(search_path.read_bytes())
        family = next(f for f in search['families'] if f['name'] == item['family'])
        validate_parameters(p, family)
        assert 0 < p['weak_fraction'] <= 1 and 0 < p['quiet_fraction'] <= 1
        assert p['trail_atr'] > 0 and p['exit_width'] > 0
        assert p['exit_policy'] in {'hard','ramp','daily_close'}
        participation_factor(1.,p['participation_threshold'],p['quiet_fraction'],
            p['participation_width'],p['participation_policy'])
        assert definition["execution_spec"]["account"]["cash_availability"] == "IMMEDIATE_RESEARCH"
        ref, payload = read_account(ROOT / item["account"])
        header = json.loads(ref.resolve(ROOT).read_bytes())
        assert header["request"]["candidate_definition"] == definition
        run = payload["runs"]["candidate"]
        orders = {r["order_id"]: r for r in run["orders"]}
        assert len(orders) == len(run["orders"])
        by_decision = {r["decision_id"]: r for r in run["orders"]}
        assert len(by_decision) == len(orders)
        fills = {}
        for fill in run["fills"]:
            order = orders[fill["order_id"]]
            assert order["status"] == "FILLED" and fill["side"] == order["side"]
            assert fill["quantity"] == order["quantity"] and fill["quantity"] > 0
            assert fill["quantity"] == int(fill["quantity"]) and fill["price"] > 0 and fill["fees"] >= 0
            fills.setdefault(order["decision_id"], []).append(fill)
        for order in orders.values():
            assert order["status"] in {"FILLED", "EXPIRED"}
            assert len(fills.get(order["decision_id"], [])) == int(order["status"] == "FILLED")
        quantity, entry_day, state, cash, cycle_id = 0, None, None, 100000., None
        entries = exits = holding_checks = reductions = triggers = positive_target_closes = 0
        expected_targets = []
        max_cash_error = cash_rounding_bound = 0.
        for decision, point in zip(run["decisions"], run["account_points"], strict=True):
            stamp = pd.Timestamp(decision["execution_start"])
            decision_at = pd.Timestamp(decision["decision_at"])
            day = stamp.tz_convert("America/New_York").strftime("%Y-%m-%d")
            grid, i = fine[day], ordinals[day]
            assert i >= 65
            slot = int((stamp-grid.BarStart.iloc[0]).total_seconds()/1800)
            assert 0 <= slot < len(grid)
            price = float(daily.Close.iloc[i-1] if slot == 0 else grid.Close.iloc[slot-1])
            observed = daily.AvailableDate.iloc[i-1] if slot == 0 else grid.AvailableDate.iloc[slot-1]
            assert observed <= decision_at <= stamp
            assert pd.Timestamp(decision["observed_through"]) <= decision_at
            assert daily.AvailableDate.iloc[i-1] <= decision_at
            assert point["decision_id"] == decision["decision_id"]
            assert pd.Timestamp(point["time"]) == pd.Timestamp(decision["execution_end"])
            assert point["cash"] >= -1e-8 and point["quantity"] >= 0 and point["receivable"] == 0
            current_atr = float(true_range.iloc[i-14:i].mean())
            assert np.isfinite(current_atr) and current_atr > 0
            facts = {x["key"]: x["text"] for x in decision["explanation"]["basis"]}
            assert int(facts["slot"]) == slot and np.isclose(float(facts["price"]), price, atol=1e-12, rtol=0)
            assert facts['participation_policy'] == p['participation_policy']
            assert float(facts['participation_width']) == p['participation_width']
            if quantity:
                assert state is not None
                old_fraction = state["fraction"]
                expected, state, stopped = holding_step(p, state, price, slot, i-ordinals[entry_day], current_atr)
                holding_checks += 1
                reductions += state["fraction"] < old_fraction
                triggers += stopped
                scale = current_atr if p["exit_policy"] == "rolling_atr" else state["atr"]
                trail = state["peak"] - p["trail_atr"]*scale
                expected_facts = {"high_water": state["peak"], "entry_atr": state["atr"],
                    "risk_atr": scale, "trail_price": trail, "risk_fraction": state["fraction"]}
                assert all(np.isclose(float(facts[k]), v, atol=1e-12, rtol=0) for k,v in expected_facts.items())
                assert int(facts["held"]) == i-ordinals[entry_day] and int(facts["breach_count"]) == state["count"]
                assert facts["stopped"] == str(stopped) and facts["touched"] == str(price <= trail)
                assert facts["exit_policy"] == p["exit_policy"]
            elif slot == 1:
                assert state is None
                assert sector.AvailableDate.iloc[i-1] <= decision_at
                assert sector_first.Date.iloc[i] == first.Date.iloc[i]
                assert sector_first.AvailableDate.iloc[i] <= decision_at and first.AvailableDate.iloc[i] <= decision_at
                prior, anchor = float(daily.Close.iloc[i-1]), float(daily.Close.iloc[i-2])
                enter = prior < anchor and price < anchor and price > grid.Open.iloc[0]
                relative = (prior/daily.Close.iloc[i-64])/(sector.Close.iloc[i-1]/sector.Close.iloc[i-64])
                base = 1.0 if relative > 1 else p["weak_fraction"]
                opening_ratio = first.Volume.iloc[i]/first.Volume.iloc[i-3:i].median()
                previous_ratio = daily.Volume.iloc[i-1]/daily.Volume.iloc[i-4:i-1].median()
                a = participation_factor(opening_ratio,p['participation_threshold'],p['quiet_fraction'],
                    p['participation_width'],p['participation_policy'])
                b = participation_factor(previous_ratio,p['participation_threshold'],p['quiet_fraction'],
                    p['participation_width'],p['participation_policy'])
                participation = max(a,b)
                assert all(np.isclose(float(facts[k]),v,atol=1e-12,rtol=0) for k,v in {
                    'opening_factor':a,'prior_factor':b,'participation_factor':participation,
                    'participation':opening_ratio,'prior_participation':previous_ratio}.items())
                base *= participation
                expected = base if enter else 0.0
                assert np.isclose(float(facts["allocation"]), base, atol=1e-12, rtol=0)
                assert np.isclose(float(facts["entry_atr"]), current_atr, atol=1e-12, rtol=0)
            else:
                assert state is None
                expected = 0.0
            assert np.isfinite(expected) and 0 <= expected <= 1 and 0 <= decision["target"] <= 1
            assert np.isclose(float(facts["target_weight"]), expected, atol=1e-12, rtol=0)
            expected_targets.append(expected)
            assert np.isclose(expected, decision["target"], atol=5.01e-11, rtol=0), (item, day, slot, expected, decision["target"])
            order = by_decision.get(decision["decision_id"])
            assert (order is not None) == bool(decision["quantity"])
            if order is not None:
                assert order["quantity"] == decision["quantity"] and order["side"] == decision["side"]
                assert pd.Timestamp(order["valid_start"]) == stamp
                assert pd.Timestamp(order["valid_end"]) == pd.Timestamp(decision["execution_end"])
            before = quantity
            for fill in fills.get(decision["decision_id"], []):
                assert pd.Timestamp(fill["interval_start"]) == stamp
                assert pd.Timestamp(fill["interval_end"]) == pd.Timestamp(decision["execution_end"])
                sign = 1 if fill["side"] == "BUY" else -1
                assert fill["side"] in {"BUY", "SELL"}
                if quantity == 0:
                    assert fill["side"] == "BUY" and cycle_id is None
                    cycle_id = fill["cycle_id"]
                    assert cycle_id
                assert fill["cycle_id"] == cycle_id
                quantity += sign*fill["quantity"]
                cash -= sign*fill["quantity"]*fill["price"] + fill["fees"]
                cash_rounding_bound += (fill["quantity"]+1)*5.01e-11
            assert quantity == point["quantity"] and quantity >= 0
            assert point["cycle_id"] == (cycle_id if quantity else None)
            cash_error = abs(cash-point["cash"])
            assert cash_error <= cash_rounding_bound + 1e-5, (item, day, cash_error, cash_rounding_bound)
            max_cash_error = max(max_cash_error, cash_error)
            if before == 0 and quantity > 0:
                assert slot == 1 and expected > 0
                entry_day = day
                state = {"base": base, "peak": price, "atr": current_atr,
                    "fraction": 1., "count": 0, "exiting": False}
                entries += 1
            elif before > 0 and quantity == 0:
                # A positive ramp target below one integer unit can also flatten.
                if expected > 0:
                    assert p["exit_policy"] == "ramp"
                    positive_target_closes += 1
                entry_day = state = cycle_id = None
                exits += 1
        serialized = json.loads(pd.DataFrame({"target": expected_targets}).to_json(
            orient="records", date_format="iso", date_unit="us"))
        assert [x["target"] for x in serialized] == [x["target"] for x in run["decisions"]]
        assert exits == run["metrics"]["closed_cycles"]
        values = np.array([100000., *(x["equity"] for x in run["account_daily"])])
        dd = 1-values/np.maximum.accumulate(values)
        trough = int(dd.argmax())
        peak = int(values[:trough+1].argmax())
        results.append({**item, "account_sha256": ref.sha256, "strategy_source_sha256": definition["source_sha256"],
            "exit_policy": p["exit_policy"], "decisions": len(expected_targets), "entries": entries, "exits": exits,
            "participation_policy":p['participation_policy'],"participation_width":p['participation_width'],
            "holding_decisions": holding_checks, "risk_fraction_reductions": reductions, "stop_observations": triggers,
            "recorded_exit_facts": "PASS",
            "positive_target_integer_closes": positive_target_closes,
            "business_rules": "PASS", "signal_availability": "PASS", "holding_and_position_feedback": "PASS",
            "cash_longonly_integer": "PASS", "order_fill_status": "PASS", "serialized_targets_exact": "PASS",
            "maximum_target_rounding_error": max(abs(x-y["target"]) for x,y in zip(expected_targets,run["decisions"],strict=True)),
            "maximum_cash_reconstruction_error": max_cash_error,
            "cash_serialization_error_bound": cash_rounding_bound+1e-5,
            "mdd": float(dd[trough]), "drawdown_peak": run["account_daily"][peak-1]["session"] if peak else "INITIAL",
            "drawdown_trough": run["account_daily"][trough-1]["session"]})
        print("ACCOUNT_AUDIT_PASS", item["account"], p["exit_policy"], flush=True)
    output.write_bytes((json.dumps({"manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
        "audit_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "adapter_source_sha256": sha256(Path(__file__).with_name("family_close_inputs.py").read_bytes()).hexdigest(),
        "scope": "All decisions of selected accounts; source-bar targets and confirmed fill/order/cash state. Execution price optimality and unseen accounts are outside this audit.",
        "results": results}, ensure_ascii=False, indent=2)+"\n").encode())
    print("BUSINESS_AUDIT_PASS", sum(r["decisions"] for r in results), flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--check-boundaries"]:
        boundary_checks()
    else:
        main(Path(sys.argv[1]), Path(sys.argv[2]))
