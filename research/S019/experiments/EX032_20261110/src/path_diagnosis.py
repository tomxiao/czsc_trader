"""Locate the remaining C0080 drawdown using the saved account only."""
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research/S019/experiments/EX013_20261110/src"))
from runner import read_account, save  # noqa: E402

ref, payload = read_account(ROOT / "research/S019/experiments/EX029_20261110/others/maximum_account.json")
run = payload["runs"]["candidate"]
equity = np.array([100000., *(x["equity"] for x in run["account_daily"])])
dd = 1 - equity / np.maximum.accumulate(equity)
trough = int(dd.argmax())
peak = int(equity[:trough + 1].argmax())
start, end = run["account_daily"][peak - 1]["session"], run["account_daily"][trough - 1]["session"]
decisions = [{"execution_start": x["execution_start"], "target": x["target"], "facts": x["explanation"]["basis"]}
    for x in run["decisions"] if start <= x["execution_start"][:10] <= end
    and any(v["key"] == "participation" for v in x["explanation"]["basis"])]
save(WORK / "others/baseline_path.json", {"account": ref.to_dict(), "mdd": float(dd[trough]),
    "peak": start, "trough": end, "entry_decisions": decisions,
    "trades": [x for x in run["trades"] if x["entry_at"][:10] <= end and x["exit_at"][:10] >= start]})
print("C0080_MDD", start, end, dd[trough], flush=True)
