"""Fixed multi-mechanism daily census for S018."""
# ruff: noqa: E402
from collections import Counter
from datetime import date
from hashlib import sha256
from pathlib import Path
from uuid import UUID
import json
import os
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "research/S018/batch.json").is_file())
os.environ["TMP"] = os.environ["TEMP"] = str(ROOT / ".tmp")
sys.pycache_prefix = str(ROOT / ".tmp/s018-pycache")

import pandas as pd
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, create_experiment,
    ExperimentRequest, publish_evidence, validate_experiment)
from dataflows import (AssetClass, BarFrequency, EquityDataRequest, EquityProduct, EquityQuery,
    InstrumentId, MarketId, ProviderConfig, PreparedDataRef, SourceRef)


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


MECHANISMS = {
    "M007": ("连续下跌后的抛压衰竭", "连续三个收盘下跌"),
    "M008": ("大幅收跌后的流动性修复", "收盘跌幅至少为此前20日平均真实振幅的1.5倍"),
    "M009": ("低开缺口当日回补", "低开至少此前20日平均真实振幅的一半，收盘收复前收"),
    "M010": ("放量下影承接反转", "下影占日内振幅至少一半，收于区间上三分之一，成交量至少为此前20日均量1.5倍"),
    "M011": ("震荡区间下沿回归", "此前20日价格净变化不超过总振幅三分之一，触及此前区间下四分之一但收回其上"),
    "M012": ("缩量回撤后的需求恢复", "前一日收跌且量低于此前20日均量0.7倍，当日收复前高"),
    "M013": ("长趋势中的深回撤企稳", "收盘在MA120上方且较此前60日最高收盘回落至少15%，当日收阳并高于前收"),
    "M014": ("中期趋势重新站稳", "收盘从不高于MA60转为高于MA60，且MA60高于20日前"),
    "M015": ("短期相对强势加速", "5日涨幅首次超过此前60日日收益标准差乘以根号5，且收盘高于MA20"),
    "M016": ("内包整理后的上沿突破", "前一日为内包日，当日收盘超过内包日的母线最高价"),
    "M017": ("外包阳线后的方向延续", "当日高低价扩展前日区间，收阳且收盘超过前日最高价"),
    "M018": ("宽幅强收盘后的延续", "日内振幅至少为此前20日平均真实振幅1.5倍，收阳且收于区间上四分之一"),
    "M019": ("尾盘收弱后的短期反弹", "收于区间下五分之一且低于前收，收盘仍高于MA60"),
    "M020": ("两日上涨确认后的跟随", "连续两日收涨，此前一日收跌或持平，且当前收盘高于MA20"),
    "M021": ("放量低进展后的吸收修复", "成交量至少此前20日均量1.5倍，收盘较前收变化不超过0.25倍平均真实振幅，且收于当日区间中点以上"),
    "M022": ("月初资金流时点效应", "当月首个已完成交易日"),
    "M023": ("月末前资金流时点效应", "距自然月末1至4个自然日且当日为交易日"),
    "M024": ("除息后的价格修复", "当日为已生效的现金分红除息日"),
}


def signals(f, dividends):
    prev = f.Close.shift()
    ret = f.Close.pct_change()
    tr = pd.concat([f.High - f.Low, (f.High - prev).abs(), (f.Low - prev).abs()], axis=1).max(axis=1)
    atr = tr.shift().rolling(20).mean()
    volume = f.Volume.shift().rolling(20).mean()
    sma20, sma60, sma120 = (f.Close.rolling(n).mean() for n in (20, 60, 120))
    span = f.High - f.Low
    loc = (f.Close - f.Low) / span.where(span.gt(0))
    lo, hi = f.Low.shift().rolling(20).min(), f.High.shift().rolling(20).max()
    lower = lo + .25 * (hi - lo)
    r5 = f.Close.pct_change(5)
    sigma5 = ret.shift().rolling(60).std() * 5 ** .5
    days = pd.to_datetime(f.day)
    month = days.dt.to_period("M")
    return {
        "M007": ret.lt(0) & ret.shift().lt(0) & ret.shift(2).lt(0),
        "M008": (prev - f.Close).ge(1.5 * atr),
        "M009": (prev - f.Open).ge(.5 * atr) & f.Close.ge(prev),
        "M010": (f[["Open", "Close"]].min(axis=1) - f.Low).ge(.5 * span)
                & loc.ge(2 / 3) & f.Volume.ge(1.5 * volume),
        "M011": (prev - f.Close.shift(21)).abs().le((hi - lo) / 3) & f.Low.le(lower) & f.Close.gt(lower),
        "M012": ret.shift().lt(0) & f.Volume.shift().lt(.7 * volume.shift()) & f.Close.gt(f.High.shift()),
        "M013": f.Close.gt(sma120) & f.Close.le(.85 * prev.rolling(60).max()) & f.Close.gt(f.Open) & f.Close.gt(prev),
        "M014": f.Close.gt(sma60) & prev.le(sma60.shift()) & sma60.gt(sma60.shift(20)),
        "M015": r5.gt(sigma5) & r5.shift().le(sigma5.shift()) & f.Close.gt(sma20),
        "M016": f.High.shift().lt(f.High.shift(2)) & f.Low.shift().gt(f.Low.shift(2)) & f.Close.gt(f.High.shift(2)),
        "M017": f.High.gt(f.High.shift()) & f.Low.lt(f.Low.shift()) & f.Close.gt(f.Open) & f.Close.gt(f.High.shift()),
        "M018": span.ge(1.5 * atr) & f.Close.gt(f.Open) & loc.ge(.75),
        "M019": loc.le(.2) & f.Close.lt(prev) & f.Close.gt(sma60),
        "M020": ret.gt(0) & ret.shift().gt(0) & ret.shift(2).le(0) & f.Close.gt(sma20),
        "M021": f.Volume.ge(1.5 * volume) & (f.Close - prev).abs().le(.25 * atr) & loc.ge(.5),
        "M022": month.ne(month.shift()),
        "M023": (days.dt.days_in_month - days.dt.day).between(1, 4),
        "M024": f.day.isin(dividends),
    }


def main():
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef("S018")
    folder = ROOT / "research/S018"
    ctx = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
    e = create_experiment(ctx, ExperimentRequest("MU新增18种日线机制普查",
        "对照M007至M024的固定条件收益和机会密度", date(2026, 11, 3)))
    w = folder / "experiments" / e.experiment_id
    out = w / "others"
    out.mkdir(exist_ok=True)
    index = {k: {"name": n, "rule": rule, "experiment": e.experiment_id} for k, (n, rule) in MECHANISMS.items()}
    save(out / "mechanism_additions.json", index)
    protocol = {"mechanisms": index, "development": ["2023-01-03", "2026-10-30"],
        "segments": ["2023–2024", "2025–2026"], "horizons": [5, 10, 20],
        "entry": "下一交易日按信号收盘×1.01向下取整至分的买入限价。开盘不高于限价按开盘，否则最低价严格低于限价按限价",
        "exit": "持有N日后的下一日开盘，单侧0.1%，计持仓分红权益",
        "control": "每段同期全部可观察日期，包括触发日",
        "coverage": "按最早退出优先去重，同日退出和再次入场也视为重叠。频率仅为固定持有期事件诊断",
        "risk": "单股、收盘净值及退出价的持有回撤，不用入场日盘中极值",
        "scope": "所有参数事前固定。阶段二事件研究。成交量为供应商日线口径，信号采用RAW",
        "decision": "优先看两段都优于同期一般入场的收益中位数及回撤，其次看成交数量与非重叠覆盖。保留稀少和负面结果。"}
    save(out / "protocol.json", protocol)

    def material(name, path, media="application/json"):
        return publish_evidence(ctx, d.MaterialEvidenceWrite(e, name, path.read_bytes(), media, path.suffix[1:]))

    protocol_ref = material("mu-broad-census-protocol", out / "protocol.json")
    p = json.loads((folder / "experiments/EX001_20261103/others/daily_preparation.json").read_bytes())["reference"]
    prepared = PreparedDataRef(UUID(p["space_id"]), UUID(p["preparation_id"]), p["manifest_sha256"])
    inst = InstrumentId(MarketId.US, AssetClass.STOCK, "MU")

    def data(product, source):
        result = ctx.data.fetch(EquityDataRequest(inst, source,
            EquityQuery(product, date(2022, 1, 3), date(2026, 10, 30), BarFrequency.DAILY)), prepared=prepared)
        if result.dataframe is None:
            raise ValueError(str(result.error))
        frame = pd.DataFrame(result.dataframe).reset_index(drop=True)
        frame["day"] = pd.to_datetime(frame.Date, utc=True).dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
        return frame

    f = data(EquityProduct.BARS, SourceRef("futu", "s018-mu-daily-20261103"))
    a = data(EquityProduct.ACTIONS, SourceRef("s018-mu-actions", "futu-spglobal-crosscheck-v1"))
    dividends = dict(zip(a.day, a.CashPerShare, strict=True))
    flags = signals(f, dividends)
    events = []
    for i in range(len(f) - 21):
        if f.day[i] < "2023-01-03":
            continue
        limit = int(round(float(f.Close[i]) * 101, 8)) / 100
        entry = i + 1
        fill = float(f.Open[entry]) if f.Open[entry] <= limit else limit if f.Low[entry] < limit else None
        group = "2023–2024" if f.day[i] < "2025-01-01" else "2025–2026"
        for n in (5, 10, 20):
            exit_i = entry + n
            if group == "2023–2024" and f.day[exit_i] >= "2025-01-01":
                continue
            row = dict(signal_day=f.day[i], entry=entry, exit=exit_i, exit_day=f.day[exit_i], n=n,
                       group=group, mechanisms=[k for k, flag in flags.items() if flag[i]], filled=fill is not None)
            if fill is not None:
                income = 0.
                cost = fill * 1.001
                peak, dd = cost, 0.
                for j in range(entry, exit_i + 1):
                    if j > entry:
                        income += dividends.get(f.day[j], 0.)
                    value = (float(f.Open[j]) * .999 if j == exit_i else float(f.Close[j])) + income
                    peak = max(peak, value)
                    dd = max(dd, 1 - value / peak)
                row.update(net=value / cost - 1, dd=dd)
            events.append(row)
    events_frame = pd.DataFrame(events)
    groups = ("2023–2024", "2025–2026")
    summaries = []
    for n in (5, 10, 20):
        subset = events_frame[events_frame.n.eq(n)]
        for k in ("GENERAL", *MECHANISMS):
            rows = subset if k == "GENERAL" else subset[subset.mechanisms.map(lambda keys: k in keys)]
            filled = rows[rows.filled]
            picked, last = [], -1
            for item in filled.itertuples():
                if item.entry > last:
                    picked.append(item.exit)
                    last = item.exit
            counts = Counter(picked)
            dev_start = int(f.index[f.day.eq("2023-01-03")][0])
            closed_windows = [sum(counts[j] for j in range(i, i+60)) for i in range(dev_start, len(f)-59)]
            for group in groups:
                valid = filled[filled.group.eq(group)]
                event_count = int(rows.group.eq(group).sum())
                summaries.append(dict(id=k, group=group, n=n, signals=event_count, fills=len(valid),
                    non_overlapping=sum(1 for j in picked if (f.day[j] < "2025-01-01") == (group == groups[0])),
                    median_net=None if valid.empty else float(valid.net.median()),
                    q10_net=None if valid.empty else float(valid.net.quantile(.1)),
                    median_dd=None if valid.empty else float(valid.dd.median()),
                    full_nonoverlap_frequency_median=float(pd.Series(closed_windows).median()),
                    full_nonoverlap_coverage=sum(x >= 3 for x in closed_windows) / len(closed_windows)))
    save(out / "results.json", summaries)
    save(out / "events.json", events)
    src = w / "src"
    src.mkdir(exist_ok=True)
    code_path = src / "census.py"
    code_path.write_bytes(Path(__file__).read_bytes())
    rr = material("mu-broad-census-results", out / "results.json")
    er = material("mu-broad-census-events", out / "events.json")
    cr = material("mu-broad-census-code", code_path, "text/x-python")
    fmt = lambda v: "—" if v is None else f"{v:.2%}"
    report = ["# MU 日线多机制普查", "", "采用 5、10、20 日固定持有期。下表为 5 日结果，完整期限见逐项汇总。",
        "", "|时段|机制|信号/成交|非重叠次数|净收益中位|净收益Q10|持有回撤中位|",
        "|---|---|---:|---:|---:|---:|---:|"]
    for row in [x for x in summaries if x["n"] == 5]:
        name = "同期一般机会" if row["id"] == "GENERAL" else f"{row['id']} {MECHANISMS[row['id']][0]}"
        report.append(f"|{row['group']}|{name}|{row['signals']}/{row['fills']}|{row['non_overlapping']}|"
                      f"{fmt(row['median_net'])}|{fmt(row['q10_net'])}|{fmt(row['median_dd'])}|")
    report += ["", "[完整期限汇总](others/results.json)和[固定方案](others/protocol.json)。"
               "重叠事件不提供独立样本，去重频率仅描述固定持有期的机会密度。"]
    body = ("\n".join(report) + "\n").encode()
    (w / "report.md").write_bytes(body)
    published = publish_evidence(ctx, d.ExperimentReportWrite(e, sha256(body).hexdigest(),
        d.ExperimentOutcome.COMPLETED, (protocol_ref, rr, er, cr)))
    assert validate_experiment(repo, d.ExperimentValidationRequest(e,
        d.ExperimentValidationScope.REPORT_PUBLICATION)).status is d.ValidationStatus.PASS
    save(out / "publication.json", {"report": published.to_dict(), "protocol": protocol_ref.to_dict(),
        "results": rr.to_dict(), "code": cr.to_dict()})
    for x in summaries:
        print(x["id"], x["n"], x["group"], x["fills"], x["non_overlapping"],
              fmt(x["median_net"]), fmt(x["median_dd"]), x["full_nonoverlap_frequency_median"])


if __name__ == "__main__":
    main()
