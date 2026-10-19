"""Publish EX040 execution-only completion; no delivery/intent or account changes."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EX / "src/revision02"))
from run_accounts import context, digest, publish_file, read, write  # noqa: E402


def main():
    ctx = context()
    index = read(EX / "others/accounts_index.json")
    assert [(r["index"], r["status"]) for r in index["records"]] == [
        (0, "FAILED"),
        (3, "SUCCEEDED"),
        (4, "SUCCEEDED"),
        (5, "SUCCEEDED"),
    ]
    files = [
        EX / "others/build_failure_v2_package_name.json",
        EX / "others/manifest_alias_erratum.json",
    ]
    refs = {
        p.relative_to(EX).as_posix(): publish_file(ctx, p, "ex040-closeout-" + p.stem)
        for p in files
    }
    note = {
        "action": "export_existing_inputs.py complete original-input CSV copy and local material publication",
        "execution": "REJECTED_BEFORE_PROCESS_START_NOT_RUN",
        "review_reason_verbatim": "该命令会把五类认证输入的完整CSV内容发布到公共证据存储，属于可能含敏感研究/供应商数据的外部泄露；现有授权覆盖账户诊断，不明确授权原始数据向该目的地公开。",
        "no_workaround_or_retry": True,
        "safe_alternative": "Independent auditor reads same authenticated existing PreparedDataRef via public data.fetch; no prepare/supplier call/CSV duplication",
        "actual_api_destination_verified": "publish_evidence calls local _publish_bytes; EvidenceRef.repository_path is research/S014/assets/evidence/EX040_20261019/",
        "export_script_not_executed": True,
    }
    p = EX / "others/input_export_approval_rejection.json"
    write(p, note)
    refs[p.relative_to(EX).as_posix()] = publish_file(
        ctx, p, "ex040-input-export-approval-rejection-and-safe-alternative"
    )
    result = {
        "status": "EXECUTION_COMPLETE_WITH_PRESERVED_TECHNICAL_FAILURE",
        "experiment": "EX040_20261019",
        "records": index["records"],
        "total_dispatched": 4,
        "succeeded": 3,
        "failed": 1,
        "unknown": 0,
        "formal_candidate_registrations": 0,
        "external_market_calls": 0,
        "economic_endpoint": "2025-12-31 SESSION_CLOSE",
        "full_account_window": ["2020-01-02", "2026-10-15"],
        "account_index_ref": read(EX / "others/accounts_index_ref.json"),
        "v1_lock_ref": read(EX / "protocols/published_lock.json"),
        "v2_lock_ref": read(EX / "protocols/revision02/published_lock.json"),
        "additional_evidence": refs,
        "runtime_internal_audit": {
            str(r["index"]): r["audit"] for r in index["records"] if r["audit"]
        },
        "independent_audit": {
            "path": "research/S014/materials/20261019_2025_action_execution/accounting/independent_account_audit.json",
            "reported_sha256": "f06b73b93cad6947e75b9888aecfdce089c330c94800033e411c252657c69842",
            "checks": 307071,
            "status": "PASS",
            "additional_existing_input_fill_rules_check": "delegated independent read-only public fetch",
        },
        "source": {
            "path": Path(__file__).relative_to(ROOT).as_posix(),
            "sha256": digest(Path(__file__)),
        },
        "delivery_and_family_intent_modified_here": False,
    }
    p = EX / "others/execution_result.json"
    write(p, result)
    ref = publish_file(ctx, p, "ex040-execution-result")
    write(EX / "others/execution_result_ref.json", ref)
    print(ref["sha256"], flush=True)


if __name__ == "__main__":
    main()
