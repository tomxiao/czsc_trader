"""Audit the same successful BASE evidence; no preparation or account execution."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef
from audit_accounts_v2 import audit

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
receipt_path = EX / "others/accounts/run-000.json"
receipt = json.loads(receipt_path.read_bytes())
assert receipt["status"] == "SUCCEEDED" and receipt["audit"]["status"] == "FAIL"
ref = EvidenceRef.from_dict(receipt["evidence"])
assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest() == ref.sha256
account = json.loads(ref.resolve(ROOT).read_bytes())
assert account["result_hash"] == receipt["result_hash"]
report = audit(account, {"pause_profile": "BASE"})
result = {"status": report["status"], "kind": "SAME_ACCOUNT_ADDITIVE_INTERNAL_AUDIT_CORRECTION",
          "original_receipt_path": receipt_path.relative_to(ROOT).as_posix(), "original_receipt_sha256": sha256(receipt_path.read_bytes()).hexdigest(),
          "original_internal_audit_status": "FAIL", "original_account_execution_status": "SUCCEEDED",
          "account_ref": receipt["evidence"], "result_hash": receipt["result_hash"],
          "source_sha256": sha256((EX / "src/strategy_runtime/strategies/completed_pause_review.py").read_bytes()).hexdigest(),
          "account_parent_lock_ref": json.loads((EX / "protocols/published_lock.json").read_bytes()),
          "corrected_audit_source_sha256": sha256((EX / "src/audit_accounts_v2.py").read_bytes()).hexdigest(),
          "correction_scope": "D-state must use daily_by_date[D]; zipped daily row represents next E and must match decision.valid_session and daily.signal_date. Only original prewindow D2019-12-31 uses explicit original100000 cash/0shares. No strategy/fee/price/quantity/tolerance change.",
          "new_account_dispatches": 0, "original_failed_record_retained_unchanged": True, "audit": report}
with (EX / "others/control_audit_correction_v2.json").open("x", encoding="utf-8", newline="\n") as f:
    json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
    f.write("\n")
print("SAME_CONTROL_REAUDIT", report)
assert report["status"] == "PASS"
