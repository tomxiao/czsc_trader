"""Freeze one-component state-split adaptation before new results."""

from pathlib import Path
import re

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
source = (ROOT / ".tmp/s013-opportunity-supply/opportunity_statistics.py").read_text(
    encoding="utf-8"
)
source = source.replace(
    'COMPONENTS = (\n    "late_weakness",\n    "early_reclaim_weakness",\n)',
    'COMPONENTS = ("late_weakness",)',
)
source = source.replace('    "return_1": 1,\n', "").replace('    "downside_1": 1,\n', "")
source = source.replace("s013-fee-aware-reversal-horizon-v1", "s013-true-flat-held-split-v1")
source = source.replace(
    '["controls", "controls+late", "controls+reclaim", "controls+both"]',
    '["controls", "controls+late"]',
)
source = source.replace("all 16 feature columns finite", "all 15 feature columns finite")
source = source.replace('        "controls+reclaim": [*range(n_controls), n_controls + 1],\n', "")
source = source.replace('        "controls+both": list(range(n_controls + len(COMPONENTS))),\n', "")
source, n = re.subn(
    r'    scope_masks = \{"all".*?    index, positions = features.index, np.arange\(len\(features\)\)',
    """    if not isinstance(opportunity, pd.DataFrame) or not features.index.equals(opportunity.index):
        raise ValueError("Aligned predeclared scope frame required")
    if tuple(opportunity.columns) != ("flat_eligible", "held_eligible", "declining_flat", "declining_held"):
        raise ValueError("Four fixed actual-state scopes required")
    if any(not pd.api.types.is_bool_dtype(opportunity[c].dtype) for c in opportunity) or opportunity.isna().any().any():
        raise ValueError("Non-null boolean scopes required")
    scope_masks = {c:opportunity[c].to_numpy(bool) for c in opportunity}
    index, positions = features.index, np.arange(len(features))""",
    source,
    flags=re.S,
)
assert n == 1
Path(__file__).with_name("opportunity_statistics.py").write_text(source, encoding="utf-8")
