"""Source-only sealing of the explicit original date-axis technical correction."""
import ast
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from driver import public, read

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


original = read(HERE/"execution_freeze.json")
assert digest(HERE/"execution_freeze.json") == "5d78a36fe638e55f3ecae0e794d28b4fefef159ac2e76b43dfc26632b33410d7"
assert all(digest(HERE/n) == h for n, h in original["source_files"].items())
expected = (HERE/"input_authentication.py").read_text().replace(
    "if not decision_axis.equals(sessions):", "if not decision_axis.equals(full_axis[:-1]):")
assert ast.dump(ast.parse(expected)) == ast.dump(ast.parse((HERE/"input_authentication_v2.py").read_text()))
attempt_path = ".tmp/s013-cross-day-curvature/actual/authentication_attempt.json"
failure_path = ".tmp/s013-cross-day-curvature/actual/authentication_failure.json"
attempt, failure = read(ROOT/attempt_path), read(ROOT/failure_path)
record = {"status": "SOURCE_ONLY_EXPLICIT_TECHNICAL_CORRECTION",
          "original_method_reference": attempt["method_reference"],
          "original_execution_freeze_sha256": digest(HERE/"execution_freeze.json"),
          "original_attempt": {"path": attempt_path, "sha256": digest(ROOT/attempt_path)},
          "original_failure": {"path": failure_path, "sha256": digest(ROOT/failure_path)},
          "original_attempt_content": attempt, "original_failure_content": failure,
          "only_substantive_correction": "decision_axis exact comparison: sessions -> full_axis[:-1]",
          "actual_schema": "1636 decisions2019-12-31(anchor)..2026-09-29;1636 executions2020-01-02..2026-09-30",
          "unchanged": "full original anchor prefix shifted before1635grid reindex; no deleted anchor or forced first-signal flat; formula/17controls/labels/positive prior/two scopes/statistics/reading unchanged",
          "original_input_authentication_AST": "exact after only declared comparison replacement",
          "interpretation": "schema correction, no new mechanism or financial evaluation; previous failed attempt remains failed",
          "next": "root publishes prospective technical declaration and invokes v2 only in new work directory; source author performs no actual authentication/analyze"}
write_new(HERE/"technical_correction_v2.json", record)
proof = read(HERE/"execution_pureproof_v2.json")
assert proof["check_count"] == 27
assert all(digest(HERE/n) == h for n, h in proof["source_files"].items())
new_files = ["execution_freeze.json", "input_authentication_v2.py", "driver_v2.py", "execution_checks_v2.py",
             "prepare_v2.py", "seal_v2.py", "execution_pureproof_v2.json", "technical_correction_v2.json"]
source_files = {**original["source_files"], **{n: digest(HERE/n) for n in new_files}}
freeze = {"status": "SOURCE_ONLY_READY", "source_files": source_files, "technical_continuation": record,
          "pure_checks": 27, "original_core_math_checks": 39, "ruff": "PASS", "cli_help": "PASS",
          "actual_authentication_calls": 0, "actual_analyze_calls": 0, "provider_calls": 0,
          "new_accounts": 0, "new_experiments": 0, "publications": 0}
write_new(HERE/"execution_freeze_v2.json", freeze)
old_method = read(public(attempt["method_reference"]))
assert old_method["source_freeze_sha256"] == record["original_execution_freeze_sha256"]
draft = deepcopy(old_method)
draft.update(status="SOURCE_ONLY_TECHNICAL_METHOD_DRAFT_NOT_DECLARED", source_files=source_files,
             source_freeze_sha256=digest(HERE/"execution_freeze_v2.json"), technical_continuation=record)
draft["root_required_before_execution"] = "separate public prospective technical declaration; setstatus PROSPECTIVE_DECLARED only after declaration; then driver_v2 in new actual_v2 work. No original source/evidence overwritten."
write_new(HERE/"technical_method_draft_v2.json", draft)
print(json.dumps({n: digest(HERE/n) for n in ["execution_freeze_v2.json", "input_authentication_v2.py",
      "driver_v2.py", "execution_pureproof_v2.json", "technical_correction_v2.json", "technical_method_draft_v2.json"]}, indent=2))
