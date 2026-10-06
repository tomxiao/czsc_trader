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
from .diagnostics import run, labels, avg

EID = "EX039_20261006"
INPUTS = {
    "daily": ("EX038_20261006", "daily.parquet"),
    "baseline": ("EX038_20261006", "features.parquet"),
    "legacy_signals": ("EX038_20261006", "signals.parquet"),
    "legacy_valids": ("EX038_20261006", "valids.parquet"),
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
            "正常定价门和M05确认是否有必要增量，互补收益是否依赖六日时间表起点？",
            "原事件正收益未必带来执行贡献；直接比较删门父组与六种固定起点。",
            ("固定全阶段6相位无法保留增量或来源于一个年度，限制门的决策用途。",),
            date(2026, 9, 30),
            12039,
            ("etf.unadjusted_daily",),
            ExperimentProtocol(
                ExperimentStage.MECHANISM_DISCOVERY,
                ("EX038显示固定起点与纯动量父对照敏感；按既有自主授权做必要性与起点解释。",),
                ("4主定义、2父：N09相对纯正动量、M05/非M05在N09中、同动量非N09竞争。",),
                ("所有信号继承EX038，不重新挑价格阈值、相关期数或符号。",),
                ("1/3/5日×延迟0/1/2×每側10/20bp，108路径756年度，主5日。",),
                (
                    "日线四控制及年/方向/波动/当日符号父匹配；全池父时间表及去单年继承。",
                    "另固定从上市首日编号mod6=0至5的全部六相位；各相位每六交易日一次，所有有效父日/共同日保持位置。",
                    "分别报告六相位及按槽数加权总值，不选择最好相位、不将其当账户或六组合资金曲线。",
                    "旧O01|N09、加M05集合保持同相位同窗口；年度子集不重排。",
                    "所有历史已见，费用/延迟/年度/CI负证据全部保留。",
                ),
                predecessor_experiment_ids=("EX038_20261006",),
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
        np.testing.assert_array_equal(s.U01 | s.U04, s.C_MOM)
        assert not (s.U01 & s.U04).any()
        np.testing.assert_array_equal(s.U02 | s.U03, s.C_N09)
        assert not (s.U02 & s.U03).any()
        ids = [np.flatnonzero((np.arange(len(d)) % 6 == p) & v.C_MOM.to_numpy()) for p in range(6)]
        np.testing.assert_array_equal(np.sort(np.concatenate(ids)), np.flatnonzero(v.C_MOM))
        checks = tuple(
            ExperimentPreflightCheck(k, ExperimentPreflightStatus.PASS, t)
            for k, t in (
                ("PREFIX", "前缀不变"),
                ("PARTITIONS", "必要性及确认竞争互斥"),
                ("PHASES", "六相位恰覆盖有效日不重复"),
            )
        )
        return ExperimentPrecheckResult(
            checks, ExperimentResult(ExperimentOutcome.PASS, {"hypotheses": 4}, {})
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
        rows, annual, inference, panels = run(d, f, s, v, seed=12039)
        if (len(rows), len(annual), len(inference)) != (108, 756, 4):
            raise ValueError("frozen family differs")
        phase_results = []
        complement = []
        inherited, iv = frames["legacy_signals"], frames["legacy_valids"]
        controls = f[["etf5", "etf20", "vol20", "own_day"]].notna().all(axis=1)
        calendar = np.arange(len(d))
        for delay in (0, 1, 2):
            for fee in (0.001, 0.002):
                p = labels(d, 5, delay, fee)
                for key, h, parent, role, title in HYPOTHESES:
                    mask = v[key] & v[parent] & controls & p.net.notna() & s[parent]
                    for phase in range(6):
                        pa = np.flatnonzero(mask.to_numpy() & (calendar % 6 == phase))
                        ret = np.nan_to_num(p.limit_net.to_numpy()[pa], nan=0)
                        keep = s[key].to_numpy()[pa]
                        for year in (None, *range(2020, 2027)):
                            choose = (
                                np.ones(len(pa), dtype=bool)
                                if year is None
                                else d.index[pa].year == year
                            )
                            phase_results.append(
                                {
                                    "signal": key,
                                    "delay": delay,
                                    "fee": fee,
                                    "phase": phase,
                                    "year": year,
                                    "slots": int(choose.sum()),
                                    "base_limit": avg(ret[choose]),
                                    "filtered_limit": avg(np.where(keep, ret, 0)[choose]),
                                    "limit_delta": avg((np.where(keep, ret, 0) - ret)[choose]),
                                    "kept_fills": int(
                                        (
                                            keep & np.isfinite(p.limit_net.to_numpy()[pa]) & choose
                                        ).sum()
                                    ),
                                }
                            )
                common = iv.C_ALL & iv.C_M05 & controls & p.net.notna()
                old = inherited.L01 | inherited.L02
                new = old | inherited.C_M05
                for phase in range(6):
                    pa = np.flatnonzero(common.to_numpy() & (calendar % 6 == phase))
                    ret = np.nan_to_num(p.limit_net.to_numpy()[pa], nan=0)
                    before = np.where(old.to_numpy()[pa], ret, 0)
                    after = np.where(new.to_numpy()[pa], ret, 0)
                    for year in (None, *range(2020, 2027)):
                        choose = (
                            np.ones(len(pa), dtype=bool)
                            if year is None
                            else d.index[pa].year == year
                        )
                        complement.append(
                            {
                                "delay": delay,
                                "fee": fee,
                                "phase": phase,
                                "year": year,
                                "slots": int(choose.sum()),
                                "base_limit": avg(before[choose]),
                                "after_limit": avg(after[choose]),
                                "marginal_limit": avg((after - before)[choose]),
                                "base_fills": int(
                                    (
                                        old.to_numpy()[pa]
                                        & np.isfinite(p.limit_net.to_numpy()[pa])
                                        & choose
                                    ).sum()
                                ),
                                "after_fills": int(
                                    (
                                        new.to_numpy()[pa]
                                        & np.isfinite(p.limit_net.to_numpy()[pa])
                                        & choose
                                    ).sum()
                                ),
                            }
                        )
        save("phase_parent.json", phase_results, "diagnostic")
        save("phase_complementarity.json", complement, "diagnostic")
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
            "hypotheses": 4,
            "controls": 2,
            "paths": 108,
            "annual_rows": 756,
            "label_scenarios": 18,
            "phases": 6,
            "phase_parent_rows": len(phase_results),
            "phase_complement_rows": len(complement),
            "best_phase_selected": False,
            "selection_history": "全部已见开发池后继解释，不声称独立确认",
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
            {"hypotheses": 4, "paths": 108, "annual_rows": 756},
            {"scope": "原机会固定定义复验与互补覆盖，完整收口另经人工审计"},
            tuple(artifacts),
        )
