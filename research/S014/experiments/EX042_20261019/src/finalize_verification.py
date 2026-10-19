"""Authenticate final independent audits and every fixed diagnostic account reference."""

from pathlib import Path

from czsc_trader.research_tools import EvidenceRef
from run_accounts import context, digest, publish_file, read, write

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "research/S014/materials/20261019_2025_action_execution/accounting"


def main():
    ctx = context()
    expected = {
        "independent_account_audit.json": "f06b73b93cad6947e75b9888aecfdce089c330c94800033e411c252657c69842",
        "independent_early_cycle_audit.json": "d09e48e8b115938d0ebdfe89fab4d3c8694885cb469cdc45106b607cac7a7585",
        "independent_early_execution_constraints.json": "5c01f90e16a0530a5648c2f60fa49f54dc53dab11d6fc3928d4810709d3cb7c3",
        "independent_joint_account_audit.json": "23347604e2e7a08d36bfd6b132774c40d9cbcd40a4ad79f12e353331e4a2db17",
        "independent_joint_execution_constraints.json": "35c334623b621c9bdad7524135b908d4fb5693d917f6c57045fa26306beffbea",
    }
    audits = {}
    for name, checksum in expected.items():
        path = AUDIT / name
        assert digest(path) == checksum
        audits[name] = publish_file(ctx, path, "ex042-final-independent-" + path.stem)
    first_constraints = AUDIT / "independent_execution_constraints.json"
    audits[first_constraints.name] = publish_file(
        ctx, first_constraints, "ex042-final-independent-first-wave-execution-constraints"
    )
    accounts = []
    locks = []
    for name in ("EX040_20261019", "EX041_20261019", "EX042_20261019"):
        folder = ROOT / "research/S014/experiments" / name
        source_locks = [folder / "protocols/execution_lock.json"]
        if name == "EX040_20261019":
            source_locks.append(folder / "protocols/revision02/execution_lock.json")
        for path in source_locks:
            lock = read(path)
            for relative, checksum in lock["source_hashes"].items():
                assert digest(folder / relative) == checksum
            for relative, checksum in lock.get("external_source_hashes", {}).items():
                assert digest(ROOT / relative) == checksum
            locks.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "sha256": digest(path),
                    "source_bytes_unchanged": True,
                }
            )
        for row in read(folder / "others/accounts_index.json")["records"]:
            if row["evidence"]:
                ref = EvidenceRef.from_dict(row["evidence"])
                account = read(ref.resolve(ROOT))
                assert account["result_hash"] == row["result_hash"]
            accounts.append(
                {
                    "experiment": name,
                    "index": row["index"],
                    "mode": row["mode"],
                    "candidate": row["candidate"],
                    "status": row["status"],
                    "evidence": row["evidence"],
                    "result_hash": row["result_hash"],
                }
            )
    result = {
        "status": "PASS_EXECUTION_AND_INDEPENDENT_AUDIT_SCOPE",
        "account_dispatches": 8,
        "succeeded": 7,
        "technical_failed": 1,
        "unknown": 0,
        "failed_v1_retained": True,
        "all_successful_account_refs_SHA_and_result_hash_verified": True,
        "all_frozen_source_locks_byte_identical": locks,
        "independent_final_audit_refs": audits,
        "accounts": accounts,
        "additional_accounts_dispatched": 0,
        "new_formal_registered_candidates": 0,
        "new_external_market_calls": 0,
        "new_fits": 0,
        "raw_input_CSV_export": "NOT_RUN; approval rejection retained in EX040; safe original PreparedDataRef read-only audit used",
        "scope_limit": "Fixed known-node retrospective diagnostics including all subsequent participation; not a qualified deployable strategy or general signal proof",
        "unique_economic_endpoint": "2025-12-31 SESSION_CLOSE",
        "git_commit_or_family_intent_write_performed_by_executor": False,
        "source_sha256": digest(Path(__file__)),
    }
    path = EX / "others/final_verification.json"
    write(path, result)
    ref = publish_file(ctx, path, "ex042-final-three-wave-execution-verification")
    write(EX / "others/final_verification_ref.json", ref)
    print(ref["sha256"], flush=True)


if __name__ == "__main__":
    main()
