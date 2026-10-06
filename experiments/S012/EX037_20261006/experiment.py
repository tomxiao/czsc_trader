"""Managed causal intraday repair/pullback competition; formal snapshots only."""

from datetime import date
from dataclasses import fields, is_dataclass
from collections.abc import Mapping
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
import json
import numpy as np
import pandas as pd
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
from .mechanisms import build, synthetic_frames, HYPOTHESES
from .diagnostics import run, labels, row

EID = "EX037_20261006"
INPUTS = {
    "daily": ("EX036_20261006", "daily.parquet"),
    "baseline": ("EX036_20261006", "features.parquet"),
    "minute": ("EX014_20261005", "data/target_30m.parquet"),
    "minute_daily": ("EX014_20261005", "data/target_daily.parquet"),
    "quality": ("EX014_20261005", "data_audit.json"),
}


def plain(x):
    if is_dataclass(x):
        return {f.name: plain(getattr(x, f.name)) for f in fields(x)}
    if isinstance(x, Mapping):
        return {k: plain(v) for k, v in x.items()}
    if isinstance(x, (tuple, list)):
        return [plain(v) for v in x]
    return x


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            2,
            EID,
            "S012",
            ExperimentMode.FORMAL,
            "午后修复及尾盘回调能否提供限价兼容的互补收益；M05内盘中状态有无必要增量？",
            "盘中不同收益形成路径在相同日线状态下可能反映需求吸收或低价成交机会。",
            (
                "父事件内部控制后无增量；固定父成交贡献下降；年度、费用或执行延迟推翻解释。",
                "只靠异常数据、少量高收益簇或未来质量标签的结果不足以支持组件。",
            ),
            date(2026, 9, 30),
            12037,
            ("etf.unadjusted_daily", "etf.unadjusted_intraday"),
            ExperimentProtocol(
                ExperimentStage.MECHANISM_DISCOVERY,
                ("用户要求继续研究直至完成阶段二交付；既有分支与授权资源内自主完成。",),
                (
                    "12固定定义、5父对照：午后修复/延续四竞争、日跌尾盘两竞争、人民币支撑回调两竞争、M05盘中四竞争。",
                ),
                ("不搜索阈值；所有符号门在正式收益读取前冻结；全上市1535日开发池。",),
                ("主5交易日；1/3/5日×额外延迟0/1/2日×每侧0.1/0.2%，18标签场景306路径2142年度。",),
                (
                    "T17用完整八根30分钟Close，下午11:30至15:00，尾盘14:00至15:00；不读取次日分钟作信号。",
                    "事件控制仅日线5/20日变化、20日波动和当日收益，保留20日前热身；父匹配年/5日方向/波动三分位/当日方向。",
                    "父事件内匹配/OLS、固定父限价零填贡献、年度与去单年、区块999/循环399/BH12为诊断。",
                    "主样本保留26质量异常日；未来异常影响窗排除仅离线敏感性，不进入可交易信号。",
                    "EX001—36已见，不声称独立验证；无账户目标复验，完整交付收口须全面角色及证据审计。",
                ),
                predecessor_experiment_ids=("EX036_20261006", "EX014_20261005"),
            ),
            ExperimentDataScope.DEVELOPMENT,
            subjects=("518850.SH",),
            dependencies=tuple(ExperimentDependency(k, version(k)) for k in ("numpy", "pandas")),
            capabilities=ExperimentCapabilities(reads_real_returns=True, selects_parameters=False),
        )

    def synthetic_precheck(self):
        d, b, m = synthetic_frames()
        f, s, v, a = build(d, b, m)
        cut = d.index[219]
        fp, sp, vp, ap = build(d.loc[:cut], b.loc[:cut], m.loc[m.Date.dt.normalize() <= cut])
        for left, right in ((f, fp), (s, sp), (v, vp), (a, ap)):
            pd.testing.assert_frame_equal(left.loc[:cut], right)
        changed = m.copy()
        changed.loc[changed.Date.dt.normalize() > cut, "Close"] *= 10
        ff, ss, vv, _ = build(d, b, changed)
        for left, right in ((f, ff), (s, ss), (v, vv)):
            pd.testing.assert_frame_equal(left.loc[:cut], right.loc[:cut])
        missing = m.drop(index=0)
        fm, sm, vm, am = build(d, b, missing)
        assert not am.structural_valid.iloc[0] and not vm.I01.iloc[0]
        delayed = m.copy()
        delayed.loc[0, "AvailableDate"] = d.index[1] + pd.Timedelta(hours=18)
        _, _, vd, ad = build(d, b, delayed)
        assert not ad.structural_valid.iloc[0] and not vd.I09.iloc[0]
        for first, second, parent in (
            ("I01", "I02", "C_MDOWN"),
            ("I03", "I04", "C_MUP"),
            ("I05", "I06", "C_DOWN"),
            ("I07", "I08", "C_PULL"),
            ("I09", "I10", "C_M05"),
            ("I11", "I12", "C_M05"),
        ):
            domain = v[first] & v[second] & v[parent]
            np.testing.assert_array_equal((s[first] | s[second]) & domain, s[parent] & domain)
            assert not (s[first] & s[second]).any()
        panel = labels(d, 5, 0, 0.001)
        r, _, _ = row(panel, f, s.I01, v.I01, s.C_MDOWN, 5, 0, 0.001, "I01")
        assert (
            abs(
                r["fixed_parent_limit_delta"]
                - (r["fixed_parent_limit_filtered"] - r["fixed_parent_limit_base"])
            )
            < 1e-12
        )
        assert panel.net.iloc[-6:].isna().all()
        checks = tuple(
            ExperimentPreflightCheck(k, ExperimentPreflightStatus.PASS, t)
            for k, t in (
                ("CAUSAL_PREFIX", "真实计算截断与未来分钟扰动不影响历史"),
                ("BAR_AVAILABILITY", "缺失或迟到分钟特征无效，不按未来质量筛选"),
                ("PAIR_PARTITIONS", "全部竞争组互斥并划分同父有效域"),
                ("EXECUTION_LABEL", "T+1费用/尾部及固定父限价零填贡献一致"),
            )
        )
        return ExperimentPrecheckResult(
            checks, ExperimentResult(ExperimentOutcome.PASS, {"rows": len(d), "hypotheses": 12}, {})
        )

    def execute(self, context):
        context.record_capability(ExperimentCapability.READ_REAL_RETURNS)
        base = Path(__file__).resolve().parents[1]
        frames = {}
        hashes = {}
        artifacts = []
        for key, (eid, name) in INPUTS.items():
            source = base / eid / "artifacts/rex" / name
            prior = context.predecessors[eid]
            expected = {a.path: a.sha256 for a in prior.artifacts}
            digest = sha256(source.read_bytes()).hexdigest()
            if digest != expected[name]:
                raise ValueError("changed predecessor " + eid + "/" + name)
            hashes[key] = {"experiment_id": eid, "artifact": name, "sha256": digest}
            if name.endswith(".parquet"):
                frames[key] = pd.read_parquet(source)
                frames[key].attrs = {}
            else:
                frames[key] = json.loads(source.read_text(encoding="utf-8"))

        def save(n, x, kind):
            context.workspace.path(n).write_text(
                json.dumps(plain(x), ensure_ascii=False, indent=2, allow_nan=False, default=str)
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            artifacts.append(context.workspace.register_artifact(n, kind))

        d = frames["daily"]
        md = frames["minute_daily"].copy()
        md["Date"] = pd.to_datetime(md.Date)
        md = md.set_index("Date")
        cols = ["Open", "High", "Low", "Close", "Volume", "Amount"]
        pd.testing.assert_frame_equal(d[cols], md[cols], check_freq=False)
        if (
            len(d) != 1535
            or str(d.index[0].date()) != "2020-06-05"
            or str(d.index[-1].date()) != "2026-09-30"
        ):
            raise ValueError("full window differs")
        f, s, v, a = build(d, frames["baseline"], frames["minute"])
        rows, annual, inference, panels = run(d, f, s, v, seed=12037)
        if (len(rows), len(annual), len(inference)) != (306, 2142, 12):
            raise ValueError("frozen family count differs")
        quality = frames["quality"]["target_30m"]["quality"]
        bad = set(quality["minute"]["inaccurate_dates"])
        if len(bad) != 26:
            raise ValueError("original quality anomaly count changed")
        sensitivity = []
        for r in rows:
            key = r["signal"]
            spec = next((x for x in HYPOTHESES if x[0] == key), None)
            parent = s[spec[2]] if spec else pd.Series(True, index=d.index)
            valid = v[key] & (v[spec[2]] if spec else True)
            panel = labels(d, r["horizon"], r["delay"], r["fee"])
            polluted = np.zeros(len(d), dtype=bool)
            raw_bad = np.array([str(day.date()) in bad for day in d.index])
            for offset in range(r["horizon"] + r["delay"] + 2):
                polluted[: len(d) - offset] |= raw_bad[offset:]
            rr, _, _ = row(
                panel, f, s[key], valid & ~polluted, parent, r["horizon"], r["delay"], r["fee"], key
            )
            sensitivity.append(
                {**rr, "diagnostic_only": True, "future_quality_exclusion_used_for_signal": False}
            )
        loo = []
        for key, h, parent, role, title in HYPOTHESES:
            for delay in (0, 1, 2):
                for fee in (0.001, 0.002):
                    selected = [
                        r
                        for r in annual
                        if (r["signal"], r["horizon"], r["delay"], r["fee"]) == (key, h, delay, fee)
                    ]
                    for omit in range(2020, 2027):
                        kept = [
                            r
                            for r in selected
                            if r["year"] != omit and r["fixed_parent_limit_slots"] > 0
                        ]
                        slots = sum(r["fixed_parent_limit_slots"] for r in kept)
                        delta = (
                            sum(
                                r["fixed_parent_limit_delta"] * r["fixed_parent_limit_slots"]
                                for r in kept
                            )
                            / slots
                            if slots
                            else None
                        )
                        loo.append(
                            {
                                "signal": key,
                                "delay": delay,
                                "fee": fee,
                                "omitted_year": omit,
                                "slots": slots,
                                "limit_delta": delta,
                            }
                        )
        coverage = {
            "sessions": 1535,
            "hypotheses": 12,
            "controls": 5,
            "label_scenarios": 18,
            "paths": 306,
            "annual_rows": 2142,
            "quality_sensitivity_paths": 306,
            "known_quality_bad_dates": sorted(bad),
            "future_quality_mask_for_decisions": False,
            "structural_valid_days": int(a.structural_valid.sum()),
            "primary_eligible_days": {
                x[0]: next(
                    r["eligible_days"]
                    for r in rows
                    if (r["signal"], r["horizon"], r["delay"], r["fee"]) == (x[0], 5, 0, 0.001)
                )
                for x in HYPOTHESES
            },
            "selection_history": "EX001—36已见；本轮固定方向，不是独立样本外",
        }
        for n, x, kind in (
            ("source_hashes.json", hashes, "source_lineage"),
            ("opportunities.json", rows, "mechanism"),
            ("annual.json", annual, "mechanism"),
            ("inference.json", inference, "uncertainty"),
            ("quality_sensitivity.json", sensitivity, "diagnostic"),
            ("leave_one_year_out.json", loo, "diagnostic"),
            ("coverage.json", coverage, "coverage"),
            (
                "hypothesis_definitions.json",
                [
                    dict(zip(("id", "primary_horizon", "parent", "role", "hypothesis"), x))
                    for x in HYPOTHESES
                ],
                "protocol",
            ),
        ):
            save(n, x, kind)
        for n, x in (
            ("daily", d),
            ("features", f),
            ("signals", s),
            ("valids", v),
            ("alignment", a),
            ("labels", panels),
        ):
            x.to_parquet(context.workspace.path(n + ".parquet"))
            artifacts.append(context.workspace.register_artifact(n + ".parquet", "mechanism"))
        print(
            "PATHS",
            len(rows),
            "PRIMARY",
            len(inference),
            "STRUCTURAL",
            int(a.structural_valid.sum()),
            flush=True,
        )
        return ExperimentResult(
            ExperimentOutcome.INCONCLUSIVE,
            {"hypotheses": 12, "paths": 306, "annual_rows": 2142},
            {"scope": "全池分钟机制；技术回执不代表收益成立，阶段二收口由完整证据判断"},
            tuple(artifacts),
        )
