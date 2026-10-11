"""Validate retained public evidence and produce an auditable comparison report."""

import os

for variable in (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[variable] = "1"
# ruff: noqa: E402
from hashlib import sha256
import html
import json
from pathlib import Path
import shutil
import sys
import numpy as np
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from strategy_evaluator import CandidateAssessmentRequest, assess_candidates

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".tmp/c2132-s003-compare"
OUT = ROOT / "research/comparisons/C2132_S003_v1_20261011"
sys.path.insert(0, str(WORK))
from run_compare import read, write, cache_read, ctx, material


def main():
    receipts = read(OUT / "account_receipts.json")
    assert len(receipts) == 2
    projection_proof = read(WORK / "s003_projection_proof.json")
    strict_proof = read(WORK / "s003_strict_proof.json")
    supplemental_method = read(WORK / "overlay_hfq_method.json")
    for name, digest in supplemental_method["files"].items():
        assert sha256((WORK / name).read_bytes()).hexdigest() == digest
    assert supplemental_method["receipt_sha256"] == sha256((OUT / "account_receipts.json").read_bytes()).hexdigest()
    assert projection_proof["status"] == strict_proof["status"] == "PASS"
    assert len(projection_proof["accounts"]) == len(strict_proof["accounts"]) == 34
    assert projection_proof["source_sha256"] == sha256((WORK / "verify_published_projection.py").read_bytes()).hexdigest()
    assert strict_proof["source_sha256"] == sha256((WORK / "overlay_hfq_validation.py").read_bytes()).hexdigest()
    exact_by_hash = {x["reference"]["sha256"]: x for x in projection_proof["accounts"]}
    strict_by_hash = {x["reference"]["sha256"]: x for x in strict_proof["accounts"]}
    checks = []
    for receipt in receipts:
        references = [
            receipt["center"],
            receipt["stress"],
            *[x["reference"] for x in receipt["parameters"]],
        ]
        assert len(references) == 34 and len(receipt["parameters"]) == 32
        for raw in references:
            ref = EvidenceRef.from_dict(raw)
            path = ref.resolve(ROOT)
            assert sha256(path.read_bytes()).hexdigest() == ref.sha256
            try:
                validate_evaluation_evidence(read(path))
                checks.append({"reference": raw, "native_public_validation": "PASS"})
            except ValueError as error:
                if receipt["family"] != "S003" or str(error) != "evaluation account audit failed":
                    raise
                exact, strict = exact_by_hash[ref.sha256], strict_by_hash[ref.sha256]
                assert exact["reference"] == strict["reference"] == raw
                assert exact["status"] == strict["status"] == strict["proof"]["status"] == "PASS"
                assert exact["full_projection_exact"] is True
                checks.append({"reference": raw, "native_public_validation": "FAIL",
                               "native_error": str(error), "supplemental_strict_validation": "PASS",
                               "full_authenticated_projection_exact": True,
                               "supplemental_proof": strict["proof"]})
        print("ACCOUNT_VALIDATION_RETAINED", receipt["family"], 34, flush=True)
    panels = read(OUT / "assessment_panels.json")
    summaries = {}
    for family, wrapper in panels.items():
        request = CandidateAssessmentRequest.from_dict(wrapper["assessment_request"])
        panel = assess_candidates(request)
        assert panel.to_dict() == wrapper["assessment_panel"]
        assert panel.sha256 == wrapper["assessment_panel_sha256"]
        row = wrapper["assessment_panel"]["rows"][0]
        values = {d["metric"]: d["value"] for d in row["diagnostics"]}
        assert all(d["status"] == "AVAILABLE" for d in row["diagnostics"])
        req, result = cache_read(WORK / (family + "-center.pkl.gz"))
        account = result.runs[0].execution.account_daily
        equity = account.equity.to_numpy(dtype=float)
        net_cagr = float((equity[-1] / 1e6) ** (252 / len(equity)) - 1)
        wealth = np.r_[1e6, equity]
        dd = float(np.max(1 - wealth / np.maximum.accumulate(wealth)))
        closed = int(result.runs[0].execution.trades.status.eq("CLOSED").sum())
        freq = closed * 60 / len(equity)
        assert np.isclose(net_cagr, values["NET_ANNUAL_RETURN"], rtol=0, atol=1e-12)
        assert np.isclose(dd, values["DRAWDOWN_MAGNITUDE"], rtol=0, atol=1e-12)
        assert freq == values["FULL_SAMPLE_FREQUENCY"]
        point_runs = [cache_read(WORK / f"{family}-P{i:02}.pkl.gz")[1].runs[0] for i in range(32)]
        returns = [float(x.observation.net_cagr) for x in point_runs]
        drawdowns = [abs(float(x.observation.max_drawdown)) for x in point_runs]
        # Native MetricObservation field names are inspected by the public adapter;
        # independent Q10/Q90 calculations retain all32 points, never select them.
        q10 = float(np.quantile(returns, 0.1, method="linear"))
        q90 = float(np.quantile(drawdowns, 0.9, method="linear"))
        assert np.isclose(
            max(0, net_cagr - q10), values["PARAMETER_RETURN_DEGRADATION"], atol=1e-12, rtol=0
        )
        assert np.isclose(
            max(0, q90 - dd), values["PARAMETER_DRAWDOWN_DEGRADATION"], atol=1e-12, rtol=0
        )
        benchmark = {d["metric"]: d["value"] for d in row["benchmark"]["diagnostics"]}
        summaries[family] = {
            "label": "C2132" if family == "S013" else "S003-v1",
            "values": values,
            "closed_trades": closed,
            "sessions": len(equity),
            "ending_equity": float(equity[-1]),
            "parameter_cagr_q10": q10,
            "parameter_drawdown_q90": q90,
            "uncertainty": row["uncertainty"],
            "benchmark": benchmark,
            "parameter_context": row["parameter_context"],
            "family_diagnostics": wrapper["assessment_panel"]["family_diagnostics"],
            "coverage_gaps": row["coverage_gaps"],
            "assessment_reference": wrapper["reference"],
        }
    assert summaries["S013"]["benchmark"] == summaries["S003"]["benchmark"]
    latest = read(OUT / "declaration.json")
    stat = {
        "status": "COMPLETE_WITH_PUBLIC_AUDIT_LIMITATION",
        "business_accounts": 68,
        "technical_duplicates": 2,
        "start": latest["start"],
        "end": latest["end"],
        "cash": 1e6,
        "price_basis": "HFQ_RESEARCH",
        "costs": {"baseline": 0.001, "stress": 0.002},
        "strategies": summaries,
        "bias_limit": "同统一口径完整历史研究族矩阵不存在，PBO/DSR不可比；未填零或以两策略代替完整族。",
        "historical_bias_sources": [
            {
                "path": "research/S013/experiments/EX008_20261010/others/report.md",
                "scope": "旧1636日/原费用价格协议/79筛选中心/1536历史尝试；不作为统一口径结果",
            },
            {
                "path": "experiments/S003/20260911_S003_EX47/artifacts/corrected_statistical_summary.json",
                "scope": "旧日内优势及费用、142尝试135有效路径；不作为统一口径结果",
            },
        ],
        "scope": "原策略比较；不优化参数，不改变冻结源，不启动新机制；完成后暂停",
        "account_audit_limit": "S003公开审计未通过：校验器使用后复权价直接取整限价，并将正确未成交及依赖阻断判为异常。原FAIL保持；独立逐笔补充验证另列，不视为原生审计PASS。",
    }
    c, s = [summaries[family]["values"] for family in ("S013", "S003")]
    findings = [
        f"共同条件下，C2132年化{c['NET_ANNUAL_RETURN'] * 100:.2f}%、最大回撤{c['DRAWDOWN_MAGNITUDE'] * 100:.2f}%；S003-v1为{s['NET_ANNUAL_RETURN'] * 100:.2f}%、{s['DRAWDOWN_MAGNITUDE'] * 100:.2f}%。C2132中心收益更高，最大跌幅更小。",
        f"32点参数扰动后，C2132年化退化{c['PARAMETER_RETURN_DEGRADATION'] * 100:.2f}个百分点、回撤恶化{c['PARAMETER_DRAWDOWN_DEGRADATION'] * 100:.2f}个百分点；S003分别为{s['PARAMETER_RETURN_DEGRADATION'] * 100:.2f}、{s['PARAMETER_DRAWDOWN_DEGRADATION'] * 100:.2f}个百分点。结合各自参数域解释，不能把同一几何距离当作相同经济冲击。",
        f"费用加倍后，C2132年化为{(c['NET_ANNUAL_RETURN'] - c['STRESS_ANNUAL_LOSS']) * 100:.2f}%，S003为{(s['NET_ANNUAL_RETURN'] - s['STRESS_ANNUAL_LOSS']) * 100:.2f}%。两者绝对年化费用损失都接近4个百分点，S003原本利润空间较薄，已转为负收益。",
    ]
    stat["plain_findings"] = findings
    write(OUT / "comparison.json", stat)
    rows = []
    labels = [
        ("年化净收益", "NET_ANNUAL_RETURN", "%"),
        ("全区间最大回撤", "DRAWDOWN_MAGNITUDE", "%"),
        ("每60交易日完成交易", "FULL_SAMPLE_FREQUENCY", "笔"),
        ("参数扰动：年化退化", "PARAMETER_RETURN_DEGRADATION", "百分点"),
        ("参数扰动：回撤恶化", "PARAMETER_DRAWDOWN_DEGRADATION", "百分点"),
        ("126日滚动超额收益Q10", "ROLLING_EXCESS_Q10", "百分点"),
        ("前10%盈利交易贡献", "PROFIT_CONCENTRATION", "%"),
        ("每侧费用10bp→20bp年化损失", "STRESS_ANNUAL_LOSS", "百分点"),
    ]
    for label, key, unit in labels:
        nums = [summaries[f]["values"][key] for f in ("S013", "S003")]
        formatted = [f"{number * (1 if unit == '笔' else 100):.4f}{unit}" for number in nums]
        rows.append(
            f"<tr><td>{html.escape(label)}</td><td>{formatted[0]}</td><td>{formatted[1]}</td></tr>"
        )
    for family in ("S013", "S003"):
        assert summaries[family]["uncertainty"]["status"] == "AVAILABLE"
    intervals = []
    for family in ("S013", "S003"):
        u = summaries[family]["uncertainty"]
        intervals.append(f"[{u['lower_95'] * 100:.4f}, {u['upper_95'] * 100:.4f}]百分点")
    rows.append(
        f"<tr><td>超额年化收益95%重抽样区间</td><td>{intervals[0]}</td><td>{intervals[1]}</td></tr>"
    )
    rows.append(
        "<tr><td>完整研究族选择偏差</td><td>统一口径证据缺失，PBO/DSR不可比</td><td>统一口径证据缺失，PBO/DSR不可比</td></tr>"
    )
    stressed = [
        f"{(values['NET_ANNUAL_RETURN'] - values['STRESS_ANNUAL_LOSS']) * 100:.4f}%"
        for values in (c, s)
    ]
    rows.append(
        f"<tr><td>压力费用下的年化收益</td><td>{stressed[0]}</td><td>{stressed[1]}</td></tr>"
    )
    benchmark = summaries["S013"]["benchmark"]
    rows.append(
        f"<tr><td>共同买入持有：年化 / 最大回撤</td><td colspan='2'>{benchmark['NET_ANNUAL_RETURN'] * 100:.4f}% / {benchmark['DRAWDOWN_MAGNITUDE'] * 100:.4f}%</td></tr>"
    )
    report = (
        """<!doctype html><html lang="zh"><meta charset="utf-8"><title>C2132 与 S003-v1 统一对照</title>
<style>body{font:16px/1.7 system-ui,sans-serif;max-width:1060px;margin:40px auto;padding:0 24px;color:#17252c}table{border-collapse:collapse;width:100%;margin:24px 0}td,th{padding:9px 14px;border:1px solid #c9d4da;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#e9f2f5}a{color:#176f8c}.note{background:#f5f7f8;padding:16px}</style>
<h1>C2132 与 S003-v1：同口径原策略对照</h1>
<p>共同区间2021-04-23至2026-09-08，共1305个交易日；各100万元。每日、日内成交和净值计价均使用同一后复权因子与2021-04-22锚点；标准每侧0.1%，压力每侧0.2%。共同可执行买入持有基准完全一致。</p>
<p>保留各自原参数与规则。C2132保留原买入确认及牛熊进出机制；S003保留一半核心仓与上午库存轮转交易。没有优化、删改规则、选取优胜扰动点或开启新机制实验。</p>
<table><thead><tr><th>指标（五项自检及账户表现）</th><th>C2132</th><th>S003-v1</th></tr></thead><tbody>"""
        + "".join(rows)
        + """</tbody></table>
<div class="note"><p>年化收益：把本次整个账户净收益换算为每年平均增长速度。最大回撤：账户从历史高点到后续低点的最大跌幅，包含初始资金。交易频率：完成买入和退出的笔数×60/1305。</p>
<p>参数自检：同一5%总域宽标准化距离、32点、种子13，C2132为13维原域，S003为2维、事前声明L=[1,252]与q=[0,1]，实际L48至72。S003的50%核心仓与50%事件仓结构固定，本检查仅覆盖L/q，不代表仓位结构也稳健。方法一致不等于经济冲击完全相同；S003的有限L域不是原历史搜索域。首日及全部信号的热身完整性已检查，不使用收益决定起始日期。</p>
<p>时间自检：126个交易日滚动、每21日一步；相对共同买入持有基准累计收益差的10%分位数。集中性：盈利闭合交易中前ceil(10%×盈利笔数)笔净利润占全部正净利润的比例。S003未闭合核心仓的涨跌计入整体净值，但不计闭合交易集中性，所以这个指标不能完整代表核心仓收益来源。</p>
<p>统计自检：相同配对平稳分块重抽样，2000次、平均块长20、种子13。区间不是未来成功概率。两族完整搜索收益矩阵无法在本次统一条件下复用，因此PBO/DSR明确缺失；旧诊断另列来源，不伪装为本次数据。两策略均使用已见开发数据，没有独立样本外验证。</p>
<p>后复权消除分红除息造成的价格断点；它并不把分红的经济收益从总回报中扣除。本次未另加现金分红，以免重复计算。</p></div>
<div class="note"><p>账户审计状态：C2132公开原生账户校验通过；S003公开原生审计仍为FAIL。已定位校验器对后复权限价网格及未成交后阻断卖单的适配限制，并以独立逐笔校验核对原账本、成交、费用、未成交依赖及指标。补充校验不是原生审计PASS，原失败及全部账本保持不变，详情见validation.json。本次未修改平台校验器。</p></div>
<p>完整机器结果：<a href="comparison.json">comparison.json</a>；事前方案：<a href="declaration.json">declaration.json</a>；账户证据引用：<a href="account_receipts.json">account_receipts.json</a>；五项自检：<a href="S013-assessment.json">C2132</a>、<a href="S003-assessment.json">S003-v1</a>；完整校验：<a href="validation.json">validation.json</a>。</p>
<p>本次对照已完成，后续研究暂停，等待用户下一步指令。</p></html>"""
    )
    report = report.replace(
        "<table><thead>",
        "".join(f"<p>{html.escape(finding)}</p>" for finding in findings) + "<table><thead>",
        1,
    )
    (OUT / "comparison.html").write_text(report, encoding="utf-8")
    source_dir = OUT / "sources"
    source_dir.mkdir(exist_ok=True)
    for name in (
        "run_compare.py",
        "closeout.py",
        "local_data.py",
        "assessment_helper.py",
        "focused.py",
        "focused.json",
        "method.json",
        "local_prepare_probe.json",
        "local_5m_audit.json",
        "driver_review.json",
        "driver_review_resolution.json",
        "local_data_freeze.json",
        "declare_method.py",
        "closeout_failed_v1.py",
        "closeout_failed_v1.json",
        "diagnose_s003_audit.py",
        "s003_audit_diagnosis.json",
        "overlay_hfq_validation.py",
        "s003_strict_proof.json",
        "verify_published_projection.py",
        "s003_projection_proof.json",
        "verify_overlay_hfq.py",
        "overlay_hfq_focused.py",
        "overlay_hfq_focused.json",
        "overlay_hfq_method.json",
    ):
        if (WORK / name).exists():
            shutil.copyfile(WORK / name, source_dir / name)
    shutil.copytree(WORK / "geometry-review", source_dir / "geometry-review", dirs_exist_ok=True)
    for source in WORK.glob("local_*"):
        if source.is_file() and source.suffix in (".py", ".json"):
            shutil.copyfile(source, source_dir / source.name)
    if (WORK / "history").is_dir():
        shutil.copytree(WORK / "history", source_dir / "history", dirs_exist_ok=True)
    validation = {
        "status": "COMPLETE_WITH_PUBLIC_AUDIT_LIMITATION",
        "native_public_account_evidence_PASS": sum(x["native_public_validation"] == "PASS" for x in checks),
        "native_public_account_evidence_FAIL_preserved": sum(x["native_public_validation"] == "FAIL" for x in checks),
        "supplemental_strict_S003_accounts_PASS": 34,
        "full_authenticated_S003_projections_exact": 34,
        "audit_limit": stat["account_audit_limit"],
        "account_checks": checks,
        "current_SE_panel_exact_recomputations": 2,
        "independent_performance_and_parameter_quantiles": "PASS",
        "exact_common_benchmark": "PASS",
        "common_HFQ_pricing_and_daily_frames": "PASS",
        "source_hashes": {
            p.relative_to(OUT).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in source_dir.rglob("*")
            if p.is_file()
        },
        "new_mechanism_or_optimization": False,
        "status_after_delivery": "PAUSED",
    }
    states = cache_read(WORK / "prepared.pkl.gz")
    references = {}
    for family, experiment, *_ in states:
        context = ctx(family)
        refs = {
            "comparison": material(
                context, experiment, "unified-comparison-results", stat
            ).to_dict(),
            "validation": material(
                context, experiment, "unified-comparison-validation", validation
            ).to_dict(),
        }
        refs["report"] = publish_evidence(
            context,
            MaterialEvidenceWrite(
                experiment,
                "plain-comparison-report",
                (OUT / "comparison.html").read_bytes(),
                "text/html",
                "html",
            ),
        ).to_dict()
        references[family] = refs
    write(OUT / "validation.json", validation)
    write(OUT / "completion_references.json", references)
    print(
        json.dumps({"status": stat["status"], "strategies": summaries}, ensure_ascii=False), flush=True
    )


if __name__ == "__main__":
    main()
