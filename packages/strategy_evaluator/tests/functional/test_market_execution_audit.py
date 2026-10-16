"""Market execution is independently authenticated without importing TXE."""
from copy import deepcopy
from dataclasses import replace

import pytest

from strategy_evaluator import AuditStatus, BenchmarkEvidence, audit_benchmark_replay, audit_replay
from strategy_evaluator._market_execution import blocked_order
from test_champion_ledger_authentication import _replay as closed_replay
from test_intraday_replay_audit import _evidence as overlay_replay


def rules(sessions, *, lower=.8, upper=1.2):
    return {"contract_version": "OPEN_LIMIT_BLOCK_V1", "symbol": "510300.SH",
            "sessions": [{"session": day, "down_limit": lower, "up_limit": upper} for day in sessions]}


def benchmark():
    days = ("2026-01-05", "2026-01-06")
    return BenchmarkEvidence(
        "BUYHOLD", 100., 0., days,
        ({"date": days[0], "open": 10., "close": 10.},
         {"date": days[1], "open": 9., "close": 9.}), (),
        ({"date": days[0], "target_position": 1., "cash": 100., "quantity": 0., "equity": 100.},
         {"date": days[1], "target_position": 1., "cash": 1., "quantity": 11., "equity": 100.}),
        ({"execution_date": days[1], "side": "BUY", "size": 11., "price": 9., "fees": 0.},), (),
        {"return": 0., "max_drawdown": 0., "calmar": None, "sharpe": None,
         "win_loss_ratio": None, "win_loss_ratio_status": "NO_CLOSED_TRADES",
         "closed_trades": 0, "win_rate": None}, 1,
        market_rules=rules(days, lower=8., upper=10.),
        attempts=({"execution_date": days[0], "side": "BUY", "quantity": 10., "status": "UNFILLED"},
                  {"execution_date": days[1], "side": "BUY", "quantity": 11., "status": "FILLED"}),
    )


def strategy():
    source = closed_replay()
    market = rules(source.evaluation_sessions)
    # First buy is blocked; the still-valid target is attempted next session.
    market["sessions"][1]["up_limit"] = 1.
    first, retry = source.evaluation_sessions[1:3]
    buy, sell = source.orders
    orders = ({**buy, "status": "UNFILLED"},
              {**buy, "order_id": "retry", "decision_id": "d2", "signal_date": first,
               "execution_date": retry}, sell)
    fills = ({**source.fills[0], "order_id": "retry", "decision_id": "d2",
              "signal_date": first, "fill_time": retry + "T09:30:00"},
             {**source.fills[1], "fill_time": str(source.fills[1]["fill_time"])[:10] + "T09:30:00"})
    accounts = list(source.account_daily)
    accounts[1] = {**accounts[1], "cash": 100000., "quantity": 0, "equity": 100000.}
    accounts[2] = {**accounts[2], "cash_before": 100000., "quantity_before": 0}
    return replace(source, execution_spec={**source.execution_spec, "market_rules": market},
                   orders=orders, fills=fills, account_daily=tuple(accounts),
                   trades=({**source.trades[0], "entry_date": retry},))


@pytest.mark.parametrize("kind", ["benchmark", "strategy"])
def test_true_unfilled_then_retry_passes(kind):
    evidence, audit = (benchmark(), audit_benchmark_replay) if kind == "benchmark" else (strategy(), audit_replay)
    original = deepcopy(evidence.to_dict())
    result = audit(evidence)
    assert result.status is AuditStatus.PASS, result.reason_codes
    assert evidence.to_dict() == original


@pytest.mark.parametrize("kind", ["benchmark", "strategy"])
@pytest.mark.parametrize("bad", [None, [], 1, {"sessions": []}, "unknown", {"invalid"}])
def test_invalid_market_contract_returns_fail(kind, bad):
    evidence, audit = (benchmark(), audit_benchmark_replay) if kind == "benchmark" else (strategy(), audit_replay)
    valid = evidence.market_rules if kind == "benchmark" else evidence.execution_spec["market_rules"]
    value = {**valid, "sessions": None} if bad is None else bad
    changed = (replace(evidence, market_rules=value) if kind == "benchmark" else
               replace(evidence, execution_spec={**evidence.execution_spec, "market_rules": value}))
    assert audit(changed).status is AuditStatus.FAIL


@pytest.mark.parametrize("kind", ["benchmark", "strategy"])
@pytest.mark.parametrize("tamper", ["unknown", "missing", "nan", "negative", "duplicate", "symbol"])
def test_market_boundary_corruption_cannot_pass(kind, tamper):
    evidence, audit = (benchmark(), audit_benchmark_replay) if kind == "benchmark" else (strategy(), audit_replay)
    market = deepcopy(evidence.market_rules if kind == "benchmark" else evidence.execution_spec["market_rules"])
    if tamper == "unknown":
        market["contract_version"] = "FUTURE_UNSUPPORTED_VERSION"
    elif tamper == "missing":
        market["sessions"].pop(0)
    elif tamper == "duplicate":
        market["sessions"].append(market["sessions"][-1])
    elif tamper == "symbol":
        market["symbol"] = "AAPL"
    else:
        market["sessions"][0]["up_limit"] = float("nan") if tamper == "nan" else -1.
    changed = (replace(evidence, market_rules=market) if kind == "benchmark" else
               replace(evidence, execution_spec={**evidence.execution_spec, "market_rules": market}))
    assert audit(changed).status is AuditStatus.FAIL


@pytest.mark.parametrize("kind", ["benchmark", "strategy"])
def test_forged_blocked_fill_fails(kind):
    if kind == "benchmark":
        evidence = benchmark()
        forged = replace(evidence, orders=({**evidence.orders[0], "execution_date": evidence.evaluation_sessions[0],
                                            "price": 10.}, *evidence.orders))
        result = audit_benchmark_replay(forged)
    else:
        evidence = strategy()
        forged = {**evidence.fills[0], "order_id": "buy", "decision_id": "d1",
                  "fill_time": evidence.evaluation_sessions[1]}
        result = audit_replay(replace(evidence, fills=(forged, *evidence.fills)))
    assert result.status is AuditStatus.FAIL


@pytest.mark.parametrize("kind", ["benchmark", "strategy"])
def test_tampered_unfilled_day_cash_fails(kind):
    evidence, audit = (benchmark(), audit_benchmark_replay) if kind == "benchmark" else (strategy(), audit_replay)
    index = 0 if kind == "benchmark" else 1
    accounts = list(evidence.account_daily)
    accounts[index] = {**accounts[index], "cash": accounts[index]["cash"] - .01}
    assert audit(replace(evidence, account_daily=tuple(accounts))).status is AuditStatus.FAIL


def test_benchmark_missing_or_forged_attempt_fails():
    evidence = benchmark()
    assert audit_benchmark_replay(replace(evidence, attempts=evidence.attempts[1:])).status is AuditStatus.FAIL
    changed = ({**evidence.attempts[0], "status": "FILLED"}, evidence.attempts[1])
    assert audit_benchmark_replay(replace(evidence, attempts=changed)).status is AuditStatus.FAIL


@pytest.mark.parametrize("side,price,bounds,blocked", [
    ("BUY", 100. - 5e-9, (80., 100.), True),
    ("BUY", 100. - 2e-8, (80., 100.), False),
    ("SELL", .01 + 5e-13, (.01, 100.), True),
    ("SELL", .01 + 2e-12, (.01, 100.), False),
    ("SELL", 100., (80., 100.), False),
    ("BUY", 80., (80., 100.), False),
])
def test_market_tolerance_and_opposite_side(side, price, bounds, blocked):
    assert blocked_order(side, price, bounds) is blocked


def test_overlay_cannot_ignore_unknown_or_unsupported_market_contract():
    evidence = overlay_replay()
    for contract in ("unknown", rules(evidence.evaluation_sessions, lower=8., upper=12.)):
        changed = replace(evidence, execution_spec={**evidence.execution_spec, "market_rules": contract})
        assert audit_replay(changed).status is AuditStatus.FAIL


@pytest.mark.parametrize("kind", ["benchmark", "strategy"])
@pytest.mark.parametrize("field", ["price", "fees"])
def test_nonfinite_actual_fill_cannot_pass(kind, field):
    if kind == "benchmark":
        evidence = benchmark()
        changed = replace(evidence, orders=({**evidence.orders[0], field: float("nan")},))
        audit = audit_benchmark_replay
    else:
        evidence = strategy()
        changed = replace(evidence, fills=({**evidence.fills[0], field: float("nan")}, *evidence.fills[1:]))
        audit = audit_replay
    assert audit(changed).status is AuditStatus.FAIL


def test_unknown_order_status_cannot_pass():
    evidence = strategy()
    orders = list(evidence.orders)
    orders[1] = {**orders[1], "status": "UNKNOWN"}
    assert audit_replay(replace(evidence, orders=tuple(orders))).status is AuditStatus.FAIL


def test_outside_limit_is_a_real_unfilled_order_and_invalid_limit_rejected():
    assert blocked_order("BUY", 10., (9., 11.), order_type="LIMIT", limit_price=11.01)
    assert not blocked_order("BUY", 10., (9., 11.), order_type="LIMIT", limit_price=11.)
    with pytest.raises(ValueError, match="invalid market order limit"):
        blocked_order("BUY", 10., (9., 11.), order_type="LIMIT", limit_price=None)


@pytest.mark.parametrize("tamper", ["missing_order", "wrong_fill_date", "wrong_decision", "unknown_side"])
def test_fill_must_belong_to_its_real_order(tamper):
    evidence = strategy()
    if tamper == "missing_order":
        changed = replace(evidence, orders=evidence.orders[:1] + evidence.orders[2:])
    elif tamper == "unknown_side":
        orders = list(evidence.orders)
        orders[1] = {**orders[1], "side": "UNKNOWN"}
        changed = replace(evidence, orders=tuple(orders))
    else:
        field, value = ("fill_time", evidence.evaluation_sessions[1]) if tamper == "wrong_fill_date" else ("decision_id", "forged")
        changed = replace(evidence, fills=({**evidence.fills[0], field: value}, *evidence.fills[1:]))
    assert audit_replay(changed).status is AuditStatus.FAIL


@pytest.mark.parametrize("section,field,index", [
    ("orders", "quantity", 1), ("fills", "quantity", 0),
    ("account_daily", "quantity_before", 2), ("account_daily", "quantity", 2),
    ("trades", "quantity", 0),
])
@pytest.mark.parametrize("bad", [99900.5, True, float("nan"), float("inf"), "99900"])
def test_market_quantities_are_strict_finite_integers(section, field, index, bad):
    evidence = strategy()
    rows = list(getattr(evidence, section))
    rows[index] = {**rows[index], field: bad}
    result = audit_replay(replace(evidence, **{section: tuple(rows)}))
    assert result.status is AuditStatus.FAIL


@pytest.mark.parametrize("field", ["cash_before", "cash", "close", "equity"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True, "100000"])
def test_market_account_values_are_finite_real_numbers(field, bad):
    evidence = strategy()
    rows = list(evidence.account_daily)
    rows[2] = {**rows[2], field: bad}
    assert audit_replay(replace(evidence, account_daily=tuple(rows))).status is AuditStatus.FAIL


@pytest.mark.parametrize("clock", ["23:00:00", "09:31:00", "09:29:59", "12:00:00", "09:30:00+08:00"])
@pytest.mark.parametrize("index", [0, 1], ids=["OPEN", "OPEN_MARKET"])
def test_open_fill_requires_exact_local_0930(index, clock):
    evidence = strategy()
    rows = list(evidence.fills)
    rows[index] = {**rows[index], "fill_time": str(rows[index]["fill_time"])[:10] + "T" + clock}
    result = audit_replay(replace(evidence, fills=tuple(rows)))
    assert result.status is AuditStatus.FAIL


def intraday_strategy():
    evidence = strategy()
    day = evidence.evaluation_sessions[2]
    daily = tuple({**row, "open": 1.05} if str(row["date"])[:10] == day else row
                  for row in evidence.execution_daily)
    bars = tuple({"time": day + "T" + clock, "low": low, "high": 1.06}
                 for clock, low in (("09:35:00", 1.), ("09:40:00", .999), ("09:45:00", .998)))
    fills = ({**evidence.fills[0], "trigger": "INTRADAY_LIMIT", "fill_time": day + "T09:40:00"},
             evidence.fills[1])
    return replace(evidence, execution_daily=daily, execution_intraday=bars, fills=fills)


def test_intraday_fill_matches_first_strict_cross_not_equal_touch():
    evidence = intraday_strategy()
    result = audit_replay(evidence)
    assert result.status is AuditStatus.PASS, result.reason_codes
    for clock in ("09:35:00", "09:41:00", "09:45:00"):
        fills = ({**evidence.fills[0], "fill_time": evidence.evaluation_sessions[2] + "T" + clock},
                 evidence.fills[1])
        assert audit_replay(replace(evidence, fills=fills)).status is AuditStatus.FAIL


@pytest.mark.parametrize("tamper", ["lunch", "unknown_session", "unordered", "missing_price"])
def test_unknown_or_ineligible_intraday_evidence_rejected(tamper):
    evidence = intraday_strategy()
    bars = list(evidence.execution_intraday)
    if tamper == "lunch":
        bars[1] = {**bars[1], "time": evidence.evaluation_sessions[2] + "T12:00:00"}
    elif tamper == "unknown_session":
        bars[1] = {**bars[1], "time": "2030-01-02T09:40:00"}
    elif tamper == "unordered":
        bars.reverse()
    else:
        bars[1] = {key: value for key, value in bars[1].items() if key != "low"}
    assert audit_replay(replace(evidence, execution_intraday=tuple(bars))).status is AuditStatus.FAIL
