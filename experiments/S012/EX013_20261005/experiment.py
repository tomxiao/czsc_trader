"""Revalidate the full target history under the confirmed DFLS acceptance rule."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date
from importlib.metadata import version
import json

import pandas as pd
from dataflows import DataRequest, Dataset, PreparePolicy, canonical_frame_sha256
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentCapabilities, ExperimentProtocol, ExperimentStage, ExperimentResult,
    ExperimentOutcome, ExperimentPrecheckResult, ExperimentPreflightCheck,
    ExperimentPreflightStatus, ExperimentDependency,
)

REQUESTS = (
    ("daily", Dataset.ETF_UNADJUSTED_DAILY, "daily"),
    ("5m", Dataset.ETF_UNADJUSTED_INTRADAY, "5m"),
    ("30m", Dataset.ETF_UNADJUSTED_INTRADAY, "30m"),
)


def plain(value):
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def acceptance(quality, frequency):
    daily = quality["daily"]
    passed = (quality["total_sessions"] > 0 and daily["completeness"] == 1.0
              and daily["accuracy"] >= 0.99)
    if frequency != "daily":
        minute = quality["minute"]
        passed = passed and minute["completeness"] == 1.0 and minute["accuracy"] >= 0.95
    return bool(passed)


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            2, "EX013_20261005", "S012", ExperimentMode.FORMAL,
            "518850全部上市历史能否按已确认DFLS容差和比例门槛通过准备与读取？",
            "可信修复后日线完整率100%、准确率至少99%，分钟线完整率100%、准确率至少95%；剩余异常保留明细。",
            ("任一请求未READY、缺少质量证据或未满足比例门槛。",
             "真实数据身份、准备引用、日历覆盖或保存副本哈希不能核验。"),
            date(2026, 9, 30), 12013, tuple(sorted({r[1].value for r in REQUESTS})),
            ExperimentProtocol(ExperimentStage.DATA_GATE,
                ("用户明确恢复S012；先复验全历史数据。",),
                ("数据可用于研究准备，不将统计通过解释成每根K线已修复。",),
                ("正式prepare REFRESH，再持明确引用fetch；日线、5m、30m分请求留证。",),
                ("按DFLS现有容差计数；与EX012旧逐日阻断结论并列，不重写历史。",),
                ("本实验不读取收益标签、不选型、不变更标的及三个经济目标。",
                 "市场观察AvailableDate不能证明供应商历史实时发布；阶段三未获授权。"),
                predecessor_experiment_ids=("EX012_20261004",)),
            ExperimentDataScope.DEVELOPMENT, subjects=("518850.SH",),
            dependencies=tuple(ExperimentDependency(p, version(p)) for p in ("numpy", "pandas")),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def synthetic_precheck(self):
        q = {"total_sessions": 100, "daily": {"completeness": 1., "accuracy": .99},
             "minute": {"completeness": 1., "accuracy": .95}}
        assert acceptance(q, "5m")
        q["minute"]["accuracy"] = .9499
        assert not acceptance(q, "5m") and acceptance(q, "daily")
        q["minute"].update(completeness=.99, accuracy=1.)
        assert not acceptance(q, "30m")
        q["daily"]["accuracy"] = .9899
        assert not acceptance(q, "daily")
        q["daily"].update(completeness=.99, accuracy=1.)
        assert not acceptance(q, "daily")
        q["total_sessions"] = 0
        assert not acceptance(q, "daily")
        frame = pd.DataFrame({"Date": pd.to_datetime(["2020-06-05 14:30", "2020-06-05 15:00"]),
                              "AvailableDate": pd.to_datetime(["2020-06-05 14:30", "2020-06-05 15:00"]),
                              "Close": [4., 4.]})
        assert (frame.AvailableDate <= frame.Date.dt.normalize() + pd.Timedelta(hours=17)).all()
        assert self.definition.development_cutoff == date(2026, 9, 30)
        assert len(canonical_frame_sha256(frame)) == 64
        sample = ExperimentResult(ExperimentOutcome.PASS, {"full_history_ready": True},
                                  {"quality": plain(q), "return_paths": 0})
        json.loads(json.dumps(sample.to_dict(), allow_nan=False))
        return ExperimentPrecheckResult((ExperimentPreflightCheck(
            "QUALITY_BOUNDARIES", ExperimentPreflightStatus.PASS,
            "比例边界、缺日、零分母、时间可得性、帧身份及结果序列化。"),), sample)

    def execute(self, context):
        audit, artifacts = {}, []
        for name, dataset, frequency in REQUESTS:
            request = DataRequest(dataset, "518850.SH", "2020-06-05", "2026-09-30",
                                  "2026-09-30", frequency=frequency)
            print(json.dumps({"event": "prepare", "frequency": frequency}), flush=True)
            prepared = context.data.prepare((request,), policy=PreparePolicy.REFRESH)
            item = {"request": plain(request), "prepare": plain(prepared), "accepted": False}
            if prepared.ready:
                result = context.data.fetch(request, prepared=prepared.reference)
                item["fetch_status"] = result.status.value
                if result.ready:
                    frame, metadata = result.dataframe, plain(result.identity.metadata)
                    quality = metadata["ohlcv_quality"]
                    dates = pd.to_datetime(frame.Date).dt.normalize()
                    observed = {str(v.date()) for v in dates.unique()}
                    expected = set(metadata["daily_session_coverage"]["expected_dates"])
                    item.update(rows=len(frame), sessions=len(observed), quality=quality,
                                missing_sessions=sorted(expected - observed),
                                unexpected_sessions=sorted(observed - expected),
                                content_sha256=result.identity.content_sha256,
                                hash_verified=canonical_frame_sha256(frame) == result.identity.content_sha256,
                                temporal_contract=plain(result.identity.temporal_contract),
                                repair_records=metadata.get("repair_records", []))
                    item["accepted"] = (acceptance(quality, frequency) and item["hash_verified"]
                                        and not item["missing_sessions"] and not item["unexpected_sessions"]
                                        and len(observed) == 1535 and not frame.Date.duplicated().any())
                    frame.to_parquet(context.workspace.path(f"data/{name}.parquet"), index=False)
                    artifacts.append(context.workspace.register_artifact(f"data/{name}.parquet", "source_data"))
                    sessions = metadata["ohlcv_quality_evidence"]["sessions"]
                    evidence = pd.DataFrame([{"date": d, **plain(v)} for d, v in sessions.items()])
                    evidence.to_json(context.workspace.path(f"quality/{name}.json"), orient="records", indent=2)
                    artifacts.append(context.workspace.register_artifact(f"quality/{name}.json", "daily_quality"))
                    context.workspace.path(f"metadata/{name}.json").write_text(
                        json.dumps(metadata, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
                    artifacts.append(context.workspace.register_artifact(f"metadata/{name}.json", "data_identity"))
                else:
                    item["fetch_error"] = plain(result.error)
            audit[name] = item
            print(json.dumps({"event": "result", "frequency": frequency,
                              "accepted": item["accepted"], "quality": item.get("quality")}, default=str), flush=True)
        context.workspace.path("data_audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("data_audit.json", "data_gate"))
        ready = all(item["accepted"] for item in audit.values())
        return ExperimentResult(ExperimentOutcome.PASS if ready else ExperimentOutcome.INCONCLUSIVE,
            {"full_history_ready": ready, "requests": len(audit), "accepted": sum(v["accepted"] for v in audit.values()),
             "return_paths": 0},
            {"interpretation": "现行DFLS准备门通过不等于剩余异常已被独立真值修复；研究特征须另做异常敏感性。"},
            tuple(artifacts))
