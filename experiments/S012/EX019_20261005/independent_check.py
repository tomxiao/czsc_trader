"""Independent successor audit using the EX018 reference, never formal modules."""

import json
from pathlib import Path
import runpy
import numpy as np

root = Path(__file__).resolve().parents[3]
reference = runpy.run_path(str(root / "experiments/S012/EX018_20261005/independent_check.py"))
read = reference["read"]
dates, years, features = (reference[name] for name in ("dates", "years", "features"))
inherited = reference["signals"]
inherited_valid = reference["valids"]
array_check = reference["array_check"]
check_fields = reference["check_fields"]
recompute = reference["recompute"]
labels = reference["labels"]
counts = reference["counts"]
initial_count = counts["numeric_fields"]
eid = "EX019_20261005"
rows = read(eid, "confirmation.json")
annual = read(eid, "annual.json")
history = read(eid, "selection_history.json")
signals = read(eid, "signals.parquet")
valids = read(eid, "valids.parquet")
gates = read(eid, "gates.parquet")
gate_valid = read(eid, "gate_valids.parquet")
recorded_labels = read(eid, "labels.parquet")
inference = read(eid, "inference.json")
for name, digest in history["source_hashes"].items():
    assert reference["sources"][name] == digest
for name, digest in history["predecessor_receipts"].items():
    assert reference["receipts"][name] == digest

own_return = reference["closes"] / reference["opens"] - 1
own_valid = np.isfinite(own_return)
own_positive = own_valid & (own_return > 0)
array_check(features.intraday, own_return)
array_check(gates.own_intraday_positive, own_positive, True)
array_check(gate_valid.own_intraday_positive, own_valid, True)
array_check(gates.peer_positive, reference["gates"]["peer_positive"], True)
array_check(gate_valid.peer_positive, reference["gate_valid"]["peer_positive"], True)
for base in ("o01", "mid_momentum_positive"):
    array_check(signals[base], inherited[base], True)
    array_check(valids[base], inherited_valid[base], True)
    for suffix, condition in (
        ("positive", own_positive),
        ("nonpositive", own_valid & (own_return <= 0)),
    ):
        name = base + "_own_" + suffix
        expected_valid = inherited_valid[base].to_numpy() & own_valid
        expected = inherited[base].to_numpy() & condition & expected_valid
        array_check(signals[name], expected, True)
        array_check(valids[name], expected_valid, True)
    assert not (signals[base + "_own_positive"] & signals[base + "_own_nonpositive"]).any()
    assert np.array_equal(
        (signals[base + "_own_positive"] | signals[base + "_own_nonpositive"]).to_numpy(),
        inherited[base].to_numpy() & inherited_valid[base].to_numpy() & own_valid,
    )

for key in reference["cache"]:
    h, delay, fee = key
    y, ly, downside, clean = labels(h, delay, fee)
    panel = recorded_labels[f"h{h}_delay{delay}_fee{fee}"]
    array_check(panel.net, y)
    array_check(panel.limit_net, ly)
    array_check(panel.downside, downside)
    array_check(panel.clean, clean, True)
for row in rows + annual:
    h, delay, fee = row["horizon"], row["delay"], row["fee"]
    y, _, _, clean = labels(h, delay, fee)
    parent_raw = (
        (years >= 2022)
        & np.isfinite(y)
        & features.sell_pressure.notna().to_numpy()
        & signals[row["base"]].to_numpy()
        & valids[row["base"]].to_numpy()
    )
    if row["quality"] == "quality_clean":
        parent_raw &= clean
    parent = parent_raw & gate_valid[row["gate"]].to_numpy()
    if "year" in row:
        parent &= years == row["year"]
    expected = recompute(parent, gates[row["gate"]].to_numpy(), h, delay, fee)
    if "unknown_confirmation_events" in row:
        expected["unknown_confirmation_events"] = int(
            (parent_raw & ~gate_valid[row["gate"]].to_numpy()).sum()
        )
    check_fields(row, expected)

key_fields = ("base", "gate", "horizon", "delay", "fee", "quality")
old_lookup = {tuple(row[name] for name in key_fields): row for row in reference["rows"]}
cross_rows = 0
for row in rows:
    if row["base"] in ("o01", "mid_momentum_positive") and row["gate"] == "peer_positive":
        old = old_lookup[tuple(row[name] for name in key_fields)]
        expected = {name: value for name, value in old.items() if name not in key_fields}
        check_fields(row, expected)
        cross_rows += 1
year_lookup = {
    tuple(row[name] for name in key_fields + ("year",)): row for row in reference["annual"]
}
cross_annual = 0
for row in annual:
    if row["base"] in ("o01", "mid_momentum_positive") and row["gate"] == "peer_positive":
        old = year_lookup[tuple(row[name] for name in key_fields + ("year",))]
        expected = {
            name: value for name, value in old.items() if name not in key_fields + ("year",)
        }
        check_fields(row, expected)
        cross_annual += 1

inferred = []
average = reference["average"]
schedule = reference["schedule"]
for i, base in enumerate(history["pairs"]):
    for j, gate_name in enumerate(history["pairs"][base]):
        y, _, _, _ = labels(5, 0, 0.001)
        parent = (
            (years >= 2022)
            & np.isfinite(y)
            & features.sell_pressure.notna().to_numpy()
            & signals[base].to_numpy()
            & valids[base].to_numpy()
            & gate_valid[gate_name].to_numpy()
        )
        ids = np.where(parent)[0]
        anchors = schedule(parent, 5)
        gate = gates[gate_name].to_numpy()
        expected = {
            name: None
            for name in (
                "p",
                "q",
                "lift_ci_low",
                "lift_ci_high",
                "contribution_ci_low",
                "contribution_ci_high",
            )
        }
        if int(gate[anchors].sum()) >= 6 and int((~gate[anchors]).sum()) >= 6:
            rng = np.random.default_rng(12018 + i * 100 + j)
            pattern = gate[ids]
            observed = average(y[ids][pattern]) - average(y[ids][~pattern])
            groups = [np.where(years[ids] == year)[0] for year in np.unique(years[ids])]
            extreme = 0
            for _ in range(399):
                permuted = pattern.copy()
                for group in groups:
                    shift = int(rng.integers(len(group)))
                    permuted[group] = pattern[group][(np.arange(len(group)) - shift) % len(group)]
                effect = average(y[ids][permuted]) - average(y[ids][~permuted])
                extreme += abs(effect) >= abs(observed)
            expected["p"] = (extreme + 1) / 400
            block_ids = np.zeros(len(dates), dtype=int)
            pools, offset = [], 0
            for year in np.unique(years):
                year_ids = np.where(years == year)[0]
                local_ids = np.arange(len(year_ids)) // 20
                block_ids[year_ids] = local_ids + offset
                pools.append(np.arange(offset, offset + int(local_ids.max()) + 1))
                offset += int(local_ids.max()) + 1
            sampled_pools = [rng.choice(pool, size=(999, len(pool))) for pool in pools]
            lifts, contributions = [], []
            for sample in range(999):
                draws = np.concatenate([pool[sample] for pool in sampled_pools])
                weights = np.bincount(draws, minlength=offset)
                opportunity_weights = weights[block_ids[ids]]
                passing_weights = opportunity_weights * pattern
                if passing_weights.sum() > 0:
                    lifts.append(
                        float(
                            np.average(y[ids], weights=passing_weights)
                            - np.average(y[ids], weights=opportunity_weights)
                        )
                    )
                anchor_weights = weights[block_ids[anchors]]
                if anchor_weights.sum() > 0:
                    contributions.append(
                        float(
                            np.average(
                                np.where(gate[anchors], 0, -y[anchors]), weights=anchor_weights
                            )
                        )
                    )
            expected["lift_ci_low"], expected["lift_ci_high"] = np.quantile(
                lifts, [0.025, 0.975]
            ).tolist()
            expected["contribution_ci_low"], expected["contribution_ci_high"] = np.quantile(
                contributions, [0.025, 0.975]
            ).tolist()
        inferred.append(expected)
ordered = sorted(
    [i for i, item in enumerate(inferred) if item["p"] is not None], key=lambda i: inferred[i]["p"]
)
previous = 1.0
for rank in range(len(ordered), 0, -1):
    i = ordered[rank - 1]
    previous = min(previous, inferred[i]["p"] * len(inferred) / rank)
    inferred[i]["q"] = previous
for actual, expected in zip(inference, inferred):
    check_fields(actual, expected)

primary = [
    row
    for row in rows
    if row["horizon"] == 5 and row["delay"] == 0 and row["fee"] == 0.001 and row["quality"] == "all"
]
joint_counts = []
for base in ("o01", "mid_momentum_positive"):
    y, _, _, _ = labels(5, 0, 0.001)
    parent = (
        (years >= 2022)
        & np.isfinite(y)
        & features.sell_pressure.notna().to_numpy()
        & inherited[base].to_numpy()
        & inherited_valid[base].to_numpy()
        & own_valid
        & gate_valid.peer_positive.to_numpy()
    )
    peer = gates.peer_positive.to_numpy()
    for own_sign in (False, True):
        for peer_sign in (False, True):
            joint_counts.append(
                {
                    "base": base,
                    "own_positive": own_sign,
                    "peer_positive": peer_sign,
                    "events": int(
                        (parent & (own_positive == own_sign) & (peer == peer_sign)).sum()
                    ),
                }
            )
result = {
    "status": "PASS",
    "experiment_id": eid,
    "formal_module_imports": [],
    "reference_script": "experiments/S012/EX018_20261005/independent_check.py",
    "source_hashes": reference["sources"],
    "receipt_hashes": reference["receipts"],
    "rows_verified": len(rows),
    "annual_rows_verified": len(annual),
    "cross_predecessor_rows_verified": cross_rows,
    "cross_predecessor_annual_verified": cross_annual,
    "numeric_fields_verified": counts["numeric_fields"] - initial_count,
    "primary_results": primary,
    "own_peer_joint_counts": joint_counts,
    "verification_scope": "原始日线自身方向、4符号子池、2确认门、全部192路径及年度数值、12标签场景、原父同类路径与EX018一致、回执及制品SHA。",
    "inference_rows_verified": len(inference),
    "maximum_absolute_difference": check_fields.__globals__["maximum"],
    "interpretation": [
        "自身正向在O01内可作为有边界的条件确认，限制为原价、T17观测、次日执行、开发池与当前成本。",
        "同类与自身方向共享底层黄金价格信息，不一致子组小，独立确认作用证据不足。",
        "年度表逐年重建父非重叠时间表，年度贡献不可直接加总解释全年。",
        "延迟2日固定限价贡献可能反向，信号不能解释为持久支持。",
        "固定事件收益贡献是诊断，无复利账户年化或账户最大回撤含义。",
    ],
}
output = root / "research/S012/materials/confirmation_competition_verification_20261005.json"
output.write_text(
    json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
)
print(
    json.dumps(
        {
            "status": "PASS",
            "rows": len(rows),
            "annual": len(annual),
            "cross_rows": cross_rows,
            "cross_annual": cross_annual,
            "numeric_fields": result["numeric_fields_verified"],
            "joint_counts": joint_counts,
        },
        ensure_ascii=False,
    )
)
