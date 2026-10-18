"""Fixed E9 arithmetic from authenticated public account evidence; no execution."""

from hashlib import sha256
from pathlib import Path
import io
import json
import socket

import numpy as np
import pandas as pd

from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "research/S014/materials/20261018_e9_extension_review"
OLD = ROOT / "research/S014/experiments/EX034_20261018"
EPS = 1e-10
VALUE_COLUMNS = ("A6", "L6", "O6", "A9", "L9", "O9", "J9", "delta_A", "delta_O")


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def read_public(value):
    ref = EvidenceRef.from_dict(value)
    raw = ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == ref.sha256
    return raw


def sign(value):
    return int(value > EPS) - int(value < -EPS)


def ledger(account, name):
    assert len(account["runs"]) == 1
    frame = pd.DataFrame(account["runs"][0]["ledgers"][name]["data"])
    for column in ("date", "signal_date", "valid_session", "fill_time", "execution_date"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column]).dt.strftime("%Y-%m-%d")
    return frame


def terminal(account, day, dates):
    """Only account state and decisions available at the endpoint are used."""
    daily = ledger(account, "account_daily").set_index("date")
    row = daily.loc[day]
    decisions = ledger(account, "decisions")
    decision = decisions.loc[decisions.signal_date.eq(day)]
    assert len(decision) == 1, (day, len(decision))
    action = str(decision.iloc[0].action).upper()
    fills = ledger(account, "fills")
    seen = fills.loc[fills.fill_time.le(day)]
    quantity = int(row.quantity)
    plan = None
    if quantity:
        buys = seen.loc[seen.side.str.upper().eq("BUY")]
        assert len(buys)
        entry = buys.iloc[-1].fill_time
        # The original intervention position is sold by E6 in this fixed inventory.
        # Any E9 holding is a fresh original-policy H3 position.
        index = dates.index(entry) + 3
        plan = dates[index] if index < len(dates) else None
    cash, close, equity = float(row.cash), float(row.close), float(row.equity)
    assert abs(equity - cash - quantity * close) < 1e-6
    return {
        "value": equity, "cash": cash, "quantity": quantity,
        "state": "HOLDING" if quantity else "CASH", "next_action": action,
        "pending": action if action in ("BUY", "SELL") else "NONE",
        "planned_exit": plan,
        "planned_exit_beyond_calendar": bool(quantity and plan is None),
        "planned_exit_already_due": bool(plan is not None and plan <= day),
    }


def pair_counts(frame, left, right):
    a, b = frame[left].map(sign), frame[right].map(sign)
    return {
        "strict_opposite_n": int((a * b).eq(-1).sum()),
        "same_sign_n": int(a.eq(b).sum()),
        "zero_boundary_difference_n": int((a.ne(b) & (a.eq(0) | b.eq(0))).sum()),
        "left_positive_right_negative_n": int((a.eq(1) & b.eq(-1)).sum()),
        "left_negative_right_positive_n": int((a.eq(-1) & b.eq(1)).sum()),
        "transition_counts": {
            f"{x}:{y}": int((a.eq(x) & b.eq(y)).sum())
            for x in (-1, 0, 1) for y in (-1, 0, 1)
        },
    }


def summary(frame):
    if frame.empty:
        return {"n": 0}
    result = {
        "n": len(frame),
        "means_pp": {key: float(frame[key].mean() * 100) for key in VALUE_COLUMNS},
        "medians_pp": {key: float(frame[key].median() * 100) for key in VALUE_COLUMNS},
        "mean_absolute_pp": {key: float(frame[key].abs().mean() * 100) for key in VALUE_COLUMNS},
        "quantiles_pp": {
            key: {str(q): float(frame[key].quantile(q) * 100) for q in (0, .1, .25, .5, .75, .9, 1)}
            for key in VALUE_COLUMNS
        },
        "sign_counts": {
            key: {str(s): int(frame[key].map(sign).eq(s).sum()) for s in (-1, 0, 1)}
            for key in VALUE_COLUMNS
        },
        "A6_to_A9": pair_counts(frame, "A6", "A9"),
        "L6_to_A9": pair_counts(frame, "L6", "A9"),
        "L9_to_A9": pair_counts(frame, "L9", "A9"),
        "L6_to_A6": pair_counts(frame, "L6", "A6"),
        "nonzero_delta_A_n": int(frame.delta_A.abs().gt(EPS).sum()),
        "nonzero_J9_n": int(frame.J9.abs().gt(EPS).sum()),
        "A9_abs_greater_than_A6_n": int((frame.A9.abs() - frame.A6.abs()).gt(EPS).sum()),
        "A9_abs_less_than_A6_n": int((frame.A9.abs() - frame.A6.abs()).lt(-EPS).sum()),
    }
    originals = frame.loc[frame.original_E6_flip]
    result["original_E6_flip_subset"] = {
        "n": len(originals),
        "persists_opposite_L6_A9_n": int((originals.L6.map(sign) * originals.A9.map(sign)).eq(-1).sum()),
        "same_L6_A9_sign_n": int(originals.L6.map(sign).eq(originals.A9.map(sign)).sum()),
        "A9_zero_n": int(originals.A9.map(sign).eq(0).sum()),
    }
    return result


def cash_terminal(value, action="HOLD"):
    return {"value": float(value), "cash": float(value), "quantity": 0,
            "state": "CASH", "next_action": action,
            "pending": "BUY" if action == "BUY" else "NONE",
            "planned_exit": None, "planned_exit_beyond_calendar": False,
            "planned_exit_already_due": False}


def main():
    def blocked(*args, **kwargs):
        raise RuntimeError("EX035 analysis: network disabled")
    socket.socket.connect = blocked
    socket.create_connection = blocked
    for name in ("events.csv", "summary.json"):
        assert not (EX / "others" / name).exists(), name
    design_raw = (EX / "protocols/design.json").read_bytes()
    design = json.loads(design_raw)
    lock = json.loads((EX / "protocols/published_design.json").read_bytes())
    assert read_public(lock) == design_raw
    assert design["execution_authorized"]
    assert design["proposed_caps"]["account_runs"] == 69
    publication = json.loads((REVIEW / "publication.json").read_bytes())
    inventory_raw = read_public(publication["evidence"]["inventory.json"])
    assert inventory_raw == (REVIEW / "inventory.json").read_bytes()
    inventory = json.loads(inventory_raw)
    original = json.loads(read_public(inventory["sources"]["C0011"]))
    assert original["result_hash"] == inventory["sources"]["C0011_result_hash"]
    dates = pd.read_csv(io.BytesIO(read_public(inventory["sources"]["calendar"]))).date.tolist()
    original_daily = ledger(original, "account_daily").set_index("date")
    assert original_daily.index.tolist() == dates and len(dates) == 1642
    original_decisions = ledger(original, "decisions").set_index("signal_date")
    prior_result = json.loads((OLD / "others/result.json").read_bytes())
    assert prior_result["status"] == "COMPLETE"
    assert prior_result["validation"]["status"] == "PASS"
    old_raw = read_public(prior_result["evidence"]["others/events.csv"])
    assert old_raw == (OLD / "others/events.csv").read_bytes()
    old = pd.read_csv(io.BytesIO(old_raw)).set_index("cycle_id")
    assert len(old) == 146 and old.index.is_unique
    nodes = sorted((n for n in inventory["events"] if n["eligible"]), key=lambda n: (n["E2"], n["cycle_id"]))
    replay_nodes = [n for n in nodes if n["route"] == "PUBLIC_H_REPLAY_REQUIRED"]
    assert len(nodes) == 145 and len(replay_nodes) == 68
    assert len(inventory["events"]) == 147
    expected = {0: None, **{i: node for i, node in enumerate(replay_nodes, 1)}}
    receipts, failures = {}, []
    receipt_paths = sorted((EX / "others/accounts").glob("run-*.json"))
    assert len(receipt_paths) <= 69
    for path in receipt_paths:
        receipt = json.loads(path.read_bytes())
        index = receipt["index"]
        assert index in expected and index not in receipts
        assert path.name == f"run-{index:03d}.json"
        receipts[index] = receipt
        if receipt["status"] != "SUCCEEDED" or receipt.get("audit", {}).get("status") != "PASS":
            failures.append({"index": index, "reason": "account_or_audit_failed", "receipt": receipt})
    for index in expected:
        if index not in receipts:
            failures.append({"index": index, "reason": "missing_receipt"})
    if failures:
        write(EX / "others/summary.json", {
            "status": "FAIL_INCOMPLETE_FIXED_COHORT", "expected_account_receipts": 69,
            "available_receipts": len(receipts), "failures": failures,
            "node_groups_planned": 145, "primary_labels_computed": 0,
            "reason": "No complete-case success claim; fixed analysis requires all69 successful audited accounts",
        })
        raise RuntimeError("Fixed cohort incomplete; explicit failure summary written")
    accounts, authenticated = {}, []
    for index, receipt in sorted(receipts.items()):
        data = json.loads(read_public(receipt["evidence"]))
        authenticated.append({"index": index, "evidence": receipt["evidence"], "result_hash": data["result_hash"],
                              "receipt_sha256": sha256((EX / f"others/accounts/run-{index:03d}.json").read_bytes()).hexdigest()})
        if index:
            node = expected[index]
            stored = receipt.get("node")
            if isinstance(stored, dict):
                assert stored["cycle_id"] == node["cycle_id"]
            elif isinstance(stored, str):
                assert stored in (node["cycle_id"], node["entry_date"])
            accounts[node["cycle_id"]] = data
        else:
            # Independent economic control check; separate audit verifies signal identity.
            control_daily = ledger(data, "account_daily").set_index("date")
            pd.testing.assert_frame_equal(control_daily, original_daily, check_exact=True)
    rows = []
    for node in nodes:
        prior = old.loc[node["cycle_id"]]
        d, e6, day = node["E2"], node["E6"], node["E9"]
        assert prior.decision_date == d and prior.terminal_date == e6
        assert prior.H_state == prior.C_state == "CASH"
        assert prior.H_actual_exit == e6 and prior.C_actual_exit <= e6
        assert dates[dates.index(node["entry_date"]) + 9] == day
        wd = float(prior.W_D)
        assert abs(wd - float(original_daily.loc[d].equity)) < 1e-6
        x = terminal(original, day, dates)
        if node["route"] == "EXACT_H_CASH_REUSE":
            for t in (node["E6"], node["E7"], node["E8"]):
                decision = original_decisions.loc[t]
                assert not all(bool(decision[k]) for k in ("ready", "parent", "high"))
            decision = original_decisions.loc[day]
            action = "BUY" if all(bool(decision[k]) for k in ("ready", "parent", "high")) else "HOLD"
            h = cash_terminal(prior.H_T, action)
        else:
            account = accounts[node["cycle_id"]]
            replay_daily = ledger(account, "account_daily").set_index("date")
            assert abs(float(replay_daily.loc[d].equity) - wd) < 1e-6
            assert abs(float(replay_daily.loc[e6].equity) - float(prior.H_T)) < 1e-6
            assert int(replay_daily.loc[e6].quantity) == 0
            h = terminal(account, day, dates)
        c = cash_terminal(prior.C_T)
        a9, l9 = (h["value"] - x["value"]) / wd, (h["value"] - c["value"]) / wd
        o9, j9 = (x["value"] - c["value"]) / wd, (h["value"] - float(prior.H_T)) / wd
        a6, l6, o6 = float(prior.A), float(prior.L), float(prior.O)
        assert abs(a9 - l9 + o9) < EPS
        assert abs(l9 - l6 - j9) < EPS
        assert abs(a9 - a6 - j9 + o9 - o6) < EPS
        row = {"cycle_id": node["cycle_id"], "entry_date": node["entry_date"],
               "decision_date": d, "E6": e6, "terminal_date": day,
               "entry_year": int(node["entry_date"][:4]), "decision_year": int(d[:4]),
               "route": node["route"], "W_D": wd,
               "A6": a6, "L6": l6, "O6": o6, "H6": float(prior.H_T),
               "X6": float(prior.X_T), "C6": float(prior.C_T),
               "A9": a9, "L9": l9, "O9": o9, "J9": j9,
               "delta_A": a9 - a6, "delta_O": o9 - o6,
               "original_E6_flip": sign(a6) * sign(l6) == -1,
               "A6_A9_strict_flip": sign(a6) * sign(a9) == -1,
               "L6_A9_strict_flip": sign(l6) * sign(a9) == -1,
               "L9_A9_strict_flip": sign(l9) * sign(a9) == -1}
        for branch, values in (("X", x), ("H", h), ("C", c)):
            row[f"{branch}9"] = values["value"]
            row.update({f"{branch}_{key}": value for key, value in values.items() if key != "value"})
        rows.append(row)
    frame = pd.DataFrame(rows).sort_values(["decision_date", "cycle_id"]).reset_index(drop=True)
    assert np.isfinite(frame[list(VALUE_COLUMNS) + ["W_D", "X9", "H9", "C9"]]).all().all()
    endpoint, cluster, assignments = None, 0, []
    for row in frame.itertuples():
        if endpoint is None or row.decision_date > endpoint:
            cluster += 1
        endpoint = max(endpoint or row.terminal_date, row.terminal_date)
        assignments.append(cluster)
    frame["cluster_id"] = assignments
    frame.to_csv(EX / "others/events.csv", mode="x", index=False, lineterminator="\n")
    ranked = frame.assign(rank_abs_delta=frame.delta_A.abs()).sort_values(
        ["rank_abs_delta", "decision_date", "cycle_id"], ascending=[False, True, True])
    total_abs_change = float(frame.delta_A.abs().sum())
    deleted = {}
    for n in (1, 3, 5):
        removed = ranked.head(n)
        deleted[str(n)] = {
            "removed": removed.cycle_id.tolist(),
            "removed_absolute_change_share": float(removed.delta_A.abs().sum()) / total_abs_change if total_abs_change else 0.0,
            "remaining": summary(frame.loc[~frame.cycle_id.isin(removed.cycle_id)]),
        }
    groups = {str(key): summary(group) for key, group in frame.groupby("cluster_id")}
    means = frame.groupby("cluster_id")[list(VALUE_COLUMNS)].mean()
    original_flips = old.loc[(old.A.map(sign) * old.L.map(sign)).eq(-1)]
    assert len(original_flips) == 25
    flip_ids = set(original_flips.index)
    current_ids = set(frame.cycle_id)
    result = {
        "status": "PASS", "design": lock, "sign_zero_tolerance": EPS,
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "events_sha256": sha256((EX / "others/events.csv").read_bytes()).hexdigest(),
        "source_refs": {"review_inventory": publication["evidence"]["inventory.json"],
                        "C0011": inventory["sources"]["C0011"], "calendar": inventory["sources"]["calendar"],
                        "EX034_events": prior_result["evidence"]["others/events.csv"]},
        "authenticated_accounts": authenticated,
        "all": summary(frame),
        "without2026": summary(frame.loc[frame.decision_date.le("2025-12-31") & frame.terminal_date.le("2025-12-31")]),
        "by_route": {str(key): summary(group) for key, group in frame.groupby("route")},
        "by_decision_year": {str(year): summary(frame.loc[frame.decision_year.eq(year)]) for year in range(2020, 2027)},
        "by_entry_year": {str(year): summary(frame.loc[frame.entry_year.eq(year)]) for year in range(2020, 2027)},
        "original_25_flips": {
            "original_n": 25, "observable_n": len(flip_ids & current_ids),
            "censored_n": len(flip_ids - current_ids), "censored_cycle_ids": sorted(flip_ids - current_ids),
            "observable": summary(frame.loc[frame.cycle_id.isin(flip_ids)]),
            "persisted_cycle_ids": frame.loc[frame.original_E6_flip & frame.L6_A9_strict_flip, "cycle_id"].tolist(),
            "collapsed_cycle_ids": frame.loc[frame.original_E6_flip & ~frame.L6_A9_strict_flip, "cycle_id"].tolist(),
        },
        "censored_nodes": [node for node in inventory["events"] if not node["eligible"]],
        "cluster_count": cluster,
        "cluster_sizes": {str(k): int(v) for k, v in frame.groupby("cluster_id").size().value_counts().sort_index().items()},
        "cluster_equal_means_pp": {key: float(means[key].mean() * 100) for key in VALUE_COLUMNS},
        "clusters": groups,
        "leave_one_cluster_out": {str(k): summary(frame.loc[frame.cluster_id.ne(k)]) for k in sorted(frame.cluster_id.unique())},
        "delete_top_abs_delta_A": deleted,
        "terminal_states": {
            branch: {
                "state_counts": {str(k): int(v) for k, v in frame[f"{branch}_state"].value_counts().items()},
                "pending_counts": {str(k): int(v) for k, v in frame[f"{branch}_pending"].value_counts().items()},
                "planned_exit_already_due_n": int(frame[f"{branch}_planned_exit_already_due"].sum()),
                "planned_exit_beyond_calendar_n": int(frame[f"{branch}_planned_exit_beyond_calendar"].sum()),
            } for branch in ("X", "H", "C")
        },
        "reconciliation": {
            "A9_L9_O9_max_abs": float((frame.A9 - frame.L9 + frame.O9).abs().max()),
            "L9_L6_J9_max_abs": float((frame.L9 - frame.L6 - frame.J9).abs().max()),
            "delta_A_J9_delta_O_max_abs": float((frame.delta_A - frame.J9 + frame.delta_O).abs().max()),
            "C9_C6_max_abs": float((frame.C9 - frame.C6).abs().max()),
            "cash_reuse_H9_H6_max_abs": float((frame.loc[frame.route.eq("EXACT_H_CASH_REUSE"), "H9"] - frame.loc[frame.route.eq("EXACT_H_CASH_REUSE"), "H6"]).abs().max()),
        },
        "counts": {"inventory": 147, "eligible": 145, "censored": 2, "cash_reuse": 77,
                   "replay": 68, "account_receipts": 69, "account_success": 69, "failed": 0},
        "actual_budget": {"account_runs": 69, "node_groups": 145, "primary_A9_labels": 145,
                          "fixed_attribution_values": 435, "terminal_values": 435,
                          "new_upstream_calls": 0, "model_fits": 0, "alternate_endpoints": 0,
                          "account_external_matching_trials": 0, "new_qualified_candidates": 0},
        "interpretation": "Diagnostic local wealth contrasts only, not strategy returns or predictive alpha. L9 includes H post-sale reentry; route is computation only. All history seen; E9 holdings retain future risk.",
    }
    write(EX / "others/summary.json", result)
    print(json.dumps({key: result[key] for key in ("status", "all", "without2026", "counts", "cluster_count", "cluster_equal_means_pp", "terminal_states", "reconciliation")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
