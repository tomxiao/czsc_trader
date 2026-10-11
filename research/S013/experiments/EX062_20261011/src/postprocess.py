"""EX062 result-only closeout: never prepare/evaluate or change frozen driver."""
from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
from time import time_ns

import driver
from czsc_trader.application import (
    CandidateRegistrationRequest, assemble_delivery, load_candidate,
    publish_evidence, register_candidate, validate_delivery,
)
from czsc_trader.research_tools import MaterialEvidenceWrite, delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_manager import CandidateDerivationKind, CandidateKey
from strategy_evaluator import AssessmentPanel, CandidateAssessmentRequest, assess_candidates

ROOT, WORK, EXPERIMENT = driver.draft.ROOT, driver.WORK, driver.EXPERIMENT
OUT = ROOT / ".tmp/s013-robust-center/closeout"


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def checked_reference(value):
    reference = EvidenceRef.from_dict(value)
    if digest(reference.resolve(ROOT)) != reference.sha256:
        raise ValueError("Formal evidence SHA differs: " + reference.repository_path)
    return reference


def validate_summary(analysis, checks, state):
    if analysis["status"] != "COMPLETE" or checks["status"] != "COMPLETE":
        raise ValueError("Nine-center analysis and selected five checks must be complete")
    rows = analysis["centers"]
    if state["status"] != "COMPLETE" or state["failure"] or len(rows) != 9:
        raise ValueError("Partial/failed search cannot be closed out")
    if [row["queue_index"] for row in rows] != list(range(9)):
        raise ValueError("Frozen nine-center ordering differs")
    for row in rows:
        actual = driver.draft.summarize_panel(row["center"], row["points"])
        if any(row[key] != value for key, value in actual.items()):
            raise ValueError("Recomputed complete32 summary differs: " + row["label"])
        if len(row["point_references"]) != 32:
            raise ValueError("Full32 references missing")
    if analysis["selection"] != driver.draft.selection(rows):
        raise ValueError("Deterministic preference/Pareto differs")
    if state["new_successful_business"] != 262 or state["technical_duplicates"] != 1:
        raise ValueError("Expected262 new role evaluations plus1 preflight duplicate")
    if state["evaluation_attempts"] != 263 + state["pressure_successful"]:
        raise ValueError("Actual evaluation counts do not conserve")
    preferred = analysis["selection"]["preferred"]
    expected = ["BASE"] + ([preferred] if preferred else [])
    if [item["label"] for item in checks["selected_checks"]] != expected:
        raise ValueError("Five-check scope is BASE and at most one preferred center")
    if checks["pressure_successful"] != state["pressure_successful"] or len(expected) != state["pressure_successful"]:
        raise ValueError("Separate pressure accounts missing or count differs")
    return rows


def report_text(analysis, checks, roles):
    lines = ["# EX062 固定九中心参数研究", "",
        "策略机制、费用及计价保持 EX058/C8880；每个中心均检查原13完整域、5%联合半径、32点和seed13。中心未过原四门仍保留完整邻域诊断。", "",
        "297个中心/参数角色对应294个唯一标准业务配置；35个旧角色复用33个唯一旧账户。新业务配置261个，新角色评价262次，另有1次串行/多进程技术重复；费用压力账户另列。", "",
        "|中心|候选|中心四门|32收益|32年度回撤|32频率|32亏损年盈利|32联合|Q10净年化|Q90全期回撤|收益退化|回撤退化|",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in analysis["centers"]:
        counts = row["gate_pass_counts"]
        candidate = next(item["candidate_id"] for item in roles if item["role"] == row["label"] + ":center")
        gates = "、".join(f"{key}={'通过' if value else '未过'}" for key, value in row["center_gates"].items())
        values = [counts[key] for key in driver.draft.GATES]
        numbers = "|".join(f"{row[key]:.6%}" for key in ("q10_cagr", "q90_drawdown", "return_degradation", "drawdown_degradation"))
        lines.append(f"|{row['label']}|{candidate}|{gates}|" + "|".join(map(str, values)) + f"|{row['joint_pass_count']}|{numbers}|")
    selected = analysis["selection"]
    lines += ["", "|中心|净年化|全期回撤|实际闭合交易|全部自然年净收益|", "|---|---:|---:|---:|---|"]
    for row in analysis["centers"]:
        economics = row["center"]
        lines.append(f"|{row['label']}|{economics['net_cagr']:.6%}|{economics['drawdown']:.6%}|{economics['closed_trades']}|{economics['annual']}|")
    lines += ["", f"原四门合格中心：{', '.join(selected['qualified_labels']) or '无'}。全部三目标Pareto：{', '.join(selected['pareto_all'])}。",
        f"冻结次序优选：{selected['preferred'] or '无'}。绝对尾部改善：{'找到' if selected['absolute_tail_improvement_found'] else '未找到'}。相对退化仅报告，不新增资格否决。", "",
        "Q10表示32点中较差一端的净年化水平，Q90表示较差一端的回撤。不同中心重新生成自己的扰动设计，不能把同序号账户作利润配对。", "", "## 五项自检", ""]
    for item in checks["selected_checks"]:
        lines.append(f"- {item['label']}：参数、时间、集中性、独立双倍费用、统计不确定性完整公共SE结果见 selfchecks.json；压力证据 SHA `{item['stress_reference']['sha256']}`。")
        lines += ["", "|公共诊断|值|状态|", "|---|---|---|"]
        for metric in item["panel"]["rows"][0]["diagnostics"]:
            lines.append(f"|{metric['metric']}|{metric['value']}|{metric['status']}|")
        lines += ["", f"统计区间：{item['panel']['rows'][0]['uncertainty']}。研究族诊断：{item['panel']['family_diagnostics']}。", ""]
        for limit in item["limitations"]:
            lines.append("  - " + limit)
    lines += ["", "本轮使用已见开发池和事后选定的两端点，属于样本内有限研究；未提供独立验证或完整研究族选择校正。已有五处30分钟High/Low偏差保持原状，原生收益为实际账户事实；现金账本复核不代表全部限价成交政策或行情质量已认证。", "",
        "仅原四门合格的新中心登记；全部失败中心、参数点、空组及证据均保留。没有新增机制或继续搜索。本轮收口不自动证明整体稳健目标达成。", ""]
    return "\n".join(lines)


def collect(method_ref):
    method = driver.draft.require_frozen_method(method_ref)
    driver.legacy_pickle_support()
    state = driver.read(WORK / "checkpoint.json")
    analysis, checks = (driver.read(WORK / name) for name in ("analysis.json", "selfchecks.json"))
    rows = validate_summary(analysis, checks, state)
    independent_path = EXPERIMENT.resolve(ROOT) / "protocols/independent_audit.json"
    independent = driver.read(independent_path)
    validate_independent_audit(independent, method_ref, analysis, state)
    study = driver.cache_read(WORK / "study.pkl.gz")
    trials = []
    for index, (trial, row) in enumerate(zip(study.trials, rows, strict=True)):
        values = (row["joint_pass_count"], row["q10_cagr"], row["q90_drawdown"])
        if trial.state.name != "COMPLETE" or trial.number != index or trial.params != {"center_index": index} or tuple(trial.values) != values:
            raise ValueError("Optuna fixed queue/native objectives differ")
        trials.append({"index": index, "label": row["label"], "params": trial.params, "values": list(trial.values), "state": trial.state.name})
    driver.write(OUT / "optuna_trials.json", {"status": "PASS", "trials": trials,
        "study_cache_sha256": digest(WORK / "study.pkl.gz"), "no_added_trials": True})
    ctx = driver.draft.existing_only_context(method_ref, 1)
    roles, contents, evidence = [], set(), {}
    natives = []
    for row in rows:
        native = driver.cache_read(WORK / f"complete-center-{row['queue_index']:02}.pkl.gz")
        pairs = [native["center"], *native["points"]]
        refs = [row["center_reference"], *row["point_references"]]
        for index, (pair, value) in enumerate(zip(pairs, refs, strict=True)):
            reference = checked_reference(value)
            identity = driver.draft.authenticate_native(ctx, *pair, reference)
            role = row["label"] + (":center" if index == 0 else f":P{index-1:02}")
            contents.add(identity.content_sha256)
            roles.append({"role": role, "candidate_id": pair[0].strategy.candidate_id,
                "content_sha256": identity.content_sha256, "request_hash": pair[1].request_hash,
                "result_hash": pair[1].result_hash, "reference": reference.to_dict()})
            evidence[reference.repository_path] = reference
        natives.append(native["center"])
    if len(roles) != 297 or len(contents) != 294:
        raise ValueError("Role/unique-content accounting differs")
    duplicate = driver.read(WORK / "binding_duplicate.json")
    preflight = driver.read(WORK / "preflight.json")
    if duplicate["status"] != "PASS" or preflight["status"] != "PASS":
        raise ValueError("Both technical-duplicate proofs must pass")
    for item in checks["selected_checks"]:
        request = CandidateAssessmentRequest.from_dict(item["request"])
        if assess_candidates(request) != AssessmentPanel.from_dict(item["panel"]):
            raise ValueError("Public SE five-check recomputation differs")
        for key in ("stress_reference", "reference"):
            reference = checked_reference(item[key])
            evidence[reference.repository_path] = reference
        row = next(row for row in rows if row["label"] == item["label"])
        stress = driver.cache_read(WORK / "native" / f"fee-stress-{row['queue_index']:02}.pkl.gz")
        driver.draft.authenticate_native(ctx, *stress, EvidenceRef.from_dict(item["stress_reference"]))
    output = {"status": "PASS", "roles": roles, "standard_unique_configurations": len(contents),
        "standard_role_count": len(roles), "method_reference": method_ref.to_dict(),
        "counts": state, "all32_native_formal_exact": True,
        "qualified_new_center_indices": [row["queue_index"] for row in rows if row["queue_index"] >= 3 and row["center_qualified"]],
        "new_account_evaluations": 0, "preparations": 0}
    driver.write(OUT / "role_manifest.json", output)
    (OUT / "report.md").write_text(report_text(analysis, checks, roles), encoding="utf-8")
    return ctx, method, analysis, checks, output, natives, evidence


def validate_independent_audit(audit, method_ref, analysis, state):
    source = EXPERIMENT.resolve(ROOT) / "src/independent_audit.py"
    if audit["status"] != "PASS" or audit["method_reference"] != method_ref.to_dict():
        raise ValueError("Complete independent audit of this frozen method required")
    if audit["source_sha256"] != digest(source) or audit["selection"] != analysis["selection"]:
        raise ValueError("Independent audit source or selection differs")
    expected = {"roles": 297, "unique_configurations": 294, "old_unique_native": 33,
                "new_unique_business": 261, "new_role_evaluations": 262,
                "center_fee_pressure": state["pressure_successful"],
                "actual_new_evaluations": state["evaluation_attempts"]}
    if any(audit["counts"][key] != value for key, value in expected.items()):
        raise ValueError("Independent audit role/configuration accounting differs")
    if any(audit[key] != 0 for key in ("new_account_evaluations_by_audit", "preparations", "publications")):
        raise ValueError("Independent audit must not create replacement accounts or evidence")


def registration(ctx, analysis, manifest, natives):
    path = OUT / "registration.json"
    if path.exists():
        raise ValueError("Existing registration receipt cannot be overwritten")
    records = []
    for index in manifest["qualified_new_center_indices"]:
        request, result = natives[index]
        derivation = request.lineage.derivation
        if derivation.kind is not CandidateDerivationKind.PARAMETERS or derivation.parent != CandidateKey("S013", "C8880"):
            raise ValueError("New center must retain actual PARAMETERS parent C8880")
        reference = checked_reference(analysis["centers"][index]["center_reference"])
        record = register_candidate(ctx.repository, CandidateRegistrationRequest(request.strategy, EXPERIMENT,
            (reference,), request.dependencies, derivation))
        identity = ctx.runtime.identify(load_candidate(ctx.repository, record.key), dependencies=request.dependencies)
        if identity.content_sha256 != result.runs[0].identity.content_sha256:
            raise ValueError("Registered center identity differs")
        records.append(record.to_dict())
    output = {"status": "PASS", "registrations": records, "new_qualified": len(records),
        "old_center_ids_not_reregistered": ["C8880", "C8840", "C8860"], "no_children_registered": True}
    driver.write(path, output)
    return output


def publish(method_ref, mandate, previous, collected=None):
    ctx, method, analysis, checks, manifest, natives, evidence = collected or collect(method_ref)
    target = EXPERIMENT.resolve(ROOT) / "protocols/delivery_reference.json"
    if target.exists():
        raise ValueError("Existing FULL55 cannot be overwritten")
    registration_result = driver.read(OUT / "registration.json")
    if registration_result["status"] != "PASS" or registration_result["new_qualified"] != len(manifest["qualified_new_center_indices"]):
        raise ValueError("All qualified new centers must be registered")
    materials = {"method": method_ref}
    paths = [WORK / name for name in ("authentication.json", "checkpoint.json", "analysis.json", "selfchecks.json", "centers.json", "binding_duplicate.json", "preflight.json")]
    paths += [OUT / "role_manifest.json", OUT / "registration.json", OUT / "optuna_trials.json", Path(__file__)]
    paths.append(EXPERIMENT.resolve(ROOT) / "src/independent_audit.py")
    # Includes the pre-financial packaging correction; never edits its source/evidence.
    paths += list((EXPERIMENT.resolve(ROOT) / "protocols").glob("*.json"))
    for relative in method["sources"]:
        paths.append(ROOT / relative)
    seen = {method_ref.sha256}
    for path in paths:
        hashed = digest(path)
        if hashed in seen:
            continue
        seen.add(hashed)
        reference = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, "closeout-" + path.stem.replace("_", "-") + "-" + hashed[:12],
            path.read_bytes(), "application/json" if path.suffix == ".json" else "text/x-python", path.suffix[1:]))
        materials[path.relative_to(ROOT).as_posix()] = reference
    for row in analysis["centers"]:
        reference = checked_reference(row["plan_reference"])
        materials["plan-" + row["label"]] = reference
    entries = []
    for row, pair in zip(analysis["centers"], natives, strict=True):
        if row["center_qualified"]:
            reference = checked_reference(row["center_reference"])
            entries.append(d.CandidateEntry(d.CandidateIdentityRef(CandidateKey("S013", pair[0].strategy.candidate_id), pair[1].runs[0].identity.content_sha256),
                "固定机制的完整原13域参数中心研究", "原四门合格；32邻域及五项选型诊断不增加候选否决，未阶段四交接", (d.EvaluationEvidenceRef(reference),)))
    summary = d.SearchSummary("EX062-fixed-nine-centers", method["sampling"],
        "S013/EX058固定源码与原账户契约；9中心完整32，失败中心也完整诊断",
        33 + manifest["counts"]["evaluation_attempts"], 294,
        "原四门资格；绝对尾部优选=" + str(analysis["selection"]["preferred"]) + ";全部合格与Pareto保留",
        tuple(analysis["limits"]), tuple(materials.values()))
    payload = d.CandidateSet(tuple(entries), (), (summary,),
        "固定九中心研究完整收口，未新增机制或后续搜索；整体目标是否达成由完整尾部与相对退化共同说明。")
    for reference in materials.values():
        evidence[reference.repository_path] = reference
    report = (OUT / "report.md").read_text(encoding="utf-8") + "\n## 正式证据\n\n"
    for name, reference in {**materials, **{role["role"]: EvidenceRef.from_dict(role["reference"]) for role in manifest["roles"]}}.items():
        report += f"- [{name}](../../../assets/deliveries/CANDIDATES/55/{reference.path})\n"
    receipt = assemble_delivery(ctx.repository, d.DeliveryDefinition(ctx.batch, d.DeliveryStage.CANDIDATES, 55,
        (d.DeliveryReference.from_dict(driver.read(mandate)), d.DeliveryReference.from_dict(driver.read(previous)))),
        d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, (), (), report=report, evidence=tuple(evidence.values())))
    validation = validate_delivery(ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
    if validation.status.value != "PASS":
        driver.write(OUT / "delivery_failure.json", validation.to_dict())
        raise ValueError("FULL55 failed; evidence retained")
    driver.write(target, receipt.reference.to_dict())
    driver.write(OUT / "delivery_validation.json", {"status": "PASS", "reference": receipt.reference.to_dict(), "validation": validation.to_dict()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("report", "register", "publish", "finalize"))
    parser.add_argument("--method-reference", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--mandate-reference", type=Path)
    parser.add_argument("--previous-reference", type=Path)
    args = parser.parse_args()
    if digest(__file__) != args.source_sha256:
        parser.error("Closeout source SHA differs from root-reviewed source")
    reference = checked_reference(driver.read(args.method_reference))
    if args.action in {"publish", "finalize"}:
        if not args.mandate_reference or not args.previous_reference:
            parser.error("FULL55 requires mandate and CANDIDATES54 predecessors")
        if args.action == "finalize":
            collected = collect(reference)
            ctx, _, analysis, _, manifest, natives, _ = collected
            registration(ctx, analysis, manifest, natives)
            publish(reference, args.mandate_reference, args.previous_reference, collected)
        else:
            publish(reference, args.mandate_reference, args.previous_reference)
    else:
        ctx, _, analysis, _, manifest, natives, _ = collect(reference)
        if args.action == "register":
            registration(ctx, analysis, manifest, natives)
    print({"status": "PASS", "action": args.action, "new_account_evaluations": 0, "preparations": 0})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        driver.write(OUT / f"failure-{time_ns()}.json", {"status": "FAILED", "source_sha256": digest(__file__),
            "error": {"type": type(exc).__name__, "message": str(exc)}, "new_account_evaluations": 0, "preparations": 0})
        raise
