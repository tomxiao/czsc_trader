"""Publish reviewed component result, assemble and FULL validate; no financial runs."""

from hashlib import sha256
import json
import importlib
from pathlib import Path
import sys
from czsc_trader.application import assemble_delivery, publish_evidence, validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
WORK = ROOT / ".tmp/s013-vol-concentration-result"
sys.path.insert(0, str(ROOT / "research/S013/experiments/EX058_20261011/src"))
common = importlib.import_module("common")


def read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def put(ctx, exp, path):
    path = Path(path)
    return publish_evidence(
        ctx,
        MaterialEvidenceWrite(
            exp,
            "vol-" + path.stem,
            path.read_bytes(),
            "text/x-python" if path.suffix == ".py" else "application/json",
            path.suffix[1:],
        ),
    ).to_dict()


def main():
    plan = read(WORK / "plan.json")
    exp = ExperimentRef.from_dict(plan["experiment"])
    protocols = exp.resolve(ROOT) / "protocols"
    refs = {
        **read(protocols / "method_references.json"),
        **read(protocols / "result_references.json"),
        **read(protocols / "audit_references.json"),
    }
    review = read(WORK / "root_review.json")
    if (
        review["status"] != "ROOT_REVIEWED"
        or review["objective_achieved"] is not False
        or review["new_accounts"] != 0
        or review["original_four_hard_gates_changed"] is not False
    ):
        raise ValueError("Component-only root review with unchanged economic gates required")
    if set(review["roles"]) != {"return_4", "downside_4"}:
        raise ValueError("Both fixed h4 labels must be reviewed")
    for key in ("plan.json", "statistics.json", "verification.json"):
        if review["evidence_references"][key] != refs[key]:
            raise ValueError("Root review must bind actual verified evidence")
    for value in refs.values():
        ref = EvidenceRef.from_dict(value)
        if (
            ref.experiment.strategy_id != "S013"
            or sha256(ref.resolve(ROOT).read_bytes()).hexdigest() != ref.sha256
        ):
            raise ValueError("Exact S013 immutable evidence required")
    if read(EvidenceRef.from_dict(refs["verification.json"]).resolve(ROOT))["status"] != "PASS":
        raise ValueError("Independent numerical audit must pass")
    predecessors = tuple(d.DeliveryReference.from_dict(x) for x in plan["predecessors"])
    if (
        len(predecessors) != 1
        or predecessors[0].stage != d.DeliveryStage.MANDATE
        or predecessors[0].revision != 6
        or predecessors[0].content_sha256
        != "e2128159814ccf64784aa50588379e802a581d6e5867349069b0fb0fc751af46"
    ):
        raise ValueError("Exact original MANDATE6 required")
    if (WORK / "closeout_attempt.json").exists():
        raise ValueError("Immutable single closeout attempt")
    ctx = common.context(1)
    write(
        WORK / "closeout_attempt.json",
        {"new_accounts": 0, "statistics_calls": 0, "experiment": exp.to_dict()},
    )
    refs["root_review.json"] = put(ctx, exp, WORK / "root_review.json")
    refs["closeout.py"] = put(ctx, exp, Path(__file__))
    refs["root_review.py"] = put(ctx, exp, ROOT / ".tmp/s013_vol_review.py")
    refs["continuation_budget.json"] = put(ctx, exp, WORK / "continuation_budget.json")
    write(protocols / "continuation_budget_reference.json", refs["continuation_budget.json"])
    tests = tuple(
        d.ComponentTestResult(
            "VOL-CONCENTRATION4-20-" + label.upper(),
            exp.experiment_id,
            EvidenceRef.from_dict(refs["plan.json"]),
            d.ComponentTestStatus(role["status"]),
            role["judgment"],
            tuple(
                EvidenceRef.from_dict(refs[name])
                for name in ("statistics.json", "verification.json", "root_review.json")
            ),
        )
        for label, role in review["roles"].items()
    )
    entry = d.ComponentEntry(
        "HELD-VOL-CONCENTRATION4-20",
        d.ExperimentDefinitionRef(
            EvidenceRef.from_dict(refs[".tmp/s013-vol-concentration/component.py"]), "construct"
        ),
        "原Close近期4日/20日波动集中：固定原实际持仓且T计划继续的h4观察风险与继续收益信息；风险正向、收益负向",
        "未来OpenT+5/OpenT+1-1，两端相同SELL成本抵消；O/C观察下行风险；不是策略账本/账户回撤",
        "固定4个完整session，T信号下一OPEN与第5个未来OPEN比较，原5相位；无h8或期限搜索",
        "原EX07122controls恢复late_recovery及population log-return sigma20共24；raw/partial秩、500x40 seed13、成熟年度ridge10与控制/训练均值两基准",
        "T完成Close；原quantity/fills截至T、已知持仓年龄/浮盈与T当前target；不以未来成交、退出或标签选scope；零波动明确不可用",
        "原510500.SH HFQ开发池2020-01-02..2026-09-30及原2019预热；固定.2803 anchor，无分红重叠，0账户、原1%执行合同保持",
        "已见开发族、单原策略内生持仓池、反事实延长可能跨原未来退出、O/C漏盘中极值；研究相关不能替代可执行盈利及32点验证",
        review["judgment"],
        tests,
    )
    report = (
        review["report_markdown"]
        + "\n\n正式证据：\n\n"
        + "".join(
            f"- [{name}]({EvidenceRef.from_dict(value).path})\n" for name, value in refs.items()
        )
    )
    evidence = tuple(
        dict.fromkeys(
            EvidenceRef.from_dict(value)
            for value in (*refs.values(), *plan["input_references"].values())
        )
    )
    definition = d.DeliveryDefinition(
        d.ResearchBatchRef("S013"), d.DeliveryStage.COMPONENTS, 13, predecessors
    )
    receipt = assemble_delivery(
        ctx.repository,
        definition,
        d.DeliveryContent(
            d.ComponentPanel((entry,), review["judgment"]),
            d.DeliveryStatus.COMPLETE,
            (),
            (),
            report=report,
            evidence=evidence,
        ),
    )
    write(protocols / "delivery_reference.json", receipt.reference.to_dict())
    validation = validate_delivery(
        ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL
    )
    write(protocols / "delivery_validation.json", validation.to_dict())
    write(protocols / "closeout_references.json", refs)
    src = exp.resolve(ROOT) / "src"
    (src / "closeout.py").write_bytes(Path(__file__).read_bytes())
    (src / "root_review.py").write_bytes((ROOT / ".tmp/s013_vol_review.py").read_bytes())
    if validation.status.value != "PASS":
        raise RuntimeError(validation.to_dict())
    print(
        {"experiment": exp.experiment_id, "COMPONENTS": 13, "FULL": "PASS", "new_accounts": 0},
        flush=True,
    )


if __name__ == "__main__":
    main()
