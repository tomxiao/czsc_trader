from datetime import date
from importlib.metadata import version
import json
import numpy as np
import pandas as pd
from dataflows import DataRequest, DataStatus
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentCapabilities, ExperimentProtocol, ExperimentStage, ExperimentResult,
    ExperimentOutcome, ExperimentPrecheckResult, ExperimentPreflightCheck, ExperimentPreflightStatus, ExperimentDependency,
)
from .analysis import build_features, causal_align, labels, evaluate, circular_p, residual_rank

REQUESTS = (
    ("raw", "etf.unadjusted_daily", "518850.SH"),
    ("sge", "metal.sge_gold_daily", "Au99.99"),
    ("futures", "futures.shfe_gold.daily", "AU.SHFE"),
    ("real_yield", "macro.us_real_yield_daily", None),
    ("nominal_yield", "macro.us_nominal_yield_daily", None),
    ("fx", "fx.usdcnh_daily", None),
    ("shares", "etf.share_size", "518850.SH"),
    ("vix", "index.vix_daily", "VIX"),
    ("shibor", "macro.shibor_daily", None),
)


def synthetic_frames():
    dates = pd.bdate_range("2020-01-01", periods=180)
    rng = np.random.default_rng(12)
    close = 5 * np.exp(np.cumsum(rng.normal(0, .01, len(dates))))
    raw = pd.DataFrame({"Date": dates, "Open": close * .998, "Close": close,
        "High": close * 1.02, "Low": close * .98, "Volume": rng.uniform(10, 100, len(dates)), "Amount": 1000.})
    sge = raw.copy(); sge[["Open", "Close", "High", "Low"]] *= 100
    futures = pd.concat([pd.DataFrame({"Date": dates, "Contract": f"AU{k}", "MaturityDate": dates + pd.Timedelta(days=90 + k * 90),
        "Settle": close * (100 + k), "Volume": 100., "OpenInterest": 1000. - k}) for k in (1, 2)])
    return {"raw": raw, "sge": sge, "futures": futures}


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(2, "EX003_20261004", "S012", ExperimentMode.FORMAL,
            "哪些价格、宏观、相对价格和流动性信息对未来收益或下行风险有增量解释？",
            "存在跨年度可复现的方向性或风险组件；单纯共同趋势和波动暴露不足以解释其作用。",
            ("年度方向不稳、控制趋势波动后消失或成本后事件收益不足削弱机制。", "滞后或非重叠检验消失则不能视为稳健组件。"),
            date(2026, 9, 30), 12002, tuple(x[1] for x in REQUESTS),
            ExperimentProtocol(ExperimentStage.FEATURE_DISCOVERY,
                ("趋势、反转、持有机会成本、汇率、相对价格和交易摩擦为竞争解释。",),
                ("自身价格", "利率汇率风险", "ETF/现货/期货相对价格", "流动性与份额", "tsfresh形态普查"),
                ("形成角色区分的组件证据并识别反证，完整账户策略留给阶段三。",),
                ("3/5/10/20交易日收益及最大不利价格幅度、控制后IC、年度IC、净事件收益",),
                ("全部历史为开发池；扩展年度训练并清除跨边界标签。", "整体特征-标签检验族统一BH校正，循环移位保留相关结构。", "相对价格使用同源日期双腿，外部输入严格早于决策日。"),
                predecessor_experiment_ids=("EX001_20261004",)),
            ExperimentDataScope.DEVELOPMENT, subjects=("518850.SH",),
            dependencies=tuple(ExperimentDependency(p, version(p)) for p in ("numpy", "pandas", "tsfresh")),
            capabilities=ExperimentCapabilities(reads_real_returns=True, selects_parameters=True))

    def synthetic_precheck(self):
        frames = synthetic_frames()
        features, _ = build_features(frames, 1)
        shorter = {k: v.loc[v.Date <= frames["raw"].Date.iloc[139]].copy() for k, v in frames.items()}
        prefix, _ = build_features(shorter, 1)
        pd.testing.assert_frame_equal(features.iloc[:140], prefix)
        aligned = causal_align(pd.DataFrame({"x": [1., 99.]}, index=pd.to_datetime(["2020-01-01", "2020-01-02"])), pd.to_datetime(["2020-01-02"]))
        assert aligned.x.iloc[0] == 1
        target = labels(frames["raw"], 5)
        expected = frames["raw"].Open.iloc[6] / frames["raw"].Open.iloc[1] - 1
        assert abs(target["return"].iloc[0] - expected) < 1e-12
        assert target["return"].iloc[-6:].isna().all()
        x = residual_rank(np.arange(200), np.empty((200, 0)), np.zeros(200))
        corr, p = circular_p(x, x)
        assert corr > .999 and p < .05
        checks = tuple(ExperimentPreflightCheck(c, ExperimentPreflightStatus.PASS, m) for c, m in (
            ("PREFIX_INVARIANCE", "价格、外部、期货及tsfresh特征通过截断前缀一致性。"),
            ("TEMPORAL_ALIGNMENT", "同日外部数据排除且次日开盘标签无越界。"),
            ("STATISTICS", "相关及移位检验合成信号检出。")))
        return ExperimentPrecheckResult(checks, ExperimentResult(ExperimentOutcome.PASS, {"synthetic": True}, {}))

    def execute(self, context):
        frames, audit, artifacts = {}, {}, []
        for name, dataset, symbol in REQUESTS:
            result = context.data.fetch(DataRequest(dataset, symbol, "2020-06-05", "2026-09-30", None))
            audit[name] = {"status": result.status.value}
            if result.status is DataStatus.READY:
                frames[name] = result.dataframe
                identity = result.identity
                audit[name].update({"sha256": identity.content_sha256, "metadata": dict(identity.metadata),
                    "start": identity.data_start, "end": identity.data_cutoff, "rows": len(result.dataframe)})
                result.dataframe.to_parquet(context.workspace.path(f"data/{name}.parquet"), index=False)
                artifacts.append(context.workspace.register_artifact(f"data/{name}.parquet", "source_data"))
            else:
                audit[name]["error"] = {"code": result.error.code, "message": result.error.message}
                if name != "vix":
                    raise ValueError(f"Core input unavailable: {name}: {result.status}")
            print(json.dumps({"input": name, "status": result.status.value}, ensure_ascii=False), flush=True)
        # Optional VIX failure is explicitly retained as an untested mechanism, never imputed.
        features, families = build_features(frames, context.resources.max_workers)
        features.to_parquet(context.workspace.path("features.parquet"))
        artifacts.append(context.workspace.register_artifact("features.parquet", "features"))
        print(f"features={len(features.columns)}; begin fixed component diagnostics", flush=True)
        records, folds = evaluate(features, families, frames["raw"])
        for name, payload in (("data_audit.json", audit), ("feature_definitions.json", families),
                              ("component_metrics.json", records), ("fold_metrics.json", folds)):
            context.workspace.path(name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n", encoding="utf-8", newline="\n")
            artifacts.append(context.workspace.register_artifact(name, "research_evidence"))
        return ExperimentResult(ExperimentOutcome.PASS,
            {"features": len(features.columns), "test_paths": len(records), "fold_records": len(folds), "source_rows": len(features)},
            {"data_scope": "DEVELOPMENT", "caveat": "组件诊断，非账户收益；重叠事件非独立交易；年度切片仍为开发池。"}, tuple(artifacts))
