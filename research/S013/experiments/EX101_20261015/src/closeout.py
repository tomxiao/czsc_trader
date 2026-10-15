"""Preserve the fixed comparison and negative result via public delivery API."""

from hashlib import sha256
from datetime import datetime, timezone
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
import json
from czsc_trader.application import publish_evidence, assemble_delivery, validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite, EvidenceRef
from czsc_trader.research_tools import delivery as d
from common import ROOT, SRC, PROTOCOLS, RUNS, EXPERIMENT, context, read, write, file_hash


def main():
    assert not (PROTOCOLS / "delivery_reference.json").exists(), "Do not overwrite delivery"
    analysis = read(RUNS / "analysis.json")
    assert analysis["status"] == "PASS"
    completion = read(RUNS / "completion.json")
    assert completion["actual_full_accounts"] == 3
    attempts = read(RUNS / "attempts.json")["attempts"]
    assert len(attempts) == 3 and all(x["status"] == "SUCCEEDED" for x in attempts)
    assert read(PROTOCOLS / "result_peer_review.json")["status"] == "PASS"
    assert read(RUNS / "serial_spawn_equivalence.json")["status"] == "PASS"
    rows = {x["configuration"]: x for x in analysis["rows"]}
    assert all(not x["four_targets_jointly_pass"] for x in rows.values())
    assert rows["COMBINED"]["net_cagr"] < rows["BASE"]["net_cagr"]
    assert rows["COMBINED"]["max_drawdown"] > rows["BASE"]["max_drawdown"]
    ctx = context(1)
    refs = {
        k: EvidenceRef.from_dict(v) for k, v in read(PROTOCOLS / "method_references.json").items()
    }
    account_refs = {k: EvidenceRef.from_dict(v) for k, v in analysis["sources"].items()}
    for ref in account_refs.values():
        assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest() == ref.sha256
    for key in ("prior_anomaly_source", "known_anomaly_source"):
        if key in analysis:
            ref = EvidenceRef.from_dict(analysis[key])
            refs[key] = ref
    # The actual analyzer embeds the separately authenticated quality source here.
    for key, value in analysis.items():
        if isinstance(value, dict) and value.get("type") == "EvidenceRef":
            refs[key] = EvidenceRef.from_dict(value)
    material_paths = [
        RUNS / name
        for name in (
            "analysis.json",
            "attempts.json",
            "completion.json",
            "synthetic_checks.json",
            "serial_spawn_equivalence.json",
        )
    ]
    material_paths += [
        PROTOCOLS / name
        for name in ("peer_review.json", "result_peer_review.json", "account_references.json")
    ]
    for path in material_paths:
        ref = publish_evidence(
            ctx,
            MaterialEvidenceWrite(
                EXPERIMENT,
                "trend-final-" + path.stem.replace("_", "-"),
                path.read_bytes(),
                "application/json",
                "json",
            ),
        )
        assert ref.resolve(ROOT).read_bytes() == path.read_bytes()
        refs[path.name] = ref
    paths = (
        [p for p in SRC.rglob("*.py")]
        + [p for p in PROTOCOLS.glob("*.json")]
        + list(RUNS.glob("*.csv"))
    )
    paths += [ROOT / ".tmp/s013-trend-fixed-20261015/bootstrap.py"]
    manifest = dict(
        kind="EX101_FIXED_TREND_NEGATIVE_RESULT_REPRODUCTION",
        experiment=EXPERIMENT.to_dict(),
        archived_utc=datetime.now(timezone.utc).isoformat(),
        files={p.relative_to(ROOT).as_posix(): file_hash(p) for p in paths},
        original_accounts={k: v.to_dict() for k, v in account_refs.items()},
        counts=completion,
        technical_notes=[
            "PreparedDataRef/DataRequest use public fields/dataclasses serialization; fixed before real account evaluations.",
            "Analyzer assessment/ledger date values identical; canonical datetime64ns comparison fixed representation-only us/ns difference.",
            "Arbitrary watch date removed before analysis; only formally authenticated five known anomaly dates retained.",
            "Generated unfilled-order boundary test passed; all actual orders filled, so no claim actual sample exercised unfilled reattempt.",
            "Three FULL attempts include one technical repeat, not three business discoveries; no fourth evaluation performed.",
        ],
        state="PAUSED",
        new_registered_candidates=0,
        preservation="Retain S013 assets/data plus published evidence/delivery and source bundle; .tmp alone is not formal evidence.",
    )
    write(RUNS / "reproduction.json", manifest)
    bundle = ROOT / ".tmp/s013-trend-fixed-20261015/reproduction.zip"
    hashes = {}
    with ZipFile(bundle, "w", compression=ZIP_DEFLATED) as archive:
        for path in paths + [RUNS / "reproduction.json"]:
            name = path.relative_to(ROOT).as_posix()
            payload = path.read_bytes()
            info = ZipInfo(name, date_time=(2026, 10, 15, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, payload)
            hashes[name] = sha256(payload).hexdigest()
    with ZipFile(bundle) as archive:
        assert archive.testzip() is None
        assert all(sha256(archive.read(name)).hexdigest() == h for name, h in hashes.items())
    for name, path, media, extension in [
        ("reproduction.json", RUNS / "reproduction.json", "application/json", "json"),
        ("reproduction.zip", bundle, "application/zip", "zip"),
    ]:
        refs[name] = publish_evidence(
            ctx,
            MaterialEvidenceWrite(
                EXPERIMENT, "trend-final-" + path.stem, path.read_bytes(), media, extension
            ),
        )
        assert refs[name].resolve(ROOT).read_bytes() == path.read_bytes()
    old = ROOT / "research/S013/deliveries/CANDIDATES"
    revision = max(int(p.name) for p in old.iterdir() if p.name.isdigit()) + 1
    assert revision == 75, "Unexpected concurrent candidate delivery; inspect first"
    report = """# S013 EX101：固定20/10趋势参与对照

本轮验证已完成，整体策略目标未达成。新增趋势机制确实补上部分上涨参与，但这版组合收益降低、回撤扩大，未解决当前四项目标。停止这组固定表达并恢复暂停，不自动调整邻近周期或优先级。

## 规则、对照与口径

510500.SH，2020-01-02至2026-09-30共1636日；原2019年数据仅预热，2019-12-31首次信号从空状态开始。前20交易日收盘新高买入、前10交易日收盘新低退出，严格排除当日并固定20/10。T日收盘决策、T+1执行；100万元、只做多、不加杠杆，1%限价买入、原市价退出，每侧0.1%费用，固定LimitBuyHold基准与HFQ研究单位。

原C2132账本认证复用；新增趋势单独组与单仓组合组。组合同时入场时原策略优先，持仓后由所属机制退出，同日不再入场，被占仓挡住的旧入口不迟到补入。原策略影子信号逐日核对相同，不把信号意图当作成交。

## 完整账户结果

| 组别 | 净年化 | 全区间最大回撤 | 基准盈利年闭合笔数 | 2023净收益 |
| --- | ---: | ---: | ---: | ---: |
"""
    labels = {"BASE": "原策略", "TREND_ONLY": "趋势单独", "COMBINED": "组合"}
    for key, row in rows.items():
        report += f"| {labels[key]} | {row['net_cagr']:.4%} | {row['max_drawdown']:.4%} | {row['positive_year_closed_cycles']} | {row['annual']['2023']['net_return']:.4%} |\n"
    report += """
交易频率只在基准盈利年份合并计算：1152日须至少77笔，不能用全区间125笔替代组合实际74笔。净年化目标以同口径基准7.2193%的1.5倍比较；年度回撤目标逐年比较，并纳入上年末权益，表中的全区间回撤仅供总览。

| 组别 | 年化目标 | 各年回撤更小 | 盈利年频率 | 各亏损基准年策略盈利 | 四项同时 |
| --- | --- | --- | --- | --- | --- |
"""
    for key, row in rows.items():
        gates = ["通过" if value else "未通过" for value in row["gates"].values()]
        report += "| " + labels[key] + " | " + " | ".join(gates) + " | 未通过 |\n"
    report += "\n## 分年结果与贡献\n\n| 年份 | 原策略净收益 | 趋势单独净收益 | 组合净收益 | 组合回撤 | 同口径基准回撤 |\n| --- | ---: | ---: | ---: | ---: | ---: |\n"
    for year in rows["BASE"]["annual"]:
        values = [rows[key]["annual"][year]["net_return"] for key in labels]
        report += f"| {year} | {values[0]:.4%} | {values[1]:.4%} | {values[2]:.4%} | {rows['COMBINED']['annual'][year]['max_drawdown']:.4%} | {rows['COMBINED']['benchmark_annual'][year]['max_drawdown']:.4%} |\n"
    report += """
组合在2025年由11.08%增至26.20%，说明补上涨参与在部分年份有价值；但2020、2021由盈利变亏，2023由+0.2841%变为-1.0004%，整体代价更大。组合的年度回撤在2020、2021未能小于基准。

组合实际新增趋势职责29笔闭合交易，9赚20亏，扣费合计亏33,619.46元；趋势持仓占464个日末，并挡住16个原策略入场信号。原策略闭合从112笔降至96笔，组合总闭合125笔。被挡原交易的原账本利润不能直接加回，因实际资金与数量已经改变。趋势部分自身也净亏，因此不能仅把问题归咎于占仓安排。

这修正了之前的方向判断：原策略空仓错过上涨是事实，但“增加上涨突破买入”不足以保证改善；必须同时回答新增交易能否扣费赚钱、以及如何避免损害原有机会。本轮否定的是此20/10固定组合，并非全部趋势机制。下一步建议先审查新增交易的亏损发生在入场后反转还是盈利回吐，形成能区分原因的问题，再决定是否继续该方向；暂不扫描参数或扩充成分股数据。

## 验证与边界

生成数据的边界与未来不变性检查通过。趋势组串行与spawn的信号及策略/基准五类账本逐值一致，结果哈希相同；独立审查重算三组年化、回撤、频率、2023结果和归因一致。实际成交的现金、数量、权益、费用、闭合与尾仓均已核对。原策略和组合各有1个尾仓，未强制清仓凑频率；实际订单均已成交，未成交分支只在生成用例中覆盖。

原正式证据列明的五个异常30分钟交易日已单列；当日只有OPEN或OPEN_MARKET成交或无订单，未依赖异常分时限价首触。没有修复、剔除或重跑这些数据；不据此保证全部原数据无异常。

开发池已反复使用，规则由此前诊断选定，不能称为独立样本外检验。没有32点、费用压力、选型、冻结、PTE或生产验收；历史203个登记候选及资格不变，本轮无新登记候选、无新交接。

本次新实验1轮已完成，剩余实验0；2个业务配置、3次FULL（其中1次串行/spawn技术重复），原账本复用1份。额度上限4次，另1次技术预留未使用，不续作新研究。来源请求、模型训练、搜索、32及费用压力账户均为0。研究状态PAUSED。

## 正式证据

"""
    all_refs = list(dict.fromkeys(tuple(account_refs.values()) + tuple(refs.values())))
    for ref in all_refs:
        report += f"- [{ref.name}]({ref.path})\n"
    summary = d.SearchSummary(
        "S013-EX101-fixed-trend-20-10",
        "事前固定两中心对照，无搜索；TREND_ONLY串行/spawn等价重复后复用，COMBINED一次spawn；最大2进程各1原生线程，seed13。",
        "既有S013开发池，原四项目标，固定1%执行合同；原C2132账本认证复用。",
        3,
        2,
        "两新配置均未达四项目标，固定组合劣于原策略；不选型、不新增候选交接。",
        tuple(analysis["limitations"]),
        (refs["analysis.json"], refs["reproduction.json"]),
    )
    mandate = d.DeliveryReference.from_dict(read(PROTOCOLS / "mandate_reference.json"))
    receipt = assemble_delivery(
        ctx.repository,
        d.DeliveryDefinition(ctx.batch, d.DeliveryStage.CANDIDATES, revision, (mandate,)),
        d.DeliveryContent(
            d.CandidateSet(
                (),
                (),
                (summary,),
                "固定20/10趋势组合补上部分上涨参与，但新增趋势净亏且遮挡原入口；总体退化，无新达标配置，停止本表达并暂停。",
            ),
            d.DeliveryStatus.COMPLETE,
            (),
            (),
            report=report,
            evidence=tuple(all_refs),
        ),
    )
    validation = validate_delivery(
        ctx.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL
    )
    assert validation.status.value == "PASS", validation.to_dict()
    write(PROTOCOLS / "delivery_reference.json", receipt.reference.to_dict())
    write(PROTOCOLS / "delivery_validation.json", validation.to_dict())
    write(PROTOCOLS / "result_references.json", {k: v.to_dict() for k, v in refs.items()})
    formal = ROOT / f"research/S013/deliveries/CANDIDATES/{revision}/report.md"
    copy = SRC.parent / "others/report.md"
    with copy.open("xb") as stream:
        stream.write(formal.read_bytes())
    assert formal.read_bytes() == copy.read_bytes()
    write(
        PROTOCOLS / "report_copy_verification.json",
        dict(
            status="PASS",
            formal_report=formal.relative_to(ROOT).as_posix(),
            experiment_report=copy.relative_to(ROOT).as_posix(),
            formal_bytes=formal.stat().st_size,
            copy_bytes=copy.stat().st_size,
            formal_sha256=file_hash(formal),
            copy_sha256=file_hash(copy),
            exact_bytes=True,
        ),
    )
    closeout = dict(
        status="FIXED_COMPARISON_COMPLETE_NO_NEW_QUALIFIED_STRATEGY",
        experiment=EXPERIMENT.to_dict(),
        delivery=receipt.reference.to_dict(),
        analysis=refs["analysis.json"].to_dict(),
        source_bundle=refs["reproduction.zip"].to_dict(),
        research_execution_state="PAUSED",
        actual_counts=completion,
        result_summary=[
            {
                key: row[key]
                for key in (
                    "configuration",
                    "net_cagr",
                    "max_drawdown",
                    "positive_year_closed_cycles",
                    "gates",
                )
            }
            for row in rows.values()
        ],
        next_direction="先评审新增趋势交易亏在入场反转还是退出回吐；不自动追加账户、改参数或新增数据。",
    )
    write(PROTOCOLS / "closeout.json", closeout)
    target = ROOT / "research/S013/materials/trend_participation_result_20261015_reference.json"
    assert not target.exists()
    write(target, closeout)
    print(
        json.dumps(
            dict(
                status="PASS",
                delivery=receipt.reference.to_dict(),
                report_copy="EXACT_BYTES",
                bundle_members=len(hashes),
                actual_full_accounts=3,
                research_state="PAUSED",
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
