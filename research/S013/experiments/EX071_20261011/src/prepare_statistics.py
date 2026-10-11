"""Prepare source only; no allocation, market read or statistical execution."""

from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
HERE = Path(__file__).parent
source = (ROOT / ".tmp/s013-multiday-pressure/opportunity_statistics.py").read_text("utf-8")
source = source.replace(
    'COMPONENTS = ("short_stretch4", "overnight_down_share4")', 'COMPONENTS = ("late_weakness",)'
)
source = source.replace('    "late_recovery",\n', "")
source = source.replace(
    '    "max_down_run_share",\n)',
    '    "max_down_run_share",\n    "holding_age",\n    "entry_mark_pnl",\n    "known_falling",\n)',
)
source = source.replace("s013-four-session-pressure-df-v1", "s013-actual-held-continuation-df-v1")
source = source.replace(
    "all twenty controls",
    "all twenty-two controls, explicitly excluding component linear opposite late_recovery",
)
source = source.replace("all 22 feature columns finite", "all 23 feature columns finite")
source = source.replace(
    '"return_h": "Open[T+1+h]/Open[T+1]*(1-.001)/(1+.001)-1; fractional open-fill fee proxy; h complete sessions held"',
    '"return_h": "Open[T+1+h]/Open[T+1]-1; same future/current SELL fee cancels, no new BUY fee"',
)
source = source.replace(
    '"downside_h": "max(0,1-min(Low[T+1:T+h])/Open[T+1])"',
    '"downside_h": "max(0,1-min(Open/Close T+1..T+h and finalOpen[T+1+h])/Open[T+1]); fixed daily observation downside, not path/account DD"',
)
source = source.replace(
    '"models": ["controls", "controls+stretch", "controls+overnight", "controls+both"]',
    '"models": ["controls", "controls+late"]',
)
source = source.replace(
    '        "controls+stretch": [*range(n_controls), n_controls],',
    '        "controls+late": [*range(n_controls), n_controls],',
)
source = source.replace('        "controls+overnight": [*range(n_controls), n_controls + 1],\n', "")
source = source.replace('        "controls+both": list(range(n_controls + len(COMPONENTS))),\n', "")
source = source.replace(
    '("all", "past20_declining", "flat_eligible", "declining_flat")',
    '("actual_held", "declining_actual_held", "actual_signal_continue", "actual_signal_exit")',
)
source = source.replace(
    "all, past20_declining, true original signal-flat eligible, declining-flat",
    "actual_held, declining_actual_held, actual_signal_continue, actual_signal_exit; no flat zero imputation",
)
source = source.replace(
    "Not tested: next open gap is already realized before proposed entry",
    "Initial Tclose-to-nextOpen gap retained for accounting attribution only; both T+1 decision alternatives share it",
)
(HERE / "opportunity_statistics.py").write_text(source, "utf-8")
