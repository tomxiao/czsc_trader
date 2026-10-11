"""Prepare a fully frozen adaptation of EX061 mature-training reducer."""

from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
old = ROOT / "research/S013/experiments/EX061_20261011/src/opportunity_statistics.py"
source = old.read_text(encoding="utf-8")
for old_text, new in (
    ("late_recovery", "late_weakness"),
    ("early_volume_reclaim", "early_reclaim_weakness"),
    ('"return_3": 3, "return_5": 5', '"return_4": 4, "return_8": 8'),
    ('"downside_3": 3, "downside_5": 5', '"downside_4": 4, "downside_8": 8'),
    ("s013-tail-opportunity-statistics-v1", "s013-fee-aware-reversal-horizon-v1"),
    (
        "Open[T+1+h]/Open[T+1]-1; h complete sessions held",
        "Open[T+1+h]/Open[T+1]*(1-.001)/(1+.001)-1; fractional open-fill fee proxy; h complete sessions held",
    ),
):
    if old_text not in source:
        raise ValueError(old_text)
    source = source.replace(old_text, new)
anchor = "    index, positions = features.index, np.arange(len(features))"
source = source.replace(
    anchor,
    """    scope_masks["past20_declining"] = features["momentum20"].lt(0).to_numpy(bool)
    if opportunity is not None:
        scope_masks["declining_opportunity"] = scope_masks["past20_declining"] & opportunity.to_numpy(bool)
"""
    + anchor,
)
Path(__file__).with_name("opportunity_statistics.py").write_text(source, encoding="utf-8")
verify = (ROOT / "research/S013/experiments/EX064_20261011/src/verification.py").read_text(
    encoding="utf-8"
)
verify = verify.replace("negative_gap_repair", "late_weakness").replace(
    "positive_gap_fade", "early_reclaim_weakness"
)
verify = verify.replace('"controls+late_weakness"', '"controls+late"').replace(
    '"controls+early_reclaim_weakness"', '"controls+reclaim"'
)
verify = verify.replace("'controls+late_weakness'", "'controls+late'").replace(
    "'controls+early_reclaim_weakness'", "'controls+reclaim'"
)
verify = verify.replace(
    "{'all','opportunity'}", "{'all','opportunity','past20_declining','declining_opportunity'}"
)
verify = verify.replace(
    "selected = np.ones(len(index),dtype=bool) if scope == 'all' else opportunity.to_numpy()",
    "selected = {'all':np.ones(len(index),dtype=bool), 'opportunity':opportunity.to_numpy(), 'past20_declining':features.momentum20.lt(0).to_numpy(), 'declining_opportunity':(opportunity & features.momentum20.lt(0)).to_numpy()}[scope]",
)
Path(__file__).with_name("verify_statistics.py").write_text(verify, encoding="utf-8")
tests = (ROOT / "research/S013/experiments/EX061_20261011/src/statistics_checks.py").read_text(
    encoding="utf-8"
)
tests = tests.replace(
    "from opportunity_statistics import", "from stats_test_module import"
).replace("frame.late_recovery", "frame.late_weakness")
tests = tests.replace(
    "engine':'EX060 tested arithmetic retained; only declared components, controls, label horizons and model names changed",
    "engine':'EX061 reducer adapted for fee-aware4/8 labels and reversal components; no real data",
)
Path(__file__).with_name("statistics_checks.py").write_text(tests, encoding="utf-8")
Path(__file__).with_name("stats_test_module.py").write_text(source, encoding="utf-8")
