"""Source/authority schema checks only; no real input or statistics reads."""

import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import actual_verification_wrapper as wrapper


def run():
    work = Path(__file__).resolve().parent
    bindings = {
        name: "a" * 64
        for name in (
            "wrapper_freeze_sha256",
            "independent_freeze_sha256",
            "input_references_sha256",
            "result_references_sha256",
            "statistics_authority_sha256",
            "preflight_freeze_sha256",
        )
    }
    authority = dict(
        status="APPROVED", phase="verification", expected_experiment_id="EX075_20261011", **bindings
    )
    wrapper.require_contract(authority, bindings)
    checks = ["exact_new_verification_authority_schema_acceptance"]
    refused = []
    cases = [
        ("no_approval", {**authority, "status": "PENDING"}),
        ("wrong_phase", {**authority, "phase": "statistics"}),
        ("wrong_experiment", {**authority, "expected_experiment_id": "EX074_20261011"}),
    ]
    cases += [("wrong_" + name, {**authority, name: "b" * 64}) for name in bindings]
    for name, bad in cases:
        try:
            wrapper.require_contract(bad, bindings)
        except PermissionError:
            refused.append(name)
        else:
            raise AssertionError("missing exact authority refusal: " + name)
    # The actual authority entrypoint must stop on missing NEW root file.
    assert not (work / "root_verification_authorization.json").exists()
    try:
        wrapper.authority()
    except FileNotFoundError:
        refused.append("missing_new_root_verification_authority")
    else:
        raise AssertionError("no actual authority exists during pure preparation")
    source = (work / "actual_verification_wrapper.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    for node in imports:
        name = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
        assert name.split(".")[0] in {"datetime", "hashlib", "importlib", "json", "pathlib", "sys"}
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "verify")
    body = [ast.unparse(n) for n in function.body]
    attempt = next(
        p
        for p, text in enumerate(body)
        if text.startswith("write_new(work / 'verification_attempt.json'")
    )
    cache = next(p for p, text in enumerate(body) if "common.cache_read" in text)
    assert attempt < cache
    assert "checker.verify_statistics" in source
    assert "statistics_draft_v2" not in source or "source_files" in source
    assert "create_experiment" not in source and "ctx.data.fetch" not in source
    assert "serialize_evaluation_evidence(bound, cached)" in source
    checks.append(
        "attempt_before_inputs_exact_public_cache_bindings_one_checker_no_account_or_provider"
    )
    spec = importlib.util.spec_from_file_location(
        "synthetic_wrapper_pure_import", work / "actual_verification_wrapper.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checks.append("pure_import_standardlibs_only_no_actual_phase")
    for filename in ("source_freeze_v7.json", "independent_verification_source_freeze.json"):
        frozen = json.loads((work / filename).read_text(encoding="utf-8"))
        assert all(
            sha256((work / name).read_bytes()).hexdigest() == digest
            for name, digest in frozen["source_files"].items()
        )
    checks.append("original64_and_independent5_source_sha_unchanged")
    return dict(
        status="PASS",
        source_only=True,
        checks=checks,
        refusals=refused,
        actual_inputs_read=0,
        actual_statistics_runs=0,
        accounts=0,
        provider_calls=0,
        source_sha256={
            name: sha256((work / name).read_bytes()).hexdigest()
            for name in ("actual_verification_wrapper.py", "actual_verification_guard_checks.py")
        },
    )


if __name__ == "__main__":
    result = run()
    with (
        Path(__file__)
        .with_name("actual_verification_guard_checks.json")
        .open("x", encoding="utf-8") as f
    ):
        json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(result, ensure_ascii=False))
