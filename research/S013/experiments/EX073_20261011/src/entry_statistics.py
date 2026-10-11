"""Fixed single entry pool binary pressure correlations; no predictive fitting."""

from collections import Counter
import numpy as np
from scipy.stats import rankdata

CONTROLS = (
    "momentum20",
    "range_position60",
    "acf1",
    "volatility20",
    "intraday_return",
    "overnight_gap",
    "intraday_energy20",
    "intraday_rms20",
    "confirmation_score",
    "daily_close_location",
    "feature_intraday_down_energy20",
    "feature_overnight_down_energy20",
    "turnover20",
    "volume_ratio20",
)
PRIMARY = ("late_return", "late_downside")
METHOD = {
    "version": "s013-entry-pressure-fixed-statistics-v1",
    "component": "pressure_flag binary 1 versus 0",
    "scope": "all first actual C8880 bear entries only; no future-exit selections",
    "controls": list(CONTROLS),
    "primary": list(PRIMARY),
    "hypothesis": "flag positively associated with late_downside and negatively with late_return; retain original EX069 reversal hypothesis failure, this is new risk-role hypothesis",
    "correlation": "Spearman average ties; partial OLS rank residuals on intercept+14 controls. Require n>=20 and residual df=n-rank(design)>=10; record rank/df, otherwise null reason. Rank residual norms <=1e-10 times original centered norm => explicitly explained/null.",
    "finite": "raw uses finite flag and label, partial additionally all14 controls finite; retain missing counts, no control dropping or filling",
    "bootstrap": {
        "replicates": 500,
        "block_sessions": 40,
        "seed": 13,
        "sampling": "uniform overlapping starts on full original1635-session T axis, concatenate full blocks and truncate, then filter actual bear entry pool; no event-axis bootstrap",
        "interval": "2.5/97.5 linear quantiles only when >=400 valid replicates; all500 statuses/n/group counts/rank/df and failure reasons retained, no replacements",
    },
    "year_phase": "Every signal year2019..2026; five phases T full original session index mod5 before filtering, matching T+5 full maturity. Report n,flag/clear, raw/partial/rank/df; thin null, no fitting/CI per year/phase.",
    "groups": "Observed means/descriptive only. Either group n<20 => NOT_RELIABLE_GROUP_EVIDENCE; no grouped CI, outcome-selected partitions, significance or economic gate.",
    "companions": "first2/full4 algebra and descriptive means only, no correlations, bootstrap, models or added horizons",
    "selection": "Already seen S013 development data and EX069/071/072 failure selected this final responsibility question; intervals uncorrected for that history; no sealed validation or hardgate claim",
}


def ic(x, y, controls=None):
    good = np.isfinite(x) & np.isfinite(y)
    if controls is not None:
        good &= np.isfinite(controls).all(axis=1)
    xx, yy = x[good], y[good]
    n = len(xx)
    result = {
        "n": n,
        "flag_n": int((xx == 1).sum()),
        "clear_n": int((xx == 0).sum()),
        "design_rank": None,
        "residual_df": None,
        "value": None,
        "reason": None,
    }
    design = None
    if controls is not None:
        design = np.column_stack(
            [np.ones(n), *(rankdata(v, method="average") for v in controls[good].T)]
        )
        rank = int(np.linalg.matrix_rank(design)) if n else 0
        result.update(design_rank=rank, residual_df=n - rank)
        if n - rank < 10:
            return {**result, "reason": "INSUFFICIENT_RESIDUAL_DF"}
    if n < 20:
        return {**result, "reason": "INSUFFICIENT_SAMPLE"}
    if np.ptp(xx) == 0 or np.ptp(yy) == 0:
        return {**result, "reason": "CONSTANT_COMPONENT_OR_LABEL"}
    xr, yr = rankdata(xx, method="average"), rankdata(yy, method="average")
    if design is not None:
        xn, yn = np.linalg.norm(xr - xr.mean()), np.linalg.norm(yr - yr.mean())
        xr -= design @ np.linalg.lstsq(design, xr, rcond=None)[0]
        yr -= design @ np.linalg.lstsq(design, yr, rcond=None)[0]
        if np.linalg.norm(xr) <= 1e-10 * xn or np.linalg.norm(yr) <= 1e-10 * yn:
            return {**result, "reason": "CONSTANT_OR_EXPLAINED_RESIDUAL"}
    xc, yc = xr - xr.mean(), yr - yr.mean()
    norm = np.linalg.norm(xc) * np.linalg.norm(yc)
    if norm <= np.finfo(float).eps * max(1, n):
        return {**result, "reason": "CONSTANT_OR_EXPLAINED_RESIDUAL"}
    return {**result, "value": float(np.clip(xc @ yc / norm, -1, 1))}


def sampled_indices(n):
    if n < 40:
        raise ValueError("full calendar must support40 sessions")
    rng = np.random.default_rng(13)
    starts = rng.integers(0, n - 40 + 1, size=(500, (n + 39) // 40))
    return (starts[:, :, None] + np.arange(40)).reshape(500, -1)[:, :n]


def describe(x, y):
    good = np.isfinite(x) & np.isfinite(y)
    rows = {}
    for name, value in (("flag", 1), ("clear", 0)):
        v = y[good & (x == value)]
        rows[name] = {
            "n": len(v),
            "mean": float(v.mean()) if len(v) else None,
            "negative_n": int((v < 0).sum()),
            "zero_n": int((v == 0).sum()),
            "positive_n": int((v > 0).sum()),
            "descriptive_only": True,
            "reliable_group_evidence": len(v) >= 20,
            "reason": None if len(v) >= 20 else "NOT_RELIABLE_GROUP_EVIDENCE",
        }
    return rows


def analyze(features, labels, scope):
    x, c = features.pressure_flag.to_numpy(float), features.loc[:, CONTROLS].to_numpy(float)
    mask = scope.to_numpy(bool)
    sampled = sampled_indices(len(features))
    outcome = {
        "method": METHOD,
        "full_axis_n": len(features),
        "entry_n": int(mask.sum()),
        "labels": {},
        "companions": {},
        "models": 0,
    }
    for name in PRIMARY:
        y = labels[name].to_numpy(float)
        panel = {
            "raw": ic(x[mask], y[mask]),
            "partial": ic(x[mask], y[mask], c[mask]),
            "groups": describe(x[mask], y[mask]),
            "bootstrap": {},
            "years": {},
            "phases": {},
        }
        for kind, partial in (("raw", False), ("partial", True)):
            records = []
            for i, row in enumerate(sampled):
                selected = row[mask[row]]
                v = ic(x[selected], y[selected], c[selected] if partial else None)
                records.append({"replicate": i, **v})
            values = [v["value"] for v in records if v["value"] is not None]
            panel["bootstrap"][kind] = {
                "requested_replicates": 500,
                "valid_replicates": len(values),
                "failure_reasons": dict(
                    Counter(v["reason"] for v in records if v["reason"] is not None)
                ),
                "ic95": np.quantile(values, [0.025, 0.975], method="linear").tolist()
                if len(values) >= 400
                else None,
                "reason": None if len(values) >= 400 else "INSUFFICIENT_VALID_BOOTSTRAP_REPLICATES",
                "replicates": records,
                "descriptive_only": True,
                "selection_corrected": False,
            }
        for category, values in (("years", range(2019, 2027)), ("phases", range(5))):
            for k in values:
                keep = mask & (
                    (features.index.year == k)
                    if category == "years"
                    else (np.arange(len(x)) % 5 == k)
                )
                panel[category][str(k)] = {
                    "entry_n": int(keep.sum()),
                    "raw": ic(x[keep], y[keep]),
                    "partial": ic(x[keep], y[keep], c[keep]),
                    "groups": describe(x[keep], y[keep]),
                }
        outcome["labels"][name] = panel
    for name in ("first2", "full4"):
        outcome["companions"][name] = describe(x[mask], labels[name].to_numpy(float)[mask])
    return outcome
