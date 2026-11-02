"""Geometry-only RSCH proposal; never replay, qualify, or rank an account."""
from collections import Counter
from hashlib import sha256
from itertools import combinations, product
import json
from math import prod
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
KEYS = ("C0338", "C0339", "C0340", "C0341", "C0342", "C0352")
NAMES = ("alpha", "initial_fraction", "accepted_fraction", "g_when_u", "g_when_other", "g_when_mf")


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def main():
    control = WORK / "others/neighborhood_execution_v2_control.json"
    assert read(control)["pause_requested"] is True
    protected = (control, WORK / "others/neighborhood_execution_v2.json",
                 WORK / "others/calmar_v2_targets.json", WORK / "protocols/confirmed_calmar_selfcheck_v2.json")
    protected_hashes = {path: digest(path) for path in protected}
    signs = tuple((*first, prod(first)) for first in product((-1, 1), repeat=5))
    assert len(set(signs)) == 32
    for count in range(1, 6):
        for columns in combinations(range(6), count):
            seen = Counter(tuple(row[i] for i in columns) for row in signs)
            assert len(seen) == 2**count and set(seen.values()) == {32 // 2**count}
    centers = {}
    for key in KEYS:
        plan_path = WORK / "others/parameter_plans" / (key + ".json")
        reference_path = WORK / "others/parameter_plans" / (key + "-reference.json")
        plan, reference = read(plan_path), read(reference_path)
        axes = plan["design"]["space"]["axes"]
        assert tuple(axis["name"] for axis in axes) == NAMES
        center = tuple(axis["center"] for axis in axes)
        lookup = {tuple(next(v["value"] for v in point["values"] if v["name"] == name)
                        for name in NAMES): point["index"] for point in plan["design"]["points"]}
        levels = [tuple(sorted({center[i], *(values[i] for values in lookup)})) for i in range(6)]
        assert all(len(items) in (2, 3) for items in levels)
        axial = []
        for i in range(6):
            for value in levels[i]:
                if value != center[i]:
                    point = list(center)
                    point[i] = value
                    axial.append(tuple(point))
        joint = [tuple(levels[i][0 if sign == -1 else -1] for i, sign in enumerate(row)) for row in signs]
        points = (*axial, *joint)
        assert len(set(points)) == len(points) and all(point in lookup and point != center for point in points)
        n = len(points)
        centers[key] = {"center": dict(zip(NAMES, center, strict=True)),
            "legal_axis_values": dict(zip(NAMES, levels, strict=True)),
            "source_full_plan_sha256": digest(plan_path), "source_full_plan_reference": reference["reference"],
            "source_full_design_sha256": reference["design_sha256"], "source_full_N": reference["N"],
            "axial_count": len(axial), "joint_count": len(joint), "proposed_N": n,
            "proposed_required_joint_passes": (13 * n + 15) // 16,
            "proposed_points": [{"proposal_index": index, "kind": "AXIAL" if index < len(axial) else "JOINT_HALF_FRACTION",
                "source_full_plan_point_index": lookup[point], "values": dict(zip(NAMES, point, strict=True))}
                for index, point in enumerate(points)]}
    assert sum(item["axial_count"] for item in centers.values()) == 65
    assert sum(item["joint_count"] for item in centers.values()) == 192
    assert sum(item["proposed_N"] for item in centers.values()) == 257
    # Selection is now complete. Only then inspect source availability; metrics
    # never select points, levels, signs, thresholds, or the fraction orientation.
    available = {}
    batch_hashes = {}
    for folder in ("neighborhood_batches", "neighborhood_batches_v2"):
        for path in sorted((WORK / "others" / folder).glob("*.json")):
            batch = read(path)
            if batch["status"] == "PREPARATION_TYPE_COMPARISON_FAILED_ZERO_ACCOUNTS":
                continue
            assert batch["status"] == "COMPLETED"
            batch_hashes[path.relative_to(ROOT).as_posix()] = digest(path)
            for row in batch["records"]:
                coordinate = batch["center"], row["index"]
                assert coordinate not in available
                available[coordinate] = {name: row[name] for name in (
                    "candidate", "identity", "evidence", "evaluation_id", "request_hash", "parameter_binding")}
    assert len(available) == 444
    for key, item in centers.items():
        for point in item["proposed_points"]:
            source = available.get((key, point["source_full_plan_point_index"]))
            point["existing_completed_source"] = source
            point["source_status"] = "PUBLISHED_BATCH_COMPLETE_REQUIRES_IDENTITY_VERIFICATION" if source else "NO_COMPLETED_BATCH_SOURCE"
        item["existing_completed_points"] = sum(point["existing_completed_source"] is not None for point in item["proposed_points"])
        item["additional_replay_upper_bound"] = item["proposed_N"] - item["existing_completed_points"]
    replay_upper = sum(item["additional_replay_upper_bound"] for item in centers.values())
    per_point = sum(read(ROOT / path)["elapsed_seconds"] for path in batch_hashes
                    if "/neighborhood_batches_v2/" in path) / 192
    proposal = {"schema": "s017-bounded-parameter-check-proposal/v1",
        "status": "RSCH_PROPOSAL_NOT_APPROVED_NOT_EXECUTED", "execution_stays_paused": True,
        "construction": {"axis_order": NAMES, "joint_generator": "F=A*B*C*D*E; A..E enumerate (-1,+1)^5",
            "orientation": "+1 fixed independently of performance and existing-account availability",
            "levels": "existing legal min/max for joint rows; every legal noncenter axis value for axial rows",
            "boundary_handling": "keep legal center endpoint where only one perturbation direction exists; never clip an illegal value",
            "joint_each_factor_low_high_counts": [16, 16], "joint_each_pair_four_combination_counts": [8, 8, 8, 8],
            "point_weights": "all axial and joint points jointly form one equally weighted declared test set",
            "selection_uses_performance": False, "selection_uses_source_availability": False},
        "proposed_total_points": 257, "existing_completed_sources": 257 - replay_upper,
        "additional_replay_upper_bound": replay_upper,
        "unchanged_numeric_rules": {"minimum_joint_passes": "ceil(13*N/16) over the proposed complete point set",
            "joint_calmar": ">= 1.25 times same-contract benchmark", "joint_dd": "<= .9 times benchmark",
            "every_test_point_dd": "<= .25", "independent_annual_return_gate": False},
        "ranking": "same v6 order, but parameter Q10/Q90 describe this new selected test set, not the old full Cartesian neighborhood",
        "sample_roles": "2024-2025 development evidence reused after prior results; no new independent validation",
        "limits": ["only half of the 64 corner combinations", "most mixed center/endpoint combinations untested",
            "no guarantee over the continuous parameter region or higher-order interactions",
            "all previously observed adverse evidence remains contrary evidence; no retroactive old-protocol PASS"],
        "evidence_semantics": "preserve every source account and original full-plan point binding; new explicit selection mapping must not relabel original evidence",
        "budget_estimate": {"source_point_count": 192, "observed_full_flow_seconds_per_point": per_point,
            "parallel_batch_cap_if_later_authorized": 12,
            "new_replay_nominal_minutes_at_previous_rate": replay_upper * per_point / 12 / 60,
            "all_257_points_from_scratch_nominal_minutes": 257 * per_point / 12 / 60,
            "aggregate_wall_time_measured": False, "development_or_performance_improvements_included": False},
        "centers": centers, "availability_source_batch_hashes": batch_hashes,
        "method_reference": "https://www.itl.nist.gov/div898/handbook/pri/section3/pri3347.htm",
        "proposal_only_new_strategy_accounts": 0, "formal_contract_changed": False}
    output = WORK / "others/bounded_parameter_check_proposal.json"
    assert not output.exists(), "Review an existing proposal rather than silently replacing it"
    save(output, proposal)
    assert all(digest(path) == expected for path, expected in protected_hashes.items())
    print("GEOMETRY_ONLY_PROPOSAL", proposal["proposed_total_points"], "existing", 257 - replay_upper,
          "additional_upper_bound", replay_upper, flush=True)
    for key, item in centers.items():
        print(key, item["axial_count"], item["joint_count"], item["proposed_N"],
              item["proposed_required_joint_passes"], item["existing_completed_points"],
              item["additional_replay_upper_bound"], flush=True)
    print("NOMINAL_NEW_REPLAY_MINUTES", proposal["budget_estimate"]["new_replay_nominal_minutes_at_previous_rate"], flush=True)


if __name__ == "__main__":
    main()
