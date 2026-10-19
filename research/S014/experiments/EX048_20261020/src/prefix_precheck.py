"""Pure separation of new feedback, original state, target and funded dates."""
from hashlib import sha256
import json
from pathlib import Path

from audit_accounts import divergence_dates

EX = Path(__file__).resolve().parents[1]
checks = []


def check(name, actual, expected):
    assert actual == expected, (name, actual, expected)
    checks.append(name)


old = [dict(signal_date=f"2020-01-0{i}", target_position=0.0, reservation_index=-1, pause_loss_profile=1.0, pause_profit_profile=0.0) for i in (2, 3, 6)]
rows = [dict(r, pause_armed_before_candidate=False) for r in old]
daily = [dict(date=r["signal_date"], cash=100000.0, cash_before=100000.0, quantity=0, quantity_before=0, equity=100000.0) for r in old]
check("identical old and feedback state", divergence_dates(rows, old, daily, daily), (None, None, None, None))
for row in rows:
    row["pause_loss_profile"] = 0.0
check("inherited constant profile flags ignored for mutable state and money", divergence_dates(rows, old, daily, daily), (None, None, None, None))
rows[0]["completed_net_known"] = True
check("completed history enters new memory without selected arm", divergence_dates(rows, old, daily, daily), ("2020-01-02", None, None, None))
rows[0]["completed_net_known"] = False
rows[0]["pause_armed_before_candidate"] = True
check("feedback only is no original or money change", divergence_dates(rows, old, daily, daily), ("2020-01-02", None, None, None))
rows[1]["reservation_index"] = 11
check("reservation first original state without target or money", divergence_dates(rows, old, daily, daily), ("2020-01-02", "2020-01-03", None, None))
rows[2]["target_position"] = 1.0
check("target separated from prior feedback and reservation", divergence_dates(rows, old, daily, daily), ("2020-01-02", "2020-01-03", "2020-01-06", None))
changed = [dict(r) for r in daily]
changed[2]["cash"] = 99000.0
changed[2]["quantity"] = 100
check("actual funded cash and quantity only", divergence_dates(rows, old, changed, daily), ("2020-01-02", "2020-01-03", "2020-01-06", "2020-01-06"))
value = {"status": "PASS_PURE_SYNTHETIC_ONLY", "checks_count": len(checks), "checks": checks,
         "audit_source_sha256": sha256((EX / "src/audit_accounts.py").read_bytes()).hexdigest(),
         "precheck_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(), "new_accounts": 0, "new_market_reads": 0}
with (EX / "others/audit_prefix_precheck.json").open("x", encoding="utf-8", newline="\n") as f:
    json.dump(value, f, ensure_ascii=False, indent=2)
    f.write("\n")
print("PURE_FOUR_DATES_PASS", len(checks))
