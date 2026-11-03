from pathlib import Path
import sys, json, os
from datetime import date
from hashlib import sha256
from dataclasses import asdict

R = Path(__file__).resolve().parents[1]
os.environ["TMP"] = os.environ["TEMP"] = str(R / ".tmp")
sys.pycache_prefix = str(R / ".tmp/s018-pycache")
import pandas as pd
from dataflows import (AssetClass, BarFrequency, EquityDataRequest, EquityProduct, EquityQuery,
    InstrumentId, MarketId, ProviderConfig, PreparedDataRef, SourceRef)
from czsc_trader.application import (RepositoryContext, create_research_context, create_experiment,
    ExperimentRequest, publish_evidence, validate_experiment)
from czsc_trader import research_tools as d

B = d.ResearchBatchRef("S018")
F = R / "research/S018"
repo = RepositoryContext.discover(R)
ctx = create_research_context(repo, B, providers=ProviderConfig(bindings={}, equity_bindings={}))
start, end = date(2022,1,3), date(2026,10,30)
prep = json.loads((F/"experiments/EX001_20261103/others/daily_preparation.json").read_bytes())
from uuid import UUID
p = prep["reference"]
ref = PreparedDataRef(UUID(p["space_id"]), UUID(p["preparation_id"]), p["manifest_sha256"])
instrument = InstrumentId(MarketId.US, AssetClass.STOCK, "MU")

def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode())

def data(product, source):
    result = ctx.data.fetch(EquityDataRequest(instrument, source, EquityQuery(product,start,end,BarFrequency.DAILY)), prepared=ref)
    if result.dataframe is None:
        raise ValueError(str(result.error))
    return pd.DataFrame(result.dataframe).reset_index(drop=True)

def main():
    e = create_experiment(ctx, ExperimentRequest("MU日线走强后的盈利持续能力",
        "20日收盘新高后还有多少可执行的收益和风险", date(2026,11,3)))
    w = F / "experiments" / e.experiment_id
    out = w / "others"
    out.mkdir(exist_ok=True)
    protocol = dict(signal="Close strictly exceeds previous 20 closes",
        control="all eligible signal days including breakout, same execution rules",
        entry="next session opening improvement or prior close times 1.01 rounded down to cents; strict low touch",
        exit="open after N held sessions", horizons=[5,10,20], fee_per_side=.001,
        development=["2023-01-03","2026-10-30"], comparison_groups=["2023–2024","2025–2026"],
        dividend="include only cash entitlements while holding across ex-date; fixed one-share event diagnostic",
        risk="close marked drawdown including accrued dividends; from entry price",
        limitations="Overlapping opportunities; not independent trades. No optimized parameters. No end-of-window truncation.",
        decision="Use direction of median excess and signal frequency across groups to decide whether to try a complete account.")
    save(out/"protocol.json",protocol)
    def material(name,path):
        return publish_evidence(ctx,d.MaterialEvidenceWrite(e,name,path.read_bytes(),
            "application/json" if path.suffix==".json" else "text/x-python",path.suffix[1:]))
    protocol_ref=material("census-prespecified-protocol",out/"protocol.json")
    f=data(EquityProduct.BARS,SourceRef("futu","s018-mu-daily-20261103"))
    f["day"]=pd.to_datetime(f.Date,utc=True).dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    a=data(EquityProduct.ACTIONS,SourceRef("s018-mu-actions","futu-spglobal-crosscheck-v1"))
    a["day"]=pd.to_datetime(a.Date,utc=True).dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    dividends=dict(zip(a.day,a.CashPerShare,strict=True))
    breakout=f.Close.gt(f.Close.shift().rolling(20).max())
    events=[]
    for i in range(len(f)-21):
        if f.day[i]<"2023-01-03":
            continue
        entry_i=i+1
        limit=int(round(float(f.Close[i])*101,8))/100
        fill=float(min(f.Open[entry_i],limit)) if f.Low[entry_i]<limit else None
        for n in (5,10,20):
            exit_i=entry_i+n
            group="2023–2024" if f.day[i]<"2025-01-01" else "2025–2026"
            if group=="2023–2024" and f.day[exit_i]>="2025-01-01":
                continue
            row=dict(signal_day=f.day[i],entry_day=f.day[entry_i],exit_day=f.day[exit_i],
                     breakout=bool(breakout[i]),n=n,group=group,filled=fill is not None)
            if fill is not None:
                income=0.
                cost=fill*1.001
                marks=[cost]
                for j in range(entry_i,exit_i):
                    if j>entry_i:
                        income+=dividends.get(f.day[j],0.)
                    marks.append(float(f.Close[j])+income)
                income+=dividends.get(f.day[exit_i],0.)
                value=float(f.Open[exit_i])*.999+income
                marks.append(value)
                series=pd.Series(marks)
                row.update(net=value/cost-1,dd=float((1-series/series.cummax()).max()))
            events.append(row)
    f=pd.DataFrame(events)
    summaries=[]
    for (group,n), rows in f.groupby(["group","n"]):
        for name, subset in [("breakout",rows[rows.breakout]),("general",rows)]:
            valid=subset[subset.filled]
            summaries.append(dict(group=group,n=int(n),kind=name,signals=len(subset),fills=len(valid),
                median_net=float(valid.net.median()),win_rate=float(valid.net.gt(0).mean()),
                median_dd=float(valid.dd.median())))
    save(out/"results.json",summaries)
    save(out/"events.json",events)
    source_copy=w/"src"
    source_copy.mkdir(exist_ok=True)
    source_file=source_copy/"census.py"
    source_file.write_bytes(Path(__file__).read_bytes())
    results_ref=material("census-results",out/"results.json")
    event_ref=material("census-events",out/"events.json")
    code_ref=material("census-code",source_file)
    lines=["# MU 日线收益持续普查","","事前固定20日收盘新高，按下一交易日限价及未来固定持有期退出。数据来自阶段一已准备的原始行情及分红。",
        "", "|时段|持有日|入场组|信号/成交|净收益中位|盈利占比|回撤中位|",
        "|---|---:|---|---:|---:|---:|---:|"]
    lines += [f"|{x['group']}|{x['n']}|{x['kind']}|{x['signals']}/{x['fills']}|{x['median_net']:.2%}|{x['win_rate']:.2%}|{x['median_dd']:.2%}|" for x in summaries]
    lines+=["","对照是同期所有可用日期，含信号日。重叠事件用于描述路径，实际账户会受持仓重叠及交易频率约束。回撤按收盘估值。"]
    report=("\n".join(lines)+"\n").encode()
    (w/"report.md").write_bytes(report)
    publication=publish_evidence(ctx,d.ExperimentReportWrite(e,sha256(report).hexdigest(),
        d.ExperimentOutcome.COMPLETED,(protocol_ref,results_ref,event_ref,code_ref)))
    assert validate_experiment(repo,d.ExperimentValidationRequest(e,d.ExperimentValidationScope.REPORT_PUBLICATION)).status is d.ValidationStatus.PASS
    save(out/"publication.json",{"report":publication.to_dict(),"results":results_ref.to_dict(),
        "protocol":protocol_ref.to_dict(),"code":code_ref.to_dict()})
    print(e.experiment_id,json.dumps(summaries,ensure_ascii=False))

if __name__=="__main__":
    main()
