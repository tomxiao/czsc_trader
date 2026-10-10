"""Independent read-only account diagnostics; writes only its adjacent audit outputs."""
from pathlib import Path
from collections import defaultdict
import hashlib
import json
import math
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / 'research/S007/assets/runs/EX003_20261010/independent-audit'
OUT.mkdir(parents=True, exist_ok=True)
SOURCES = {}

def source(relative):
    path = ROOT / relative
    raw = path.read_bytes()
    SOURCES[relative] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    return path

def js(relative):
    return json.loads(source(relative).read_text(encoding="utf-8-sig"))

def csv(relative):
    return pd.read_csv(source(relative), encoding="utf-8-sig", float_precision="round_trip")

def rolling(account, benchmark, initial_cash, prefix):
    assert len(account) == len(benchmark)
    assert (account["date"].to_numpy() == benchmark["date"].to_numpy()).all()
    assert account["date"].is_unique and account["date"].is_monotonic_increasing
    own = np.r_[initial_cash, account["equity"].to_numpy(float)]
    ref = np.r_[initial_cash, benchmark["equity"].to_numpy(float)]
    records = []
    for start in range(0, len(own)-126, 21):
        own_return = own[start+126]/own[start]-1
        benchmark_return = ref[start+126]/ref[start]-1
        records.append({"start_index": start,
                        "opening_anchor": "INITIAL_CASH" if start == 0 else account["date"].iloc[start-1],
                        "first_return_date": account["date"].iloc[start],
                        "last_return_date": account["date"].iloc[start+125],
                        "strategy_return": own_return, "benchmark_return": benchmark_return,
                        "excess_return": own[start+126]/own[start]-ref[start+126]/ref[start]})
    frame = pd.DataFrame(records)
    frame.to_csv(OUT / f"{prefix}_rolling.csv", index=False, lineterminator="\n")
    return {"daily_points":len(account), "first_date":account["date"].iloc[0],
            "last_date":account["date"].iloc[-1],"windows":len(frame),"size":126,"step":21,
            "q10_linear":float(np.quantile(frame["excess_return"],.1,method="linear")),
            "formula":"own[start+126]/own[start] - benchmark[start+126]/benchmark[start]",
            "prepending_initial_cash":initial_cash,
            "index_definition":"Index 0 is initial cash; daily account row i is index i+1."}

def reconcile(account, fills, closed, initial_cash, opening_cash, opening_quantity, prefix, trades=None):
    flow = defaultdict(float)
    qty = defaultdict(int)
    total_buys = defaultdict(float)
    by_date = defaultdict(list)
    last = {}
    for fill in fills:
        by_date[fill["date"]].append(fill)
    assert set(by_date).issubset(set(account["date"]))
    cash, quantity = opening_cash, opening_quantity
    daily_cash_error = daily_equity_error = 0.0
    before_cash_error = 0.0
    max_fee_error = 0.0
    for point in account.to_dict("records"):
        if "cash_before" in point:
            before_cash_error=max(before_cash_error,abs(cash-point["cash_before"]))
            assert quantity==point["quantity_before"]
        for fill in by_date[point["date"]]:
            signed_qty = fill["quantity"] if fill["side"] == "BUY" else -fill["quantity"]
            fill_flow = -signed_qty*fill["price"]-fill["fees"]
            cash += fill_flow
            quantity += signed_qty
            flow[fill["cycle_id"]] += fill_flow
            qty[fill["cycle_id"]] += signed_qty
            last[fill["cycle_id"]] = fill["date"]
            if fill["side"] == "BUY":
                total_buys[fill["cycle_id"]] += -fill_flow
            max_fee_error = max(max_fee_error,abs(fill["fees"]-.001*fill["quantity"]*fill["price"]))
        assert quantity == point["quantity"]
        daily_cash_error = max(daily_cash_error, abs(cash-point["cash"]))
        daily_equity_error = max(daily_equity_error, abs(point["equity"]-point["cash"]-point["quantity"]*point["close"]))
    assert set(closed).issubset(flow)
    for cid, exit_date in closed.items():
        assert qty[cid] == 0 and last[cid] == exit_date
    assert all(q >= 0 for q in qty.values())
    assert all(q > 0 or cid in closed for cid,q in qty.items())
    cycle_records = [{"cycle_id":cid,"closed":cid in closed,"cash_net_profit":flow[cid],
                      "quantity_remaining":qty[cid],"buy_cash_including_fee":total_buys[cid],
                      "cash_return":flow[cid]/total_buys[cid] if cid in closed else None}
                     for cid in flow]
    pd.DataFrame(cycle_records).to_csv(OUT/f"{prefix}_cycles.csv",index=False,lineterminator="\n")
    winners=sorted([flow[cid] for cid in closed if flow[cid]>0],reverse=True)
    top_n=math.ceil(.1*len(winners))
    closed_pnl=sum(flow[cid] for cid in closed)
    open_pnl=sum(flow[cid]+qty[cid]*account["close"].iloc[-1] for cid in flow if cid not in closed)
    wealth_error=abs(closed_pnl+open_pnl+opening_cash-initial_cash-(account["equity"].iloc[-1]-initial_cash))
    trade_return_error = trade_qty_error = trade_entryprice_error = trade_exitprice_error = 0.0
    if trades is not None:
        assert set(trades["cycle_id"]) == set(closed)
        for t in trades.to_dict("records"):
            cid=t["cycle_id"]
            f=[x for x in fills if x["cycle_id"]==cid]
            buys=[x for x in f if x["side"]=="BUY"]
            sells=[x for x in f if x["side"]=="SELL"]
            bq=sum(x["quantity"] for x in buys)
            sq=sum(x["quantity"] for x in sells)
            assert bq==sq and buys[0]["date"]==t["entry_date"] and sells[-1]["date"]==t["exit_date"]
            trade_qty_error=max(trade_qty_error,abs(t["quantity"]-bq))
            trade_entryprice_error=max(trade_entryprice_error,abs(t["entry_price"]-sum(x["price"]*x["quantity"] for x in buys)/bq))
            trade_exitprice_error=max(trade_exitprice_error,abs(t["exit_price"]-sum(x["price"]*x["quantity"] for x in sells)/sq))
            trade_return_error=max(trade_return_error,abs(t["net_return"]-flow[cid]/total_buys[cid]))
    assert max(daily_cash_error,daily_equity_error,wealth_error,max_fee_error,before_cash_error)<1e-6
    assert max(trade_return_error,trade_qty_error,trade_entryprice_error,trade_exitprice_error)<1e-9
    return {"closed_cycles":len(closed),"positive_closed_cycles":len(winners),"top_count":top_n,
            "total_positive_cash_profit":sum(winners),"top_cash_profit":sum(winners[:top_n]),
            "profit_concentration":sum(winners[:top_n])/sum(winners),"closed_cash_net_profit":closed_pnl,
            "open_cycles":len(flow)-len(closed),"open_pnl":open_pnl,"ending_quantity":quantity,
            "ending_equity":float(account["equity"].iloc[-1]),"initial_cash":initial_cash,
            "wealth_reconciliation_error":wealth_error,"max_daily_cash_error":daily_cash_error,
            "max_daily_before_cash_error":before_cash_error,
            "max_daily_equity_error":daily_equity_error,"max_fee_rate_error":max_fee_error,
            "trade_table_check_performed":trades is not None,
            "trade_net_return_error":trade_return_error,"trade_quantity_error":trade_qty_error,
            "trade_entryprice_error":trade_entryprice_error,"trade_exitprice_error":trade_exitprice_error,
            "fills":len(fills),"fees_total":sum(x["fees"] for x in fills),
            "formula":"sum(top ceil(0.1*n_positive) closed-cycle cash profits)/sum(all positive closed-cycle cash profits)"}

def main():
    b31="experiments/S007/20260915_S007_EX31"
    b32="experiments/S007/20260915_S007_EX32"
    m31,m32=js(b31+"/experiment_manifest.json"),js(b32+"/experiment_manifest.json")
    own=csv(b31+"/artifacts/account_daily.csv")
    fills=csv(b31+"/artifacts/fills.csv")
    trades=csv(b31+"/artifacts/trades.csv")
    benchmark=csv(b32+"/artifacts/buyhold_account_daily.csv")
    matrix=csv(b32+"/artifacts/daily_return_matrix.csv")
    for folder,manifest in [(b31,m31),(b32,m32)]:
        for rel, expected in manifest["files"].items():
            path=folder+"/"+rel
            if path in SOURCES:
                assert SOURCES[path]=={"sha256":expected["sha256"],"bytes":expected["bytes"]}
    assert own["date"].iloc[0]=="2021-01-05" and own["date"].iloc[-1]=="2026-09-02"
    assert (own["date"]<= "2026-09-02").all() and len(own)==1373
    assert len(trades)==139 and (trades["status"]=="CLOSED").all() and trades["cycle_id"].is_unique
    assert set(fills["side"])=={"BUY","SELL"}
    assert (fills["quantity"]>0).all() and ((fills["quantity"]%100)==0).all()
    s007_fills=[dict(x,date=x["fill_time"]) for x in fills.to_dict("records")]
    s007_rec=reconcile(own,s007_fills,dict(zip(trades["cycle_id"],trades["exit_date"])),100000.,100000.,0,"s007",trades)
    s007_rolling=rolling(own,benchmark,100000.,"s007")
    assert (matrix["date"].to_numpy()==own["date"].to_numpy()).all()
    matrix_errors={}
    for label,account in [("S007-C001",own),("BuyHold-588080",benchmark)]:
        returns=np.diff(np.r_[100000.,account["equity"].to_numpy(float)])/np.r_[100000.,account["equity"].to_numpy(float)][:-1]
        matrix_errors[label]=float(np.max(np.abs(returns-matrix[label].to_numpy(float))))
        assert matrix_errors[label]<1e-12
    auth=js("research/S013/assets/runs/EX008_20261010/center_authentication.json")
    center=next(x for x in auth["centers"] if x["candidate"]["key"]["candidate_id"]=="C2132")
    ref=center["formal_account"]
    raw_path="research/S013/assets/evidence/"+ref["experiment"]["experiment_id"]+"/"+ref["evidence_id"]
    raw=js(raw_path)
    assert SOURCES[raw_path]["sha256"]==ref["sha256"]
    receipt=js("research/S013/deliveries/ASSESSMENT/2/receipt.json")
    auth_sha=SOURCES["research/S013/assets/runs/EX008_20261010/center_authentication.json"]["sha256"]
    assert any(x["sha256"]==auth_sha for x in receipt["files"])
    ev=next(x for x in raw["assessment_evidence"] if x["scenario_id"]=="baseline")
    assert ev["candidate"]["content_sha256"]==center["candidate"]["content_sha256"]
    assert ev["scenario_context"]["one_way_cost"]==.001
    s013_own=pd.DataFrame(ev["account"]).rename(columns={"session":"date"})
    s013_bh=pd.DataFrame({"date":s013_own["date"],"equity":ev["benchmark_equity"]})
    s013_fills=[dict(x,date=x["session"]) for x in ev["fills"]]
    s013_rec=reconcile(s013_own,s013_fills,{x["cycle_id"]:x["exit_session"] for x in ev["closed_cycles"]},ev["initial_cash"],ev["opening_cash"],ev["opening_quantity"],"c2132")
    s013_rolling=rolling(s013_own,s013_bh,ev["initial_cash"],"c2132")
    panel=js("research/S013/assets/runs/EX008_20261010/assessment.json")
    row=next(x for x in panel["rows"] if x["candidate"]["candidate_id"]=="S013-C2132")
    published=js("research/S013/assets/deliveries/ASSESSMENT/2/delivery.json")
    publication_sha=SOURCES["research/S013/assets/deliveries/ASSESSMENT/2/delivery.json"]["sha256"]
    assert any(x["path"]=="delivery.json" and x["sha256"]==publication_sha for x in receipt["files"])
    formal_row=next(x for x in published["content"]["payload"]["assessment"]["rows"] if x["candidate"]["candidate_id"]=="S013-C2132")
    assert formal_row==row
    del published
    diag={x["metric"]:x for x in row["diagnostics"]}
    checks={}
    for metric,value in [("PROFIT_CONCENTRATION",s013_rec["profit_concentration"]),("ROLLING_EXCESS_Q10",s013_rolling["q10_linear"])]:
        entry=next(x for name,x in diag.items() if name.upper()==metric)
        checks[metric]=abs(entry["value"]-value)
        assert checks[metric]<1e-12
    result={"status":"PASS","scope":"No new account evaluation; allowed original development pool account diagnostics only.",
            "s007":{"concentration":s007_rec,"time_stability":s007_rolling,"matrix_errors":matrix_errors},
            "s013_c2132":{"candidate":ev["candidate"],"concentration":s013_rec,"time_stability":s013_rolling,"formal_metric_errors":checks},
            "sources":SOURCES}
    (OUT/"independent_audit.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({k:v for k,v in result.items() if k!="sources"},ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
