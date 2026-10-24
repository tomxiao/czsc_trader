"""Read-only S015 account audit; writes only the selected experiment's audit.json.

No strategy replay, data fetch, model fitting, attribution fallback or publication.
Official UNSUPPORTED remains UNSUPPORTED. Independent arithmetic below describes
retained ledger facts; it does not identify a mechanism or an avoidable loss.
"""

# ruff: noqa: E402
import os

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"

from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext, diagnose_accounts
from czsc_trader.research_tools import (
    AccountDiagnosisRequest,
    AccountRunRef,
    EvaluationIdentity,
    EvaluationWindow,
    EvidenceRef,
)
from strategy_manager import CandidateKey
from strategy_runtime import EntryCycleState


ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
BASE = ROOT / "research/S015/experiments"
WINDOWS = {
    "full": EvaluationWindow("full", date(2025, 1, 2), date(2026, 10, 21)),
    "s011_common": EvaluationWindow("s011_common", date(2025, 2, 6), date(2026, 10, 21)),
}


def read(path):
    return json.loads(path.read_bytes())


def close(a, b):
    np.testing.assert_allclose(a, b, rtol=1e-10, atol=1e-7, equal_nan=False)


def day(value):
    return str(value)[:10]


def state(encoded):
    value = json.loads(encoded) if isinstance(encoded, str) else encoded
    return None if value is None else EntryCycleState.from_dict(value)


def identity(run):
    raw = run["identity"]
    return EvaluationIdentity(
        CandidateKey(**raw["candidate"]), **{k: v for k, v in raw.items() if k != "candidate"}
    )


def experiment_path(experiment):
    if re.fullmatch(r"EX\d{3}_\d{8}", experiment) is None:
        raise ValueError("experiment must be EXnnn_YYYYMMDD within S015")
    return BASE / experiment


def frame(payload):
    # Public account-evaluation ledgers retain pandas table-schema fields,
    # including the columns of a genuinely empty fills/orders/trades ledger.
    return pd.DataFrame(payload["data"], columns=[x["name"] for x in payload["schema"]["fields"]])


def distribution(values):
    a = np.asarray(values, dtype=float)
    profits, losses = a[a > 0], -a[a < 0]
    total_profit = float(profits.sum())
    return {
        "count": len(a),
        "profit_count": int((a > 0).sum()),
        "loss_count": int((a < 0).sum()),
        "zero_count": int((a == 0).sum()),
        "profit_yuan": total_profit,
        "loss_yuan": float(losses.sum()),
        "net_yuan": float(a.sum()),
        "quantiles_yuan": None
        if not len(a)
        else {str(q): float(np.quantile(a, q)) for q in (0, 0.1, 0.25, 0.5, 0.75, 0.9, 1)},
        "top_positive_share": {
            str(n): float(np.sort(profits)[-n:].sum() / total_profit) if total_profit else None
            for n in (1, 3, 5, 10)
        },
    }


def describe(run, summary):
    tables = {name: frame(payload) for name, payload in run["ledgers"].items()}
    daily, decisions, orders, fills, trades = [
        tables[name].copy() for name in ("account_daily", "decisions", "orders", "fills", "trades")
    ]
    window = run["window_id"]
    assert len(daily) == len(decisions) == (434 if window == "full" else 415)
    daily["day"] = daily.date.map(day)
    assert daily.day.is_unique and daily.day.is_monotonic_increasing
    assert decisions.decision_id.is_unique
    assert list(decisions.valid_session.map(day)) == list(daily.day)
    assert (decisions.signal_date.map(day) < decisions.valid_session.map(day)).all()
    close(daily.cash_before.iloc[0], 100000)
    assert daily.quantity_before.iloc[0] == 0
    close(daily.cash_before.iloc[1:], daily.cash.iloc[:-1])
    close(daily.quantity_before.iloc[1:], daily.quantity.iloc[:-1])
    close(daily.equity, daily.cash + daily.quantity * daily.close)
    policy = run["signal_support"]["execution_policy"]["settings"]["capital"]
    assert policy == {
        "fee_rate": 0.002,
        "mode": "signal_cash_fraction",
        "target_scope": "entry_cycle",
    }
    fee = Decimal(str(policy["fee_rate"]))
    for column in ("quantity", "price", "fees"):
        fills[column] = pd.to_numeric(fills[column])
    assert (fills.quantity % 100 == 0).all()
    close(fills.fees, fills.quantity * fills.price * float(fee))
    fills["day"] = fills.fill_time.map(day)
    fills["qchange"] = np.where(fills.side.eq("BUY"), fills.quantity, -fills.quantity)
    fills["cashchange"] = -fills.qchange * fills.price - fills.fees
    flows = fills.groupby("day")[["qchange", "cashchange"]].sum().reindex(daily.day, fill_value=0)
    close(daily.quantity - daily.quantity_before, flows.qchange)
    close(daily.cash - daily.cash_before, flows.cashchange)
    previous = None
    opened = []
    remaining_checks = 0
    for i, decision in decisions.iterrows():
        before, after = state(decision.entry_cycle_before), state(decision.entry_cycle_after)
        settled = state(daily.entry_cycle.iloc[i])
        assert before == previous
        current_orders = orders[orders.decision_id.eq(decision.decision_id)]
        current_fills = fills[fills.decision_id.eq(decision.decision_id)]
        if after is None:
            assert settled is None and current_fills.empty and current_orders.empty
        else:
            if before is None:
                opened.append(after.cycle_id)
                assert after.opening_signal_identity == decision.signal_identity
                close(
                    float(after.cash_budget),
                    float(daily.cash_before.iloc[i]) * float(after.allocation_fraction),
                )
                buys = current_orders[current_orders.side.eq("BUY")]
                assert not buys.empty
                limit = Decimal(str(buys.limit_price.iloc[0]))
                target = int(after.cash_budget / (limit * (1 + fee)) // 100) * 100
                assert after.target_quantity == target
                assert after.buy_cost_including_fees == 0
            else:
                for key in (
                    "cycle_id",
                    "opening_signal_identity",
                    "allocation_fraction",
                    "cash_budget",
                    "target_quantity",
                    "buy_cost_including_fees",
                ):
                    assert getattr(before, key) == getattr(after, key)
            if after.phase.value == "ACTIVE":
                buy_orders = current_orders[current_orders.side.eq("BUY")]
                assert len(buy_orders) == len(current_orders)
                assert int(buy_orders.quantity.sum()) <= after.target_quantity - int(
                    daily.quantity_before.iloc[i]
                )
                for order in buy_orders.itertuples():
                    assert Decimal(str(order.limit_price)) * int(order.quantity) * (
                        1 + fee
                    ) <= after.remaining_budget + Decimal(".0000001")
                total_reserved = sum(
                    (
                        Decimal(str(order.limit_price)) * int(order.quantity) * (1 + fee)
                        for order in buy_orders.itertuples()
                    ),
                    Decimal(0),
                )
                assert total_reserved <= after.remaining_budget + Decimal(".0000001")
                remaining_checks += 1
            buys = current_fills[current_fills.side.eq("BUY")]
            cost = sum(
                (Decimal(str(f.price)) * int(f.quantity) * (1 + fee) for f in buys.itertuples()),
                Decimal(0),
            )
            cumulative = after.buy_cost_including_fees + cost
            assert cumulative <= after.cash_budget + Decimal(".0000001")
            if settled is None:
                assert after.phase.value == "EXITING" and int(daily.quantity.iloc[i]) == 0
            else:
                assert settled.cycle_id == after.cycle_id
                close(float(settled.buy_cost_including_fees), float(cumulative))
                assert int(daily.quantity.iloc[i]) <= settled.target_quantity
        previous = settled
    assert len(opened) == len(set(opened))
    daily = daily.set_index("day")
    cycles = []
    for cycle_id, group in fills.groupby("cycle_id", sort=False):
        buys = group[group.side.eq("BUY")]
        sells = group[group.side.eq("SELL")]
        assert not buys.empty
        first = buys.iloc[0]
        remaining = int(group.qchange.sum())
        assert remaining >= 0
        gross = float((-group.qchange * group.price).sum() + remaining * daily.close.iloc[-1])
        firstday_buys = buys[buys.day.eq(first.day)]
        entry_gross = float(
            (firstday_buys.quantity * (daily.loc[first.day, "close"] - firstday_buys.price)).sum()
        )
        entry_fees = float(firstday_buys.fees.sum())
        fees = float(group.fees.sum())
        cycles.append(
            {
                "cycle_id": cycle_id,
                "entry_day": first.day,
                "exit_day": None if remaining else str(sells.iloc[-1].day),
                "buy_fills": len(buys),
                "sell_fills": len(sells),
                "remaining_quantity": remaining,
                "gross_yuan": gross,
                "fees_yuan": fees,
                "net_yuan": gross - fees,
                "first_entry_day_gross_yuan": entry_gross,
                "first_entry_day_net_yuan": entry_gross - entry_fees,
                "subsequent_gross_yuan": gross - entry_gross,
                "subsequent_net_yuan": gross - entry_gross - (fees - entry_fees),
            }
        )
    equity = np.r_[100000.0, daily.equity.to_numpy(float)]
    changes = np.diff(equity)
    net_yuan = float(equity[-1] - equity[0])
    close(sum(c["net_yuan"] for c in cycles), net_yuan)
    closed = trades[trades.status.eq("CLOSED")].copy()
    closed_days = closed.exit_date.map(day).value_counts().reindex(daily.index, fill_value=0)
    frequencies = closed_days.rolling(60).sum().dropna()
    net_return = float(equity[-1] / equity[0] - 1)
    drawdown = float(np.max(1 - equity / np.maximum.accumulate(equity)))
    close(net_return, summary["net_return"])
    close(drawdown, summary["dd"])
    assert len(closed) == summary["closed"]
    close(float(frequencies.median()), summary["frequency_median"])
    assert int((frequencies >= 3).sum()) == summary["frequency_good"]
    firstdays = {c["entry_day"] for c in cycles}
    entry_mask = daily.index.isin(firstdays)
    exposure = daily.quantity * daily.close / daily.equity
    years = []
    for year in sorted({x[:4] for x in daily.index}):
        selected = np.array([x.startswith(year) for x in daily.index])
        indices = np.flatnonzero(selected)
        years.append(
            {
                "year": int(year),
                "opening_equity": float(equity[indices[0]]),
                "closing_equity": float(equity[indices[-1] + 1]),
                "net_return": float(equity[indices[-1] + 1] / equity[indices[0]] - 1),
                "net_yuan": float(changes[selected].sum()),
                "first_entry_dates_equity_change_yuan": float(changes[selected & entry_mask].sum()),
                "other_dates_equity_change_yuan": float(changes[selected & ~entry_mask].sum()),
            }
        )
    return {
        "status": "ARITHMETIC_CHECKS_PASS",
        "window": window,
        "net_yuan": net_yuan,
        "net_return": net_return,
        "drawdown": drawdown,
        "fees_yuan": float(fills.fees.sum()),
        "years": years,
        "lock_checks": {
            "opened_cycles": len(opened),
            "active_remaining_order_checks": remaining_checks,
            "budget_limit_decisions": int(decisions.cycle_status.eq("BUDGET_LIMIT").sum()),
        },
        "exposure": {
            "holding_days": int((daily.quantity > 0).sum()),
            "mean_end_day": float(exposure.mean()),
            "maximum_end_day": float(exposure.max()),
        },
        "frequency": {
            "closed_trades": len(closed),
            "windows": len(frequencies),
            "rolling60_median": float(frequencies.median()),
            "rolling60_at_least3": int((frequencies >= 3).sum()),
        },
        "account_day_grouping": {
            "first_entry_dates": distribution(changes[entry_mask]),
            "other_dates": distribution(changes[~entry_mask]),
        },
        "cycle_distribution": distribution([c["net_yuan"] for c in cycles]),
        "closed_cycle_distribution": distribution(
            [c["net_yuan"] for c in cycles if not c["remaining_quantity"]]
        ),
        "cycle_sums": {
            key: float(sum(c[key] for c in cycles))
            for key in (
                "first_entry_day_gross_yuan",
                "first_entry_day_net_yuan",
                "subsequent_gross_yuan",
                "subsequent_net_yuan",
            )
        },
        "cycles": cycles,
    }


def main():
    from czsc_trader.research_tools.evaluation import validate_evaluation_evidence

    here = BASE / "EX063_20261024"
    output = here / "others/stress_audit.json"
    assert not output.exists(), "Preserve prior audit; use an explicit new revision"
    rows = read(here / "others/stress_results.json")
    centers = {r["candidate_id"]: r for r in read(here / "others/centers.json")}
    assert len(rows) == len(centers) == 16
    assert {r["candidate_id"] for r in rows} == set(centers)
    repository = RepositoryContext.discover(ROOT)
    report = {
        "status": "PENDING",
        "accounts": [],
        "technical_accounts": [],
        "method": "EX062 independent ledger arithmetic copied unchanged except expected fee .002; public evidence authentication precedes arithmetic.",
        "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "inputs": {
            str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
            for p in (here / "others/stress_results.json", here / "others/centers.json")
        },
        "limitations": [
            "UNSUPPORTED is preserved, not official attribution.",
            "No new account execution, publication or candidate registration.",
            "Entry-day and later cycle profits are descriptive, not causal identification.",
        ],
    }
    authenticated = {}

    def evidence(refdict):
        ref = EvidenceRef.from_dict(refdict)
        assert ref.experiment.strategy_id == "S015"
        value = read(ref.resolve(ROOT))
        validate_evaluation_evidence(value)
        return ref, value

    try:
        for row in rows:
            cid = row["candidate_id"]
            center = centers[cid]
            ref, value = evidence(row["evidence"])
            oldref, old = evidence(center["evidence"])
            assert ref.experiment.experiment_id == "EX063_20261024"
            assert value["request_hash"] == row["request_hash"]
            assert value["result_hash"] == row["result_hash"]
            request, prior = value["request_identity"], old["request_identity"]
            assert request["costs"] == [
                {"scenario_id": "fee_x2", "one_way_cost": 0.002, "measurement_tier": "STRESS"}
            ]
            assert request["content_sha256"] == center["identity"]["content_sha256"]
            assert request["strategy_reference"] == "S015-" + cid
            for field in (
                "content_sha256",
                "strategy_identity",
                "runtime_binding_hash",
                "symbol",
                "asset_type",
                "data_cutoff",
                "initial_cash",
                "price_basis",
                "pricing",
                "benchmark",
                "market_rules",
                "execution_mode",
            ):
                assert request[field] == prior[field], (cid, field)
            assert request["initial_cash"] == 100000
            assert len(value["runs"]) == 1
            run = value["runs"][0]
            oldrun = next(r for r in old["runs"] if r["window_id"] == "full")
            assert run["window_id"] == "full" and run["scenario_id"] == "fee_x2"
            assert run["identity"]["candidate"] == oldrun["identity"]["candidate"]
            assert run["identity"]["content_sha256"] == oldrun["identity"]["content_sha256"]
            assert run["signal_support"]["evaluation_fee_rate"] == 0.002
            for field in ("input_binding", "execution_input_identities"):
                assert run["signal_support"][field] == oldrun["signal_support"][field], (cid, field)
            assert run["signals"] == oldrun["signals"], (cid, "signal sequence changed")
            daily, trades = (frame(run["ledgers"][n]) for n in ("account_daily", "trades"))
            eq = np.r_[100000.0, daily.equity.to_numpy(float)]
            closed = trades[trades.status.eq("CLOSED")]
            days = daily.date.map(day)
            frequencies = (
                closed.exit_date.map(day)
                .value_counts()
                .reindex(days, fill_value=0)
                .rolling(60)
                .sum()
                .dropna()
            )
            summary = {
                "net_return": float(eq[-1] / eq[0] - 1),
                "dd": float(np.max(1 - eq / np.maximum.accumulate(eq))),
                "closed": len(closed),
                "frequency_median": float(frequencies.median()),
                "frequency_good": int((frequencies >= 3).sum()),
            }
            diagnosis = diagnose_accounts(
                repository,
                AccountDiagnosisRequest(AccountRunRef(ref, identity(run)), None, WINDOWS["full"]),
            )
            assert diagnosis.status.value not in ("INVALID_EVIDENCE", "INCOMPARABLE")
            accounting = describe(run, summary)
            bhfills = frame(run["buyhold"]["fills"])
            close(bhfills.fees, bhfills.quantity * bhfills.price * 0.002)
            bheq = np.r_[100000.0, frame(run["buyhold"]["account_daily"]).equity.to_numpy(float)]
            bhdd = float(np.max(1 - bheq / np.maximum.accumulate(bheq)))
            cagr = float((eq[-1] / eq[0]) ** (252 / 434) - 1)
            bhcagr = float((bheq[-1] / bheq[0]) ** (252 / 434) - 1)
            report["accounts"].append(
                {
                    "candidate_id": cid,
                    "evidence": ref.to_dict(),
                    "standard_evidence": oldref.to_dict(),
                    "identity_unchanged": True,
                    "full_window_signals_unchanged": True,
                    "public_diagnosis": diagnosis.to_dict(),
                    "accounting_description": accounting,
                    "stress_comparison": {
                        "cagr": cagr,
                        "buyhold_cagr": bhcagr,
                        "buyhold_dd": bhdd,
                        "positive_cagr": cagr > 0,
                        "beats_buyhold_cagr": cagr > bhcagr,
                        "beats_buyhold_dd": summary["dd"] < bhdd,
                        "dd_at_most_25pct": summary["dd"] <= 0.25,
                    },
                }
            )
            authenticated[cid] = value
            print("AUDITED", cid, flush=True)
        serial = read(here / "others/serial_fee_x2.json")
        sref, technical = evidence(serial["evidence"])
        cid = technical["runs"][0]["identity"]["candidate"]["candidate_id"]
        formal = authenticated[cid]
        assert technical["result_hash"] == formal["result_hash"] == serial["result_hash"]
        assert technical["request_hash"] == formal["request_hash"]
        assert technical["runs"] == formal["runs"]
        report["technical_accounts"].append(
            {
                "candidate_id": cid,
                "evidence": sref.to_dict(),
                "public_authentication": "PASS",
                "formal_result_and_all_ledgers_equal": True,
            }
        )
        report["status"] = "ARITHMETIC_CHECKS_PASS"
        report["official_diagnosis_statuses"] = sorted(
            {x["public_diagnosis"]["status"] for x in report["accounts"]}
        )
        report["formal_accounts"] = len(report["accounts"])
        report["new_accounts_created_by_audit"] = 0
    except Exception as exc:
        report["status"] = "BLOCKED"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(report["status"], output.relative_to(ROOT), flush=True)


if __name__ == "__main__":
    main()
