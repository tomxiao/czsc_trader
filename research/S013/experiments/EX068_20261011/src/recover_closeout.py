"""Resume original EX068 assembly after existing S013 batch lock releases."""

from driver import WORK, ROOT, common, read, write, put
from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef


def main():
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    plan = read(WORK / "plan.json")
    ctx = common.context(1)
    refs = read(exp.resolve(ROOT) / "protocols/verification_references.json")
    review = read(WORK / "judgment.json")
    report = (WORK / "report.md").read_text(encoding="utf-8")
    report += "\n\n首次交付发布遇同S013批次EX067的发布锁占用；原统计与判断保持，保留失败记录后顺序恢复同一COMPONENTS7，没有删除锁、改平台或另建实验。"
    for n in (
        "compact_statistics.json",
        "judgment.json",
        "conclusion.json",
        "report.md",
        "finish.py",
        "failed_closeout.json",
        "recover_closeout.py",
    ):
        refs[n] = put(ctx, exp, WORK / n)
        if n.endswith(".py"):
            (exp.resolve(ROOT) / "src" / n).write_bytes((WORK / n).read_bytes())
    entries = []
    for c in ("early_down_share", "max_down_run_share"):
        j = review[c]
        test = d.ComponentTestResult(
            c.upper() + "-H4",
            exp.experiment_id,
            EvidenceRef.from_dict(refs["plan.json"]),
            d.ComponentTestStatus(j["status"]),
            j["judgment"],
            tuple(
                EvidenceRef.from_dict(refs[n])
                for n in ("statistics.json", "verification.json", "judgment.json")
            ),
        )
        entries.append(
            d.ComponentEntry(
                c.upper(),
                d.ExperimentDefinitionRef(EvidenceRef.from_dict(refs["driver.py"]), "study"),
                "日内下跌顺序与连续段的新入场增量",
                "return4/downside4主，return8/downside8辅",
                "T+1开盘至T+1+h开盘",
                "18controls；500x40块seed13；成熟顺序训练ridge10，四模型同样本",
                "T8根30m完成，T+1可用；历史实际发布时间未独立验证",
                "原HFQ，两侧10bp开盘代理，无分红叠加",
                "S013已见全池/过去20日下跌/原信号空仓资格，非封存",
                j["judgment"],
                (test,),
            )
        )
    links = "\n## 正式证据引用\n\n" + "".join(
        f"- [{n}]({EvidenceRef.from_dict(r).path})\n" for n, r in refs.items()
    )
    receipt = assemble_delivery(
        ctx.repository,
        d.DeliveryDefinition(
            ctx.batch,
            d.DeliveryStage.COMPONENTS,
            7,
            tuple(d.DeliveryReference.from_dict(x) for x in plan["predecessors"]),
        ),
        d.DeliveryContent(
            payload=d.ComponentPanel(
                tuple(entries), "日内顺序增量不足；局部收益事实不等于亏损年份达标"
            ),
            status=d.DeliveryStatus.COMPLETE,
            facts=(),
            explanations=(),
            report=report + links,
            evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(x) for x in refs.values())),
        ),
    )
    validation = validate_delivery(
        ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL
    )
    for n, value in (
        ("delivery_reference.json", receipt.reference.to_dict()),
        ("delivery_validation.json", validation.to_dict()),
        ("final_evidence_references.json", refs),
    ):
        write(exp.resolve(ROOT) / "protocols" / n, value)
    (exp.resolve(ROOT) / "others").mkdir(exist_ok=True)
    (exp.resolve(ROOT) / "others/report.md").write_text(
        report
        + "\n## 正式证据引用\n\n"
        + "".join(
            f"- [{n}](../../../assets/deliveries/COMPONENTS/7/{EvidenceRef.from_dict(r).path})\n"
            for n, r in refs.items()
        ),
        encoding="utf-8",
    )
    assert validation.status.value == "PASS", validation.to_dict()
    assert not common.SOURCE_CALLS
    print(
        {"experiment": exp.experiment_id, "FULL": validation.status.value, "goal_achieved": False},
        flush=True,
    )


if __name__ == "__main__":
    main()
