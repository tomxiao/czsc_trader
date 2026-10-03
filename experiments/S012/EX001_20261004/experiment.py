"""S012 data and temporal-availability census; no return-based selection."""
from datetime import date
import json
from importlib.metadata import version
from pathlib import Path
import numpy as np
import pandas as pd
from dataflows import DataRequest, DataStatus
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentCapabilities, ExperimentProtocol, ExperimentStage, ExperimentResult,
    ExperimentOutcome, ExperimentPrecheckResult, ExperimentPreflightCheck, ExperimentPreflightStatus, ExperimentDependency,
)

REQUESTS = (
    ("raw", "etf.unadjusted_daily", "518850.SH"),
    ("hfq", "etf.ohlcv", "518850.SH"),
    ("calendar", "calendar.trading_sessions", "SSE"),
    ("sge", "metal.sge_gold_daily", "Au99.99"),
    ("futures", "futures.shfe_gold.daily", "AU.SHFE"),
    ("real_yield", "macro.us_real_yield_daily", None),
    ("nominal_yield", "macro.us_nominal_yield_daily", None),
    ("fx", "fx.usdcnh_daily", None),
    ("shares", "etf.share_size", "518850.SH"),
    ("vix", "index.vix_daily", None),
    ("shibor", "macro.shibor_daily", None),
)


def coverage(frame):
    dates = pd.to_datetime(frame.Date)
    return {"rows": len(frame), "start": str(dates.min().date()), "end": str(dates.max().date()),
            "duplicate_dates": int(dates.duplicated().sum()), "columns": list(frame.columns),
            "missing_cells": {str(k): int(v) for k, v in frame.isna().sum().items() if v}}


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            2, "EX001_20261004", "S012", ExperimentMode.FORMAL,
            "既有DFLS黄金相关数据是否足以支持因果组件研究？",
            "ETF自身价格、黄金现货期货、利率汇率及资金流可覆盖互补的竞争机制；不完整或不可得输入须单独排除。",
            ("来源失败或覆盖不足不得视为可用。", "无法约束历史可得性的字段不得宣称因果预测证据。"),
            date(2026, 9, 30), 12001, tuple(x[1] for x in REQUESTS),
            ExperimentProtocol(ExperimentStage.DATA_GATE,
                ("人民币黄金受金价、汇率、机会成本及交易摩擦共同影响。",),
                ("趋势与反转", "利率与汇率", "现货期货和ETF相对价格", "份额、成交及波动状态"),
                ("核验数据权限、覆盖、字段和时间语义，确定下一轮输入。",),
                ("状态、覆盖、缺失、复权因子变化、可得时点",),
                ("全部请求为既有Tushare来源；快照探查不自动裁决全期可用。", "不计算绩效、不筛选因子。")),
            ExperimentDataScope.DEVELOPMENT, subjects=("518850.SH",),
            dependencies=tuple(ExperimentDependency(p, version(p)) for p in ("numpy", "pandas", "tsfresh")),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def synthetic_precheck(self):
        frame = pd.DataFrame({"Date": pd.to_datetime(["2020-06-05", "2020-06-08"]), "Close": [1., 2.]})
        audit = coverage(frame)
        assert audit["rows"] == 2 and audit["duplicate_dates"] == 0
        duplicate = coverage(pd.concat([frame, frame.iloc[:1]]))
        assert duplicate["duplicate_dates"] == 1
        return ExperimentPrecheckResult((ExperimentPreflightCheck("CENSUS", ExperimentPreflightStatus.PASS,
            "合成日期、重复行与JSON结构核验。"),), ExperimentResult(ExperimentOutcome.PASS, audit, {}))

    def execute(self, context):
        audit, artifacts, frames = {}, [], {}
        for name, dataset, symbol in REQUESTS:
            request = DataRequest(dataset, symbol, "2020-06-05", "2026-09-30", None)
            result = context.data.fetch(request)
            record = {"dataset": dataset, "symbol": symbol, "status": result.status.value,
                      "warnings": list(result.warnings), "snapshot": True}
            if result.status is DataStatus.READY:
                frame = result.dataframe
                frames[name] = frame
                record.update(coverage(frame))
                ident = result.identity
                record["identity"] = {"dataset": ident.dataset, "source": ident.source,
                    "symbol": ident.symbol, "start": ident.data_start, "end": ident.data_cutoff,
                    "content_sha256": ident.content_sha256, "metadata": dict(ident.metadata)}
                frame.to_parquet(context.workspace.path(f"data/{name}.parquet"), index=False)
                artifacts.append(context.workspace.register_artifact(f"data/{name}.parquet", "source_data"))
            else:
                record["error"] = {"code": result.error.code, "message": result.error.message}
            audit[name] = record
            print(json.dumps({"input": name, "status": record["status"], "rows": record.get("rows"), "error": record.get("error")}, ensure_ascii=False), flush=True)
        if "raw" in frames and "hfq" in frames:
            raw, hfq = frames["raw"].set_index("Date"), frames["hfq"].set_index("Date")
            factor = hfq.Close.div(raw.Close).dropna()
            audit["adjustment_audit"] = {"factor_min": float(factor.min()), "factor_max": float(factor.max()),
                "relative_change_count_gt_1e_7": int((factor.pct_change().abs() > 1e-7).sum()),
                "note": "恒定比率可支持本区间价格收益一致，不能证明历史发布日期。"}
        path = context.workspace.path("data_audit.json")
        path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
        artifacts.append(context.workspace.register_artifact("data_audit.json", "data_audit"))
        return ExperimentResult(ExperimentOutcome.PASS,
            {"requests": len(REQUESTS), "ready": sum(v.get("status") == "READY" for v in audit.values())},
            {"scope": "数据可用性检查；失败输入保留，收益机制未评价。"}, tuple(artifacts))
