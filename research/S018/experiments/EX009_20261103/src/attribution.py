"""Attribute retained EX008 account paths without any strategy replay."""
# ruff: noqa: E402
from collections import Counter, defaultdict
from datetime import date
from hashlib import sha256
from math import exp, fsum, log
from pathlib import Path
import json
import os
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p/"research/S018/batch.json").is_file())
os.environ["TMP"] = os.environ["TEMP"] = str(ROOT / ".tmp")
sys.pycache_prefix = str(ROOT / ".tmp/s018-pycache")
from dataflows import ProviderConfig
from strategy_manager import CandidateKey
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, create_experiment,
    ExperimentRequest, diagnose_accounts, publish_evidence, validate_experiment,
    update_research_intent, ResearchIntentUpdate)


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode())


def main():
    folder = ROOT/"research/S018"
    source = folder/"experiments/EX008_20261103"
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef("S018")
    ctx = create_research_context(repo,batch,providers=ProviderConfig(bindings={},equity_bindings={}))
    account = d.EvidenceRef.from_dict(read(source/"others/results.json")["results"]["C9004"]["account_ref"])
    header_path = account.resolve(ROOT)
    header = read(header_path)
    e = create_experiment(ctx,ExperimentRequest("MU固定合并账户归因",
        "深亏来自哪些持有阶段，相对买持的主要差距出现在哪里",date(2026,11,3)))
    work = folder/"experiments"/e.experiment_id
    out=work/"others"
    out.mkdir(exist_ok=True)
    save(out/"protocol.json",{"account":account.to_dict(),"new_replays":0,
        "pnl": "公共账户诊断分解入场、持仓、退出及费用",
        "relative": "按日净值对数收益差加总，按持仓、入场、退出、全天空仓分组",
        "flat": "前日和当日收盘均空仓且当日无成交",
        "drawdown": "净值历史高点至最大回撤低点，包含起始资金",
        "cycles": "按已保存的首次买入决策识别触发机制，多触发单列",
        "decision": "描述事实并明确潜在改进方向，归因不视为反事实"})

    def material(name,path,mime="application/json"):
        return publish_evidence(ctx,d.MaterialEvidenceWrite(e,name,path.read_bytes(),mime,path.suffix[1:]))

    protocol=material("mu-attribution-protocol",out/"protocol.json")
    identity=dict(header["evaluation_identity"])
    identity["candidate"]=CandidateKey(**identity["candidate"])
    diagnosis=diagnose_accounts(repo,d.AccountDiagnosisRequest(d.AccountRunRef(account,d.EvaluationIdentity(**identity)),
        None,d.EvaluationWindow("MU_DEVELOPMENT",date(2023,1,3),date(2026,10,30))))
    if diagnosis.status.value!="COMPUTED":
        raise RuntimeError(str(diagnosis.issues))
    daily=diagnosis.to_dict()["pnl_breakdown"][0]["daily"]
    save(out/"account_pnl.json",diagnosis.to_dict())

    def ledger(role):
        digest=header[role+"_ref"]["sha256"]
        data=(header_path.parent/(digest+".json")).read_bytes()
        assert sha256(data).hexdigest()==digest
        return json.loads(data)["run"]

    candidate,benchmark=ledger("candidate"),ledger("benchmark")
    assert len(daily)==len(candidate["account_points"])==len(benchmark["account_points"])==961
    rows=[]
    cprev,bprev=100000.,100000.
    qty=0
    for p,c,b in zip(daily,candidate["account_points"],benchmark["account_points"],strict=True):
        assert p["session"]==c["session"]==b["session"]
        assert abs(p["opening_equity"]-cprev)<1e-6 and abs(p["closing_equity"]-c["equity"])<1e-6
        kind=("HOLD" if qty and c["quantity"] else "EXIT" if qty else "ENTRY" if c["quantity"]
              else "FLAT" if not p["fill_ids"] else "INTRADAY")
        row={**p,"kind":kind,"candidate_log":log(c["equity"]/cprev),"benchmark_log":log(b["equity"]/bprev),
            "relative_log":log(c["equity"]/cprev)-log(b["equity"]/bprev)}
        rows.append(row)
        qty,cprev,bprev=c["quantity"],c["equity"],b["equity"]
    assert abs(fsum(r["relative_log"] for r in rows)-log(cprev/bprev))<1e-10
    assert abs(fsum(r["equity_change"] for r in rows)-(cprev-100000))<1e-6

    def group(seq):
        return {k:{"sessions":len(rs),**{field:fsum(r[field] for r in rs)
            for field in ("entry","holding","exit","fees","equity_change","candidate_log","benchmark_log","relative_log")}}
            for k in sorted({r["kind"] for r in seq}) if (rs := [r for r in seq if r["kind"]==k])}

    spans=[]
    current=[]
    for r in rows+[{"kind":"END"}]:
        if r["kind"]=="FLAT":
            current.append(r)
        elif current:
            spans.append({"start":current[0]["session"],"end":current[-1]["session"],
                "sessions":len(current),"benchmark_return":exp(fsum(x["benchmark_log"] for x in current))-1})
            current=[]
    peak,peak_i=100000.,-1
    drawdown,from_i,to_i=0.,-1,-1
    for i,r in enumerate(rows):
        equity=r["closing_equity"]
        if equity>peak:
            peak,peak_i=equity,i
        if 1-equity/peak>drawdown:
            drawdown,from_i,to_i=1-equity/peak,peak_i,i
    dd_rows=rows[from_i+1:to_i+1]
    decisions={x["decision_id"]:x for x in candidate["decisions"]}
    orders={x["order_id"]:x for x in candidate["orders"]}
    entries={}
    for fill in candidate["fills"]:
        if fill["side"]=="BUY" and fill["cycle_id"] not in entries:
            basis=decisions[orders[fill["order_id"]]["decision_id"]]["explanation"]["basis"]
            entries[fill["cycle_id"]]=tuple(sorted(x["key"].upper() for x in basis if x["text"]=="True"))
    cycles=[{**x,"mechanisms":entries[x["cycle_id"]]} for x in candidate["trades"] if x["status"]=="CLOSED"]
    assert len(cycles)==94 and all(x["mechanisms"] for x in cycles)
    buckets=defaultdict(list)
    for x in cycles:
        buckets["+".join(x["mechanisms"])].append(x)
    bucket_summary={k:{"closed":len(rs),"losses":sum(x["net_pnl"]<0 for x in rs),
        "net_pnl":fsum(x["net_pnl"] for x in rs),"loss_pnl":fsum(min(0.,x["net_pnl"]) for x in rs)}
        for k,rs in buckets.items()}
    worst=sorted(cycles,key=lambda x:x["net_pnl"])[:10]
    names=read(folder/"materials/mechanism_index.json")["mechanisms"]
    result={"rounds_used":8,"rounds_authorized":10,"account":account.to_dict(),
        "reconciliation":diagnosis.to_dict()["reconciliation"],"full_path":group(rows),
        "segments":{label:group([r for r in rows if (r["session"]<"2025-01-01")==early])
            for label,early in [("2023–2024",True),("2025–2026",False)]},
        "max_drawdown":{"magnitude":drawdown,"peak":rows[from_i]["session"] if from_i>=0 else "INITIAL",
            "trough":rows[to_i]["session"],"pnl":{k:fsum(r[k] for r in dd_rows) for k in ("entry","holding","exit","fees","equity_change")}},
        "worst_cycles":worst,"worst_exit_months":dict(Counter(x["exit_at"][:7] for x in worst)),
        "cycles_by_signal_set":bucket_summary,"largest_flat_rallies":sorted(spans,key=lambda x:x["benchmark_return"],reverse=True)[:5],
        "unfilled_buy_reasons":dict(Counter(x["reason"] for x in candidate["orders"] if x["side"]=="BUY" and x["status"]!="FILLED")),
        "pnl":{k:fsum(r[k] for r in rows) for k in ("entry","holding","exit","fees","equity_change")}}
    save(out/"results.json",result)
    src=work/"src"
    src.mkdir(exist_ok=True)
    (src/"attribution.py").write_bytes(Path(__file__).read_bytes())
    evidence=(account,protocol,material("mu-attribution-results",out/"results.json"),
        material("mu-account-pnl",out/"account_pnl.json"),material("mu-attribution-code",src/"attribution.py","text/x-python"))
    lines=["# MU 固定合并账户归因","","复用 EX008 的连续账户与同窗买持。归因仅解释已发生的净值路径。","",
        "|账户状态|交易日|策略对数收益百分点|买持对数收益百分点|相对差额|","|---|---:|---:|---:|---:|"]
    labels={"HOLD":"跨日持仓","ENTRY":"入场日","EXIT":"退出日","FLAT":"全天空仓","INTRADAY":"日内往返"}
    for k,v in result["full_path"].items():
        lines.append(f"|{labels[k]}|{v['sessions']}|{100*v['candidate_log']:.2f}|{100*v['benchmark_log']:.2f}|{100*v['relative_log']:.2f}|")
    draw=result["max_drawdown"]
    pnl=result["pnl"]
    lines+=["",f"全期净损益 {pnl['equity_change']:,.2f} 美元。入场日变动 {pnl['entry']:,.2f}，持有期间 {pnl['holding']:,.2f}，退出 {pnl['exit']:,.2f}，费用 {pnl['fees']:,.2f}。",
        "",f"最大回撤 {drawdown:.2%}，净值高点 {draw['peak']}，低点 {draw['trough']}。该区间变动 {draw['pnl']['equity_change']:,.2f} 美元。",
        "", "## 深亏与空仓上涨","","|首次买入|退出|触发机制|净损益（美元）|净收益|","|---|---|---|---:|---:|"]
    for x in worst[:5]:
        label="、".join(f"{k} {names[k]['name']}" for k in x["mechanisms"])
        lines.append(f"|{x['entry_at'][:10]}|{x['exit_at'][:10]}|{label}|{x['net_pnl']:,.2f}|{x['net_return']:.2%}|")
    lines+=["","|空仓起止|天数|同段买持净值变化|","|---|---:|---:|"]
    for x in result["largest_flat_rallies"]:
        lines.append(f"|{x['start']} 至 {x['end']}|{x['sessions']}|{x['benchmark_return']:.2%}|")
    lines+=["","最差交易按美元损益排序，受到当时账户规模影响。空仓上涨按买持净值描述，不能直接计作可避免的损失。"
        "净值对数收益可跨日相加，状态分组包含执行及费用影响。下一轮若研究新规则，须独立验证其完整账户。",
        "", "累计使用 8/10 轮。完整分段、最大回撤账本分项与触发组合见[归因结果](others/results.json)。"]
    body=("\n".join(lines)+"\n").encode()
    (work/"report.md").write_bytes(body)
    report=publish_evidence(ctx,d.ExperimentReportWrite(e,sha256(body).hexdigest(),d.ExperimentOutcome.COMPLETED,evidence))
    check=validate_experiment(repo,d.ExperimentValidationRequest(e,d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert check.status is d.ValidationStatus.PASS
    save(out/"publication.json",{"report":report.to_dict(),"validation":check.to_dict()})
    notes=work/"notes.md"
    notes.write_bytes(notes.read_text(encoding="utf-8").encode())
    intent=read(ROOT/"research/registrations/S018/family.json")["research_intent"]
    intent.update(stage_two_rounds_used=8,latest_attribution=report.to_dict(),
        next_action="已复核固定合并账户深亏与空仓上涨。评审可验证的持有机制再决定剩余轮次。")
    update_research_intent(repo,batch,ResearchIntentUpdate(research_intent=intent),actor="RSCH",
        reason="完成用户批准的既有账户归因")
    print(e.experiment_id,json.dumps({k:result[k] for k in ("full_path","segments","max_drawdown","largest_flat_rallies","pnl","cycles_by_signal_set")},ensure_ascii=False))


if __name__=="__main__":
    main()
