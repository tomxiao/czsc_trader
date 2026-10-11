"""Freeze the fixed two-component/18-control adaptation before market study."""
from pathlib import Path
import re

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
HERE = Path(__file__).parent
source = (ROOT / ".tmp/s013-opportunity-supply/opportunity_statistics.py").read_text("utf-8")
old = 'COMPONENTS = (\n    "late_weakness",\n    "early_reclaim_weakness",\n)'
assert old in source
source = source.replace(old, 'COMPONENTS = ("early_down_share", "max_down_run_share")')
source = source.replace('    "volume_ratio20",\n)', '    "volume_ratio20",\n    "late_recovery",\n    "early_volume_reclaim",\n    "total_down",\n    "total_up",\n)')
source = source.replace('    "return_1": 1,\n', '').replace('    "downside_1": 1,\n', '')
source = source.replace("s013-fee-aware-reversal-horizon-v1", "s013-intraday-order-state-v1")
source = source.replace("all fourteen controls", "all eighteen controls")
source = source.replace("all 16 feature columns finite", "all 20 feature columns finite")
source = source.replace("controls+late", "controls+early").replace("controls+reclaim", "controls+run")
source = source.replace("full-pool and opportunity-pool only", "all four predeclared scopes")
source, count = re.subn(
    r'    scope_masks = \{"all".*?    index, positions = features.index, np.arange\(len\(features\)\)',
    '''    if not isinstance(opportunity, pd.DataFrame) or not features.index.equals(opportunity.index):
        raise ValueError("Aligned predeclared scope frame required")
    if tuple(opportunity.columns) != ("all", "past20_declining", "flat_eligible", "declining_flat"):
        raise ValueError("Four fixed scopes required")
    if any(not pd.api.types.is_bool_dtype(opportunity[c].dtype) for c in opportunity) or opportunity.isna().any().any():
        raise ValueError("Non-null boolean scopes required")
    scope_masks = {c: opportunity[c].to_numpy(bool) for c in opportunity}
    index, positions = features.index, np.arange(len(features))''',
    source, flags=re.S,
)
assert count == 1
source = source.replace("all rows and optional original strategy ex-ante eligibility", "all, past20_declining, true original signal-flat eligible, declining-flat")
(HERE / "opportunity_statistics.py").write_text(source, "utf-8")
(HERE / "late_recovery_component.py").write_bytes((ROOT / "research/S013/experiments/EX061_20261011/src/late_recovery_component.py").read_bytes())
