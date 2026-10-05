"""Peer confirmation versus own daily price support; fixed successor."""

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
from .mechanism import BASES, PAIRS, make_inputs
from .statistics import run

EID = "EX019_20261005"


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            2,
            EID,
            "S012",
            ExperimentMode.FORMAL,
            "同类ETF正向确认是否提供超出目标自身当日上涨的独立条件信息？",
            "共同黄金价格支持可能解释EX018同类方向效应；须与目标自身Open至Close方向竞争。",
            (
                "自身方向解释同类增量或不一致子组太少，不声称同类独立确认。",
                "原机会内确认有提升但固定限价贡献或容量受损，不能只报保留均值。",
            ),
            date(2026, 9, 30),
            12019,
            (Dataset.ETF_UNADJUSTED_DAILY.value, Dataset.ETF_UNADJUSTED_INTRADAY.value),
            ExperimentProtocol(
                ExperimentStage.MECHANISM_DISCOVERY,
                ("阶段二职责补齐，EX018已见后的固定竞争解释，不构建账户。",),
                ("两个原机会中各检验目标自身/同类方向；目标正/非正四子池中检验同类。",),
                ("同费用父机会内条件均值与固定时间表贡献，8对×24敏感性=192条路径。",),
                ("1/3/5日主5日；10/20bp各侧，0/2延迟，全样本/事后质量排除。",),
                (
                    "继承EX018精确门、EX017机会与EX015原价数据，每一读取SHA核验。",
                    "自身正为Close>Open，非正含相等；不修改阈值或机会定义。",
                    "固定父时间表及重新去重分列、过滤损失守恒、限价Low触价代理。",
                    "8主对年内循环移位399次/BH，20交易日期块999次描述区间，少于6不解释。",
                    "同类确认对子池的时间表不同；不把子池贡献直接当原父机会贡献。",
                    "两种条件已见开发池比较，选择偏差、共同底层资产与历史发布限制保留。",
                ),
                predecessor_experiment_ids=("EX015_20261005", "EX017_20261005", "EX018_20261005"),
            ),
            ExperimentDataScope.DEVELOPMENT,
            subjects=("518850.SH",),
            dependencies=tuple(
                ExperimentDependency(p, version(p)) for p in ("numpy", "pandas", "scipy")
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True, selects_parameters=True),
        )

    def synthetic_precheck(self):
        index = pd.bdate_range("2022-01-03", periods=6)
        d = pd.DataFrame({"Open": 1.0, "Close": [1.1, 0.9, 1.0, np.nan, 1.1, 0.9]}, index=index)
        f = pd.DataFrame({"intraday": d.Close / d.Open - 1})
        inherited = pd.DataFrame(True, index=index, columns=BASES[:2])
        v = inherited.copy()
        peer = pd.Series([True, False, True, True, False, True], index=index)
        pv = pd.Series([True, True, True, True, False, True], index=index)
        signals, valid, gates, gate_valid = make_inputs(d, f, inherited, v, peer, pv)
        assert signals.o01_own_positive.tolist() == [True, False, False, False, True, False]
        assert signals.o01_own_nonpositive.tolist() == [False, True, True, False, False, True]
        assert not valid.o01_own_positive.iloc[3]
        assert not gate_valid.peer_positive.iloc[4]
        assert not gates.own_intraday_positive.iloc[2]
        assert sum(len(PAIRS[b]) for b in BASES) == 8
        return ExperimentPrecheckResult(
            (
                ExperimentPreflightCheck(
                    "OWN_PEER_COMPETITION_BOUNDARIES",
                    ExperimentPreflightStatus.PASS,
                    "自身符号分组互斥、相等归非正、缺输入无效，原机会与同类门保留。",
                ),
            ),
            ExperimentResult(ExperimentOutcome.INCONCLUSIVE, {"boundaries": True}, {"pairs": 8}),
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
        f = read("EX017_20261005", "features.parquet")
        inherited = read("EX017_20261005", "signals.parquet")[list(BASES[:2])]
        inherited_valid = read("EX017_20261005", "valids.parquet")[list(BASES[:2])]
        peer = read("EX018_20261005", "gates.parquet").peer_positive
        peer_valid = read("EX018_20261005", "gate_valids.parquet").peer_positive
        bad = set(read("EX015_20261005", "coverage.json")["bad_dates"])
        signals, valids, gates, gate_valid = make_inputs(
            d, f, inherited, inherited_valid, peer, peer_valid
        )
        empty = pd.DataFrame(index=d.index)
        rows, annual, inference, _, panels = run(
            d,
            f,
            signals,
            valids,
            gates,
            gate_valid,
            empty,
            empty,
            bad,
            context.resources.max_workers,
        )
        artifacts = []
        for name, value in (
            ("confirmation.json", rows),
            ("annual.json", annual),
            ("inference.json", inference),
            (
                "selection_history.json",
                {
                    "source_hashes": hashes,
                    "pairs": PAIRS,
                    "predecessor_receipts": {
                        eid: prior.receipt_sha256 for eid, prior in context.predecessors.items()
                    },
                    "trigger": "EX018同类正向候选可能由自身当日上涨解释，固定符号分组排除竞争解释。",
                    "selection_bias": "已见开发池后继；无新阈值选择或独立样本外验证。",
                },
            ),
        ):
            context.workspace.path(name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            artifacts.append(context.workspace.register_artifact(name, "confirmation_competition"))
        for name, frame in (
            ("signals.parquet", signals),
            ("valids.parquet", valids),
            ("gates.parquet", gates),
            ("gate_valids.parquet", gate_valid),
            ("labels.parquet", panels),
        ):
            frame.to_parquet(context.workspace.path(name))
            artifacts.append(context.workspace.register_artifact(name, "confirmation_competition"))
        return ExperimentResult(
            ExperimentOutcome.INCONCLUSIVE,
            {"confirmation_paths": len(rows), "conditional_pairs": 8},
            {"scope": "阶段二确认竞争解释，未构建完整账户。"},
            tuple(artifacts),
        )
