"""Fixed E6 local wealth arithmetic from published S014 evidence only."""

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
METHOD = ROOT / "research/S014/materials/20261018_action_value_method_review"
EPS = 1e-10
MONEY_EPS = 1e-7
FEE = 0.001


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def sign(value):
    return int(value > EPS) - int(value < -EPS)


def terminal_value(cash, quantity, close, endpoint, sale_date, sale_price, sale_fee):
    """Already-paid entry fees are in cash; later sales never affect endpoint."""
    if sale_date is not None and sale_date <= endpoint:
        assert sale_price is not None and sale_fee is not None
        return cash + quantity * sale_price - sale_fee, "CASH"
    return cash + quantity * close, "PENDING_SELL"


def precheck():
    args = (7.0, 100, 12.0, "2020-01-08")
    assert terminal_value(*args, "2020-01-08", 11.0, 1.1) == (1105.9, "CASH")
    assert terminal_value(*args, "2020-01-09", 999.0, 99.9) == (1207.0, "PENDING_SELL")
    assert terminal_value(*args, None, None, None) == (1207.0, "PENDING_SELL")
    assert terminal_value(*args, "2020-01-07", 11.0, 1.1) == (1105.9, "CASH")
    assert sign(1e-11) == sign(-1e-11) == 0
    assert sign(1e-8) == 1 and sign(-1e-8) == -1
    assert abs(((1207-1150)/1000) - ((1207-1105.9)/1000 - (1150-1105.9)/1000)) < EPS
    return {"status": "PASS", "checks": 7,
            "scope": "Synthetic sale timing, pending mark, fee and identity boundaries; no historical samples"}


def summary(frame):
    if frame.empty:
        return {"n": 0}
    sa, sl = frame.A.map(sign), frame.L.map(sign)
    return {
        "n": len(frame),
        "means_pp": {k: float(frame[k].mean()*100) for k in ("A", "L", "O")},
        "medians_pp": {k: float(frame[k].median()*100) for k in ("A", "L", "O")},
        "mean_abs_O_pp": float(frame.O.abs().mean()*100),
        "nonzero_O_n": int(frame.O.abs().gt(EPS).sum()),
        "opposite_sign_n": int((sa*sl).eq(-1).sum()),
        "same_sign_n": int(sa.eq(sl).sum()),
        "zero_boundary_difference_n": int((sa.ne(sl) & (sa.eq(0) | sl.eq(0))).sum()),
        "old_extend_new_exit_n": int((sl.eq(1) & sa.eq(-1)).sum()),
        "old_exit_new_extend_n": int((sl.eq(-1) & sa.eq(1)).sum()),
        "A_positive_n": int(sa.eq(1).sum()), "A_negative_n": int(sa.eq(-1).sum()),
        "L_positive_n": int(sl.eq(1).sum()), "L_negative_n": int(sl.eq(-1).sum()),
        "A_zero_n": int(sa.eq(0).sum()), "L_zero_n": int(sl.eq(0).sum()),
    }


def main():
    def blocked(*args, **kwargs):
        raise RuntimeError("EX034: upstream/network disabled")
    socket.socket.connect = blocked
    socket.create_connection = blocked
    for name in ("events.csv", "summary.json", "attempts.json", "precheck.json"):
        assert not (EX / "others" / name).exists(), name
    checked = precheck()
    checked["source_sha256"] = sha256(Path(__file__).read_bytes()).hexdigest()
    write(EX / "others/precheck.json", checked)
    design = json.loads((EX / "protocols/design.json").read_bytes())
    lock = EvidenceRef.from_dict(json.loads((EX / "protocols/published_design.json").read_bytes()))
    assert lock.resolve(ROOT).read_bytes() == (EX / "protocols/design.json").read_bytes()
    assert design["execution_authorized"] and design["sign_zero_tolerance"] == EPS
    inv = json.loads((METHOD / "inventory.json").read_bytes())
    # Reauthenticate every input before any historical outcome calculation.
    for name, rec in inv["sources"].items():
        if "public_ref" in rec:
            ref = EvidenceRef.from_dict(rec["public_ref"])
            raw = ref.resolve(ROOT).read_bytes()
            assert sha256(raw).hexdigest() == rec["sha256"] == ref.sha256
        else:
            raw = (ROOT / name).read_bytes()
            assert sha256(raw).hexdigest() == rec["sha256"]
        if name != "public_account_C0011":
            assert raw == (ROOT / name).read_bytes()

    def source(key):
        return EvidenceRef.from_dict(inv["sources"][key]["public_ref"]).resolve(ROOT).read_bytes()

    account = json.loads(source("public_account_C0011"))
    assert account["result_hash"] == inv["sources"]["public_account_C0011"]["result_hash"]
    ledgers = account["runs"][0]["ledgers"]
    daily = pd.DataFrame(ledgers["account_daily"]["data"])
    fills = pd.DataFrame(ledgers["fills"]["data"])
    trades = pd.DataFrame(ledgers["trades"]["data"])
    decisions = pd.DataFrame(ledgers["decisions"]["data"])
    for frame, columns in ((daily, ["date"]), (fills, ["fill_time"]),
                           (trades, ["entry_date", "exit_date"]),
                           (decisions, ["signal_date", "valid_session"])):
        for col in columns:
            frame[col] = pd.to_datetime(frame[col]).dt.strftime("%Y-%m-%d")
    daily = daily.set_index("date")
    members = pd.read_csv(io.BytesIO(source("research/S014/experiments/EX019_20261017/others/state_diagnostics_v2_members.csv"))).set_index("cycle_id")
    attempts = pd.read_csv(io.BytesIO(source("research/S014/experiments/EX019_20261017/others/state_diagnostics_v2_fill_attempts.csv")))
    dates = pd.read_csv(io.BytesIO(source("research/S014/experiments/EX033_20261018/others/calendar.csv"))).date.tolist()
    assert daily.index.tolist() == dates and len(dates) == 1642
    assert len(trades) == len(members) == 147 and trades.cycle_id.is_unique
    assert set(trades.cycle_id) == set(members.index)
    inventory = []
    for trade in trades.itertuples():
        pos = dates.index(trade.entry_date)
        d = dates[pos+2] if pos+2 < len(dates) else None
        t = dates[pos+6] if pos+6 < len(dates) else None
        inventory.append({"cycle_id": trade.cycle_id, "entry_date": trade.entry_date,
                          "decision_date": d, "terminal_date": t,
                          "eligible": d is not None and t is not None})
    eligible = [x for x in inventory if x["eligible"]]
    assert len(eligible) == 146 == design["proposed_caps"]["decision_node_groups"]
    rows, failures = [], []
    trade_lookup = trades.set_index("cycle_id")
    for node in eligible:
        try:
            cid, d, t = node["cycle_id"], node["decision_date"], node["terminal_date"]
            m, tr = members.loc[cid], trade_lookup.loc[cid]
            atd, att = daily.loc[d], daily.loc[t]
            q, cash, wd = int(tr.quantity), float(atd.cash), float(atd.equity)
            assert int(atd.quantity) == q == int(m.quantity) and wd > 0
            assert m.decision_date == d and m.extended_target_exit == t
            assert m.entry_date == node["entry_date"] == tr.entry_date
            assert abs(wd - cash - q*atd.close) < MONEY_EPS
            own = fills.loc[fills.cycle_id.eq(cid)]
            buy = own.loc[own.side.eq("BUY")]
            sell = own.loc[own.side.eq("SELL")]
            assert len(buy) == 1 and len(sell) <= 1
            b = buy.iloc[0]
            assert b.quantity == q and b.fill_time == tr.entry_date
            assert abs(b.fees - q*b.price*FEE) < MONEY_EPS
            outlay = q*b.price + b.fees
            assert abs(outlay - m.entry_outlay) < MONEY_EPS
            assert abs(cash - daily.loc[tr.entry_date, "cash"]) < MONEY_EPS
            assert abs(b.price - m.entry_price) < 1e-10
            s3 = sell.iloc[0] if len(sell) else None
            sd3 = str(s3.fill_time) if s3 is not None else None
            if s3 is not None:
                assert s3.quantity == q and sd3 == m.original_actual_exit == tr.exit_date
                assert abs(s3.fees - q*s3.price*FEE) < MONEY_EPS
            h6 = attempts.loc[attempts.cycle_id.eq(cid) & attempts.horizon.eq(6) & attempts.filled.eq(True)]
            assert len(h6) <= 1
            s6 = h6.iloc[0] if len(h6) else None
            sd6 = str(s6.day) if s6 is not None else None
            if s6 is not None:
                assert sd6 == m.extended_actual_exit
            h, hs = terminal_value(cash, q, att.close, t, sd6,
                                    float(s6.price) if s6 is not None else None,
                                    q*s6.price*FEE if s6 is not None else None)
            c, cs = terminal_value(cash, q, att.close, t, sd3,
                                    float(s3.price) if s3 is not None else None,
                                    float(s3.fees) if s3 is not None else None)
            x = float(att.equity)
            assert abs(x - att.cash - att.quantity*att.close) < MONEY_EPS
            flow = fills.loc[fills.fill_time.gt(d) & fills.fill_time.le(t)]
            cash_flow = sum((-1 if z.side == "BUY" else 1)*z.quantity*z.price-z.fees for z in flow.itertuples())
            q_flow = sum((1 if z.side == "BUY" else -1)*z.quantity for z in flow.itertuples())
            assert abs(cash + cash_flow - att.cash) < MONEY_EPS
            assert q + q_flow == att.quantity
            subsequent = flow.loc[flow.side.eq("BUY")]
            if len(subsequent):
                assert sd3 is not None and subsequent.fill_time.ge(sd3).all()
            a, ell, o = (h-x)/wd, (h-c)/wd, (x-c)/wd
            assert abs(a-ell+o) < EPS
            old = float(m.extension_increment)
            old_wd = old*outlay/wd
            # Old labels use actual eventual sales; endpoint residual is explicit.
            endpoint_residual = ell-old_wd
            if sd3 is not None and sd6 is not None and sd3 <= t and sd6 <= t:
                assert abs(endpoint_residual) < EPS
                assert abs((c-cash)/outlay-1-m.h3_net_return) < EPS
                assert abs((h-cash)/outlay-1-m.h6_net_return) < EPS
            current = trades.loc[trades.entry_date.le(t) & (trades.exit_date.isna() | trades.exit_date.gt(t))]
            assert len(current) <= 1 and bool(len(current)) == bool(att.quantity)
            xplan = None
            if len(current):
                ix = dates.index(current.iloc[0].entry_date)+3
                xplan = dates[ix] if ix < len(dates) else None
            dt = decisions.loc[decisions.signal_date.eq(t)]
            pending = str(dt.iloc[0].action) if len(dt) else "UNOBSERVED"
            rows.append({**node, "entry_year": int(node["entry_date"][:4]),
                         "decision_year": int(d[:4]), "D_cash": cash, "D_quantity": q,
                         "D_close": float(atd.close), "W_D": wd, "entry_outlay": outlay,
                         "terminal_close": float(att.close), "X_T": x, "H_T": float(h), "C_T": float(c),
                         "X_cash": float(att.cash), "X_quantity": int(att.quantity),
                         "A": a, "L": ell, "O": o,
                         "old_increment": old, "old_increment_W_D": old_wd,
                         "endpoint_residual": endpoint_residual, "normalization_difference": old_wd-old,
                         "sign_A": sign(a), "sign_L": sign(ell), "sign_flip": sign(a)*sign(ell) == -1,
                         "reentry_n": len(subsequent), "reentry": bool(len(subsequent)),
                         "reentry_dates": "|".join(subsequent.fill_time.tolist()),
                         "X_state": "HOLDING" if att.quantity else "CASH", "X_next_action": pending,
                         "X_planned_exit": xplan, "H_state": hs, "C_state": cs,
                         "H_planned_exit": t, "C_planned_exit": str(m.original_target_exit),
                         "H_actual_exit": sd6, "C_actual_exit": sd3,
                         "H_sell_price": float(s6.price) if s6 is not None else None,
                         "H_sell_fee": float(q*s6.price*FEE) if s6 is not None else None,
                         "C_sell_price": float(s3.price) if s3 is not None else None,
                         "C_sell_fee": float(s3.fees) if s3 is not None else None,
                         "original_sell_delayed": sd3 is not None and sd3 > m.original_target_exit,
                         "H_sell_delayed": sd6 is not None and sd6 > t})
        except Exception as exc:
            failures.append({**node, "error_type": type(exc).__name__, "error": str(exc)})
    write(EX / "others/attempts.json", {"cap": 146, "attempted": len(eligible),
          "succeeded": len(rows), "failed": len(failures), "failures": failures,
          "inventory": inventory, "retry": False})
    if failures:
        raise RuntimeError(f"{len(failures)} nodes failed; cap consumed; no automatic retry")
    frame = pd.DataFrame(rows).sort_values(["decision_date", "cycle_id"]).reset_index(drop=True)
    last_t, cluster = None, 0
    clusters = []
    for row in frame.itertuples():
        if last_t is None or row.decision_date > last_t:
            cluster += 1
        last_t = max(last_t or row.terminal_date, row.terminal_date)
        clusters.append(cluster)
    frame["cluster_id"] = clusters
    frame.to_csv(EX / "others/events.csv", index=False, lineterminator="\n", mode="x")
    groupstats = {str(k): summary(v) for k,v in frame.groupby("cluster_id")}
    clustermeans = frame.groupby("cluster_id")[["A", "L", "O"]].mean()
    rankings = frame.assign(abs_O=frame.O.abs()).sort_values(["abs_O", "decision_date", "cycle_id"], ascending=[False, True, True])
    drops = {str(n): {"removed": rankings.head(n).cycle_id.tolist(),
                     "remaining": summary(frame.loc[~frame.cycle_id.isin(rankings.head(n).cycle_id)])}
             for n in (1,3,5)}
    without2026 = frame.loc[frame.decision_date.le("2025-12-31") & frame.terminal_date.le("2025-12-31")]
    result = {
        "status": "PASS", "design": lock.to_dict(), "source_manifest": inv["sources"],
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "events_sha256": sha256((EX / "others/events.csv").read_bytes()).hexdigest(),
        "all": summary(frame), "without2026": summary(without2026),
        "by_decision_year": {str(y): summary(frame.loc[frame.decision_year.eq(y)]) for y in range(2020,2027)},
        "by_entry_year": {str(y): summary(frame.loc[frame.entry_year.eq(y)]) for y in range(2020,2027)},
        "by_reentry": {str(k): summary(v) for k,v in frame.groupby("reentry")},
        "by_X_terminal_state": {str(k): summary(v) for k,v in frame.groupby("X_state")},
        "by_original_sell_delay": {str(k): summary(v) for k,v in frame.groupby("original_sell_delayed")},
        "by_O_sign": {str(k): summary(v) for k,v in frame.groupby(frame.O.map(sign))},
        "cluster_count": cluster, "cluster_sizes": frame.groupby("cluster_id").size().value_counts().sort_index().to_dict(),
        "cluster_equal_means_pp": {k: float(clustermeans[k].mean()*100) for k in ("A", "L", "O")},
        "clusters": groupstats,
        "leave_one_cluster_out": {str(k): summary(frame.loc[frame.cluster_id.ne(k)]) for k in groupstats for k in [int(k)]},
        "delete_top_abs_O": drops,
        "reconciliation": {"identity_max_abs": float((frame.A-frame.L+frame.O).abs().max()),
                           "old_common_denominator_max_abs": float(frame.endpoint_residual.abs().max()),
                           "mean_old_entry_denominator_pp": float(frame.old_increment.mean()*100),
                           "mean_denominator_change_pp": float(frame.normalization_difference.mean()*100),
                           "mean_endpoint_residual_pp": float(frame.endpoint_residual.mean()*100)},
        "counts": {"inventory": 147, "attempted": 146, "success": len(frame), "failed": 0,
                   "excluded_missing_dates": 1, "reentry": int(frame.reentry.sum()),
                   "terminal_X_holding": int(frame.X_state.eq("HOLDING").sum()),
                   "H_pending": int(frame.H_state.eq("PENDING_SELL").sum()),
                   "C_pending": int(frame.C_state.eq("PENDING_SELL").sum())},
        "actual_budget": {"node_groups": 146, "primary_action_labels": 146,
                          "attribution_differences": 292, "terminal_values": 438,
                          "new_upstream_calls": 0, "model_fits": 0, "new_complete_accounts": 0,
                          "new_matching_calls": 0, "alternate_endpoints": 0},
        "interpretation": "Local wealth contrasts only; cohort averages not strategy returns; all data seen; no new predictor validated",
    }
    assert np.isfinite(frame[["A", "L", "O", "W_D", "X_T", "H_T", "C_T"]]).all().all()
    write(EX / "others/summary.json", result)
    print(json.dumps({k: result[k] for k in ("all", "without2026", "counts", "cluster_count", "cluster_equal_means_pp", "by_decision_year", "delete_top_abs_O", "reconciliation")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
