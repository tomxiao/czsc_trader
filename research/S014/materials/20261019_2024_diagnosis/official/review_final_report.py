"""Final narrative/data/reference review; never dispatches, fetches, or replays policies."""

from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import re

import pandas as pd

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
COUNTS = Counter()
REFS = set()


def check(name, condition):
    if not bool(condition):
        raise AssertionError(name)
    COUNTS[name] += 1


def read(path):
    REFS.add(path)
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def numeric(actual, expected):
    check(
        "published numerical agreement",
        math.isclose(float(actual), float(expected), rel_tol=1e-13, abs_tol=1e-13),
    )


def row_match(actual, expected):
    for key, value in expected.items():
        check("matching row key", key in actual)
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            numeric(actual[key], value)
        else:
            check("matching text boolean", actual[key] == value)


def main():
    destination = BASE / "final_report_review.json"
    if destination.exists():
        raise FileExistsError(destination)
    report_path, judgment_path = BASE / "report.md", BASE / "judgment.json"
    report_hash, judgment_hash = digest(report_path), digest(judgment_path)
    REFS.add(report_path)
    report = report_path.read_text(encoding="utf-8")
    judgment = read(judgment_path)
    check(
        "precise baseline population wording",
        "旧基线2020—2025实际持仓观察中，被浮盈门排除的状态只有3个D、2个持仓周期" in report,
    )
    links = []
    for value in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", report):
        check("all report links relative", not value.startswith(("/", "http", "file:", "D:")))
        path = (BASE / value.split("#")[0]).resolve()
        check("report link resolves in repository", path.is_relative_to(ROOT))
        check("all report links exist", path.is_file())
        REFS.add(path)
        links.append(dict(href=value, path=path.relative_to(ROOT).as_posix()))
    summaries = []
    for name in ["independent_ex044_audit_summary.json", "independent_clock_audit_summary.json"]:
        summary = read(BASE / "accounting" / name)
        check("both independent consolidated PASS", summary["status"].startswith("PASS"))
        for entry in summary["account_reports"]:
            path = ROOT / entry["path"]
            check("account audit immutable hash", digest(path) == entry["sha256"])
            audit = read(path)
            check("all seven account independent PASS", audit["status"] == "PASS")
        for entry in summary["outputs"].values():
            path = ROOT / entry["path"]
            check("audited output immutable hash", digest(path) == entry["sha256"])
            REFS.add(path)
            check("audited output row count", len(pd.read_csv(path)) == entry["rows"])
        summaries.append(summary)
    check(
        "full independent check count",
        summaries[0]["total_independent_account_checks"] == 815749
        and summaries[1]["total_independent_account_checks"] == 443129,
    )
    cum = summaries[1]["cumulative_EX044_EX045_resources"]
    check(
        "seven actual successes five unique economic paths",
        cum["actual_dispatches"] == 7
        and cum["status_counts"] == {"SUCCEEDED": 7}
        and cum["unique_economic_paths"] == 5
        and cum["unique_funded_wealth_paths"] == 5,
    )
    accounting = BASE / "accounting"
    annual = pd.read_csv(accounting / "policy_yearly_summary.csv")
    clock_annual = pd.read_csv(accounting / "clock_policy_yearly_summary.csv")
    summary = pd.read_csv(accounting / "policy_summary.csv")
    clock_summary = pd.read_csv(accounting / "clock_policy_summary.csv")
    check(
        "fixed five and two row counts",
        len(annual) == 30
        and len(clock_annual) == 12
        and len(summary) == 5
        and len(clock_summary) == 2,
    )
    for row in judgment["all_policy_summary"] + judgment["clock_summary"]:
        frame = clock_summary if "clock_profile" in row else summary
        found = frame.loc[frame.policy_id == row["policy_id"]].to_dict("records")
        check("judgment unique summary policy", len(found) == 1)
        row_match(row, found[0])
    check(
        "judgment all five plus two fixed profiles",
        len(judgment["all_policy_summary"]) == 5 and len(judgment["clock_summary"]) == 2,
    )
    for rows, frame in [
        (judgment["primary_policy_years"], annual),
        (judgment["clock_years"], clock_annual),
    ]:
        for row in rows:
            found = frame.loc[
                (frame.policy_id == row["policy_id"]) & (frame.year == row["year"])
            ].to_dict("records")
            check("judgment unique policy year", len(found) == 1)
            row_match(row, found[0])
    for frame in [annual, clock_annual]:
        for row in frame.to_dict("records"):
            bh = row["buyhold_return"]
            required = 1.5 * bh if bh > 0 else 0.0
            numeric(row["required_return"], required)
            check(
                "original annual return goal exact",
                row["return_pass"] == (row["return"] >= required if bh > 0 else row["return"] > 0),
            )
            check(
                "original annual DD goal exact",
                row["drawdown_pass"] == (row["max_drawdown"] < row["buyhold_drawdown"]),
            )
    labels = [
        ("上一轮固定组合", "BASE/POSITIVE_P/BASE"),
        ("急涨禁买：每天重试", "BLOCK_SHOCK/POSITIVE_P/BASE"),
        ("急涨退出不限浮盈", "BASE/ANY_P/BASE"),
        ("急涨禁买＋退出扩域", "BLOCK_SHOCK/ANY_P/BASE"),
        ("另加成本锚退出", "BASE/POSITIVE_P/NET_LOSS_1ATR"),
    ]
    for label, policy in labels:
        values = annual.loc[annual.policy_id == policy].sort_values("year")
        expected = (
            "| " + label + " | " + " | ".join(f"{100 * v:+.2f}%" for v in values["return"]) + " |"
        )
        check("report five policy annual table rounded exact", expected in report)
    for label, policy in [
        ("每天重新尝试", "RETRY_EACH_D"),
        ("跳过本轮计划机会", "KEEP_PLANNED_SLOT"),
    ]:
        values = clock_annual.loc[clock_annual.policy_id == policy].sort_values("year")
        expected = (
            "| " + label + " | " + " | ".join(f"{100 * v:+.2f}%" for v in values["return"]) + " |"
        )
        check("report clock annual table rounded exact", expected in report)
    facts = read(accounting / "diagnosis_findings.json")
    f = facts["2024_frozen"]
    for key, text in [
        ("entry_day_mark_pnl_pp", "−14.3647"),
        ("continued_holding_mark_pnl_pp", "−2.4708"),
        ("exit_to_actual_fill_pnl_pp", "−0.2444"),
        ("actual_fees_pp", "−4.0774"),
    ]:
        check(
            "phase table rounding exact",
            text in report and abs(abs(float(text.replace("−", "-"))) - abs(f[key])) < 0.00005,
        )
    check(
        "phase actual annual reconciles",
        abs(
            f["entry_day_mark_pnl_pp"]
            + f["continued_holding_mark_pnl_pp"]
            + f["exit_to_actual_fill_pnl_pp"]
            - f["actual_fees_pp"]
            - f["annual_return"] * 100
        )
        < 1e-10,
    )
    check(
        "cycle counts concentration exact",
        f["negative_calendar_cycle_contributors"] == 14
        and f["positive_calendar_cycle_contributors"] == 8
        and f"{100 * f['top2_loss_share_of_all_negative_contributions']:.2f}%" in report
        and f"{100 * f['top5_loss_share_of_all_negative_contributions']:.2f}%" in report,
    )
    for name in [
        "interpretation_results.json",
        "interpretation_adversarial_notes.json",
        "clock_interpretation_results.json",
        "clock_interpretation_notes.json",
        "clock_numeric_boundary_review.json",
        "source_state_review.json",
        "clock_source_state_review.json",
    ]:
        receipt = read(HERE / name)
        for path, expected in receipt["reviewed_hashes"].items():
            check("official interpretation source hash exact", digest(ROOT / path) == expected)
            REFS.add(ROOT / path)
    # Figure is visually reviewed separately. Check the two source bridges, not new rendering.
    year_bridge = pd.read_csv(accounting / "policy_year_accounting_bridge.csv")
    quarter_bridge = pd.read_csv(accounting / "policy_quarter_accounting_bridge.csv")
    for policy in ["BASE/BASE", "ENTRY_GRACE/SHOCK_PROFIT"]:
        row = year_bridge.loc[(year_bridge.policy_id == policy) & (year_bridge.year == 2024)].iloc[
            0
        ]
        values = [
            row.entry_day_mark_pnl,
            row.continued_holding_mark_pnl,
            row.exit_to_actual_fill_pnl,
            -row.actual_fees,
        ]
        numeric(sum(values) / row.opening_equity * 100, row.net_annual_contribution_pp)
        q = quarter_bridge.loc[
            (quarter_bridge.policy_id == policy) & quarter_bridge.quarter.str.startswith("2024")
        ]
        check(
            "figure four chronological quarters",
            list(q.quarter) == [f"2024Q{i}" for i in range(1, 5)],
        )
        numeric(q.net_annual_contribution_pp.sum(), row.net_annual_contribution_pp)
    for p in [
        accounting / "policy_year_accounting_bridge.csv",
        accounting / "policy_quarter_accounting_bridge.csv",
        BASE / "plot_diagnosis.py",
        BASE / "2024_accounting_bridge.png",
        BASE / "baseline_integrity.json",
        BASE / "design_decision.json",
        BASE / "clock_followup_design.json",
        accounting / "clock_limit_boundary_investigation.json",
        accounting / "clock_account_001_independent_failure.json",
    ]:
        check("critical figure design failure evidence exists", p.is_file())
        REFS.add(p)
    for experiment, source_name, source_hash in [
        (
            "EX044_20261019",
            "action_role_review.py",
            "e176e01873d67fff2c869915373f36b35f1f507524a5583c49b138b3c146b527",
        ),
        (
            "EX045_20261019",
            "blocked_clock_review.py",
            "07088482b6a183e8315f9fc23c3eaeee44dbe840aa598f86f89201d59e925b68",
        ),
    ]:
        folder = ROOT / "research/S014/experiments" / experiment
        source = folder / "src/strategy_runtime/strategies" / source_name
        check("final strategies frozen reviewed bytes", digest(source) == source_hash)
        REFS.add(source)
        for p in [
            folder / "protocols/execution_lock.json",
            folder / "protocols/published_lock.json",
            folder / "others/accounts_index.json",
        ]:
            check("final source locks and account index exist", p.is_file())
            REFS.add(p)
    check(
        "original strategy acceptance untouched",
        judgment["stage_advance"] is False
        and judgment["new_registered_candidates"] == 0
        and judgment["new_qualified_candidates"] == 0
        and judgment["original_goals_and_historical_candidate_eligibility"] == "UNCHANGED",
    )
    check(
        "resources exact seven no account failure retry",
        judgment["actual_resources"]
        == dict(
            diagnostic_account_dispatches=7,
            succeeded=7,
            failed=0,
            unknown=0,
            cancelled=0,
            retries=0,
            new_fits=0,
            threshold_searches=0,
            new_market_vendor_calls=0,
        ),
    )
    check(
        "final report stable during review",
        digest(report_path) == report_hash and digest(judgment_path) == judgment_hash,
    )
    REFS.add(Path(__file__))
    result = dict(
        status="PASS",
        blocking_findings=[],
        wording_findings=[],
        reviewed_hashes={p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(REFS)},
        checks=sum(COUNTS.values()),
        check_counts=dict(COUNTS),
        relative_links=links,
        figure_review=dict(
            file="2024_accounting_bridge.png",
            visual_inspection="PASS: readable Chinese labels, visible bars/negative fees and annual-contribution denominators; no clipping or unsupported economic outcomes",
            source_bridges_reconciled=True,
        ),
        interpretive_review=dict(
            partial_cost_improvement=True,
            no_all_goal_strategy=True,
            cross_year_counterexamples_retained=True,
            no_2026_economic_selection=True,
            zero_2025_gate_vetoes_explained_as_path_dependence=True,
            clock_not_linear_causal_share=True,
            slot_not_actual_cycle=True,
            helper_failure_preserved_separate_from_account_failures=True,
            known_development_not_untouched_validation=True,
        ),
        publication_readiness="Content PASS. Root publisher must generate/verify local publication manifest and final public EX045 refs before delivery; those downstream artifacts are intentionally outside this content review cycle.",
        pre_delivery_conditions=[
            "PREDELIVERY_PUBLICATION_REQUIRED: generate and authenticate publication.json against these reviewed report/judgment bytes",
            "PREDELIVERY_EX045_FINAL_REFERENCE_REQUIRED: publisher validates public final refs and closed evidence inventory",
        ],
        review_scope="Only saved S014 evidence/data derivatives, existing source/locks and final report. No account reruns, policy changes, market queries, new labels/fits or broad regression.",
    )
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            dict(
                status=result["status"],
                checks=result["checks"],
                files=len(REFS),
                links=len(links),
                report_sha256=report_hash,
                judgment_sha256=judgment_hash,
                review_sha256=digest(destination),
            )
        )
    )


if __name__ == "__main__":
    main()
