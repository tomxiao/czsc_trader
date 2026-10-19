"""Publish fixed second-wave execution receipts; no further account or intent action."""

from pathlib import Path

from run_accounts import context, digest, publish_file, read, write

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
ACCOUNTING = ROOT / "research/S014/materials/20261019_2025_action_execution/accounting"


def main():
    ctx = context()
    index = read(EX / "others/accounts_index.json")
    assert [(r["index"], r["status"]) for r in index["records"]] == [
        (0, "SUCCEEDED"),
        (1, "SUCCEEDED"),
    ]
    assert [r["candidate"] for r in index["records"]] == ["S014-C9800", "S014-C9801"]
    pre = ACCOUNTING / "early_cycle_runner_pre_review.json"
    assert digest(pre) == "bc740d7e6f601b6e46c0b33143e0852fb6a882313278724124a3710f5fc6032d"
    pre_ref = publish_file(ctx, pre, "ex041-independent-runner-pre-review")
    noop = ACCOUNTING / "independent_early_noop_audit.json"
    noop_ref = publish_file(ctx, noop, "ex041-independent-new-source-noop-audit")
    result = {
        "status": "EXECUTION_COMPLETE",
        "experiment": "EX041_20261019",
        "records": index["records"],
        "total_dispatched": 2,
        "succeeded": 2,
        "failed": 0,
        "unknown": 0,
        "formal_candidate_registrations": 0,
        "external_market_calls": 0,
        "unique_economic_endpoint": "2025-12-31 SESSION_CLOSE",
        "full_account_window": ["2020-01-02", "2026-10-15"],
        "account_index_ref": read(EX / "others/accounts_index_ref.json"),
        "source_lock_ref": read(EX / "protocols/published_lock.json"),
        "independent_runner_review": pre_ref,
        "independent_new_source_noop_audit": noop_ref,
        "actual_original_cycle": index["records"][1]["audit"],
        "scope": "Only original May30 actual BUY cycle protects from support exit; original H10/reservation/pending and subsequent original policy; independent from all EX040 paths",
        "new_source_NOOP_independently_passed_before_treatment": True,
        "joint_June19_treatment_executed": False,
        "whole_account_and_terminal_decomposition_audit": "Independent reviewer completing separate immutable materials; not claimed PASS by execution completion alone",
        "source": {
            "path": Path(__file__).relative_to(ROOT).as_posix(),
            "sha256": digest(Path(__file__)),
        },
        "delivery_and_family_intent_modified_here": False,
    }
    p = EX / "others/execution_result.json"
    write(p, result)
    ref = publish_file(ctx, p, "ex041-execution-result")
    write(EX / "others/execution_result_ref.json", ref)
    print(ref["sha256"], flush=True)


if __name__ == "__main__":
    main()
