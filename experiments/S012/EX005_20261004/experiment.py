"""Selected component robustness; inherits selection from EX004 development evidence."""
from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import rankdata
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentCapabilities, ExperimentProtocol, ExperimentStage, ExperimentResult,
    ExperimentOutcome, ExperimentPrecheckResult, ExperimentPreflightCheck, ExperimentPreflightStatus, ExperimentDependency,
)

CASES = (
    ("volatility_20", "downside", 1, (3, 5, 10, 20)),
    ("momentum_20", "downside", 1, (3, 5, 10, 20)),
    ("fresh60_return__kurtosis", "return", -1, (3, 5, 10, 20)),
    ("fresh60_return__kurtosis", "downside", 1, (3, 5, 10, 20)),
    ("opening_gap", "return", -1, (3, 5, 10)),
    ("opening_gap", "downside", 1, (3, 5)),
    ("reversal_1", "return", 1, (3, 5, 10)),
    ("momentum_3", "return", -1, (3, 5, 10)),
    ("fresh20_return__autocorrelation__lag_2", "return", 1, (10, 20)),
    ("range_5", "downside", 1, (3, 5, 10)),
)


def ranks_residual(frame, feature, role):
    columns = [np.ones(len(frame))]
    for y in sorted(set(frame.index.year))[1:]:
        columns.append((frame.index.year == y).astype(float))
    for c in ("momentum_20", "volatility_20"):
        if c != feature:
            columns.append(rankdata(frame[c]) / len(frame))
    design = np.column_stack(columns)
    def residual(series):
        ranked = rankdata(series).astype(float)
        v = ranked - design @ np.linalg.lstsq(design, ranked, rcond=None)[0]
        norm = np.linalg.norm(v)
        return v / norm if norm > 1e-12 else np.zeros(len(v))
    return residual(frame[feature]), residual(frame[role])


def label_frame(raw, h):
    raw = raw.assign(Date=pd.to_datetime(raw.Date)).set_index("Date").sort_index()
    entry = raw.Open.shift(-1)
    low = pd.concat([raw.Low.shift(-i) for i in range(1, h + 1)], axis=1).min(axis=1, skipna=False)
    return pd.DataFrame({"return": raw.Open.shift(-h - 1) / entry - 1,
                         "downside": (1 - low / entry).clip(lower=0)}, index=raw.index)


def bootstrap_ci(x, y, seed, block=60, count=499):
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(x), (count, int(np.ceil(len(x) / block))))
    indices = ((starts[:, :, None] + np.arange(block)) % len(x)).reshape(count, -1)[:, :len(x)]
    bx, by = x[indices], y[indices]
    bx -= bx.mean(axis=1, keepdims=True); by -= by.mean(axis=1, keepdims=True)
    values = (bx * by).sum(axis=1) / np.sqrt((bx * bx).sum(axis=1) * (by * by).sum(axis=1))
    return [float(v) for v in np.quantile(values, [.025, .975])]


def analyze(features, raw):
    records = []
    for feature, role, direction, horizons in CASES:
        for h in horizons:
            target = label_frame(raw, h)
            for lag in (0, 1, 2):
                xframe = features[[feature, *[c for c in ("momentum_20", "volatility_20") if c != feature]]].shift(lag)
                frame = pd.concat([xframe, target], axis=1).dropna()
                x, y = ranks_residual(frame, feature, role)
                corr = float(x @ y)
                positions = features.index.get_indexer(frame.index)
                phase_ics = []
                for phase in range(h):
                    phase_frame = frame.loc[positions % h == phase]
                    px, py = ranks_residual(phase_frame, feature, role)
                    phase_ics.append(float(px @ py))
                leave_year = {}
                for year in sorted(set(frame.index.year)):
                    lx, ly = ranks_residual(frame.loc[frame.index.year != year], feature, role)
                    leave_year[str(year)] = float(lx @ ly)
                trim = frame.loc[frame["return"].abs() <= frame["return"].abs().quantile(.99)]
                tx, ty = ranks_residual(trim, feature, role)
                records.append({"feature": feature, "role": role, "horizon": h, "lag": lag, "direction": direction,
                    "n": len(frame), "partial_ic": corr, "phase_ics": phase_ics,
                    "phase_direction_fraction": float(np.mean(np.asarray(phase_ics) * direction > 0)),
                    "leave_year_ics": leave_year, "leave_year_direction_fraction": float(np.mean(np.array(list(leave_year.values())) * direction > 0)),
                    "trim_1pct_ic": float(tx @ ty),
                    "block60_ci": bootstrap_ci(x, y, 12005) if lag == 0 else None})
    # Pairwise redundancy and predeclared complement: short reversal within lower/higher risk.
    chosen = list(dict.fromkeys(c[0] for c in CASES))
    redundancy = features[chosen].corr(method="spearman").to_dict()
    interactions = []
    for h in (3, 5, 10):
        frame = pd.concat([features, label_frame(raw, h)], axis=1)
        for year in range(2022, 2027):
            train = frame.loc[frame.index.year < year].iloc[:-(h + 1)]
            test = frame.loc[frame.index.year == year].copy()
            if len(test) < 80:
                continue
            reversal_cut = float(train.reversal_1.quantile(.75))
            for risk in ("volatility_20", "fresh60_return__kurtosis"):
                cut = float(train[risk].median())
                for regime in ("lower", "higher"):
                    eligible = test.loc[test[risk] <= cut] if regime == "lower" else test.loc[test[risk] > cut]
                    selected = eligible.loc[eligible.reversal_1 >= reversal_cut, "return"].dropna()
                    control = eligible["return"].dropna()
                    if min(len(selected), len(control)) < 10:
                        continue
                    interactions.append({"year": year, "horizon": h, "risk": risk, "regime": regime,
                        "selected_n": len(selected), "control_n": len(control),
                        "gross_mean": float(selected.mean()), "control_mean": float(control.mean()),
                        "increment": float(selected.mean() - control.mean()),
                        "net_20bp": float(((1 + selected) * .999 / 1.001 - 1).mean()),
                        "net_40bp": float(((1 + selected) * .998 / 1.002 - 1).mean())})
    return records, redundancy, interactions


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(2, "EX005_20261004", "S012", ExperimentMode.FORMAL,
            "普查候选是否承受延迟、非重叠、年度剔除和控制后复核，并形成互补组件？",
            "波动与冲击状态可提供独立风险信息；短期反转可能补充入场信息，但必须保留成本及不稳定反证。",
            ("额外滞后导致方向反转。", "效果依赖单年或少数大波动。", "风险控制后不再提供增量。"),
            date(2026, 9, 30), 12005, ("etf.unadjusted_daily",),
            ExperimentProtocol(ExperimentStage.ROBUSTNESS,
                ("EX004提示风险和冲击组件较强，方向性证据较弱。",),
                ("已见结果后的后继检验", "预先声明候选、期限、滞后和互补分组"),
                ("明确支持、条件性、无效和冗余组件，形成阶段二交接。",),
                ("增量IC、块区间、非重叠相位、留一年、费用压力及相互相关",),
                ("仅使用已绑定前驱制品；不添加未经选择历史披露的数据。", "置信区间为选择后的开发诊断，不承担封存验证含义。"),
                predecessor_experiment_ids=("EX004_20261004",)),
            ExperimentDataScope.DEVELOPMENT, subjects=("518850.SH",),
            dependencies=tuple(ExperimentDependency(p, version(p)) for p in ("numpy", "pandas", "tsfresh")),
            capabilities=ExperimentCapabilities(reads_real_returns=True, selects_parameters=True))

    def synthetic_precheck(self):
        dates = pd.bdate_range("2020-01-01", periods=200)
        raw = pd.DataFrame({"Date": dates.strftime("%Y-%m-%d"), "Open": np.arange(200.) + 100, "Low": np.arange(200.) + 99})
        target = label_frame(raw, 5)
        assert target.index.equals(dates) and np.isclose(target["return"].iloc[0], 106 / 101 - 1)
        x = np.linspace(-1, 1, 200)
        assert bootstrap_ci(x, x, 12)[0] > .999
        assert set(range(5)) == set(np.arange(200) % 5)
        return ExperimentPrecheckResult((ExperimentPreflightCheck("ROBUSTNESS_PATH", ExperimentPreflightStatus.PASS,
            "真实标签函数、块区间与非重叠相位索引合成验证。"),), ExperimentResult(ExperimentOutcome.PASS, {"synthetic": True}, {}))

    def execute(self, context):
        prior = context.predecessors["EX004_20261004"]
        archive = Path(__file__).resolve().parents[1] / "EX004_20261004/artifacts/rex"
        expected = {a.path: a.sha256 for a in prior.artifacts}
        def read_frame(relative):
            path = archive / relative
            assert sha256(path.read_bytes()).hexdigest() == expected[relative]
            return pd.read_parquet(path)
        features, raw = read_frame("features.parquet"), read_frame("data/raw.parquet")
        records, redundancy, interactions = analyze(features, raw)
        artifacts = []
        for name, value in (("robustness.json", records), ("redundancy.json", redundancy), ("interactions.json", interactions)):
            context.workspace.path(name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
            artifacts.append(context.workspace.register_artifact(name, "component_robustness"))
        return ExperimentResult(ExperimentOutcome.PASS, {"robustness_paths": len(records), "interaction_cells": len(interactions),
            "inherited_receipt": prior.receipt_sha256}, {"selection_history": "EX004结果用于本轮候选选择，全部为开发池。"}, tuple(artifacts))
