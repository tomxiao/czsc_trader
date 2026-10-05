"""Fixed normal-pricing successor using sealed EX015 and EX016 evidence."""

from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import numpy as np
import pandas as pd
from dataflows import Dataset
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
from .statistics import summary
from .mechanism import NEW, CONTROLS, annual_thresholds, make_states, audit

EID = "EX017_20261005"


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            2,
            EID,
            "S012",
            ExperimentMode.FORMAL,
            "真实成交重心附近的正常定价状态，能否提供费用后增量或过滤既有O01？",
            "成交重心两端偏离不稳定时，靠近中段可能反映较少定价扰动；需控制普通价量状态和涨市收益。",
            (
                "中段及固定子组的费用后增量不稳定，则正常定价机会缺少支持。",
                "O01过滤提升均值但牺牲过多机会、或少量年份/极值主导，须同时披露。",
            ),
            date(2026, 9, 30),
            12017,
            (Dataset.ETF_UNADJUSTED_DAILY.value, Dataset.ETF_UNADJUSTED_INTRADAY.value),
            ExperimentProtocol(
                ExperimentStage.MECHANISM_DISCOVERY,
                ("阶段二补齐竞争解释；不执行账户、策略选型或阶段三。",),
                ("真实日VWAP偏离中段及既定子组，机会/过滤角色分别解释。",),
                ("7条新增路径、历史两端/O01/无条件4项对照，完整保留所有264条诊断。",),
                ("1/3/5日主5日；10/20bp各侧费用、0/2日延迟、两项质量口径。",),
                (
                    "EX015/EX016受管前驱每个实际读取文件逐SHA核验；不请求新数据。",
                    "年度价量匹配、7变量OLS、年内20日块排列199次与11信号BH调整。",
                    "固定5项并集及限价触价容量；1535全窗口分母，不构建仓位或账户。",
                    "非重叠事件循环5事件块999次区间；少于6个事件区间为空并解释原因。",
                    "EX016已见后继，全部开发池；年度候选全集已见，不宣称独立验证。",
                ),
                predecessor_experiment_ids=("EX015_20261005", "EX016_20261005"),
            ),
            ExperimentDataScope.DEVELOPMENT,
            subjects=("518850.SH",),
            dependencies=tuple(
                ExperimentDependency(package, version(package))
                for package in ("numpy", "pandas", "scipy", "tsfresh", "expr_codegen")
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True, selects_parameters=True),
        )

    def synthetic_precheck(self):
        dates = pd.bdate_range("2020-01-01", periods=800)
        gap = pd.Series(np.linspace(-0.01, 0.01, len(dates)), index=dates)
        threshold = annual_thresholds(gap)
        disturbed = gap.copy()
        cutoff = pd.Timestamp("2022-01-01")
        disturbed.loc[disturbed.index >= cutoff] = 10.0
        changed = annual_thresholds(disturbed)
        pd.testing.assert_frame_equal(threshold.loc[dates < cutoff], changed.loc[dates < cutoff])
        assert threshold.loc[dates.year == 2020].isna().all().all()
        prefix_old = pd.DataFrame(
            {
                "actual_vwap_low": False,
                "actual_vwap_high": False,
                "o01": True,
                "late_volume_low": True,
            },
            index=dates,
        )
        prefix_valid = pd.DataFrame(True, index=dates, columns=prefix_old.columns)
        before, before_valid = make_states(
            pd.DataFrame({"actual_vwap_gap": gap, "return3": 0.01}),
            prefix_old,
            prefix_valid,
            threshold,
        )
        after, after_valid = make_states(
            pd.DataFrame({"actual_vwap_gap": disturbed, "return3": 0.01}),
            prefix_old,
            prefix_valid,
            changed,
        )
        pd.testing.assert_frame_equal(before.loc[dates < cutoff], after.loc[dates < cutoff])
        pd.testing.assert_frame_equal(
            before_valid.loc[dates < cutoff], after_valid.loc[dates < cutoff]
        )
        index = pd.bdate_range("2022-01-03", periods=8)
        features = pd.DataFrame(
            {
                "actual_vwap_gap": [-0.01, 0, 0.01, -0.010001, 0.010001, np.nan, -0.001, 0.002],
                "return3": [0.01] * 8,
            },
            index=index,
        )
        limits = pd.DataFrame(
            {"vwap_low_threshold": -0.01, "vwap_high_threshold": 0.01}, index=index
        )
        limits.iloc[-1] = np.nan
        old = pd.DataFrame(
            {
                "actual_vwap_low": False,
                "actual_vwap_high": False,
                "o01": True,
                "late_volume_low": True,
            },
            index=index,
        )
        valids = pd.DataFrame(True, index=index, columns=old.columns)
        signals, valid = make_states(features, old, valids, limits)
        assert signals.actual_vwap_mid.tolist() == [
            True,
            True,
            True,
            False,
            False,
            False,
            True,
            False,
        ]
        assert signals.mid_nonnegative.iloc[1] and not signals.mid_negative.iloc[1]
        assert signals.mid_negative.iloc[0] and signals.mid_negative.iloc[6]
        assert not valid.actual_vwap_mid.iloc[-1] and not valid.actual_vwap_mid.iloc[5]
        assert signals.vwap_near_zero.iloc[-1] and valid.vwap_near_zero.iloc[-1]
        assert not valid.vwap_near_zero.iloc[5]
        assert (signals.mid_nonnegative | signals.mid_negative).equals(signals.actual_vwap_mid)
        valids.loc[index[0], "late_volume_low"] = False
        valids.loc[index[1], "o01"] = False
        features.loc[index[2], "return3"] = np.nan
        checked, checked_valid = make_states(features, old, valids, limits)
        assert not checked_valid.mid_late_thin.iloc[0] and not checked.mid_late_thin.iloc[0]
        assert not checked_valid.o01_mid.iloc[1] and not checked.o01_mid.iloc[1]
        assert not checked_valid.mid_momentum_positive.iloc[2]
        # A four-event block interval must not silently collapse into a degenerate bound.
        mini_index = pd.bdate_range("2022-01-03", periods=24)
        mini = pd.DataFrame(index=mini_index)
        primary = pd.DataFrame({"net": 0.01, "limit_net": 0.01, "valid": True}, index=mini_index)
        labels = pd.concat({"h5_delay0": primary}, axis=1)
        small_signals = pd.DataFrame(True, index=mini_index, columns=signals.columns)
        evidence = audit(mini, small_signals, small_signals.copy(), labels)
        assert all(
            row["nonoverlap_events"] == 4 and row["ci_low"] is None and row["reason"]
            for row in evidence["bootstrap"]
        )
        sample = ExperimentResult(
            ExperimentOutcome.INCONCLUSIVE,
            {
                "mid_boundaries": True,
                "causal_threshold_prefix": True,
                "small_sample_interval": True,
            },
            {"new_signals": list(NEW), "controls": list(CONTROLS)},
        )
        return ExperimentPrecheckResult(
            (
                ExperimentPreflightCheck(
                    "MID_BOUNDARIES_AND_CAUSAL_PREFIX",
                    ExperimentPreflightStatus.PASS,
                    "中段含两端、零归正段、缺阈值及NaN无效、未来扰动不改变既有阈值、子组缺输入无效。",
                ),
                ExperimentPreflightCheck(
                    "SMALL_SAMPLE_INTERVAL",
                    ExperimentPreflightStatus.PASS,
                    "少于6个非重叠事件区间为空并给出原因。",
                ),
            ),
            sample,
        )

    def execute(self, context):
        context.record_capability(ExperimentCapability.READ_REAL_RETURNS)
        context.record_capability(ExperimentCapability.SELECT_PARAMETERS)
        hashes = {}

        def read(eid, name, parquet=True):
            prior = context.predecessors[eid]
            expected = {artifact.path: artifact.sha256 for artifact in prior.artifacts}
            path = Path(__file__).resolve().parents[1] / eid / "artifacts/rex" / name
            digest = sha256(path.read_bytes()).hexdigest()
            if digest != expected[name]:
                raise ValueError(f"changed predecessor {eid}/{name}")
            hashes[f"{eid}/{name}"] = digest
            if parquet:
                frame = pd.read_parquet(path)
                frame.attrs = {}
                return frame
            return json.loads(path.read_text(encoding="utf-8"))

        d = read("EX015_20261005", "data/daily.parquet")
        d.Date = pd.to_datetime(d.Date)
        d = d.set_index("Date")
        f = read("EX016_20261005", "features.parquet")
        inherited = read("EX016_20261005", "signals.parquet")
        inherited_valids = read("EX016_20261005", "valids.parquet")
        thresholds = read("EX016_20261005", "thresholds.parquet")
        np.testing.assert_allclose(
            thresholds.to_numpy(),
            annual_thresholds(f.actual_vwap_gap).to_numpy(),
            equal_nan=True,
            rtol=1e-12,
            atol=1e-12,
        )
        signals, valids = make_states(f, inherited, inherited_valids, thresholds)
        bad = set(read("EX015_20261005", "coverage.json", False)["bad_dates"])
        rows, annual, tests, labels = summary(
            d, f, signals, valids, bad, context.resources.max_workers
        )
        extra = audit(d, signals, valids, labels)
        artifacts = []

        def save(name, value):
            context.workspace.path(name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            artifacts.append(context.workspace.register_artifact(name, "component_audit"))

        for name, frame in (
            ("features.parquet", f),
            ("signals.parquet", signals),
            ("valids.parquet", valids),
            ("thresholds.parquet", thresholds),
            ("labels.parquet", labels),
        ):
            frame.to_parquet(context.workspace.path(name))
            artifacts.append(context.workspace.register_artifact(name, "component_audit"))
        for name, value in (
            ("opportunities.json", rows),
            ("annual.json", annual),
            ("multiplicity.json", tests),
            ("confirmation.json", extra),
        ):
            save(name, value)
        save(
            "selection_history.json",
            {
                "experiment_id": EID,
                "predecessor_receipts": {
                    eid: prior.receipt_sha256 for eid, prior in context.predecessors.items()
                },
                "source_hashes": hashes,
                "new_signals": list(NEW),
                "controls": list(CONTROLS),
                "paths": len(rows),
                "role": "o01_mid为过滤诊断，其余为事件机会/状态诊断",
                "trigger": "EX016实际VWAP上下四分位均弱，固定检验正常定价中段竞争解释。",
                "selection_bias": "已见开发池后继；本轮未进行年度候选排序，不宣称独立验证。",
                "units": "Amount元/Volume份形成VWAP元每份，gap=Close/VWAP-1为无量纲。",
            },
        )
        main = [
            row
            for row in rows
            if row["horizon"] == 5
            and row["delay"] == 0
            and row["fee"] == 0.001
            and row["sensitivity"] == "all"
        ]
        save(
            "ranking.json",
            sorted(
                main,
                key=lambda row: row["increment"] if row["increment"] is not None else -1,
                reverse=True,
            ),
        )
        return ExperimentResult(
            ExperimentOutcome.INCONCLUSIVE,
            {"paths": len(rows), "signals": len(signals.columns), "new_signals": len(NEW)},
            {"scope": "阶段二正常定价后继，事件研究不证明账户三目标。"},
            tuple(artifacts),
        )
