"""Freeze fixed pressure components and residual-DF statistical contract."""

from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
HERE = Path(__file__).parent
source = (ROOT / ".tmp/s013-order-component/opportunity_statistics.py").read_text("utf-8")
source = source.replace(
    'COMPONENTS = ("early_down_share", "max_down_run_share")',
    'COMPONENTS = ("short_stretch4", "overnight_down_share4")',
)
source = source.replace(
    '    "total_up",\n)', '    "total_up",\n    "early_down_share",\n    "max_down_run_share",\n)'
)
source = source.replace("s013-intraday-order-state-v1", "s013-four-session-pressure-df-v1")
source = source.replace(
    "all eighteen controls",
    "all twenty controls, partial residual DF n-rank(design)>=10 required; otherwise unavailable, recording design_rank/residual_df",
)
source = source.replace("all 20 feature columns finite", "all 22 feature columns finite")
source = source.replace("controls+early", "controls+stretch").replace(
    "controls+run", "controls+overnight"
)
start, end = source.index("def _ic("), source.index("\ndef _cdf_apply(")
replacement = """def _ic(x: np.ndarray, y: np.ndarray, controls: np.ndarray | None = None) -> dict:
    good = _finite(x, y) if controls is None else _finite(x, y, controls)
    n = int(good.sum())
    metadata = {"n": n, "design_rank": None, "residual_df": None}
    design = None
    if controls is not None:
        design = np.column_stack([np.ones(n), *(rankdata(col, method="average") for col in controls[good].T)])
        design_rank = int(np.linalg.matrix_rank(design)) if n else 0
        metadata.update(design_rank=design_rank, residual_df=n-design_rank)
        if n-design_rank < 10:
            return {**metadata, "value": None, "reason": "INSUFFICIENT_RESIDUAL_DF"}
    if n < MIN_N:
        return {**metadata, "value": None, "reason": "INSUFFICIENT_SAMPLE"}
    if np.ptp(x[good]) == 0 or np.ptp(y[good]) == 0:
        return {**metadata, "value": None, "reason": "CONSTANT_COMPONENT_OR_LABEL"}
    xr, yr = rankdata(x[good], method="average"), rankdata(y[good], method="average")
    if design is not None:
        x_norm, y_norm = np.linalg.norm(xr-xr.mean()), np.linalg.norm(yr-yr.mean())
        xr = xr-design @ np.linalg.lstsq(design, xr, rcond=None)[0]
        yr = yr-design @ np.linalg.lstsq(design, yr, rcond=None)[0]
        if np.linalg.norm(xr) <= 1e-10*x_norm or np.linalg.norm(yr) <= 1e-10*y_norm:
            return {**metadata, "value": None, "reason": "CONSTANT_OR_EXPLAINED_RESIDUAL"}
    value = _pearson(xr, yr)
    return {**metadata, "value": value, "reason": None if value is not None else "CONSTANT_OR_EXPLAINED_RESIDUAL"}

"""
source = source[:start] + replacement + source[end:]
(HERE / "opportunity_statistics.py").write_text(source, "utf-8")
