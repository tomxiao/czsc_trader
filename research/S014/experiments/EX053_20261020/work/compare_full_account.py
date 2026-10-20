"""Compare a public C9522 full result with immutable original C9521 evidence.

This reads already-produced results only. It never prepares data or runs accounts.
Every decision/trade linkage must preserve a bijection; identity strings naturally
change with the candidate, while all business columns are compared exactly.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
ORIGINAL = ROOT / "research/S014/assets/evidence/EX052_20261020/e5005956b926d2062a1a0d040e1387dd30f32e64692480e055597473f153d8e2.json"
ORIGINAL_SHA = "e5005956b926d2062a1a0d040e1387dd30f32e64692480e055597473f153d8e2"
IDENTITY_COLUMNS = {"decision_id", "cycle_id", "order_id", "fill_id", "trade_id"}


def compare(old, new, *, expected_candidate="C9522"):
    checks = []
    forward = {}
    reverse = {}

    def record_check(label, old_rows, new_rows):
        if len(old_rows) != len(new_rows):
            raise AssertionError(f"{label}: row count {len(old_rows)} != {len(new_rows)}")
        for index, (left, right) in enumerate(zip(old_rows, new_rows, strict=True)):
            if set(left) != set(right):
                raise AssertionError(f"{label}[{index}]: columns differ")
            for key in left:
                a, b = left[key], right[key]
                if key in IDENTITY_COLUMNS and a is not None and b is not None:
                    if not isinstance(a, str) or not isinstance(b, str):
                        raise AssertionError(f"{label}[{index}].{key}: invalid identity")
                    if forward.setdefault((key, a), b) != b or reverse.setdefault((key, b), a) != a:
                        raise AssertionError(f"{label}[{index}].{key}: linkage not bijective")
                elif a != b:
                    raise AssertionError(f"{label}[{index}].{key}: {a!r} != {b!r}")
        checks.append({"name": label, "rows": len(old_rows), "status": "EXACT"})

    old_runs, new_runs = old["runs"], new["runs"]
    if len(old_runs) != 1 or len(new_runs) != 1:
        raise AssertionError("Full equivalence requires exactly one run on each side")
    left, right = old_runs[0], new_runs[0]
    if left["candidate_id"] != "C9521" or right["candidate_id"] != expected_candidate:
        raise AssertionError("Unexpected candidate identity")
    for name in ("scenario_id", "window_id", "signal_window"):
        if left[name] != right[name]:
            raise AssertionError(f"{name}: request window differs")
    record_check("signals", left["signals"]["data"], right["signals"]["data"])
    if set(left["ledgers"]) != set(right["ledgers"]):
        raise AssertionError("Ledger set differs")
    for name in left["ledgers"]:
        record_check(f"ledger.{name}", left["ledgers"][name]["data"],
                     right["ledgers"][name]["data"])
    old_assess, new_assess = old["assessment_evidence"], new["assessment_evidence"]
    if len(old_assess) != 1 or len(new_assess) != 1:
        raise AssertionError("Exactly one assessment account is required")
    for name in ("initial_cash", "opening_cash", "opening_quantity", "frequency_window_days"):
        if old_assess[0][name] != new_assess[0][name]:
            raise AssertionError(f"Assessment initial execution conditions differ: {name}")
    for name in ("account", "fills", "closed_cycles"):
        record_check(f"assessment.{name}", old_assess[0][name], new_assess[0][name])
    observation_left = {k: v for k, v in left["observation"].items() if k != "candidate_id"}
    observation_right = {k: v for k, v in right["observation"].items() if k != "candidate_id"}
    record_check("observation", [observation_left], [observation_right])
    return {"status": "PASS_EXACT_BUSINESS_BEHAVIOR", "checks": checks,
            "identity_bijections": {name: sum(k[0] == name for k in forward)
                                    for name in sorted(IDENTITY_COLUMNS)},
            "comparison": "No float tolerance; all business fields exact; linked identity bijections."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("new_result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-candidate", choices=("C9522", "C9523"), default="C9522")
    args = parser.parse_args()
    original_bytes = ORIGINAL.read_bytes()
    if sha256(original_bytes).hexdigest() != ORIGINAL_SHA:
        raise AssertionError("Original C9521 immutable account identity mismatch")
    new_bytes = args.new_result.read_bytes()
    result = compare(json.loads(original_bytes), json.loads(new_bytes),
                     expected_candidate=args.expected_candidate)
    result.update({"original_sha256": ORIGINAL_SHA,
                   "new_result_sha256": sha256(new_bytes).hexdigest()})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "checks": len(result["checks"])}))


if __name__ == "__main__":
    main()
