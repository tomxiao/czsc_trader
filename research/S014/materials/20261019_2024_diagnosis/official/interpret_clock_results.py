"""Two audited clock paths, existing saved ledgers only; no replay or data calls."""

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
COUNTS = Counter()


def check(name, value):
    if not bool(value):
        raise AssertionError(name)
    COUNTS[name] += 1


def day(value):
    return str(value)[:10]


def read(path):
    return json.loads(path.read_bytes())


def main():
    destination = HERE / "clock_interpretation_results.json"
    if destination.exists():
        raise FileExistsError(destination)
    audits = [
        ACCOUNTING / "clock_account_000_independent_review.json",
        ACCOUNTING / "clock_account_001_independent_review_v2.json",
    ]
    reports = [read(p) for p in audits]
    check("both independent actual audits PASS", all(r["status"] == "PASS" for r in reports))
    yearly_path = ACCOUNTING / "clock_policy_yearly_summary.csv"
    summary_path = ACCOUNTING / "clock_policy_summary.csv"
    yearly, summary = pd.read_csv(yearly_path), pd.read_csv(summary_path)
    check(
        "twelve annual two summary rows",
        len(yearly) == 12 and len(summary) == 2 and set(yearly.year) == set(range(2020, 2026)),
    )
    ledgers = []
    for r in reports:
        ref = EvidenceRef.from_dict(r["account_ref"])
        check(
            "S014 EX045 reference",
            ref.experiment.strategy_id == "S014"
            and ref.experiment.experiment_id == "EX045_20261019",
        )
        content = ref.resolve(ROOT).read_bytes()
        check("public account bytehash", sha256(content).hexdigest() == ref.sha256)
        ledgers.append({k: v["data"] for k, v in json.loads(content)["runs"][0]["ledgers"].items()})
    annual = {}
    for r in reports:
        profile = r["parameters"]["clock_profile"]
        rows = []
        for a in r["original_annual_goal_audit"]:
            if a["technical_only"]:
                continue
            match = yearly.loc[(yearly.clock_profile == profile) & (yearly.year == a["year"])]
            check("unique clock annual row", len(match) == 1)
            for key in [
                "opening_equity",
                "closing_equity",
                "return",
                "max_drawdown",
                "required_return",
                "return_difference_vs_original",
                "return_difference_vs_frozen",
                "return_difference_vs_clock_control",
            ]:
                check(
                    "annual CSV audited numeric match",
                    math.isclose(float(match.iloc[0][key]), a[key], rel_tol=1e-14, abs_tol=1e-13),
                )
            rows.append(
                dict(
                    a,
                    pnl=a["closing_equity"] - a["opening_equity"],
                    return_margin_to_goal_pp=100 * (a["return"] - a["required_return"]),
                )
            )
        check(
            "only six complete economic years", [a["year"] for a in rows] == list(range(2020, 2026))
        )
        annual[profile] = rows
    ex044_path = ACCOUNTING / "account_000_independent_review.json"
    original_path = (
        ROOT
        / "research/S014/materials/20261019_exante_hold_exit/accounting/account_000_independent_review.json"
    )
    frozen, original = read(ex044_path), read(original_path)
    wealth = {}
    for r in reports:
        s = dict(r["summary"])
        s["end2024_difference_vs_clock_control"] = (
            s["development_without2025_end2024_equity"]
            - reports[0]["summary"]["development_without2025_end2024_equity"]
        )
        s["end2024_difference_vs_frozen"] = (
            s["development_without2025_end2024_equity"]
            - frozen["summary"]["development_without2025_end2024_equity"]
        )
        s["end2024_difference_vs_original"] = (
            s["development_without2025_end2024_equity"]
            - original["summary"]["development_without2025_end2024_equity"]
        )
        s["end2025_difference_vs_clock_control"] = (
            s["terminal2025_equity"] - reports[0]["summary"]["terminal2025_equity"]
        )
        s["end2025_difference_vs_frozen"] = (
            s["terminal2025_equity"] - frozen["summary"]["terminal2025_equity"]
        )
        wealth[r["parameters"]["clock_profile"]] = s
    state_first = target_first = wealth_first = None
    for left, right in zip(ledgers[0]["decisions"], ledgers[1]["decisions"]):
        check("common original D dates", left["signal_date"] == right["signal_date"])
        if day(left["signal_date"]) > "2025-12-31":
            continue
        if state_first is None and any(
            left[k] != right[k] for k in ["target_position", "reservation_index"]
        ):
            state_first = day(left["signal_date"])
        if target_first is None and left["target_position"] != right["target_position"]:
            target_first = day(left["signal_date"])
    for left, right in zip(ledgers[0]["account_daily"], ledgers[1]["account_daily"]):
        if (
            day(left["date"]) <= "2025-12-31"
            and wealth_first is None
            and any(left[k] != right[k] for k in ["cash", "quantity", "equity"])
        ):
            wealth_first = day(left["date"])
    observed = reports[1]["prefix"]
    check(
        "A first state divergence exact",
        day(observed["first_clock_state_divergence_D"]) == state_first,
    )
    check(
        "A first target divergence exact",
        day(observed["first_target_divergence_D"]) == target_first,
    )
    slots, examples = {}, {}
    for r, ledger in zip(reports, ledgers):
        profile = r["parameters"]["clock_profile"]
        index_dates = {
            int(d["warmup_sessions"]): day(d["signal_date"]) for d in ledger["decisions"]
        }
        dates = []
        for d in ledger["decisions"]:
            if day(d["signal_date"]) > "2025-12-31" or not d["entry_guard_blocked"]:
                continue
            rec = {
                k: d[k]
                for k in [
                    "signal_date",
                    "valid_session",
                    "z5",
                    "entry_guard_blocked",
                    "gate_slot_consumed",
                    "reservation_before_gate",
                    "reservation_index",
                    "planned_slot_until",
                    "held_at_close",
                    "entry_index",
                    "deadline_index",
                    "failed_buy_reset",
                ]
            }
            if d["gate_slot_consumed"]:
                rec["reservation_expiry_D"] = index_dates.get(int(d["reservation_index"]))
                rec["earliest_next_actual_buy_E"] = index_dates.get(int(d["reservation_index"]) + 1)
                check(
                    "real consumed slot no fake anchors",
                    d["held_at_close"] == 0
                    and d["entry_index"] == -1
                    and d["deadline_index"] == -1
                    and d["failed_buy_reset"] == 0,
                )
            dates.append(rec)
        slots[profile] = dates
        selected_days = {
            "2024-10-08",
            "2024-10-09",
            "2024-10-10",
            "2024-10-11",
            "2024-10-14",
            "2025-05-30",
            "2025-06-18",
            "2025-06-19",
            "2025-06-20",
            "2024-12-31",
        }
        examples[profile] = dict(
            decisions=[
                {
                    k: d[k]
                    for k in [
                        "signal_date",
                        "valid_session",
                        "held_at_close",
                        "buy_filled_today",
                        "sell_filled_today",
                        "entry_signal",
                        "entry_guard_blocked",
                        "gate_slot_consumed",
                        "reservation_index",
                        "planned_slot_until",
                        "exit_pending",
                        "net_profit",
                        "z5",
                    ]
                }
                for d in ledger["decisions"]
                if day(d["signal_date"]) in selected_days
            ],
            actual_trades=[
                t
                for t in ledger["trades"]
                if day(t["entry_date"])[:7] in {"2024-01", "2024-10", "2025-05", "2025-06"}
            ],
        )
    paths = audits + [
        yearly_path,
        summary_path,
        ex044_path,
        original_path,
        HERE / "clock_numeric_boundary_review.json",
        HERE / "clock_method_review.json",
        HERE / "clock_source_state_review.json",
        HERE.parent / "clock_followup_design.json",
        Path(__file__),
    ]
    result = dict(
        status="COMPLETE_TWO_AUDITED_CLOCK_PATHS_INTERPRETATION",
        checks=sum(COUNTS.values()),
        check_counts=dict(COUNTS),
        reviewed_hashes={
            p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in paths
        },
        annual=annual,
        wealth=wealth,
        first_differences=dict(
            state_D=state_first,
            target_D=target_first,
            actual_funded_state_E=wealth_first,
            interpretation="Do not use firsttarget as prefix anchor for old reservation fields. State divergence can precede target or economic divergence.",
        ),
        annual_D_counts={
            r["parameters"]["clock_profile"]: r["lifecycle"]["annual_D_counts"] for r in reports
        },
        annual_distinct_actual_cycles={
            r["parameters"]["clock_profile"]: r["lifecycle"]["annual_distinct_held_cycles"]
            for r in reports
        },
        actual_blocked_D=slots,
        fixed_actual_examples=examples,
        source_and_account_failures=dict(
            strategy_account_dispatches=7,
            strategy_account_successes=7,
            strategy_account_failures=0,
            helper_expression_failures_preserved=1,
            new_epsilon=0,
            account_replays_for_audit_fix=0,
        ),
        limits=[
            "Adaptive two-profile followup after seeing all EX044 outcomes; all2020-25 development, no untouched validation or new alpha proof.",
            "Reservation slot is a planned opportunity interval, not actual fill/held cycle. It may consume an opportunity whose BUY would fail and does not restore BASE schedule exactly.",
            "Annual own-opening returns include prior phase/reservation/funding; terminal difference cannot be linearly separated into signal and clock causal shares.",
            "Original annual return/drawdown/frequency goals unchanged; no2026 economic choice or new noharm/CI/count hard gate.",
            "Existing saved account/audit bytes only. No new policy runs, markets, fits, labels or raw market exports.",
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
                "sha256": sha256(destination.read_bytes()).hexdigest(),
                "first_differences": result["first_differences"],
                "slots": slots,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
