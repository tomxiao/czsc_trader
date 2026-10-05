"""Bound predecessor-based stage-two successor; no source refresh or account simulation."""

from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
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
from .statistics import summary, make_signals
from .mechanism import extend, audit, SELECTED


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            2,
            "EX016_20261005",
            "S012",
            ExperimentMode.FORMAL,
            "实际成交均价偏离是否存在独立机会；EX015正向线索能否承受选择和执行反证？",
            "收盘低于实际成交均价可能提供修复信息；日内线索须接受费用和日线价量控制，不能把涨市收益视作增量。",
            (
                "控制后或费用/异常敏感性转负，不能支持可靠机会。",
                "年度前缀选择失效、极值支配及成交容量不足须披露。",
            ),
            date(2026, 9, 30),
            12016,
            (Dataset.ETF_UNADJUSTED_DAILY.value, Dataset.ETF_UNADJUSTED_INTRADAY.value),
            ExperimentProtocol(
                ExperimentStage.MECHANISM_DISCOVERY,
                ("完成阶段二汇总交付，风险/机会角色各自留证；不进入阶段三。",),
                ("真实日VWAP偏离与分钟加权Close代理不同，补齐前轮误标的覆盖缺口。",),
                ("EX0156条已见路径固定复核，8条实际VWAP路径固定竞争检验。",),
                ("1/3/5日期限、费用/延迟/异常敏感性沿用；5日为主，1/3日探索。",),
                (
                    "继承已受管数据及信号逐文件SHA核验，无新来源及新数据请求。",
                    "同窗口年度价量匹配与OLS、999次非重叠5事件块区间、与O01及固定并集容量。",
                    "2023起年初仅用已成熟历史5日标签选方向；候选集合已见全样本，不宣称独立验证。",
                    "FSC纯计算实际调用及逐值核验；所有诊断不新增用户经济硬门。",
                ),
                predecessor_experiment_ids=("EX015_20261005",),
            ),
            ExperimentDataScope.DEVELOPMENT,
            subjects=("518850.SH",),
            dependencies=tuple(
                ExperimentDependency(p, version(p))
                for p in ("numpy", "pandas", "scipy", "tsfresh", "expr_codegen")
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True, selects_parameters=True),
        )

    def synthetic_precheck(self):

        dates = pd.bdate_range("2020-01-01", periods=540)
        d = pd.DataFrame(
            {"Open": 4.0, "High": 4.1, "Low": 3.9, "Close": 4.0, "Volume": 100.0, "Amount": 401.0},
            index=dates,
        )
        d.index.name = "Date"
        f = pd.DataFrame(
            {
                "sell_pressure": 0.1,
                "recovery": 0.1,
                "shock_time": 0.5,
                "shock": -0.01,
                "late_volume": 0.2,
                "volume_concentration": 0.1,
                "efficiency": 0.2,
                "morning": -0.001,
                "afternoon": 0.001,
                "last_hour": 0.0,
                "thin_impact": 0.1,
                "peer_gap": 0.0,
                "vwap_close_proxy_gap": -0.002,
                "day_return": 0.0,
                "return3": 0.0,
                "volume_ratio": 1.0,
                "range": 0.01,
                "location": 0.5,
                "momentum20": 0.0,
                "volatility20": 0.01,
                "closure_days": 1.0,
                "vwap_gap": 4 / 4.01 - 1,
            },
            index=dates,
        )
        s, t, v = make_signals(f)
        s["o01"] = False
        v["o01"] = True
        changed, new, valid, thresholds = extend(d, f, s, v)
        assert new.vwap_negative.all() and new.vwap_below_cost.all()
        assert not valid.actual_vwap_low.loc[dates.year == 2020].any()
        assert abs(changed.actual_vwap_gap.iloc[0] - (4 / 4.01 - 1)) < 1e-12
        sample = ExperimentResult(
            ExperimentOutcome.INCONCLUSIVE, {"synthetic_vwap": True}, {"selected": list(SELECTED)}
        )
        return ExperimentPrecheckResult(
            (
                ExperimentPreflightCheck(
                    "VWAP_UNITS_AND_TRAINING",
                    ExperimentPreflightStatus.PASS,
                    "成交额元/成交量份单位、FSC数值对照和年度阈值预热。",
                ),
            ),
            sample,
        )

    def execute(self, context):
        context.record_capability(ExperimentCapability.READ_REAL_RETURNS)
        context.record_capability(ExperimentCapability.SELECT_PARAMETERS)
        prior = context.predecessors["EX015_20261005"]
        root = Path(__file__).resolve().parents[1] / "EX015_20261005/artifacts/rex"
        expected = {a.path: a.sha256 for a in prior.artifacts}

        def read(name, parquet=True):
            path = root / name
            if sha256(path.read_bytes()).hexdigest() != expected[name]:
                raise ValueError(f"changed predecessor {name}")
            if parquet:
                x = pd.read_parquet(path)
                x.attrs = {}
                return x
            return json.loads(path.read_text(encoding="utf-8"))

        d = read("data/daily.parquet")
        d.Date = pd.to_datetime(d.Date)
        d = d.set_index("Date")
        f, s, v, thresholds = extend(
            d, read("features.parquet"), read("signals.parquet"), read("valids.parquet")
        )
        bad = set(read("coverage.json", False)["bad_dates"])
        rows, annual, tests, labels = summary(d, f, s, v, bad, context.resources.max_workers)
        extras = audit(d, s, v, labels, f, bad, context.resources.max_workers)
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
            ("signals.parquet", s),
            ("valids.parquet", v),
            ("thresholds.parquet", thresholds),
            ("labels.parquet", labels),
        ):
            frame.to_parquet(context.workspace.path(name))
            artifacts.append(context.workspace.register_artifact(name, "component_audit"))
        for name, value in (
            ("opportunities.json", rows),
            ("annual.json", annual),
            ("multiplicity.json", tests),
            ("confirmation.json", extras),
        ):
            save(name, value)
        save(
            "selection_history.json",
            {
                "prior_receipt": prior.receipt_sha256,
                "selected_prior_paths": list(SELECTED),
                "new_vwap_paths": 8,
                "paths": len(rows),
                "source_hashes": expected,
                "reason": "EX015日内筛查正向线索及机制反证；真实日VWAP此前未检验，修正协议覆盖描述。",
                "scope": "全开发池；选择后区间不消除历史筛选偏差，不产生账户或策略候选。",
            },
        )
        main = [
            r
            for r in rows
            if r["horizon"] == 5
            and r["delay"] == 0
            and r["fee"] == 0.001
            and r["sensitivity"] == "all"
        ]
        save(
            "ranking.json",
            sorted(
                main,
                key=lambda r: r["increment"] if r["increment"] is not None else -1,
                reverse=True,
            ),
        )
        return ExperimentResult(
            ExperimentOutcome.INCONCLUSIVE,
            {"paths": len(rows), "signals": len(s.columns), "new_vwap_signals": 8},
            {"scope": "阶段二选后复核及新增实际VWAP方向；不证明账户三目标。"},
            tuple(artifacts),
        )
