"""Compare opportunity overlap using the existing EX006 five-session events."""
# ruff: noqa: E402
from collections import Counter
from datetime import date
from hashlib import sha256
from itertools import combinations
from pathlib import Path
import json
import os
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p/"research/S018/batch.json").is_file())
os.environ["TMP"] = os.environ["TEMP"] = str(ROOT/".tmp")
sys.pycache_prefix = str(ROOT/".tmp/s018-pycache")

import pandas as pd
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, create_experiment,
    ExperimentRequest, publish_evidence, validate_experiment, update_research_intent, ResearchIntentUpdate)
from dataflows import ProviderConfig


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode())


def main():
    folder = ROOT/"research/S018"
    source = folder/"experiments/EX006_20261103"
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef("S018")
    context = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
    keys = ("M007","M015","M022")
    names = read(folder/"materials/mechanism_index.json")["mechanisms"]
    events_path = source/"others/events.json"
    all_events = [x for x in read(events_path) if x["n"] == 5]
    preparation = read(folder/"experiments/EX001_20261103/others/daily_preparation.json")
    sessions = preparation["sessions"]
    start = sessions - preparation["observed_development_sessions"]
    events = [dict(x, selected=[k for k in keys if k in x["mechanisms"]])
        for x in all_events if set(x["mechanisms"]).intersection(keys)]
    fills = [x for x in events if x["filled"]]
    e = create_experiment(context, ExperimentRequest("MU三类机制的重合与风险复核",
        "按固定5日口径检验合并能否增加非重叠交易机会", date(2026,11,3)))
    work = folder/"experiments"/e.experiment_id
    out = work/"others"
    out.mkdir(exist_ok=True)
    policy = {"mechanisms": list(keys), "holding_sessions": 5, "source": source.name,
        "source_event_file_sha256": sha256(events_path.read_bytes()).hexdigest(),
        "selection": "同日只计一次，按最早入场优先，入场须严格晚于上一笔退出。全期连续去重。",
        "risk": "查看保留事件最差10%及其信号月份。事件收益无复利或账户归因。",
        "decision": "如固定方案的闭合频率仍有明显缺口，优先解释缺口而非构建账户。"}
    save(out/"protocol.json",policy)

    def material(name,path,media="application/json"):
        return publish_evidence(context,d.MaterialEvidenceWrite(e,name,path.read_bytes(),media,path.suffix[1:]))

    protocol_ref = material("mu-overlap-protocol",out/"protocol.json")

    def select(rows):
        accepted, rejected = [], []
        for x in sorted(rows,key=lambda r:r["entry"]):
            (accepted if not accepted or x["entry"] > accepted[-1]["exit"] else rejected).append(x)
        return accepted,rejected

    def statistics(rows):
        accepted, rejected = select(rows)
        counts = Counter(x["exit"] for x in accepted)
        windows = [sum(counts[j] for j in range(i,i+60)) for i in range(start,sessions-59)]
        net = pd.Series([x["net"] for x in accepted])
        tail = sorted(accepted,key=lambda x:x["net"])[:max(1,(len(accepted)+9)//10)]
        return {"fills":len(rows),"accepted":len(accepted),"conflicts":len(rejected),
            "median60":float(pd.Series(windows).median()),"coverage_count":sum(x>=3 for x in windows),
            "windows":len(windows),"min60":min(windows),"max60":max(windows),
            "median_net":float(net.median()),"q10":float(net.quantile(.1)),
            "tail_months":dict(Counter(x["signal_day"][:7] for x in tail)),
            "tail":[{k:x[k] for k in ("signal_day","selected","net","dd")} for x in tail],
            "segment_medians": {group:float(pd.Series([x["net"] for x in accepted if x["group"]==group]).median())
                for group in ("2023–2024","2025–2026")}}

    individual = {k:statistics([x for x in fills if k in x["selected"]]) for k in keys}
    union = statistics(fills)
    pairs = {}
    for a,b in combinations(keys,2):
        aa, bb = ([x for x in fills if k in x["selected"]] for k in (a,b))
        pairs[a+"+"+b] = {"same_signal_day":len({x["signal_day"] for x in aa}&{x["signal_day"] for x in bb}),
            "overlap_interval_pairs":sum(x["entry"]<=y["exit"] and y["entry"]<=x["exit"] for x in aa for y in bb)}
    result = {"rounds_used":6,"rounds_authorized":10,"distinct_signals":len(events),
        "same_day_multi_mechanism_fills":sum(len(x["selected"])>1 for x in fills),
        "pairs":pairs,"individual":individual,"union":union}
    save(out/"results.json",result)
    src=work/"src"
    src.mkdir(exist_ok=True)
    (src/"overlap.py").write_bytes(Path(__file__).read_bytes())
    rr=material("mu-overlap-results",out/"results.json")
    cr=material("mu-overlap-code",src/"overlap.py","text/x-python")
    lines=["# MU 三类机制的重合与风险复核","","按 EX006 原有 5 日事件、成交及费用口径复用结果。"
        "同日多触发只计一次，持有区间重合时优先较早入场。两笔交易同日退出和入场视为冲突。","",
        "|机制|成交日期|非重叠闭合|60日中位|至少3笔覆盖|扣费收益中位|收益Q10|",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for name, x in [(f"{k} {names[k]['name']}",individual[k]) for k in keys]+[("三者合并",union)]:
        lines.append(f"|{name}|{x['fills']}|{x['accepted']}|{x['median60']:.0f}|"
            f"{x['coverage_count']}/{x['windows']}|{x['median_net']:.2%}|{x['q10']:.2%}|")
    base=max(x["accepted"] for x in individual.values())
    med_ok=union["median60"]>=6
    cov_ok=union["coverage_count"]*10>=union["windows"]*9
    judgment=("机会密度值得进行一个固定规则账户检验，回撤与Calmar仍需由账户核验。"
        if med_ok and cov_ok else "固定合并的机会密度仍低于正式要求，当前建议先保留事件证据。")
    lines += ["",f"合并比最佳单机制多 {union['accepted']-base} 笔，持有冲突排除 {union['conflicts']} 笔。"
        f"全期同日多机制成交 {result['same_day_multi_mechanism_fills']} 次。{judgment}",
        "", "事件收益为单笔路径描述。收益最差约一成的事件及月份、逐对重叠见[核验结果](others/results.json)。"
        "此轮未运行策略账户。累计使用 6/10 轮。"]
    body=("\n".join(lines)+"\n").encode()
    (work/"report.md").write_bytes(body)
    source_ref=d.EvidenceRef.from_dict(read(source/"report_ref.json")["report"])
    report=publish_evidence(context,d.ExperimentReportWrite(e,sha256(body).hexdigest(),
        d.ExperimentOutcome.COMPLETED,(source_ref,protocol_ref,rr,cr)))
    check=validate_experiment(repo,d.ExperimentValidationRequest(e,d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert check.status is d.ValidationStatus.PASS
    save(out/"publication.json",{"report":report.to_dict(),"validation":check.to_dict()})
    notes=work/"notes.md"
    notes.write_bytes(notes.read_text(encoding="utf-8").encode())
    family=read(ROOT/"research/registrations/S018/family.json")
    intent=family["research_intent"]
    intent.update(stage_two_rounds_used=6,latest_overlap=report.to_dict(),next_action=judgment)
    update_research_intent(repo,batch,ResearchIntentUpdate(research_intent=intent),
        actor="RSCH",reason="复核三机制的真实重合及非重叠机会")
    handoff=folder/"HANDOFF.md"
    text=handoff.read_text(encoding="utf-8")
    marker="## 当前阶段二结论\n\n"
    text=text.replace(marker,marker+f"[EX007](experiments/{e.experiment_id}/report.md) 完成三机制重合复核。"
        f"累计 6/10 轮。{judgment}\n\n",1)
    handoff.write_bytes(text.encode())
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
