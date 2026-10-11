"""Pure source/projection and isolated authorization-denial checks."""

import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path


def check():
    here = Path(__file__).resolve().parent

    def read(name):
        return json.loads((here / name).read_text(encoding="utf-8"))

    oldfreeze = read("source_freeze.json")
    assert len(oldfreeze["source_files"]) == 26
    assert all(
        sha256((here / n).read_bytes()).hexdigest() == h
        for n, h in oldfreeze["source_files"].items()
    )
    assert (
        sha256((here / "source_freeze.json").read_bytes()).hexdigest()
        == "264d512fb41adedfd4946981e42f46a401ff1dd4dffa57c7ea126dfb34f5f87f"
    )
    checks = ["all_original26_and_originalfreeze_exact_unchanged"]

    old, new, history = (
        read("draft_plan_v4.json"),
        read("draft_plan_v5.json"),
        read("known_history_v5.json"),
    )
    for key in (
        "component",
        "nuisance_controls",
        "controls",
        "control_n",
        "labels",
        "future_fixed_statistics",
        "scientific_reading_rules",
        "stop",
        "budget",
        "input_references",
        "predecessors",
    ):
        assert old[key] == new[key], key
    assert new["known_public_references"] == history["public_summary_references"]
    assert history["EX074_root_classification"] == "INEFFECTIVE_FOR_ABSOLUTE_ROBUSTNESS"
    assert (
        history["center_qualification_preserved"] and history["not_preferred_as_robust_improvement"]
    )
    assert not history["objective_achieved"]
    assert not history["comparison"]["paired_geometry"]
    assert (
        history["comparison"]["baseline_dimensions"] == 13
        and history["comparison"]["new_dimensions"] == 15
    )
    b, n = (history["rows"][k] for k in ("B0", "N_PRESSURE_EARLY_EXIT"))
    assert n["center"]["qualified"] and n["center"]["net_cagr"] < b["center"]["net_cagr"]
    assert n["center"]["full_drawdown"] > b["center"]["full_drawdown"]
    assert n["q10_cagr"] < b["q10_cagr"] and n["q90_full_drawdown"] > b["q90_full_drawdown"]
    assert list(n["gate_pass_counts"].values()) == [5, 24, 30, 4]
    assert list(b["gate_pass_counts"].values()) == [7, 32, 27, 2]
    assert n["joint_count"] == 1 and b["joint_count"] == 0
    assert history["integer_coverage"]["pressure_exit.lookback"] == {"4": 32}
    assert n["double_fee_2023_return"] < 0 and not n["double_fee"]["qualified"]
    assert (
        history["EX073_previous_limited_judgment"]["component_status"]
        == "LIMITED_SUPPORT_FOR_FIXED_HOLDING_TEST"
    )
    assert history["budget"]["authorized_public_summaries"] == 3
    assert all(v == 0 for k, v in history["budget"].items() if k != "authorized_public_summaries")
    checks.append(
        "fixed_method_unchanged_public_history_negative_and_limited_facts_no_reverse_no_P21_selection"
    )

    original = (here / "authorized_driver_draft.py").read_text(encoding="utf-8")
    expected = (
        original.replace("source_freeze.json", "source_freeze_v2.json")
        .replace("draft_plan_v4.json", "draft_plan_v5.json")
        .replace("_authorization.json", "_authorization_v2.json")
    )
    source = here / "authorized_driver_draft_v2.py"
    assert ast.dump(ast.parse(source.read_text(encoding="utf-8"))) == ast.dump(ast.parse(expected))
    checks.append("new_driver_only_plan_freeze_phase_authority_filename_changes")

    text_method, bytes_method = Path.read_text, Path.read_bytes

    def forbidden(*args, **kwargs):
        raise AssertionError("no input or platform action allowed in import/guard test")

    Path.read_text, Path.read_bytes = forbidden, forbidden
    try:
        spec = importlib.util.spec_from_file_location("standby_volume_driver_v2_artificial", source)
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)
    finally:
        Path.read_text, Path.read_bytes = text_method, bytes_method
    actual_authority = driver.authority

    def isolated_denial(phase):
        return actual_authority(phase, here=here / "synthetic_no_authority_v5")

    driver.authority, driver.original_common = isolated_denial, forbidden
    for phase in ("declare", "preflight", "statistics"):
        try:
            getattr(driver, phase)()
        except FileNotFoundError as error:
            assert "root_" + phase + "_authorization_v2.json" in str(error)
        else:
            raise AssertionError("newphase must stop before platform/data: " + phase)
    checks.append("pure_import_and_three_isolated_new_v2_phase_denials_before_platform")
    return {
        "status": "PASS_SOURCE_ONLY_NO_REAL_PHASE",
        "checks": checks,
        "source_sha256": {
            n: sha256((here / n).read_bytes()).hexdigest()
            for n in (
                "known_history_writer_v5.py",
                "authorized_driver_draft_v2.py",
                "history_guard_checks_v5.py",
            )
        },
        "projection_sha256": {
            n: sha256((here / n).read_bytes()).hexdigest()
            for n in ("known_history_v5.json", "draft_plan_v5.json")
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
