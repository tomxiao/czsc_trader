"""Source-only declaration metadata expression and isolated guard checks."""

import ast
import copy
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


def check():
    here = Path(__file__).resolve().parent
    oldfreeze = json.loads((here / "source_freeze_v2.json").read_text(encoding="utf-8"))
    assert len(oldfreeze["source_files"]) == 33
    assert all(
        sha256((here / n).read_bytes()).hexdigest() == h
        for n, h in oldfreeze["source_files"].items()
    )
    assert (
        sha256((here / "source_freeze_v2.json").read_bytes()).hexdigest()
        == "08d57bec52b816e904bf448538b3563b3a54ab8510e1d02e14860b9d83f8222d"
    )
    checks = ["prior33_files_and_freeze_exact_unchanged"]
    old = (here / "authorized_driver_draft_v2.py").read_text(encoding="utf-8")
    expected = old.replace("source_freeze_v2.json", "source_freeze_v3.json").replace(
        "_authorization_v2.json", "_authorization_v3.json"
    )
    marker = '        **read(work / "draft_plan_v5.json"),'
    assert expected.count(marker) == 1
    expected = expected.replace(
        marker,
        marker
        + '\n        "prior_draft_status": read(work / "draft_plan_v5.json")["status"],\n        "status": "PROSPECTIVELY_DECLARED_ZERO_ACCOUNTS_AWAITING_INPUT_AUTHENTICATION",',
    )
    source = here / "authorized_driver_draft_v3.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    assert ast.dump(tree) == ast.dump(ast.parse(expected))
    checks.append("driver_changes_only_two_metadata_keys_and_v3_freeze_authority_filenames")

    declare_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "declare"
    )
    assignment = next(
        node
        for node in declare_node.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "plan" for t in node.targets)
    )
    assert isinstance(assignment.value, ast.Dict)
    draft = {
        "status": "STANDBY_SOURCE_ONLY_NOT_DECLARED_NOT_AUTHORIZED_TO_RUN",
        "component": {"name": "synthetic-fixed-component"},
        "controls": ["unchanged"],
        "other": {"value": 42},
    }
    before = copy.deepcopy(draft)

    def artificial_read(path):
        assert path.name == "draft_plan_v5.json"
        return draft

    namespace = {
        "__builtins__": {},
        "read": artificial_read,
        "work": Path("artificial_only"),
        "exp": SimpleNamespace(to_dict=lambda: {"experiment_id": "EX075_20261011"}),
        "freeze": {"source_files": {"artificial.py": "synthetic"}},
        "datetime": datetime,
        "timezone": timezone,
        "digest": lambda path: "artificial_freeze_hash",
    }
    # Evaluate ONLY the already asserted plan dictionary assignment with stubs.
    isolated = ast.Module(body=[assignment], type_ignores=[])
    exec(compile(isolated, "artificial-plan-expression-only", "exec"), namespace)
    result = namespace["plan"]
    assert draft == before
    assert result["prior_draft_status"] == before["status"]
    assert result["status"] == "PROSPECTIVELY_DECLARED_ZERO_ACCOUNTS_AWAITING_INPUT_AUTHENTICATION"
    assert not result["statistics_authorized"]
    assert (
        result["component"] == before["component"]
        and result["controls"] == before["controls"]
        and result["other"] == before["other"]
    )
    checks.append(
        "plan_expression_preserves_prior_draft_status_overrides_current_status_without_method_mutation"
    )

    text_method, bytes_method = Path.read_text, Path.read_bytes

    def forbidden(*args, **kwargs):
        raise AssertionError("no real input/platform action permitted")

    Path.read_text, Path.read_bytes = forbidden, forbidden
    try:
        spec = importlib.util.spec_from_file_location("standby_volume_driver_v3_artificial", source)
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)
    finally:
        Path.read_text, Path.read_bytes = text_method, bytes_method
    original_authority = driver.authority

    def isolated_denial(phase):
        return original_authority(phase, here=here / "synthetic_no_authority_driver_v3")

    driver.authority, driver.original_common = isolated_denial, forbidden
    for phase in ("declare", "preflight", "statistics"):
        try:
            getattr(driver, phase)()
        except FileNotFoundError as error:
            assert "root_" + phase + "_authorization_v3.json" in str(error)
        else:
            raise AssertionError("phase did not require distinct new authorization")
    checks.append("pure_import_three_new_v3_phase_guards_refuse_before_platform")
    return {
        "status": "PASS_SOURCE_ONLY_NO_REAL_PHASE",
        "checks": checks,
        "source_sha256": {
            n: sha256((here / n).read_bytes()).hexdigest()
            for n in ("authorized_driver_draft_v3.py", "declaration_status_checks_v3.py")
        },
        "real_input_reads": 0,
        "statistics": 0,
        "signals": 0,
        "accounts": 0,
        "allocate": 0,
        "publish": 0,
        "DEV": 0,
    }


if __name__ == "__main__":
    proof = check()
    with Path(__file__).with_suffix(".json").open("x", encoding="utf-8") as f:
        json.dump(proof, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(proof, ensure_ascii=False))
