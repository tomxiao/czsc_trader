"""Root-reviewed standalone COMPONENTS10 closeout; do not run before authorization."""

from pathlib import Path
from driver_pricefix import ROOT, WORK, common, read, write, public, check, put
from czsc_trader.application import assemble_delivery, validate_delivery, publish_evidence
from czsc_trader.research_tools import delivery as d, MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef


def typed_status(review):
    if review["component_status"] != "LIMITED_SUPPORT_FOR_FIXED_HOLDING_TEST":
        raise ValueError(
            "only the explicit root fixed-holding limited-support judgment is accepted"
        )
    return d.ComponentTestStatus.SUPPORTED


def report_links(refs, prefix=""):
    return "\n## 正式证据引用\n\n" + "".join(
        f"- [{name}]({prefix}{EvidenceRef.from_dict(ref).path})\n" for name, ref in refs.items()
    )


def main():
    approval = read(WORK / "root_delivery_authorization.json")
    assert approval["authorized"] is True and approval["revision"] == 10
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    plan = read(WORK / "plan.json")
    check(plan)
    refs = read(exp.resolve(ROOT) / "protocols/complete_result_references.json")
    assert read(public(refs["verification.json"]))["status"] == "PASS"
    review = read(WORK / "root_review.json")
    assert review["status"] == "ROOT_SCIENTIFIC_REVIEWED"
    assert review["statistics_reference"] == refs["statistics.json"]
    assert review["verification_reference"] == refs["verification.json"]
    assert review["objective_achieved"] is False and review["new_accounts"] == 0
    assert review["component_status"] == "LIMITED_SUPPORT_FOR_FIXED_HOLDING_TEST"
    # Platform enum carries supported risk-role information; full scientific scope
    # remains LIMITED_SUPPORT_FOR_FIXED_HOLDING_TEST in review/report/judgment.
    j = {"status": typed_status(review).value, "judgment": review["judgment"]}
    report = review["report_markdown"]
    path = WORK / "report.md"
    assert not path.exists()
    path.write_text(report, "utf-8")
    ctx = common.context(1)
    for name in (
        "root_review.json",
        "root_review_writer.py",
        "root_delivery_authorization.json",
        "finish.py",
        "closeout_checks.py",
        "closeout_checks.json",
    ):
        refs[name] = put(ctx, exp, WORK / name)
    refs["report.md"] = publish_evidence(
        ctx, MaterialEvidenceWrite(exp, "report", path.read_bytes(), "text/markdown", "md")
    ).to_dict()
    test = d.ComponentTestResult(
        "PRESSURE-ENTRY-LATE-H2-TO-H4",
        exp.experiment_id,
        EvidenceRef.from_dict(refs["plan.json"]),
        d.ComponentTestStatus(j["status"]),
        j["judgment"],
        tuple(
            EvidenceRef.from_dict(refs[n])
            for n in (
                "statistics.json",
                "verification.json",
                "root_review.json",
                "execution_receipt.json",
            )
        ),
    )
    entry = d.ComponentEntry(
        "PRESSURE-ENTRY-LATE-CONTINUATION",
        d.ExperimentDefinitionRef(EvidenceRef.from_dict(refs["driver_pricefix.py"]), "study"),
        "真实原bear入场时冻结4日隔夜压力主导标记",
        "主第3-4日继续收益/OPEN-CLOSE下行观察风险；first2/full4只作描述与乘法分解",
        "Open[T+3]至Open[T+5]，风险O/C[T+3,T+4]+最后Open；不跨样本筛选原未来退出",
        "原14固定控制，raw/partial Spearman，rankDF至少10/n至少20；500x40全交易日轴seed13，全部状态保留，0预测模型",
        "T信息冻结，实际fill认证T+1入场；actual-filled子池不是T时可部署过滤，原提前退出也保留反事实价格标签",
        "原HFQ研究单位/anchor .2803，固定同数量两端卖费抵消，无新BUY费；原1%执行与四门不改，0新账户",
        "单一真实bear入场池，原开发池已见/选择偏差未修正；flag15薄、年度/相位不足、不声称账户或抗扰动合格",
        j["judgment"],
        (test,),
    )
    links = report_links(refs)
    predecessor = d.DeliveryReference.from_dict(
        plan["delivery_lineage"]["permitted_stage_predecessor"]
    )
    receipt = assemble_delivery(
        ctx.repository,
        d.DeliveryDefinition(ctx.batch, d.DeliveryStage.COMPONENTS, 10, (predecessor,)),
        d.DeliveryContent(
            d.ComponentPanel((entry,), j["judgment"]),
            d.DeliveryStatus.COMPLETE,
            (),
            (),
            report=report + links,
            evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(x) for x in refs.values())),
        ),
    )
    write(exp.resolve(ROOT) / "protocols/delivery_reference.json", receipt.reference.to_dict())
    validation = validate_delivery(
        ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL
    )
    write(exp.resolve(ROOT) / "protocols/delivery_validation.json", validation.to_dict())
    write(exp.resolve(ROOT) / "protocols/final_evidence_references.json", refs)
    assert validation.status.value == "PASS", validation.to_dict()
    assert not common.SOURCE_CALLS
    Path(exp.resolve(ROOT) / "others").mkdir(exist_ok=True)
    (exp.resolve(ROOT) / "others/report.md").write_text(
        report + report_links(refs, "../../../assets/deliveries/COMPONENTS/10/"), "utf-8"
    )
    print(
        {
            "experiment": exp.experiment_id,
            "FULL": validation.status.value,
            "objective_achieved": False,
        },
        flush=True,
    )


if __name__ == "__main__":
    main()
