"""Read completed published batches; never turn partial quantiles into full statistics."""
from decimal import Decimal
import json
from pathlib import Path


WORK = Path(__file__).resolve().parents[1]
COUNTS = {"C0338": 485, "C0339": 323, "C0340": 485, "C0341": 485, "C0342": 323, "C0352": 728}


def status():
    points = {key: {} for key in COUNTS}
    for path in sorted((WORK / "others/neighborhood_batches").glob("*.json")):
        record = json.loads(path.read_bytes())
        if record["status"] != "COMPLETED":
            continue
        key = record["center"]
        for row in record["records"]:
            assert row["index"] not in points[key], "duplicate point evidence"
            assert 0 <= row["index"] < COUNTS[key]
            candidate, benchmark = row["candidate_metrics"], row["benchmark_metrics"]
            bound = float(Decimal(str(benchmark["annualized_return"])) * Decimal("1.25"))
            joint = candidate["annualized_return"] >= bound if benchmark["annualized_return"] > 0 else candidate["annualized_return"] > 0
            joint = joint and candidate["drawdown"] <= float(Decimal(str(benchmark["drawdown"])) * Decimal("0.9"))
            assert joint == row["joint_pass"]
            assert (candidate["drawdown"] <= .25) == row["all_point_dd_pass"]
            points[key][row["index"]] = row
    result = {}
    for key, count in COUNTS.items():
        values = tuple(points[key].values())
        joint_pass = sum(row["joint_pass"] for row in values)
        failures = len(values) - joint_pass
        minimum = (count * 13 + 15) // 16
        risk_failures = [row["index"] for row in values if not row["all_point_dd_pass"]]
        result[key] = {"N": count, "completed": len(values), "joint_passes_observed": joint_pass,
            "joint_minimum": minimum, "maximum_possible_joint_passes": count - failures,
            "joint_gate_failure_proven": count - failures < minimum,
            "all_point_dd_failures": risk_failures,
            "observed_max_dd": max((row["candidate_metrics"]["drawdown"] for row in values), default=None),
            "full_neighborhood_quantiles_available": len(values) == count}
    return {"completed_points": sum(len(value) for value in points.values()), "total_points": 2829,
            "centers": result}


if __name__ == "__main__":
    print(json.dumps(status(), ensure_ascii=False, separators=(",", ":")))
