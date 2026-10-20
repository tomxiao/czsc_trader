"""Read-only, focused EX051 audit projection correction review; no account execution."""

import ast
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path.cwd()
EX = ROOT / "research/S014/experiments/EX051_20261020"
OUT = ROOT / "research/S014/materials/20261020_followthrough_exit_diagnosis"
HASHES = {}
CHECKS = []


def bind(path, expected=None):
    path = Path(path)
    content = path.read_bytes()
    actual = sha256(content).hexdigest()
    if expected is not None:
        assert actual == expected, str(path)
    HASHES[path.relative_to(ROOT).as_posix()] = actual
    return content


def read(path, expected=None):
    return json.loads(bind(path, expected))


def check(label, condition):
    assert condition, label
    CHECKS.append(label)


def public(ref):
    path = ROOT / "research" / ref["experiment"]["strategy_id"] / "assets/evidence"
    path = path / ref["experiment"]["experiment_id"] / ref["evidence_id"]
    return read(path, ref["sha256"])


def functions(content):
    return {
        node.name: ast.dump(node, include_attributes=False)
        for node in ast.parse(content).body
        if isinstance(node, ast.FunctionDef)
    }


def main():
    decision = read(OUT / "audit_revision_decision.json", "41d2a2a91b79497c4f09620cbcec5e0252edf5d9d87fbcc16b1741480d8db91c")
    revision = read(EX / "protocols/audit_revision.json", "acb1409b7757f9f8bd5e4f2e26f11aabeedf4df67c2c99da3762659b67eac44e")
    for item in revision.values():
        if isinstance(item, dict) and set(item) == {"path", "sha256"}:
            bind(ROOT / item["path"], item["sha256"])
    for rel, expected in decision["bindings"].items():
        bind(ROOT / rel, expected)
    source = bind(EX / "src/strategy_runtime/strategies/followthrough_anchor.py", "a97a53b0d277ef4ee5702cc3b846ce8831fd8b182c2afca83159f31f0458f670")
    old_audit = bind(EX / "src/audit_accounts.py", "d97af4461b24ab3171c8e067abb9db9b848265f00f754f8e6334df2eeb8bc271")
    new_audit = bind(EX / "src/audit_accounts_v2.py", "ea8ed9add3ad66392bf9299ed09b98313d7421b3c0d2e2f156042e528974ecc4")
    old_runner = bind(EX / "src/run_accounts.py", "83090d4c8055a4b0b8a29408e007e9e6573665cf9fa67100b56ba3043a5288ba")
    new_runner = bind(EX / "src/run_accounts_v2.py", "cd32ae001d71e11ea4f2b5f95f298d6cdb75aff3a0e3181eec7ef250e5a54d93")
    old_functions, new_functions = functions(old_audit), functions(new_audit)
    for name in ("sign", "frozen_baseline", "divergence_dates"):
        check("Unchanged audit helper " + name, old_functions[name] == new_functions[name])
    old_funcs, new_funcs = functions(old_runner), functions(new_runner)
    for name in set(old_funcs) & set(new_funcs) - {"build", "validate_lock", "execute"}:
        check("Unchanged runner helper " + name, old_funcs[name] == new_funcs[name])
    check("Strategy source untouched", b"shock_anchor_close_RUNTIME_HFQ" in source)
    new_text = new_audit.decode()
    check("No assumed raw anchor lookup", 'row["shock_anchor_close_RUNTIME_HFQ"]' not in new_text and 'row["shock_anchor_ATR0_RUNTIME_HFQ"]' not in new_text)
    check("Original prepared-only source and empty provider", "prepared=prepared" in new_text and "ProviderConfig(bindings={})" in new_text and ".data.prepare(" not in new_text)
    check("Own first anchor and formally known prior ATR", "anchor_close = source[D]" in new_text and 'anchor_atr = row["atr20_prior"]' in new_text)
    check("Exact two scalar boundaries retained", "source[D] < anchor_close" in new_text and "(anchor_close - source[D]) >= anchor_atr" in new_text)
    check("Formal flags independently compared", 'bool(row["anchor_raw_condition"]) == raw' in new_text)
    runner_text = new_runner.decode()
    check("Explicit successor import and no redispatch control", "from audit_accounts_v2 import audit" in runner_text and "assert index in (1, 2)" in runner_text)
    check("New receipt binds revision", '"audit_revision_ref": read(EX / "protocols/published_audit_revision.json")' in runner_text)
    check("Parent chain and retained failure required", 'lock["parent_source_lock_sha256"]' in runner_text and 'independent["retained_original_inline_audit_failure"] is True' in runner_text)
    original = read(EX / "others/accounts/run-000.json", "586f2d48f37dad9be5bd7c7c3d637be16944446c55957667fe1d31dc511ec17e")
    supplement = read(EX / "others/control_supplement.json", "06c684d9a2afdb2780663eaead717b2942fe440c8f95cb0a1fe94aec8e27c85a")
    account = public(original["evidence"])
    parent = public(revision["parent_source_lock_ref"])
    check("Original failed inline receipt unmodified", original["status"] == "SUCCEEDED" and original["audit"] is None and original["exception"] == "KeyError('shock_anchor_close_RUNTIME_HFQ')")
    check("Same control source lock and result", original["execution_source_lock_sha256"] == revision["parent_source_lock_sha256"] and original["result_hash"] == account["result_hash"] == supplement["original_result_hash"])
    check("Same original control ref, no reevaluation", supplement["original_account_ref"] == original["evidence"] and supplement["new_account_dispatches"] == 0 and supplement["source_changed"] is False)
    check("Corrected supplement internal PASS", supplement["audit"]["status"] == "PASS" and supplement["audit"]["checks"] == 521468 and supplement["retained_original_inline_audit_failure"] is True)
    check("Control old economics/observation exact", supplement["audit"]["strict_control_against_EX050002"] and supplement["audit"]["first_original_state_divergence_D"] is None and supplement["audit"]["first_funded_state_E"] is None)
    check("No changed projection tolerance", supplement["audit"]["original_projection_numeric_tolerance"] == 0 and supplement["new_price_tolerance"] is False)
    check("Parent source identity", parent["source_hashes"]["src/strategy_runtime/strategies/followthrough_anchor.py"] == HASHES[(EX / "src/strategy_runtime/strategies/followthrough_anchor.py").relative_to(ROOT).as_posix()])
    independent = read(ROOT / revision["A_independent_control"]["path"], revision["A_independent_control"]["sha256"])
    check("A independent same original actual control PASS", independent["status"] == "PASS" and independent["account_ref"] == original["evidence"] and independent["result_hash"] == original["result_hash"] and independent["source_NOOP_exact_C9502"] is True)
    bind(Path(__file__).resolve())
    result = {
        "status": "PASS", "reviewer": "B", "blocking_findings": [],
        "reviewed_hashes": HASHES, "checks": len(CHECKS), "check_labels": CHECKS,
        "scope": "Minimal static auditor/runner successor difference and same-account supplement authentication; no source replay, raw market fetch, reevaluation or account dispatch by B.",
        "correction": "Reconstruct sourceClose using original authenticated PreparedDataRef; freeze Close at own first anchorD and published original priorATR at that D. Derived raw anchor is not a formally observed extra column. A independently recomputes original ATR and funded lifecycle.",
        "retained_failure": {"engine_status": "SUCCEEDED", "original_inline_audit": None, "original_exception": original["exception"], "original_receipt_sha256": HASHES[(EX / "others/accounts/run-000.json").relative_to(ROOT).as_posix()]},
        "control_account_ref": original["evidence"], "same_control_result_hash": original["result_hash"],
        "parent_source_lock_sha256": revision["parent_source_lock_sha256"],
        "remaining_release_gate": "Only publish explicit v2 parent/revision lock and recovery gate binding this review, A review, original failure and same-control supplement. Then only original treatments1/2 may dispatch. No fresh control or additional profile.",
        "economic_change": False, "source_changed": False, "new_funded_accounts": 0,
        "new_market_calls": 0, "new_prepared_fetches": 0, "new_fits": 0,
    }
    target = OUT / "review/audit_revision_review.json"
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"path": target.relative_to(ROOT).as_posix(), "sha256": sha256(target.read_bytes()).hexdigest(), "checks": len(CHECKS)}))


if __name__ == "__main__":
    main()
