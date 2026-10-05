"""Managed full-history minute-shape opportunity research."""

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
from .analysis import build_features, make_signals, summary

PACKAGES = ("numpy", "pandas", "scipy", "tsfresh", "expr_codegen")


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            2,
            "EX015_20261005",
            "S012",
            ExperimentMode.FORMAL,
            "日内路径、成交权重及冲击吸收能否补充现有低频黄金机会？",
            "相同日收益与成交总量下，分钟路径顺序和冲击吸收可能提供次日后的独立收益信息。",
            (
                "费用后增量不稳、价格成交量控制后消失或异常日期支配。",
                "限价容量不足与开发池选择偏差均披露，不新增用户经济硬门。",
            ),
            date(2026, 9, 30),
            12015,
            (Dataset.ETF_UNADJUSTED_DAILY.value, Dataset.ETF_UNADJUSTED_INTRADAY.value),
            ExperimentProtocol(
                ExperimentStage.MECHANISM_DISCOVERY,
                ("自主完成阶段二组件面板，重点收益机会；阶段三未授权。",),
                ("冲击时点与恢复、价格成交权重、低量冲击、趋势效率、长休市风险补偿。",),
                ("分钟tsfresh实际提取及expr_codegen批量pandas表达式逐值核验。",),
                ("上一年底历史四分位；2022起研究；双方向竞争解释、1/3/5日标签，5日为筛查主标签。",),
                (
                    "T17:00决策，次日开盘事件标签，各侧10/20bp；延迟2日诊断，前收盘限价触价。",
                    "日收益/三日动量/量比三分位年度匹配及7价格量风险变量OLS对照；非重叠、年度、异常敏感性。",
                    "199次20日块排列与全部信号BH调整；全开发池，不是独立封存验证或账户回测。",
                ),
                predecessor_experiment_ids=("EX014_20261005", "EX010_20261004", "EX013_20261005"),
            ),
            ExperimentDataScope.DEVELOPMENT,
            subjects=("518850.SH",),
            dependencies=tuple(ExperimentDependency(p, version(p)) for p in PACKAGES),
            capabilities=ExperimentCapabilities(reads_real_returns=True, selects_parameters=True),
        )

    def synthetic_precheck(self):
        days = pd.bdate_range("2020-01-01", periods=270)
        d = pd.DataFrame(
            {
                "Date": days,
                "Open": 4.0,
                "High": 4.1,
                "Low": 3.9,
                "Close": 4.0,
                "Volume": 4800.0,
                "Amount": 19200.0,
            }
        )
        times = [
            f"{h:02d}:{v:02d}"
            for h, start, end in (
                (9, 35, 60),
                (10, 0, 60),
                (11, 0, 35),
                (13, 5, 60),
                (14, 0, 60),
                (15, 0, 5),
            )
            for v in range(start, end, 5)
        ]
        m = pd.DataFrame(
            [
                {
                    "Date": day + pd.Timedelta(hours=int(t[:2]), minutes=int(t[3:])),
                    "Close": 4 + np.sin(i) * 0.005,
                    "Volume": 100.0,
                }
                for day in days
                for i, t in enumerate(times)
            ]
        )
        m["AvailableDate"] = m.Date
        raw, f, invalid = build_features(d, m, d, 1)
        assert not invalid and len(f) == 270 and f.sell_pressure.notna().all()
        altered = d.copy()
        altered.loc[269, "Open"] = 40.0
        _, changed, _ = build_features(altered, m, d, 1)
        pd.testing.assert_frame_equal(
            f.iloc[:269].drop(columns="closure_days"),
            changed.iloc[:269].drop(columns="closure_days"),
        )
        signals, thresholds, valids = make_signals(f)
        assert not signals.filter(regex="_(low|high)$").to_numpy().any()
        delayed = m.copy()
        delayed.loc[0, "AvailableDate"] = days[1]
        _, broken, invalid = build_features(d, delayed, d, 1)
        assert str(days[0].date()) in invalid and pd.isna(broken.sell_pressure.iloc[0])
        sample = ExperimentResult(
            ExperimentOutcome.INCONCLUSIVE,
            {"synthetic_rows": 270},
            {"signals": len(signals.columns)},
        )
        return ExperimentPrecheckResult(
            (
                ExperimentPreflightCheck(
                    "CAUSAL_INTRADAY",
                    ExperimentPreflightStatus.PASS,
                    "完整分钟时点、延迟可得拒绝、未来开盘扰动、阈值预热及生成表达式逐值一致。",
                ),
            ),
            sample,
        )

    def execute(self, context):
        context.record_capability(ExperimentCapability.READ_REAL_RETURNS)
        context.record_capability(ExperimentCapability.SELECT_PARAMETERS)
        frames, audit, artifacts, bad = {}, {}, [], set()

        def save(name, value, kind):
            context.workspace.path(name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            artifacts.append(context.workspace.register_artifact(name, kind))

        for name, symbol, freq in (
            ("daily", "518850.SH", "daily"),
            ("minute", "518850.SH", "5m"),
            ("peer", "518880.SH", "daily"),
        ):
            dataset = (
                Dataset.ETF_UNADJUSTED_DAILY if freq == "daily" else Dataset.ETF_UNADJUSTED_INTRADAY
            )
            req = DataRequest(
                dataset, symbol, "2020-06-05", "2026-09-30", "2026-09-30", frequency=freq
            )
            prepared = context.data.prepare((req,), policy=PreparePolicy.REUSE)
            if not prepared.ready:
                raise RuntimeError(f"{name} prepare blocked: {prepared.items[0].error}")
            result = context.data.fetch(req, prepared=prepared.reference)
            if not result.ready:
                raise RuntimeError(f"{name} fetch blocked: {result.error}")
            metadata = dict(result.identity.metadata)
            q = metadata["ohlcv_quality"]
            bad.update(q["daily"]["inaccurate_dates"])
            if freq != "daily":
                bad.update(q["minute"]["inaccurate_dates"])
            audit[name] = {
                "quality": q,
                "content_sha256": result.identity.content_sha256,
                "reference": {
                    "space_id": str(prepared.reference.space_id),
                    "preparation_id": str(prepared.reference.preparation_id),
                    "manifest_sha256": prepared.reference.manifest_sha256,
                },
            }
            result.dataframe.to_parquet(context.workspace.path(f"data/{name}.parquet"), index=False)
            artifacts.append(
                context.workspace.register_artifact(f"data/{name}.parquet", "source_data")
            )
            frames[name] = result.dataframe.copy()
            frames[name].attrs = {}
            print("INPUT", name, len(frames[name]), flush=True)
        save("data_audit.json", audit, "data_gate")
        raw, f, invalid = build_features(
            frames["daily"],
            frames["minute"],
            frames["peer"],
            context.resources.max_workers,
            context.workspace.path("generated.py"),
        )
        artifacts.append(context.workspace.register_artifact("generated.py", "codegen"))
        signals, thresholds, valids = make_signals(f)
        prior = context.predecessors["EX010_20261004"]
        a = next(a for a in prior.artifacts if a.path == "fx/signals.parquet")
        source = Path(__file__).resolve().parents[1] / "EX010_20261004/artifacts/rex" / a.path
        if sha256(source.read_bytes()).hexdigest() != a.sha256:
            raise ValueError("O01 artifact changed")
        signals["o01"] = pd.read_parquet(source).fx_q75_dip_q25.reindex(f.index).eq(1)
        valids["o01"] = pd.read_parquet(source).fx_q75_dip_q25.reindex(f.index).notna()
        print("FEATURES", len(f.columns), "SIGNALS", len(signals.columns), flush=True)
        rows, annual, tests, labels = summary(
            raw, f, signals, valids, bad, context.resources.max_workers
        )
        for name, frame in (
            ("features.parquet", f),
            ("signals.parquet", signals),
            ("valids.parquet", valids),
            ("thresholds.parquet", thresholds),
            ("labels.parquet", labels),
        ):
            frame.to_parquet(context.workspace.path(name))
            artifacts.append(context.workspace.register_artifact(name, "mechanism"))
        save("opportunities.json", rows, "mechanism")
        save("annual.json", annual, "mechanism")
        save("multiplicity.json", tests, "statistics")
        main = [
            r
            for r in rows
            if r["horizon"] == 5
            and r["delay"] == 0
            and r["fee"] == 0.001
            and r["sensitivity"] == "all"
        ]
        ranked = sorted(
            main, key=lambda r: r["increment"] if r["increment"] is not None else -1, reverse=True
        )
        save("ranking.json", ranked, "development_selection")
        save(
            "coverage.json",
            {
                "sessions": len(raw),
                "features": len(f.columns),
                "signals": len(signals.columns),
                "paths": len(rows),
                "invalid_minutes": invalid,
                "bad_dates": sorted(bad),
                "first_threshold_year": 2022,
                "source_start": "2020-06-05",
                "source_end": "2026-09-30",
                "search_history": "EX004-EX014已有结果；本轮全部信号/期限/方向留证，筛查排名为开发选择。",
                "formulae": {c: c for c in f.columns},
                "calendar_assumption": "2026-09-30前交易所开市日历预知；末两行休市特征不可得",
            },
            "coverage",
        )
        return ExperimentResult(
            ExperimentOutcome.INCONCLUSIVE,
            {
                "sessions": len(raw),
                "signals": len(signals.columns),
                "paths": len(rows),
                "best_signal": ranked[0]["signal"],
                "best_increment": ranked[0]["increment"],
            },
            {"scope": "阶段二广泛机会筛查；排名需后继复核，未创建策略候选或账户结论。"},
            tuple(artifacts),
        )
