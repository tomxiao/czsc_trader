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
from .diagnostics import run, labels, row, anchors, avg

EID = "EX038_20261006"
INPUTS = {
    "daily": ("EX037_20261006", "daily.parquet"),
    "baseline": ("EX037_20261006", "features.parquet"),
    "legacy_signals": ("EX019_20261005", "signals.parquet"),
    "legacy_valids": ("EX019_20261005", "valids.parquet"),
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
            "原O01/N09/Q07在统一费用与固定时间表下能否保留职责，M05有何互补贡献？",
            "保留历史定义，统一同费标签及父条件，区分事件提升、过滤节省与新增机会。",
            ("限价固定贡献负或仅一年驱动削弱推荐；不因单个诊断机械改判。",),
            date(2026, 9, 30),
            12038,
            ("etf.unadjusted_daily",),
            ExperimentProtocol(
                ExperimentStage.MECHANISM_DISCOVERY,
                ("用户要求自主完成阶段二；不进入阶段三或构建账户。",),
                ("6固定主定义、4父对照：O01/N09原信号，Q07及非阳线竞争，M05新覆盖/重叠竞争。",),
                ("直接继承EX019信号与有效位，不改历史逐年前缀阈值，宏观沿用原M05符号。",),
                ("主5日；1/3/5×延迟0/1/2×每側0.1/0.2%，18标签180路径1260年度。",),
                (
                    "日线5/20日变化、20日波动和当日收益为控制；父匹配年/方向/波动/当日符号。",
                    "原全池父时间表不按年重排；6日去重及固定父限价零填贡献分开。",
                    "旧两机会集合与加M05的新集合用相同全有效日固定6日时间表，报告共同槽位边际贡献及年度。",
                    "集合对比是信息覆盖诊断，不是完整账户；原1535日频率分母不改。",
                    "20日历交易日区块999/年内循环399/BH6为诊断，旧与新所有历史已见。",
                ),
                predecessor_experiment_ids=("EX037_20261006", "EX019_20261005"),
            ),
            ExperimentDataScope.DEVELOPMENT,
            subjects=("518850.SH",),
            dependencies=tuple(ExperimentDependency(k, version(k)) for k in ("numpy", "pandas")),
            capabilities=ExperimentCapabilities(reads_real_returns=True, selects_parameters=False),
        )

    def synthetic_precheck(self):
        d, b, old, ov = synthetic_frames()
        f, s, v = build(d, b, old, ov)
        cut = d.index[219]
        fp, sp, vp = build(d.loc[:cut], b.loc[:cut], old.loc[:cut], ov.loc[:cut])
        for x, y in ((f, fp), (s, sp), (v, vp)):
            pd.testing.assert_frame_equal(x.loc[:cut], y)
        for k, c in (
            ("L01", "o01"),
            ("L02", "mid_momentum_positive"),
            ("L03", "o01_own_positive"),
            ("L04", "o01_own_nonpositive"),
        ):
            pd.testing.assert_series_equal(s[k], old[c], check_names=False)
            pd.testing.assert_series_equal(v[k], ov[c], check_names=False)
        np.testing.assert_array_equal(s.L05 | s.L06, s.C_M05)
        assert not (s.L05 & s.L06).any()
        assert not (s.L03 & s.L04).any()
        panel = labels(d, 5, 0, 0.001)
        r, _, _ = row(panel, f, s.L03, v.L03, s.C_O01, 5, 0, 0.001, "L03")
        assert (
            abs(
                r["fixed_parent_limit_delta"]
                - (r["fixed_parent_limit_filtered"] - r["fixed_parent_limit_base"])
            )
            < 1e-12
        )
        checks = tuple(
            ExperimentPreflightCheck(k, ExperimentPreflightStatus.PASS, t)
            for k, t in (
                ("PREFIX", "旧固定信号前缀保持"),
                ("EXACT_INHERITANCE", "原机会与门有效位不重估"),
                ("PARTITION", "互补/重叠和确认/反证互斥"),
                ("CONTRIBUTION", "统一费用固定父贡献守恒"),
            )
        )
        return ExperimentPrecheckResult(
            checks, ExperimentResult(ExperimentOutcome.PASS, {"hypotheses": 6}, {})
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
        if len(d) != 1535:
            raise ValueError("full window differs")
        f, s, v = build(d, frames["baseline"], frames["legacy_signals"], frames["legacy_valids"])
        rows, annual, inference, panels = run(d, f, s, v, seed=12038)
        if (len(rows), len(annual), len(inference)) != (180, 1260, 6):
            raise ValueError("frozen family differs")
        complement = []
        for delay in (0, 1, 2):
            for fee in (0.001, 0.002):
                p = labels(d, 5, delay, fee)
                valid = (
                    v.C_ALL
                    & f[["etf5", "etf20", "vol20", "own_day", "vix5", "xau5", "gold_vix_corr60"]]
                    .notna()
                    .all(axis=1)
                    & p.net.notna()
                )
                old = s.L01 | s.L02
                new = old | s.C_M05
                pa = anchors(valid.to_numpy(), 6)
                raw = np.nan_to_num(p.limit_net.to_numpy()[pa], nan=0)
                base = np.where(old.to_numpy()[pa], raw, 0)
                after = np.where(new.to_numpy()[pa], raw, 0)
                for year in (None, *range(2020, 2027)):
                    sel = np.ones(len(pa), dtype=bool) if year is None else d.index[pa].year == year
                    cm = valid if year is None else valid & (d.index.year == year)
                    complement.append(
                        {
                            "delay": delay,
                            "fee": fee,
                            "year": year,
                            "common_slots": int(sel.sum()),
                            "old_events": int((old & cm).sum()),
                            "new_events": int((new & cm).sum()),
                            "novel_m05_events": int((s.C_M05 & ~old & cm).sum()),
                            "overlap_m05_events": int((s.C_M05 & old & cm).sum()),
                            "old_fixed_limit": avg(base[sel]),
                            "new_fixed_limit": avg(after[sel]),
                            "marginal_fixed_limit": avg((after - base)[sel]),
                            "old_fixed_fills": int(
                                (
                                    old.to_numpy()[pa]
                                    & np.isfinite(p.limit_net.to_numpy()[pa])
                                    & sel
                                ).sum()
                            ),
                            "new_fixed_fills": int(
                                (
                                    new.to_numpy()[pa]
                                    & np.isfinite(p.limit_net.to_numpy()[pa])
                                    & sel
                                ).sum()
                            ),
                        }
                    )
        save("complementarity.json", complement, "diagnostic")
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
            "hypotheses": 6,
            "controls": 4,
            "label_scenarios": 18,
            "paths": 180,
            "annual_rows": 1260,
            "legacy_exact_signal_names": [
                "o01",
                "mid_momentum_positive",
                "o01_own_positive",
                "o01_own_nonpositive",
            ],
            "selection_history": "所有EX001—37已见；复验不构成独立确认",
        }
        for n, x, kind in (
            ("source_hashes.json", hashes, "source_lineage"),
            ("opportunities.json", rows, "mechanism"),
            ("annual.json", annual, "mechanism"),
            ("inference.json", inference, "uncertainty"),
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
            ("labels", panels),
        ):
            x.to_parquet(context.workspace.path(n + ".parquet"))
            artifacts.append(context.workspace.register_artifact(n + ".parquet", "mechanism"))
        print(
            "PATHS",
            len(rows),
            "PRIMARY",
            len(inference),
            flush=True,
        )
        return ExperimentResult(
            ExperimentOutcome.INCONCLUSIVE,
            {"hypotheses": 6, "paths": 180, "annual_rows": 1260},
            {"scope": "原机会固定定义复验与互补覆盖，完整收口另经人工审计"},
            tuple(artifacts),
        )
