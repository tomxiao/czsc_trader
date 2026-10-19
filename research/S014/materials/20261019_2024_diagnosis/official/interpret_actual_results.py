"""Read all five audited public accounts together; descriptive interpretation only."""

from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path

import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
ACCOUNTING = HERE.parent / "accounting"
CHECKS = Counter()


def check(name, condition):
    if not bool(condition):
        raise AssertionError(name)
    CHECKS[name] += 1


def read(path):
    return json.loads(path.read_bytes())


def date(value):
    return str(value)[:10]


def audit_ref(record):
    ref = EvidenceRef.from_dict(record["account_ref"])
    check(
        "S014 EX044 public account only",
        ref.experiment.strategy_id == "S014" and ref.experiment.experiment_id == "EX044_20261019",
    )
    content = ref.resolve(ROOT).read_bytes()
    check("account bytes authenticated", sha256(content).hexdigest() == ref.sha256)
    account = json.loads(content)
    return {key: value["data"] for key, value in account["runs"][0]["ledgers"].items()}


def economic_projection(ledger):
    daily = [
        {k: r[k] for k in ["date", "cash", "quantity", "close", "equity"]}
        for r in ledger["account_daily"]
        if date(r["date"]) <= "2025-12-31"
    ]
    fills = [
        {k: r[k] for k in ["fill_time", "side", "price", "quantity", "fees"]}
        for r in ledger["fills"]
        if date(r["fill_time"]) <= "2025-12-31"
    ]
    return daily, fills


def main():
    destination = HERE / "interpretation_results.json"
    if destination.exists():
        raise FileExistsError(destination)
    paths = [ACCOUNTING / f"account_{i:03d}_independent_review.json" for i in range(5)]
    records = [read(p) for p in paths]
    check(
        "all five audited PASS before economic interpretation",
        len(records) == 5 and all(r["status"] == "PASS" for r in records),
    )
    yearly_path = ACCOUNTING / "policy_yearly_summary.csv"
    summary_path = ACCOUNTING / "policy_summary.csv"
    yearly = pd.read_csv(yearly_path)
    summary = pd.read_csv(summary_path)
    check(
        "all thirty annual rows and five policies",
        len(yearly) == 30 and len(summary) == 5 and set(yearly.year) == set(range(2020, 2026)),
    )
    ledgers = [audit_ref(r) for r in records]
    annual = {}
    for i, r in enumerate(records):
        check(
            "complete economic years only",
            [a["year"] for a in r["original_annual_goal_audit"] if not a["technical_only"]]
            == list(range(2020, 2026)),
        )
        rows = []
        for a in r["original_annual_goal_audit"]:
            if a["technical_only"]:
                continue
            selected = yearly.loc[(yearly.policy_id == r["policy_id"]) & (yearly.year == a["year"])]
            check("one CSV audited policy year", len(selected) == 1)
            selected = selected.iloc[0]
            for key in [
                "opening_equity",
                "closing_equity",
                "return",
                "max_drawdown",
                "required_return",
                "return_difference_vs_frozen",
                "return_difference_vs_original",
            ]:
                check(
                    "CSV exact audited numeric",
                    math.isclose(float(selected[key]), a[key], rel_tol=1e-14, abs_tol=1e-13),
                )
            rows.append(
                dict(
                    a,
                    pnl=a["closing_equity"] - a["opening_equity"],
                    return_margin_to_original_goal_pp=100 * (a["return"] - a["required_return"]),
                )
            )
        annual[str(i)] = rows
    original_path = (
        ROOT
        / "research/S014/materials/20261019_exante_hold_exit/accounting/account_000_independent_review.json"
    )
    original = read(original_path)
    check("prior original audit PASS", original["status"] == "PASS")
    wealth = {}
    for i, r in enumerate(records):
        s = r["summary"]
        wealth[str(i)] = dict(s)
        wealth[str(i)]["end2024_difference_vs_frozen"] = (
            s["development_without2025_end2024_equity"]
            - records[0]["summary"]["development_without2025_end2024_equity"]
        )
        wealth[str(i)]["end2024_difference_vs_original"] = (
            s["development_without2025_end2024_equity"]
            - original["summary"]["development_without2025_end2024_equity"]
        )
        wealth[str(i)]["end2025_difference_vs_frozen"] = (
            s["terminal2025_equity"] - records[0]["summary"]["terminal2025_equity"]
        )
    equivalence = []
    for i in range(5):
        for j in range(i + 1, 5):
            a, b = economic_projection(ledgers[i]), economic_projection(ledgers[j])
            equivalence.append(
                dict(
                    policies=[i, j],
                    daily_wealth_position_cash_exact=a[0] == b[0],
                    actual_fill_economics_exact=a[1] == b[1],
                    scope="2020-25 only",
                )
            )
    interaction = {
        "definition": "endpoint3-endpoint1-endpoint2+endpoint0; descriptive joint path, not causal effect or additive rule expectation",
        "end2025_currency": records[3]["summary"]["terminal2025_equity"]
        - records[1]["summary"]["terminal2025_equity"]
        - records[2]["summary"]["terminal2025_equity"]
        + records[0]["summary"]["terminal2025_equity"],
        "annual_own_opening_pp": {
            str(y): 100
            * (
                annual["3"][y - 2020]["return"]
                - annual["1"][y - 2020]["return"]
                - annual["2"][y - 2020]["return"]
                + annual["0"][y - 2020]["return"]
            )
            for y in range(2020, 2026)
        },
    }
    lifecycle = {
        str(i): {
            "annual_D_counts": r["lifecycle"]["annual_D_counts"],
            "annual_distinct_held_cycles": r["lifecycle"]["annual_distinct_held_cycles"],
        }
        for i, r in enumerate(records)
    }
    cost_decisions = [
        d for d in ledgers[4]["decisions"] if "2020-01-01" <= date(d["signal_date"]) <= "2025-12-31"
    ]
    shrink, cost_selected = [], []
    previous = None
    for d in cost_decisions:
        if d["selected_cost_exit"]:
            row = {
                k: d[k]
                for k in [
                    "signal_date",
                    "valid_session",
                    "entry_index",
                    "holding_age",
                    "net_profit",
                    "cost_loss_price",
                    "cost_loss_atr",
                    "atr20_prior",
                    "ordinary_support_exit",
                    "original_support_exit",
                    "selected_profit_exit",
                    "cost_exit_added_vs_baseline",
                    "cost_grace_override",
                ]
            }
            cost_selected.append(row)
            if (
                previous
                and previous["held_at_close"]
                and previous["profit_exit_eligible"]
                and d["entry_index"] == previous["entry_index"]
                and not previous["selected_cost_exit"]
            ):
                no_new_decline = d["cost_loss_price"] <= previous["cost_loss_price"]
                atr_smaller = d["atr20_prior"] < previous["atr20_prior"]
                fails_previous_scale = d["cost_loss_price"] < previous["atr20_prior"]
                if no_new_decline and atr_smaller and fails_previous_scale:
                    shrink.append(
                        dict(
                            row,
                            previous_D=date(previous["signal_date"]),
                            previous_atr=previous["atr20_prior"],
                            previous_cost_loss_price=previous["cost_loss_price"],
                            definition="same actual cycle, prior eligible but cost false; current close not lower, current ATR lower and current loss below previous ATR",
                        )
                    )
        previous = d
    examples = {}
    fixed_days = {
        "2024-01-29",
        "2024-01-30",
        "2024-10-08",
        "2024-10-09",
        "2024-10-10",
        "2024-10-11",
        "2025-05-30",
        "2025-06-19",
    }
    for i, ledger in enumerate(ledgers):
        decisions = []
        for d in ledger["decisions"]:
            if date(d["signal_date"]) in fixed_days:
                fields = [
                    "signal_date",
                    "valid_session",
                    "held_at_close",
                    "buy_filled_today",
                    "sell_filled_today",
                    "entry_signal",
                    "exit_pending",
                    "entry_index",
                    "reservation_index",
                    "support_break",
                    "entry_grace_applied",
                    "original_entry_candidate",
                    "entry_guard_blocked",
                    "z5",
                    "net_profit",
                    "cost_loss_atr",
                    "selected_shock_exit",
                    "selected_cost_exit",
                    "ordinary_support_exit",
                ]
                decisions.append({k: d[k] for k in fields})
        trades = [
            t
            for t in ledger["trades"]
            if date(t["entry_date"])[:7] in {"2024-01", "2024-10", "2025-06"}
        ]
        fills = [
            f
            for f in ledger["fills"]
            if date(f["fill_time"])[:7] in {"2024-01", "2024-10", "2025-06"}
        ]
        examples[str(i)] = dict(
            decisions=decisions,
            actual_trades=trades,
            actual_fills=fills,
            selection="Calendar Jan/Oct2024 and known May30/June19 questions requested before new results; explanatory actual paths, not new outcome labels",
        )
    refs = paths + [
        yearly_path,
        summary_path,
        original_path,
        Path(__file__),
        HERE / "source_state_review.json",
        HERE / "population_inventory.json",
        HERE.parent / "design_decision.json",
    ]
    result = dict(
        status="COMPLETE_ALL_FIVE_AUDITED_PATHS_DESCRIPTIVE_INTERPRETATION",
        all_five_pass=True,
        checks=sum(CHECKS.values()),
        check_counts=dict(CHECKS),
        reviewed_hashes={
            p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in refs
        },
        annual=annual,
        wealth=wealth,
        economic_path_equivalence=equivalence,
        factorial_interaction=interaction,
        lifecycle=lifecycle,
        cost_selected_D=cost_selected,
        cost_dynamic_ATR_shrink_without_new_decline=shrink,
        fixed_actual_path_examples=examples,
        limits=[
            "All2020-25 development histories and motivating cases seen; no untouched validation or new alpha discovery claim.",
            "Each yearly return uses its own policy continuous annual opening. Calendar comparisons include prior-year inventory/funding differences.",
            "Five fixed policies, repeated D and actual cycles are not independent statistical observations.",
            "ANY_P only removes the positive-P domain; old baseline excluded three D in two cycles, not broad new risk coverage.",
            "Cost-stop marked threshold cannot recover already incurred entry-day loss or guarantee nextE sale loss/price.",
            "Entry guard recomputes every eligible D and can reenter after Z falls; not a one-off skip nor permanent avoidance.",
            "Exact duplicated paths count once as economic evidence; joint interaction is descriptive.",
            "No2026 economic selection, raw market export, new accounts, labels, fits or external source.",
        ],
    )
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "checks": result["checks"],
                "result_sha256": sha256(destination.read_bytes()).hexdigest(),
                "cost_shrink_D_count": len(shrink),
                "wealth": wealth,
                "equivalence": equivalence,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
