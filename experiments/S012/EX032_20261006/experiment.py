"""Managed preliminary GVZ/full-window and USDOLLAR/finite-window experiment."""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import numpy as np
import pandas as pd
from research_experiment import (
    ResearchExperiment,
    ExperimentDefinition,
    ExperimentMode,
    ExperimentDataScope,
    ExperimentCapabilities,
    ExperimentProtocol,
    ExperimentStage,
    ExperimentResult,
    ExperimentOutcome,
    ExperimentDependency,
    ExperimentPrecheckResult,
    ExperimentPreflightCheck,
    ExperimentPreflightStatus,
    ExperimentCapability,
)
from .mechanisms import build, synthetic_frames, HYPOTHESES
from .diagnostics import run, labels

EID = "EX032_20261006"
INPUTS = {
    "daily": ("EX031_20261006", "daily.parquet"),
    "baseline": ("EX031_20261006", "features.parquet"),
    "gvz": ("EX031_20261006", "data/gvz.parquet"),
    "usdollar": ("EX031_20261006", "data/usdollar.parquet"),
    "vix": ("EX004_20261004", "data/vix.parquet"),
}


def plain(value):
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            2,
            EID,
            "S012",
            ExperimentMode.FORMAL,
            "低相对波动的收益来源与黄金重定价、回调及本地补涨能否形成增量收益组件？",
            "依据EX031低比值反向线索拆分风险来源；检验黄金需求延续和本地回调补涨的竞争解释。",
            (
                "同费用父对照或价格、VIX水平控制后无增量；延迟后消失或仅单个已见年度支持。",
                "美元有限历史不能外推2023年6月后的信息；相反状态或同窗口对照推翻解释。",
            ),
            date(2026, 9, 30),
            12032,
            (
                "index.gold_volatility_daily",
                "fx.fxcm_daily",
                "fx.usdcnh_daily",
                "index.vix_daily",
                "etf.unadjusted_daily",
            ),
            ExperimentProtocol(
                ExperimentStage.MECHANISM_DISCOVERY,
                ("用户授权主导阶段二，以挖掘收益组件为目标；沿用已授权数据。",),
                (
                    "14固定假设、5对照：比值2、分子分母四象限4、黄金趋势与回调2、本地补涨2、低比值价格竞争2、有限美元确认2。",
                ),
                ("收益读取前冻结方向、父对照、主期限与统计协议；不择优修改参数。",),
                ("T+1开盘到开盘1/3/5/10/20日净事件收益；D07/D08/D13/D14主10日，其余主5日。",),
                (
                    "GVZ初版Date/InitialReleaseDate保留，max两日后次日16:00中国时间为政策可用时点。",
                    "USDOLLAR源日后2自然日08:00；美元决策日截止2023-06-01，不向全窗口填充。",
                    "VIX/GVZ同观测日配对，配对126源观察期、至少63期的先前比值及分子分母各自中位数为固定对照。",
                    "父对照限同有效窗口；状态匹配、原OLS及VIX/GVZ双水平OLS竞争归因，均为回顾诊断。",
                    "成本各侧0.1/0.2%，延迟0/2日；区块999、循环移位399、BH14均为诊断。",
                    "全1535日频率分母保留；有限窗口另列，标签允许已授权ETF完整历史内成熟。",
                    "所有历史已见；初步组件验证，不构建账户或宣称经济目标达成。",
                ),
                predecessor_experiment_ids=("EX031_20261006", "EX004_20261004"),
            ),
            ExperimentDataScope.DEVELOPMENT,
            subjects=("518850.SH",),
            dependencies=tuple(ExperimentDependency(p, version(p)) for p in ("numpy", "pandas")),
            capabilities=ExperimentCapabilities(reads_real_returns=True, selects_parameters=False),
        )

    def synthetic_precheck(self):
        d, baseline, g, u, v = synthetic_frames()
        cut = d.index[299]
        f, s, valid, a = build(d, baseline, g, u, v)
        assert a.loc[d.index[123], "paired_risk_SourceDate"] == d.index[122]
        fp, sp, vp, ap = build(
            d.loc[:cut],
            baseline.loc[:cut],
            g.loc[g.Date <= cut],
            u.loc[u.Date <= cut],
            v.loc[v.Date <= cut],
        )
        for x, y in ((f, fp), (s, sp), (valid, vp), (a, ap)):
            pd.testing.assert_frame_equal(x.loc[:cut], y)
        changed = g.copy()
        changed.loc[changed.Date > cut, "Close"] *= 10
        ff, ss, vv, _ = build(d, baseline, changed, u, v)
        for x, y in ((f, ff), (s, ss), (valid, vv)):
            pd.testing.assert_frame_equal(x.loc[:cut], y.loc[:cut])
        limited = u.iloc[:250]
        _, ls, lv, _ = build(d, baseline, g, limited, v)
        usd_keys = ["D13", "D14", "C_USDTREND"]
        assert not ls.loc[ls.index > limited.Date.max(), usd_keys].any().any()
        assert not lv.loc[lv.index > limited.Date.max(), usd_keys].any().any()
        absent = g.copy()
        absent["Close"] = np.nan
        _, gs, gv, _ = build(d, baseline, absent, u, v)
        assert not gs[[x[0] for x in HYPOTHESES]].any().any()
        assert not gv[[x[0] for x in HYPOTHESES]].any().any()
        observed = f[["ratio_log5", "vix_log5", "gvz_log5"]].dropna()
        np.testing.assert_allclose(
            observed.ratio_log5, observed.vix_log5 - observed.gvz_log5, atol=1e-12
        )
        # Every pair quadrant partitions its complete common parent, equality in low.
        common = valid[["D03", "D04", "D05", "D06"]].all(axis=1)
        np.testing.assert_array_equal(
            s[["D03", "D04", "D05", "D06"]].sum(axis=1), (s.C_SAFE & common).astype(int)
        )
        p = labels(d, 5, 0, 0.001)
        assert abs(p.net.iloc[0] - (d.Open.iloc[6] / d.Open.iloc[1] * 0.999 / 1.001 - 1)) < 1e-12
        assert p.net.iloc[-6:].isna().all()
        checks = tuple(
            ExperimentPreflightCheck(k, ExperimentPreflightStatus.PASS, text)
            for k, text in (
                ("CAUSAL_PREFIX", "实际计算截断与未来GVZ扰动不改变历史特征和信号"),
                ("BATCH_RELEASE_ORDER", "同可得时点选取最新观测；非单调可得输入明确拒绝"),
                ("FINITE_USD_SCOPE", "美元决策截止后无信号或有效位，缺GVZ不产生GVZ信号"),
                ("LABEL_BOUNDARY", "T+1开盘标签、双侧费用及未成熟尾部边界核验"),
            )
        )
        return ExperimentPrecheckResult(
            checks,
            ExperimentResult(
                ExperimentOutcome.PASS,
                {"synthetic_rows": len(d), "hypotheses": len(HYPOTHESES)},
                {},
            ),
        )

    def execute(self, context):
        context.record_capability(ExperimentCapability.READ_REAL_RETURNS)
        base = Path(__file__).resolve().parents[1]
        frames = {}
        hashes = {}
        artifacts = []

        def save(name, value, kind):
            context.workspace.path(name).write_text(
                json.dumps(plain(value), ensure_ascii=False, indent=2, allow_nan=False, default=str)
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            artifacts.append(context.workspace.register_artifact(name, kind))

        for name, (eid, path) in INPUTS.items():
            prior = context.predecessors[eid]
            expected = {a.path: a.sha256 for a in prior.artifacts}
            source = base / eid / "artifacts/rex" / path
            digest = sha256(source.read_bytes()).hexdigest()
            if digest != expected[path]:
                raise ValueError(f"changed formal source {eid}/{path}")
            hashes[name] = {"experiment_id": eid, "artifact": path, "sha256": digest}
            frames[name] = pd.read_parquet(source)
            frames[name].attrs = {}
        audit = {
            "input_mode": "receipt-authenticated previously managed DFLS snapshots",
            "prior_data_audit": "EX031_20261006/artifacts/rex/data_audit.json",
        }
        for name in ("gvz", "usdollar"):
            frames[name].to_parquet(context.workspace.path(f"data/{name}.parquet"), index=False)
            artifacts.append(
                context.workspace.register_artifact(f"data/{name}.parquet", "source_data")
            )
        d = frames["daily"]
        if (
            len(d) != 1535
            or str(d.index[0].date()) != "2020-06-05"
            or str(d.index[-1].date()) != "2026-09-30"
        ):
            raise ValueError("original full development window differs")
        f, s, v, alignment = build(
            d, frames["baseline"], frames["gvz"], frames["usdollar"], frames["vix"]
        )
        rows, annual, inference, panels = run(d, f, s, v, seed=12032)
        if len(rows) != 380 or len(annual) != 2660 or len(inference) != 14:
            raise ValueError("fixed research family counts differ")
        coverage = {
            "sessions": len(d),
            "hypotheses": 14,
            "controls": 5,
            "paths": len(rows),
            "annual_rows": len(annual),
            "usdollar_source_end": "2023-06-01",
            "all_history_seen": True,
            "quality_future_masks_used": False,
            "source_calendar_tolerance_days": 7,
            "valid_windows": {
                k: {
                    "days": int(v[k].sum()),
                    "first": str(v.index[v[k]][0].date()) if v[k].any() else None,
                    "last": str(v.index[v[k]][-1].date()) if v[k].any() else None,
                }
                for k in s
            },
            "time_boundary": "政策可用时点；逐条历史发布时间未核实，额外延迟敏感性不能替代真实发布时间证明。",
            "selection_history": "EX001—EX031已见；14定义在本轮正式收益读取前冻结，非独立样本外。",
            "price_roles": "USDOLLAR为FXCM四币篮子代理，非ICE DXY；GVZ为GLD期权预期波动指标，非现货黄金实际波动。",
        }
        for name, value, kind in (
            ("source_hashes.json", hashes, "formal_source_lineage"),
            ("data_audit.json", audit, "source_data"),
            ("opportunities.json", rows, "mechanism"),
            ("annual.json", annual, "mechanism"),
            ("inference.json", inference, "uncertainty"),
            ("coverage.json", coverage, "coverage"),
            (
                "hypothesis_definitions.json",
                [
                    dict(zip(("id", "primary_horizon", "parent", "role", "hypothesis"), x))
                    for x in HYPOTHESES
                ],
                "protocol",
            ),
        ):
            save(name, value, kind)
        for name, frame in (
            ("features", f),
            ("signals", s),
            ("valids", v),
            ("alignment", alignment),
            ("labels", panels),
            ("daily", d),
        ):
            frame.to_parquet(context.workspace.path(name + ".parquet"))
            artifacts.append(context.workspace.register_artifact(name + ".parquet", "mechanism"))
        print("PATHS", len(rows), "PRIMARY", len(inference), flush=True)
        return ExperimentResult(
            ExperimentOutcome.INCONCLUSIVE,
            {"hypotheses": 14, "paths": len(rows), "primary_inference": 14},
            {
                "scope": "分子分母与价格状态机制竞争；有限美元窗口不外推，阶段二后续判断按人工报告；无账户目标复验。"
            },
            tuple(artifacts),
        )
