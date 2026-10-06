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
from dataflows import DataRequest, Dataset, PreparePolicy
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

EID = "EX030_20261006"
INPUTS = {
    "daily": ("EX029_20261006", "daily.parquet"),
    "baseline": ("EX029_20261006", "features.parquet"),
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
            "GVZ相对风险和有限美元篮子变化能否提供黄金ETF事件收益的增量信息？",
            "股票风险与黄金风险的差异可能改变避险传导；美元走弱可能支持黄金需求。",
            (
                "同费用父对照或价格、VIX水平控制后无增量；延迟后消失或仅单个已见年度支持。",
                "美元有限历史不能外推2023年6月后的信息；相反状态或同窗口对照推翻解释。",
            ),
            date(2026, 9, 30),
            12030,
            (
                "index.gold_volatility_daily",
                "fx.fxcm_daily",
                "fx.usdcnh_daily",
                "index.vix_daily",
                "etf.unadjusted_daily",
            ),
            ExperimentProtocol(
                ExperimentStage.MECHANISM_DISCOVERY,
                ("用户授权切回RSCH，用完整GVZ和有限美元篮子数据初步验证。",),
                ("9固定假设和4对照；U01/U02/U03/U04有限美元，V01—V05完整GVZ。",),
                ("收益读取前冻结方向、父对照、主期限与统计协议；不择优修改参数。",),
                ("T+1开盘到开盘1/3/5/10/20日净事件收益；主期限10/5/5/5/5/5/10/10/5。",),
                (
                    "GVZ初版Date/InitialReleaseDate保留，max两日后次日16:00中国时间为政策可用时点。",
                    "USDOLLAR源日后2自然日08:00；美元决策日截止2023-06-01，不向全窗口填充。",
                    "VIX/GVZ同观测日配对，126源观察期、至少63期的先前中位数为固定对照。",
                    "父对照限同有效窗口；原价格/汇率状态匹配及OLS额外控制VIX水平。",
                    "成本各侧0.1/0.2%，延迟0/2日；区块999、循环移位399、BH9均为诊断。",
                    "全1535日频率分母保留；有限窗口另列，标签允许已授权ETF完整历史内成熟。",
                    "所有历史已见；初步组件验证，不构建账户或宣称经济目标达成。",
                ),
                predecessor_experiment_ids=("EX029_20261006", "EX004_20261004"),
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
        usd_keys = ["U01", "U02", "U03", "U04", "C_USD"]
        assert not ls.loc[ls.index > limited.Date.max(), usd_keys].any().any()
        assert not lv.loc[lv.index > limited.Date.max(), usd_keys].any().any()
        absent = g.copy()
        absent["Close"] = np.nan
        _, gs, gv, _ = build(d, baseline, absent, u, v)
        assert not gs[["V01", "V02", "V03", "V04", "V05", "U04"]].any().any()
        assert not gv[["V01", "V02", "V03", "V04", "V05", "U04"]].any().any()
        p = labels(d, 5, 0, 0.001)
        assert abs(p.net.iloc[0] - (d.Open.iloc[6] / d.Open.iloc[1] * 0.999 / 1.001 - 1)) < 1e-12
        assert p.net.iloc[-6:].isna().all()
        checks = tuple(
            ExperimentPreflightCheck(k, ExperimentPreflightStatus.PASS, text)
            for k, text in (
                ("CAUSAL_PREFIX", "实际计算截断与未来GVZ扰动不改变历史特征和信号"),
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
        requests = {
            "gvz": DataRequest(
                Dataset.GOLD_VOLATILITY_DAILY, None, "2020-01-01", "2026-09-30", "2026-09-30"
            ),
            "usdollar": DataRequest(
                Dataset.FXCM_DAILY, "USDOLLAR.FXCM", "2020-01-01", "2023-06-01", "2023-06-01"
            ),
        }
        prepared = context.data.prepare(tuple(requests.values()), policy=PreparePolicy.REUSE)
        if not prepared.ready:
            raise RuntimeError(f"data preparation failed: {prepared.items}")
        audit = {"prepared": plain(prepared.reference), "inputs": {}}
        for name, req in requests.items():
            result = context.data.fetch(req, prepared=prepared.reference)
            if not result.ready:
                raise RuntimeError(f"{name} fetch failed: {result.error}")
            frames[name] = result.dataframe.copy()
            frames[name].attrs = {}
            frames[name].to_parquet(context.workspace.path(f"data/{name}.parquet"), index=False)
            artifacts.append(
                context.workspace.register_artifact(f"data/{name}.parquet", "source_data")
            )
            audit["inputs"][name] = {"request": plain(req), "identity": plain(result.identity)}
            print("INPUT", name, len(frames[name]), flush=True)
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
        rows, annual, inference, panels = run(d, f, s, v, seed=12030)
        if len(rows) != 260 or len(annual) != 1820 or len(inference) != 9:
            raise ValueError("fixed research family counts differ")
        coverage = {
            "sessions": len(d),
            "hypotheses": 9,
            "controls": 4,
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
            "selection_history": "EX001—EX029已见；9定义在本轮正式收益读取前冻结，非独立样本外。",
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
            {"hypotheses": 9, "paths": len(rows), "primary_inference": 9},
            {
                "scope": "初步机制验证；有限美元窗口不外推，阶段二后续判断按人工报告；无账户目标复验。"
            },
            tuple(artifacts),
        )
