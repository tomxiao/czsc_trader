"""Full-history intraday data gate. No return labels or opportunity selection."""
from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import pandas as pd
from dataflows import DataRequest, DataStatus
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentCapabilities, ExperimentProtocol, ExperimentStage, ExperimentResult,
    ExperimentOutcome, ExperimentPrecheckResult, ExperimentPreflightCheck,
    ExperimentPreflightStatus, ExperimentDependency,
)

REQUESTS = (
    ("target_full", "etf.unadjusted_intraday", "518850.SH", "2020-06-05", "2026-09-30", "5m"),
    ("peer_full", "etf.unadjusted_intraday", "518880.SH", "2020-06-05", "2026-09-30", "5m"),
    ("target_volume_period", "etf.unadjusted_intraday", "518850.SH", "2024-04-03", "2024-06-14", "5m"),
    ("target_daily", "etf.unadjusted_daily", "518850.SH", "2020-06-05", "2026-09-30", "daily"),
    ("calendar", "calendar.trading_sessions", "SSE", "2020-06-05", "2026-09-30", "daily"),
)


def coverage(frame):
    dates = pd.to_datetime(frame.Date)
    return {"rows": len(frame), "sessions": int(dates.dt.normalize().nunique()),
            "start": str(dates.min()), "end": str(dates.max()),
            "duplicate_times": int(dates.duplicated().sum())}


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            2, "EX011_20261004", "S012", ExperimentMode.FORMAL,
            "全部上市历史的黄金ETF分钟数据能否通过质量与时间门？",
            "7日5分钟成交量单位错误可从完整1分钟恢复；价格冲突必须保持阻断，不能提前开展收益检验。",
            ("任一目标历史交易日不能通过一致性校验。", "时间语义只能作为市场观察假设，不能证明历史API实时发布。"),
            date(2026, 9, 30), 12011, tuple(sorted({r[1] for r in REQUESTS})),
            ExperimentProtocol(ExperimentStage.DATA_GATE,
                ("用户继续阶段二，并要求先解决全历史数据，再检验收益。",),
                ("黄金ETF相对价格及日内修复机制先接受数据门核验。",),
                ("全期分钟与日线、完整交易日和显式可得性核验；失败保留。",),
                ("全期目标、全期参考ETF、成交量修复区间、日线、日历五请求。",),
                ("禁止收益标签、阈值搜索、缩短收益评价区间或覆盖前驱。",
                 "DEV预先观察到59日差异；本轮只复核受管数据质量，不是盲测。"),
                predecessor_experiment_ids=("EX010_20261004",)),
            ExperimentDataScope.DEVELOPMENT, subjects=("518850.SH",),
            dependencies=tuple(ExperimentDependency(p, version(p)) for p in ("numpy", "pandas", "tsfresh")),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def synthetic_precheck(self):
        frame = pd.DataFrame({"Date": ["2020-06-05 09:35:00", "2020-06-05 09:40:00"], "Close": [4., 4.]})
        assert coverage(frame)["sessions"] == 1
        assert coverage(pd.concat([frame, frame.iloc[:1]]))["duplicate_times"] == 1
        assert len(REQUESTS) == 5
        assert all(pd.Timestamp(r[4]).date() <= self.definition.development_cutoff for r in REQUESTS)
        return ExperimentPrecheckResult((ExperimentPreflightCheck(
            "DATA_GATE", ExperimentPreflightStatus.PASS, "日期、重复行、请求边界及结果序列化验证。"),),
            ExperimentResult(ExperimentOutcome.INCONCLUSIVE, {"full_history_ready": False}, {}))

    def execute(self, context):
        audit, artifacts, frames = {}, [], {}
        for name, dataset, symbol, start, end, frequency in REQUESTS:
            result = context.data.fetch(DataRequest(dataset, symbol, start, end, None, frequency=frequency))
            item = {"dataset": dataset, "symbol": symbol, "start": start, "end": end,
                    "frequency": frequency, "status": result.status.value}
            if result.status is DataStatus.READY:
                frames[name] = result.dataframe
                item.update(coverage(result.dataframe))
                item["content_sha256"] = result.identity.content_sha256
                item["metadata"] = dict(result.identity.metadata)
                result.dataframe.to_parquet(context.workspace.path(f"data/{name}.parquet"), index=False)
                artifacts.append(context.workspace.register_artifact(f"data/{name}.parquet", "source_data"))
            else:
                item["error"] = {"code": result.error.code, "message": result.error.message,
                                 "context": dict(result.error.context)}
            audit[name] = item
            print(json.dumps({"request": name, "status": item["status"], "rows": item.get("rows")}), flush=True)
        if "calendar" in frames:
            calendar = frames["calendar"]
            sessions = set(pd.to_datetime(calendar.loc[calendar.IsOpen.eq(1), "Date"]).dt.normalize())
            for name in ("target_full", "peer_full", "target_daily"):
                if name in frames:
                    observed = set(pd.to_datetime(frames[name].Date).dt.normalize())
                    audit[name]["missing_sessions"] = [str(x.date()) for x in sorted(sessions - observed)]
                    audit[name]["unexpected_sessions"] = [str(x.date()) for x in sorted(observed - sessions)]
        root = Path(__file__).resolve().parents[3]
        files = ("contract.py", "facade.py", "tushare_etf.py", "history_validation.py",
                 "history_repair.py", "history_patches/gold_etf_volume.py", "history_patches/tushare_518850.py",
                 "history_patches/tushare_518880.py", "history_patches/common.py")
        source = {"packages/dataflows/src/dataflows/" + p: sha256((root / "packages/dataflows/src/dataflows" / p).read_bytes()).hexdigest() for p in files}
        for name, value in (("data_audit.json", audit), ("platform_source_hashes.json", source)):
            context.workspace.path(name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
            artifacts.append(context.workspace.register_artifact(name, "data_gate"))
        ready = audit["target_full"]["status"] == "READY" and not audit["target_full"].get("missing_sessions", ["unverified"])
        return ExperimentResult(ExperimentOutcome.PASS if ready else ExperimentOutcome.INCONCLUSIVE,
            {"requests": len(REQUESTS), "ready": sum(v["status"] == "READY" for v in audit.values()),
             "full_history_ready": ready, "return_paths": 0},
            {"scope": "仅数据质量门；价格冲突未解决时收益研究停止。参考ETF仅作信息源；历史API可用性未验证。"}, tuple(artifacts))
