"""EX076 COMPONENTS12 source-only draft; main requires separate exact authority."""

from hashlib import sha256
import json
from pathlib import Path
import sys

from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef

EXPERIMENT = ExperimentRef("S013", "EX076_20261011")
PLAN_SHA = "570ab22bb01e945db96e9facf7dff52b8061500245df74e7a76084295d249a05"
MANDATE_SHA = "e2128159814ccf64784aa50588379e802a581d6e5867349069b0fb0fc751af46"
SCOPES = ("all", "causal_original_policy_flat_eligible")


def read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def evidence(root, value):
    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != "S013":
        raise ValueError("S013-only immutable evidence required")
    path = ref.resolve(root)
    if digest(path) != ref.sha256:
        raise ValueError("evidence content hash mismatch")
    return ref, path


def build_payload(review, refs):
    """Pure typed assembly: no evidence resolve, statistics or publication."""
    if set(review["roles"]) != set(SCOPES):
        raise ValueError(
            "exactly both predeclared return4 scopes required; risk is diagnostic only"
        )
    if review["objective_achieved"] is not False or review["new_accounts"] != 0:
        raise ValueError("component-only evidence cannot prove financial target")
    if review["original_four_hard_gates_changed"] is not False:
        raise ValueError("original four financial gates remain unchanged")
    if review["return_direction"] != "positive" or review["risk_role"] != "DIAGNOSTIC_ONLY":
        raise ValueError("positive return prior and diagnostic-only risk unchanged")
    tests = tuple(
        d.ComponentTestResult(
            "PRICE-CURVATURE4-RETURN4-" + scope.upper(),
            EXPERIMENT.experiment_id,
            EvidenceRef.from_dict(refs["plan.json"]),
            d.ComponentTestStatus(review["roles"][scope]["status"]),
            review["roles"][scope]["judgment"],
            tuple(
                EvidenceRef.from_dict(refs[name])
                for name in ("statistics.json", "verification.json", "root_review.json")
            ),
        )
        for scope in SCOPES
    )
    entry = d.ComponentEntry(
        "PRICE-CURVATURE4",
        d.ExperimentDefinitionRef(EvidenceRef.from_dict(refs["component.py"]), "build_features"),
        "已有Close的四日时间曲率；固定正向未来四日净收益信息，全池与原策略空仓资格池分别评审",
        "主return4_net，两侧各10bp费用；downside4_oc仅诊断报告，无交易或退出用途",
        "T+1 OPEN入场至T+5 OPEN：四个完整执行session；风险观察同期O/C，不是实际账户回撤",
        "固定17控制(EX06614+EX0612+正short_stretch4)；raw/partial Spearman、500x40全T轴seed13；年度成熟训练17 vs17+x及pastmean，五相位，禁止优化/挑池",
        "T已完成daily Close，20日样本波动ddof1与4日曲率，无epsilon/历史填补；原N0完整决策prefix2019-12-31..2026-09-29先shift再reindex1635信号日，资格由entry_eligible和前日target0，非实际成交持仓",
        "原510500 HFQ后复权；认证2019 native anchor和原执行sessions2020-01-02..2026-09-30；理想OPEN费用标签非原1% LimitBuyHold账本；原四门保持，0账户",
        "同一原1635全T轴，两池仅mask目标，不删日期/成熟边界/bootstrap/相位；不选较好池替坏池；风险仅诊断；保留2022/2023及薄样本、已有开发族选择偏差；不证明账户或抗扰动达标",
        review["judgment"],
        tests,
    )
    return d.ComponentPanel((entry,), review["judgment"])


def report_links(refs):
    return "\n\n正式证据：\n\n" + "".join(
        f"- [{name}]({EvidenceRef.from_dict(value).path})\n" for name, value in refs.items()
    )


def run(authority_path):
    """One separately authorized formal closeout, no accounts or stats."""
    work = Path(__file__).resolve().parent
    root = next(p for p in work.parents if (p / "pyproject.toml").exists())
    approval = read(authority_path)
    freeze = read(work / "freeze.json")
    if (
        approval.get("status") != "APPROVED_EX076_COMPONENTS12_CLOSEOUT"
        or approval.get("source_freeze_sha256") != digest(work / "freeze.json")
        or approval.get("experiment") != EXPERIMENT.to_dict()
    ):
        raise PermissionError("separate exact root closeout authorization required")
    for name, expected in freeze["source_files"].items():
        if Path(name).name != name or digest(work / name) != expected:
            raise ValueError("closeout source changed or illegal path")
    if (work / "formal_attempt.json").exists():
        raise ValueError("single formal attempt; root handles any recovery")
    refs = dict(approval["evidence_references"])
    required = {
        "plan.json",
        "statistics.json",
        "verification.json",
        "root_review.json",
        "component.py",
    }
    if not required.issubset(refs):
        raise ValueError("actual plan/statistics/verification/review/source refs required")
    paths = {name: evidence(root, value)[1] for name, value in refs.items()}
    if refs["plan.json"]["sha256"] != PLAN_SHA:
        raise ValueError("original EX076 prospective plan changed")
    for name in required:
        if EvidenceRef.from_dict(refs[name]).experiment != EXPERIMENT:
            raise ValueError("actual EX076 primary evidence required")
    plan = read(paths["plan.json"])
    predecessors = tuple(d.DeliveryReference.from_dict(x) for x in plan["predecessors"])
    if len(predecessors) != 1 or (
        predecessors[0].stage != d.DeliveryStage.MANDATE
        or predecessors[0].batch != d.ResearchBatchRef("S013")
        or predecessors[0].revision != 6
        or predecessors[0].content_sha256 != MANDATE_SHA
    ):
        raise ValueError("MANDATE6 sole exact predecessor required")
    review = read(paths["root_review.json"])
    if review["status"] != "ROOT_SCIENTIFIC_REVIEWED":
        raise ValueError("actual root scientific review required")
    for name in ("plan.json", "statistics.json", "verification.json"):
        if review["evidence_references"][name] != refs[name]:
            raise ValueError("root review must bind actual evidence exactly")
    if read(paths["verification.json"])["status"] != "PASS":
        raise ValueError("independent actual statistics/input verification required")
    panel = build_payload(review, refs)
    definition = d.DeliveryDefinition(
        d.ResearchBatchRef("S013"), d.DeliveryStage.COMPONENTS, 12, predecessors
    )
    # Imports are intentionally after exact authority and all pre-mutation guards.
    from czsc_trader.application import assemble_delivery, publish_evidence, validate_delivery
    from czsc_trader.research_tools import MaterialEvidenceWrite
    import importlib

    common_source = root / "research/S013/experiments/EX058_20261011/src/common.py"
    if digest(common_source) != "f38c71d3392fb791fdd064f366cc251e33c064d7b88a0cd8b737f2603ccf236b":
        raise ValueError("original authorized context helper changed")
    sys.path.insert(0, str(common_source.parent))
    common = importlib.import_module("common")
    if Path(common.__file__).resolve() != common_source.resolve():
        raise ValueError("different common module already imported")
    ctx = common.context(1)
    write_new(
        work / "formal_attempt.json",
        {"experiment": EXPERIMENT.to_dict(), "new_accounts": 0, "statistics_runs": 0},
    )
    for name in ("postprocess.py", "checks.py", "checks.json", "freeze.json"):
        path = work / name
        refs["closeout_" + name] = publish_evidence(
            ctx,
            MaterialEvidenceWrite(
                EXPERIMENT,
                "closeout-" + path.stem,
                path.read_bytes(),
                "text/x-python" if path.suffix == ".py" else "application/json",
                path.suffix[1:],
            ),
        ).to_dict()
    refs["root_closeout_authorization.json"] = publish_evidence(
        ctx,
        MaterialEvidenceWrite(
            EXPERIMENT,
            "root-closeout-authorization",
            Path(authority_path).read_bytes(),
            "application/json",
            "json",
        ),
    ).to_dict()
    receipt = assemble_delivery(
        ctx.repository,
        definition,
        d.DeliveryContent(
            panel,
            d.DeliveryStatus.COMPLETE,
            (),
            (),
            report=review["report_markdown"] + report_links(refs),
            evidence=tuple(dict.fromkeys(EvidenceRef.from_dict(x) for x in refs.values())),
        ),
    )
    protocols = EXPERIMENT.resolve(root) / "protocols"
    write_new(protocols / "delivery_reference.json", receipt.reference.to_dict())
    validation = validate_delivery(
        ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL
    )
    write_new(protocols / "delivery_validation.json", validation.to_dict())
    write_new(protocols / "closeout_references.json", refs)
    if validation.status.value != "PASS":
        raise RuntimeError(validation.to_dict())
    print(
        {
            "experiment": EXPERIMENT.experiment_id,
            "COMPONENTS": 12,
            "FULL": "PASS",
            "new_accounts": 0,
        },
        flush=True,
    )


if __name__ == "__main__":
    run(sys.argv[1])
