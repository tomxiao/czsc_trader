"""Publish the fixed joint account execution and an eight-dispatch evidence inventory."""

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
    assert [r["candidate"] for r in index["records"]] == ["S014-C9900", "S014-C9901"]
    pre = ACCOUNTING / "joint_runner_pre_review.json"
    assert digest(pre) == "c6bd503b9163912da2684ee47e0856de6fcf8981df03236a6466cf41954f5e27"
    noop = ACCOUNTING / "independent_joint_noop_audit.json"
    refs = {
        "independent_runner_review": publish_file(ctx, pre, "ex042-independent-runner-pre-review"),
        "independent_new_source_noop_audit": publish_file(
            ctx, noop, "ex042-independent-new-source-noop-audit"
        ),
    }
    all_records = []
    for name in ("EX040_20261019", "EX041_20261019", "EX042_20261019"):
        folder = ROOT / "research/S014/experiments" / name
        for record in read(folder / "others/accounts_index.json")["records"]:
            all_records.append({"experiment": name, **record})
    assert len(all_records) == 8 and sum(r["status"] == "SUCCEEDED" for r in all_records) == 7
    inventory = EX / "others/all_execution_accounts.json"
    write(
        inventory,
        {
            "status": "ALL_EXECUTION_RECEIPTS_RETAINED",
            "records": all_records,
            "account_dispatches": 8,
            "succeeded": 7,
            "failed": 1,
            "unknown": 0,
            "original_failed_v1_retained": True,
            "new_formal_registered_candidates": 0,
            "new_market_supplier_calls": 0,
            "new_model_fits": 0,
            "primary_economic_endpoint": "2025-12-31 SESSION_CLOSE",
            "additional_accounts_not_executed": True,
        },
    )
    inventory_ref = publish_file(ctx, inventory, "ex042-all-2025-diagnostic-execution-accounts")
    result = {
        "status": "EXECUTION_COMPLETE",
        "experiment": "EX042_20261019",
        "records": index["records"],
        "total_dispatched_this_experiment": 2,
        "succeeded": 2,
        "failed": 0,
        "unknown": 0,
        "formal_candidate_registrations": 0,
        "external_market_calls": 0,
        "unique_economic_endpoint": "2025-12-31 SESSION_CLOSE",
        "full_account_window": ["2020-01-02", "2026-10-15"],
        "account_index_ref": read(EX / "others/accounts_index_ref.json"),
        "source_lock_ref": read(EX / "protocols/published_lock.json"),
        **refs,
        "joint_execution_audit": index["records"][1]["audit"],
        "scope": "Actual May30 H10 cycle and actual current June19 inventory one forced sale, original funding/history/reservation and all subsequent participation retained",
        "new_source_NOOP_independently_passed_before_treatment": True,
        "actual_account_inventory_ref": inventory_ref,
        "whole_account_and_terminal_decomposition_audit": "Independent final review in separate immutable materials; execution completion does not substitute for it",
        "source": {
            "path": Path(__file__).relative_to(ROOT).as_posix(),
            "sha256": digest(Path(__file__)),
        },
        "delivery_and_family_intent_modified_here": False,
    }
    p = EX / "others/execution_result.json"
    write(p, result)
    ref = publish_file(ctx, p, "ex042-execution-result")
    write(EX / "others/execution_result_ref.json", ref)
    print(ref["sha256"], flush=True)


if __name__ == "__main__":
    main()
