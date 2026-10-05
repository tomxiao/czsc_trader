"""Fixed last-hour relative-lag study with causal next-session labels."""
from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path

import pandas as pd
from dataflows import DataRequest, Dataset, PreparePolicy
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentCapabilities, ExperimentProtocol, ExperimentStage, ExperimentResult,
    ExperimentOutcome, ExperimentPrecheckResult, ExperimentPreflightCheck,
    ExperimentPreflightStatus, ExperimentDependency,
)
from .mechanism import THRESHOLD, features, analyze, nonoverlap


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            2, "EX014_20261005", "S012", ExperimentMode.FORMAL,
            "黄金同类ETF收盘前相对落后，能否提供独立于汇率回调的次日后修复机会？",
            "参考ETF最后一小时未跌、518850相对落后超过往返成本时，未来3日存在费用后增量。",
            ("3日主路径费用后增量<=0或异常排除后方向翻转。",
             "少数年份支配结果、限价无法取得主要收益或新事件高度重合旧O01。"),
            date(2026, 9, 30), 12014,
            (Dataset.ETF_UNADJUSTED_DAILY.value, Dataset.ETF_UNADJUSTED_INTRADAY.value),
            ExperimentProtocol(ExperimentStage.MECHANISM_DISCOVERY,
                ("全历史数据门通过后继续阶段二独立机会研究。",),
                ("共同黄金暴露下收盘局部相对卖压可能随后修复；参考ETF不能代表金价真值或NAV。",),
                ("只用14:00分钟Close和当日日线Close；T日17:00决策、T+1开盘标签。",),
                ("单一固定费用阈值、3日主标签；1/5日为诊断；绝对下跌对照、旧O01及并集。",),
                ("不搜索阈值、不用分钟Open/High/Low/VWAP；剔除异常为诊断，保留全部分母。",
                 "事件及日线触价是研究诊断，不能替代限价实际成交或账户三个目标验证。",
                 "518880仅为已授权参考输入；阶段三及交易标的切换均未授权。"),
                predecessor_experiment_ids=("EX013_20261005", "EX010_20261004")),
            ExperimentDataScope.DEVELOPMENT, subjects=("518850.SH",),
            dependencies=tuple(ExperimentDependency(p, version(p)) for p in ("numpy", "pandas")),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def synthetic_precheck(self):
        dates = pd.bdate_range("2020-06-05", periods=16)
        target = pd.DataFrame({"Date": dates, "Open": 4., "High": 4.1, "Low": 3.8,
                               "Close": 4., "Volume": 100., "Amount": 400.})
        peer = target.copy()
        tm = pd.DataFrame({"Date": dates + pd.Timedelta(hours=14), "Close": 4.02, "Volume": 100.})
        tm["AvailableDate"] = tm.Date
        pm = tm.copy()
        pm["Close"] = 3.99
        f = features(target, peer, tm, pm)
        assert f.event.all() and (f.lag < -THRESHOLD).all()
        tm.loc[0, "Volume"] = 0
        tm.loc[1, "AvailableDate"] = dates[1] + pd.Timedelta(days=1)
        f = features(target, peer, tm, pm)
        assert not f.feature_valid.iloc[:2].any()
        before = f.copy()
        shifted = target.copy()
        shifted.loc[15, "Open"] = 40.
        assert features(shifted, peer, tm, pm).equals(before)
        out, summary, annual = analyze(target, f, pd.Series(False, index=f.index), {str(dates[5].date())})
        assert len(summary) == 24 and out.net_3.iloc[-4:].isna().all()
        assert not out.clean_3.iloc[1:6].any() and out.clean_3.iloc[6]
        path = target.copy()
        path.loc[6, "Open"] = 8.
        checked, _, _ = analyze(path, f, pd.Series(False, index=f.index), set())
        assert abs(checked.net_3.iloc[2] - (2 * .999 / 1.001 - 1)) < 1e-12
        assert nonoverlap(pd.Series([True]*7), 3) == [0, 3, 6]
        assert not features(target, peer, tm.iloc[2:], pm).feature_valid.iloc[:2].any()
        absent_peer = features(target, peer, tm, pm.iloc[4:])
        assert absent_peer.absolute_control.iloc[2:4].all()
        assert not absent_peer.feature_valid.iloc[2:4].any()
        _, independent, _ = analyze(target, absent_peer, pd.Series(True, index=f.index), set())
        old = next(v for v in independent if v["signal"] == "o01" and v["horizon"] == 3 and v["sensitivity"] == "all")
        assert old["events"] == 12 and old["denominator_sessions"] == 16
        sample = ExperimentResult(ExperimentOutcome.INCONCLUSIVE, {"paths": 3}, {"summary": summary, "annual": annual})
        json.loads(json.dumps(sample.to_dict(), allow_nan=False))
        return ExperimentPrecheckResult((ExperimentPreflightCheck(
            "CAUSAL_EVENT", ExperimentPreflightStatus.PASS,
            "缺时点、无成交、延迟可得、未来价格扰动、标签尾部、异常影响窗、去重和严格序列化。"),), sample)

    def execute(self, context):
        if not context.predecessors["EX013_20261005"].facts["full_history_ready"]:
            return ExperimentResult(ExperimentOutcome.INCONCLUSIVE, {"return_paths": 0}, {"reason": "目标全历史数据门未通过"})
        frames, audit, artifacts, bad = {}, {}, [], set()
        for symbol, leg in (("518850.SH", "target"), ("518880.SH", "peer")):
            for dataset, freq in ((Dataset.ETF_UNADJUSTED_DAILY, "daily"),
                                  (Dataset.ETF_UNADJUSTED_INTRADAY, "30m")):
                name = f"{leg}_{freq}"
                request = DataRequest(dataset, symbol, "2020-06-05", "2026-09-30", "2026-09-30", frequency=freq)
                prepared = context.data.prepare((request,), policy=PreparePolicy.REUSE if leg == "target" else PreparePolicy.REFRESH)
                item = {"prepare_status": prepared.status.value, "ready": False,
                        "reference": None if not prepared.ready else {
                            "space_id": str(prepared.reference.space_id), "preparation_id": str(prepared.reference.preparation_id),
                            "manifest_sha256": prepared.reference.manifest_sha256}}
                if prepared.ready:
                    result = context.data.fetch(request, prepared=prepared.reference)
                    item["fetch_status"] = result.status.value
                    if result.ready:
                        metadata = dict(result.identity.metadata)
                        item.update(ready=True, quality=dict(metadata["ohlcv_quality"]),
                                    content_sha256=result.identity.content_sha256, rows=len(result.dataframe),
                                    repair_records=list(metadata.get("repair_records", [])))
                        frames[name] = result.dataframe
                        q = metadata["ohlcv_quality"]
                        bad.update(q["daily"]["inaccurate_dates"])
                        if freq != "daily":
                            bad.update(q["minute"]["inaccurate_dates"])
                        result.dataframe.to_parquet(context.workspace.path(f"data/{name}.parquet"), index=False)
                        artifacts.append(context.workspace.register_artifact(f"data/{name}.parquet", "source_data"))
                        # Identity/quality remain in the captured source artifact and audit.
                        # Numerical operations need observations, not copied frame attributes.
                        frames[name].attrs = {}
                    else:
                        item["error"] = {"code": result.error.code, "message": result.error.message}
                else:
                    item["error"] = {"code": prepared.items[0].error.code, "message": prepared.items[0].error.message,
                                     "context": dict(prepared.items[0].error.context)}
                audit[name] = item
                print(json.dumps({"event": "input", "name": name, "ready": item["ready"], "quality": item.get("quality")}, default=str), flush=True)
        def save(name, value, kind):
            context.workspace.path(name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
            artifacts.append(context.workspace.register_artifact(name, kind))
        save("data_audit.json", audit, "data_gate")
        if not all(v["ready"] for v in audit.values()):
            return ExperimentResult(ExperimentOutcome.INCONCLUSIVE, {"return_paths": 0, "input_ready": False},
                                    {"reason": "任一腿未通过全历史准备，停止收益检验。"}, tuple(artifacts))
        root = Path(__file__).resolve().parents[3]
        predecessor = context.predecessors["EX010_20261004"]
        artifact = next(a for a in predecessor.artifacts if a.path == "fx/signals.parquet")
        source = root / "experiments/S012/EX010_20261004/artifacts/rex" / artifact.path
        if sha256(source.read_bytes()).hexdigest() != artifact.sha256:
            raise ValueError("O01 predecessor signal hash differs")
        o01 = pd.read_parquet(source)["fx_q75_dip_q25"]
        f = features(frames["target_daily"], frames["peer_daily"], frames["target_30m"], frames["peer_30m"])
        panel, summary, annual = analyze(frames["target_daily"], f, o01, bad)
        panel.to_parquet(context.workspace.path("event_panel.parquet"))
        artifacts.append(context.workspace.register_artifact("event_panel.parquet", "mechanism"))
        save("opportunities.json", summary, "mechanism")
        save("annual.json", annual, "mechanism")
        save("feature_coverage.json", {"total_sessions": len(panel), "valid_sessions": int(panel.feature_valid.sum()),
            "invalid_dates": [str(d.date()) for d in panel.index[~panel.feature_valid]],
            "quality_anomaly_dates": sorted(bad), "warmup_loss": 0, "horizon_tail_losses": {"1": 2, "3": 4, "5": 6}}, "coverage")
        paired = panel.loc[panel.net_3.notna()]
        intersection = int((paired.event & paired.o01).sum())
        save("independence.json", {"new_events": int(paired.event.sum()), "o01_events": int(paired.o01.sum()),
            "intersection": intersection, "union": int(paired.union.sum()),
            "new_intersection_fraction": intersection / max(int(paired.event.sum()), 1),
            "o01_intersection_fraction": intersection / max(int(paired.o01.sum()), 1)}, "mechanism")
        main = next(v for v in summary if v["signal"] == "event" and v["horizon"] == 3 and v["sensitivity"] == "all")
        clean = next(v for v in summary if v["signal"] == "event" and v["horizon"] == 3 and v["sensitivity"] != "all")
        rejected = (main["year_matched_excess"] is not None and main["year_matched_excess"] <= 0)
        if main["year_matched_excess"] is not None and main["year_matched_excess"] > 0:
            rejected |= clean["year_matched_excess"] is not None and clean["year_matched_excess"] <= 0
        return ExperimentResult(ExperimentOutcome.FAIL if rejected else ExperimentOutcome.INCONCLUSIVE,
            {"input_ready": True, "return_paths": 3, "parameter_searches": 0, "main_events": main["events"],
             "main_net_mean": main["net_mean"], "main_year_matched_excess": main["year_matched_excess"],
             "clean_year_matched_excess": clean["year_matched_excess"], "feature_valid_sessions": int(panel.feature_valid.sum())},
            {"scope": "阶段二单机制诊断；数据、年度稳定性、费用和容量共同解释；未模拟账户或验证经济目标。"}, tuple(artifacts))
