"""S012 conditional confirmation and risk-context research via REX."""

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
from .mechanism import BASES, GATES, make_gates, risk_states, nonoverlap
from .statistics import run, compare, conditional_inference

EID = "EX018_20261005"


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            2,
            EID,
            "S012",
            ExperimentMode.FORMAL,
            "O01与N09机会出现后，独立确认是否改善费用后条件收益、风险或成交贡献？",
            "短期价格支持、同类方向与参与量可区分机会中的继续修复和失败，但过滤可能损失盈利与成交。",
            (
                "保留组均值提高但固定父机会收益贡献或限价贡献恶化，必须披露取舍。",
                "若确认条件内增量消失或只是定义重复，则不登记为成立的确认职责。",
            ),
            date(2026, 9, 30),
            12018,
            (Dataset.ETF_UNADJUSTED_DAILY.value, Dataset.ETF_UNADJUSTED_INTRADAY.value),
            ExperimentProtocol(
                ExperimentStage.MECHANISM_DISCOVERY,
                ("用户明确授权继续主导完成阶段二；不进入阶段三。",),
                ("父机会O01及N09固定；6个确认候选，主3项与辅助3项均完整留证。",),
                ("同父机会有效池pass/all/reject，同费用比较；不以全市场增量代替确认作用。",),
                ("1/3/5日，主5日；各侧10/20bp，延迟0/2，主样本/事后质量排除。",),
                (
                    "固定父机会非重叠时间表及筛后重新去重并列，盈利损失/避免亏损守恒核验。",
                    "日线Low限价触价代理，未成交/被过滤记零；1535全窗口容量分母。",
                    "12主路径年内父机会序列循环移位399次/BH；20交易日年内块999次描述区间。",
                    "通过或未通过的固定父机会事件少于6，不解释区间；已见开发池选择偏差保留。",
                    "三个风险状态历史中位分组只解释机会内风险，不视作独立确认或账户验证。",
                ),
                predecessor_experiment_ids=("EX015_20261005", "EX017_20261005"),
            ),
            ExperimentDataScope.DEVELOPMENT,
            subjects=("518850.SH",),
            dependencies=tuple(
                ExperimentDependency(p, version(p)) for p in ("numpy", "pandas", "scipy")
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True, selects_parameters=True),
        )

    def synthetic_precheck(self):
        index = pd.bdate_range("2020-01-01", periods=800)
        f = pd.DataFrame(
            {
                "afternoon": 0.01,
                "last_hour": 0.01,
                "location": 0.5,
                "recovery": 0.01,
                "volume_ratio": 1.0,
                "volatility20": 0.01,
                "momentum20": 0.01,
            },
            index=index,
        )
        peer = pd.DataFrame({"Open": 2.0, "Close": 2.01}, index=index)
        gates, valid = make_gates(f, peer)
        assert gates.all().all() and valid.all().all()
        f.loc[index[0], ["afternoon", "last_hour", "recovery"]] = 0
        f.loc[index[1], "volume_ratio"] = np.nan
        f.loc[index[2], "location"] = np.nan
        peer.loc[index[3], "Open"] = np.nan
        gates, valid = make_gates(f, peer)
        assert not gates.loc[
            index[0], ["afternoon_positive", "last_hour_positive", "recovered_after_shock"]
        ].any()
        assert gates.close_upper_half.iloc[0] and gates.volume_participation.iloc[0]
        assert not valid.volume_participation.iloc[1] and not gates.volume_participation.iloc[1]
        assert not valid.close_upper_half.iloc[2] and not valid.peer_positive.iloc[3]
        d = pd.DataFrame({"Close": np.exp(np.linspace(0, 0.2, len(index)))}, index=index)
        _, limits, _, _ = risk_states(d, f)
        changed = f.copy()
        changed.loc[index.year >= 2022, "volatility20"] = 10.0
        _, newlimits, _, _ = risk_states(d, changed)
        pd.testing.assert_frame_equal(
            limits.loc[index.year <= 2022], newlimits.loc[index.year <= 2022]
        )
        y = np.array([0.1, -0.2, 0.3, -0.4, 0.5, -0.6, 0.7, -0.8])
        panel = pd.DataFrame({"net": y, "limit_net": y, "downside": 0.1}, index=index[:8])
        parent = np.ones(8, dtype=bool)
        gate = y > 0
        result, anchors = compare(panel, parent, gate, 1)
        assert np.array_equal(anchors, np.array([0, 2, 4, 6]))
        assert result["lost_profitable_events"] == result["avoided_loss_events"] == 0
        assert result["fixed_contribution_delta"] == 0
        assert conditional_inference(panel, parent, gate, 1, 1)["reason"]
        all_pass, _ = compare(panel, parent, parent, 1)
        none_pass, _ = compare(panel, parent, ~parent, 1)
        assert all_pass["conditional_lift"] == 0 and none_pass["passed_net"] is None
        assert none_pass["fixed_filter_contribution"] == 0
        assert np.array_equal(nonoverlap([True, True, False, True], 2), [0, 3])
        check = ExperimentPreflightCheck(
            "CONDITIONAL_FILTER_BOUNDARIES",
            ExperimentPreflightStatus.PASS,
            "零/等号边界、缺输入、历史前缀、父机会固定时间表、过滤得失守恒及低样本空区间。",
        )
        return ExperimentPrecheckResult(
            (check,),
            ExperimentResult(
                ExperimentOutcome.INCONCLUSIVE, {"boundary_checks": True}, {"gates": list(GATES)}
            ),
        )

    def execute(self, context):
        context.record_capability(ExperimentCapability.READ_REAL_RETURNS)
        context.record_capability(ExperimentCapability.SELECT_PARAMETERS)
        hashes = {}

        def read(eid, name):
            prior = context.predecessors[eid]
            expected = {a.path: a.sha256 for a in prior.artifacts}
            path = Path(__file__).resolve().parents[1] / eid / "artifacts/rex" / name
            digest = sha256(path.read_bytes()).hexdigest()
            if digest != expected[name]:
                raise ValueError(f"changed predecessor {eid}/{name}")
            hashes[f"{eid}/{name}"] = digest
            if name.endswith(".parquet"):
                frame = pd.read_parquet(path)
                frame.attrs = {}
                return frame
            return json.loads(path.read_text(encoding="utf-8"))

        d = read("EX015_20261005", "data/daily.parquet")
        d.Date = pd.to_datetime(d.Date)
        d = d.set_index("Date")
        peer = read("EX015_20261005", "data/peer.parquet")
        peer.Date = pd.to_datetime(peer.Date)
        peer = peer.set_index("Date").reindex(d.index)
        f = read("EX017_20261005", "features.parquet")
        signals = read("EX017_20261005", "signals.parquet")[list(BASES)]
        valids = read("EX017_20261005", "valids.parquet")[list(BASES)]
        bad = set(read("EX015_20261005", "coverage.json")["bad_dates"])
        if not all(frame.index.equals(d.index) for frame in (f, signals, valids, peer)):
            raise ValueError("unaligned formal predecessors")
        gates, gate_valid = make_gates(f, peer)
        risk_values, risk_thresholds, high, risk_valid = risk_states(d, f)
        rows, annual, inference, risks, panels = run(
            d,
            f,
            signals,
            valids,
            gates,
            gate_valid,
            high,
            risk_valid,
            bad,
            context.resources.max_workers,
        )
        artifacts = []
        for name, value in (
            ("confirmation.json", rows),
            ("annual.json", annual),
            ("inference.json", inference),
            ("risk_context.json", risks),
            (
                "selection_history.json",
                {
                    "source_hashes": hashes,
                    "predecessor_receipts": {
                        eid: prior.receipt_sha256 for eid, prior in context.predecessors.items()
                    },
                    "bases": list(BASES),
                    "gates": list(GATES),
                    "paths": len(rows),
                    "main_gates": list(GATES[:3]),
                    "secondary_gates": list(GATES[3:]),
                    "trigger": "用户要求补足阶段二职责覆盖，确认组件原为0。",
                    "selection": "固定结构阈值，不基于本轮收益挑方向/阈值；已见开发池，不独立验证。",
                    "risk_context": "既有风险方向的当前原价视图；不替换历史定义与证据。",
                },
            ),
        ):
            context.workspace.path(name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            artifacts.append(context.workspace.register_artifact(name, "conditional_confirmation"))
        for name, frame in (
            ("gates.parquet", gates),
            ("gate_valids.parquet", gate_valid),
            ("risk_values.parquet", risk_values),
            ("risk_thresholds.parquet", risk_thresholds),
            ("risk_high.parquet", high),
            ("risk_valids.parquet", risk_valid),
            ("labels.parquet", panels),
        ):
            frame.to_parquet(context.workspace.path(name))
            artifacts.append(context.workspace.register_artifact(name, "conditional_confirmation"))
        return ExperimentResult(
            ExperimentOutcome.INCONCLUSIVE,
            {
                "confirmation_paths": len(rows),
                "risk_context_paths": len(risks),
                "gates": len(GATES),
            },
            {"scope": "机会内确认与风险职责，账户三目标留待阶段三。"},
            tuple(artifacts),
        )
