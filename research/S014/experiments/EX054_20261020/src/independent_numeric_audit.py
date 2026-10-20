"""Read-only, independently implemented ledger arithmetic for EX054 selfchecks.

This script authenticates published EvidenceRef files, never evaluates accounts,
does not read other experiments, and does not generate candidate rankings.
"""
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import socket

from czsc_trader.research_tools import EvidenceRef


ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OTHER = EX / "others"


def no_network(*args, **kwargs):
    raise RuntimeError("EX054 numeric audit only reads published local evidence")


def read(path):
    return json.loads(path.read_bytes())


def account(reference):
    ref = EvidenceRef.from_dict(reference)
    assert ref.experiment.strategy_id == "S014"
    assert ref.experiment.experiment_id == EX.name
    assert ref.schema == "account_evaluation" and ref.schema_version == 7
    data = ref.resolve(ROOT).read_bytes()
    assert sha256(data).hexdigest() == ref.sha256
    payload = json.loads(data)
    assert payload["schema_version"] == 7
    assert len(payload["runs"]) == len(payload["assessment_evidence"]) == 1
    record = payload["assessment_evidence"][0]
    assert record["experiment_id"] == EX.name
    assert len(record["account"]) == len(record["benchmark_equity"]) == 1642
    assert record["account"][0]["session"] == "2020-01-02"
    assert record["account"][-1]["session"] == "2026-10-15"
    assert record["initial_cash"] == 100000.0
    return payload, record


def drawdown(values, opening):
    peak = opening
    maximum = 0.0
    for value in values:
        peak = max(peak, value)
        maximum = max(maximum, 1.0 - value / peak)
    return maximum


def year_rows(record, equity):
    grouped = defaultdict(list)
    for point, value in zip(record["account"], equity, strict=True):
        grouped[int(point["session"][:4])].append(value)
    rows = []
    opening = record["initial_cash"]
    for year, values in sorted(grouped.items()):
        rows.append({"year": year, "opening": opening, "ending": values[-1],
                     "return": values[-1] / opening - 1.0,
                     "drawdown": drawdown(values, opening), "sessions": len(values)})
        opening = values[-1]
    return rows


def summarize(reference):
    payload, record = account(reference)
    values = [p["equity"] for p in record["account"]]
    rows = year_rows(record, values)
    bh = year_rows(record, record["benchmark_equity"])
    for actual, benchmark in zip(rows, bh, strict=True):
        required = 1.5 * benchmark["return"] if benchmark["return"] > 0 else 0.0
        actual.update(benchmark_return=benchmark["return"],
                      benchmark_drawdown=benchmark["drawdown"], required_return=required,
                      return_pass=(actual["return"] >= required if benchmark["return"] > 0
                                   else actual["return"] > 0),
                      drawdown_pass=actual["drawdown"] < benchmark["drawdown"])
    closed = len(record["closed_cycles"])
    frequency = 60.0 * closed / len(values)
    return {
        "candidate": record["candidate"]["candidate_id"], "account": reference,
        "sessions": len(values), "initial_cash": record["initial_cash"],
        "ending_equity": values[-1], "cagr": (values[-1] / record["initial_cash"]) ** (252.0 / len(values)) - 1,
        "drawdown": drawdown(values, record["initial_cash"]),
        "closed_cycles": closed, "frequency_60_sessions": frequency,
        "frequency_pass": frequency >= 3.0, "annual_goals": rows,
        "original_targets_pass": all(y["return_pass"] and y["drawdown_pass"] for y in rows) and frequency >= 3.0,
        "request_sha256": payload["request_hash"], "result_sha256": payload["result_hash"],
    }


def quantile_linear(values, probability):
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    fraction = index - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def concentration(reference):
    payload, record = account(reference)
    closed = {row["cycle_id"] for row in record["closed_cycles"]}
    fills = payload["runs"][0]["ledgers"]["fills"]["data"]
    money = defaultdict(float)
    quantities = defaultdict(int)
    for fill in fills:
        if fill["cycle_id"] not in closed:
            continue
        direction = 1 if fill["side"] == "SELL" else -1
        money[fill["cycle_id"]] += direction * fill["price"] * fill["quantity"] - fill["fees"]
        quantities[fill["cycle_id"]] += direction * fill["quantity"]
    assert set(money) == closed and all(v == 0 for v in quantities.values())
    positive = sorted((value for value in money.values() if value > 0.0), reverse=True)
    positive_sum = math.fsum(positive)
    net_sum = math.fsum(money.values())
    # Final account is flat: closed-cycle cashflows must reconcile to account P&L.
    assert record["account"][-1]["quantity"] == 0
    assert math.isclose(net_sum, record["account"][-1]["equity"] - record["initial_cash"], rel_tol=0, abs_tol=1e-7)
    # SE _concentration selects ceil(10% of PROFITABLE closed cycles).
    # Keep the all-closed count solely as an explicitly separate diagnostic.
    top_count = math.ceil(len(positive) * .1)
    top = math.fsum(positive[:top_count])
    all_closed_count = math.ceil(len(money) * .1)
    return {"closed_cycles": len(money), "profitable_cycles": len(positive),
            "closed_net_profit": net_sum, "sum_positive_cycle_profit": positive_sum,
            "top_decile_count": top_count,
            "top_decile_rule": "SE PROFIT_CONCENTRATION: ceil(10% of profitable closed cycles), divide by sum of positive net cycle P&L",
            "top_decile_positive_profit_share": top / positive_sum,
            "largest_positive_profit_share": positive[0] / positive_sum,
            "top_three_positive_profit_share": math.fsum(positive[:3]) / positive_sum,
            "top_decile_share_of_net_account_profit": top / net_sum,
            "extra_all_closed_tenth_count": all_closed_count,
            "extra_all_closed_tenth_positive_profit_share": math.fsum(positive[:all_closed_count]) / positive_sum,
            "extra_all_closed_tenth_note": "Additional top-10-of-92 diagnostic only; not SE PROFIT_CONCENTRATION.",
            "largest_cycle_net_profit": positive[0],
            "top_three_net_profit": math.fsum(positive[:3]),
            "denominator_note": "Primary shares divide by sum of profitable closed-cycle net P&L; losses excluded from denominator."}


def main():
    socket.socket.connect = no_network
    socket.create_connection = no_network
    assert (OTHER / "point_31.json").is_file() and (OTHER / "stress.json").is_file()
    center = summarize(read(OTHER / "center_control.json")["account"])
    selected = []
    points = []
    for index in range(32):
        attempts = [(path, read(path)) for path in sorted(OTHER.glob(f"point_{index:02d}*.json"))]
        successes = [(path, outcome) for path, outcome in attempts if outcome["status"] == "SUCCEEDED"]
        assert len(successes) == 1, (index, [(p.name, o["status"]) for p, o in attempts])
        path, outcome = successes[0]
        assert outcome["index"] == index
        item = summarize(outcome["account"])
        item["point_index"] = index
        points.append(item)
        selected.append({"index": index, "selected_attempt": path.name,
                         "all_attempt_statuses": {p.name: o["status"] for p, o in attempts}})
    stress_receipt = read(OTHER / "stress.json")
    assert stress_receipt["status"] == "SUCCEEDED"
    stress = summarize(stress_receipt["account"])
    failures = Counter()
    for point in points:
        for year in point["annual_goals"]:
            if not year["return_pass"]:
                failures[f"{year['year']}_return"] += 1
            if not year["drawdown_pass"]:
                failures[f"{year['year']}_drawdown"] += 1
        if not point["frequency_pass"]:
            failures["frequency"] += 1
    result = {
        "status": "PASS_INDEPENDENT_NUMERIC_AUDIT", "experiment": EX.name,
        "audit_semantics_version": 2,
        "semantic_review": "Unpublished audit corrected to SE _concentration's profitable-cycle count (46 -> top5); top10-of92 retained only as extra diagnostic.",
        "scope": "Only EX054 authenticated local account evidence; no account execution or other experiment reads.",
        "metric_definitions": {"cagr": "(ending_equity/100000)^(252/1642)-1",
                               "drawdown": "maximum equity decline from running high, including opening 100000",
                               "annual": "opening equity is previous calendar-year last equity; first year 100000; partial 2026 not annualized",
                               "original_hard_gates": "BH-positive year return >= 1.5*BH; otherwise return>0; annual DD strictly < BH; 60*closed/1642>=3",
                               "diagnostics": "Perturbation quantiles/pass counts, concentration and doubled costs are report-only, not extra rejection rules."},
        "center": center, "perturbation_count": len(points),
        "linear_cagr_q10": quantile_linear([p["cagr"] for p in points], .1),
        "linear_drawdown_q90": quantile_linear([p["drawdown"] for p in points], .9),
        "perturbation_original_targets_pass_count": sum(p["original_targets_pass"] for p in points),
        "perturbation_failures_by_gate": dict(sorted(failures.items())),
        "selected_attempts": selected, "points": points, "stress": stress,
        "double_cost_cagr_decrease": center["cagr"] - stress["cagr"],
        "cost_stress_limitation": stress_receipt["limitation"],
        "center_profit_concentration": concentration(center["account"]),
        "rankings_computed": False, "account_evaluations": 0, "network_calls": 0,
    }
    output = OTHER / "independent_numeric_audit.json"
    # This audit remains an unpublished editable calculation. Version 2 fixes
    # the concentration denominator/count semantics before formal publication.
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("center", "points", "selected_attempts", "stress")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
