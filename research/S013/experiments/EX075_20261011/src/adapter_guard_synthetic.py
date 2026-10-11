"""Only artificial in-memory frames and source-import/denial checks."""

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

import input_adapter_draft as adapter
import statistics_draft_v2 as statistics
from component_draft import CLOCKS


def check():
    rng = np.random.default_rng(75)
    calendar = pd.bdate_range("2020-01-02", "2026-09-30").as_unit("ns")
    signals = calendar[:1635].rename("signal_date")
    bar_index = pd.DatetimeIndex(
        np.repeat(calendar.to_numpy(), 8)
        + np.tile(pd.to_timedelta([t + ":00" for t in CLOCKS]).to_numpy(), len(calendar))
    )
    opens = np.full(len(bar_index), 100.0)
    closes = opens * np.exp(rng.normal(0, 0.001, len(bar_index)))
    bars = pd.DataFrame(
        {
            "Open": opens,
            "Close": closes,
            "Volume": rng.integers(100, 1000, len(bar_index)).astype(float),
        },
        index=bar_index,
    )
    prices = pd.DataFrame(
        {
            "Open": 100 * np.exp(rng.normal(0, 0.005, len(calendar))),
            "Close": 100 * np.exp(rng.normal(0, 0.005, len(calendar))),
        },
        index=calendar,
    )
    public = prices.copy()
    warm_calendar = pd.bdate_range("2019-04-10", "2026-09-30").as_unit("ns")
    warm = pd.DataFrame({"Open": 28.03, "Close": 28.03}, index=warm_calendar)
    warm.loc[calendar] = prices * 0.2803
    tail = adapter.original_tail(bars).reindex(signals)
    old = pd.DataFrame(rng.normal(size=(1635, 14)), index=signals, columns=statistics.CONTROLS[:14])
    old66 = old.join(
        pd.DataFrame(
            {
                "late_weakness": -tail.late_recovery,
                "early_reclaim_weakness": -tail.early_volume_reclaim,
            },
            index=signals,
        )
    )
    old69 = old.join(tail)
    values = (
        old66,
        old69,
        public,
        warm,
        bars,
        prices,
        calendar,
        {"basis": "HFQ_RESEARCH", "anchor_factor": 0.2803},
        "C8880",
        "510500.SH",
    )
    features, labels, obs, profile, checks = adapter.construct(*values)
    assert checks["independent_checks"] == 1635 and checks["accounts"] == 0
    assert tuple(features.columns) == (*statistics.CONTROLS, statistics.COMPONENT)
    assert len(labels) == 1635 and labels.label_end4.iloc[-1] == calendar[1639]
    assert (
        profile.iloc[:20].isna().all().all()
        and features.past_volume_shape_projection.iloc[:20].isna().all()
    )
    assert obs.profile_available.iloc[20:].all()
    checks_list = [
        "artificial_fullgrid_old14_oldpair_inverse_exact_HFQanchor_calendar_complete_profile_and_independent_labels"
    ]
    refusals = []
    for name, position, replacement in (
        ("other_asset", 9, "159326.SZ"),
        ("other_candidate", 8, "C2132"),
        ("other_anchor", 7, {"basis": "HFQ_RESEARCH", "anchor_factor": 1.0}),
        ("bar_missing", 4, bars.iloc[1:]),
        ("calendar_mismatch", 6, calendar[1:]),
        ("insufficient_original_axis", 0, old66.iloc[1:]),
    ):
        changed = list(values)
        changed[position] = replacement
        try:
            adapter.construct(*changed)
        except (ValueError, AssertionError):
            refusals.append(name)
        else:
            raise AssertionError("missing refusal " + name)
    badold = old69.copy()
    badold.iloc[100, 0] += 1
    try:
        adapter.construct(old66, badold, *values[2:])
    except AssertionError:
        refusals.append("oldcontrol_mismatch")
    else:
        raise AssertionError("oldcontrols mismatch not refused")

    source = Path(__file__).with_name("authorized_driver_draft.py")
    before_read, before_bytes = Path.read_text, Path.read_bytes

    def forbidden(*args, **kwargs):
        raise AssertionError("import unexpectedly read an input")

    Path.read_text, Path.read_bytes = forbidden, forbidden
    try:
        spec = importlib.util.spec_from_file_location("standby_guard_artificial", source)
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)
    finally:
        Path.read_text, Path.read_bytes = before_read, before_bytes
    original_authority = driver.authority

    def denied_artificial_authority(phase):
        return original_authority(phase, here=Path(__file__).parent / "synthetic_no_authority")

    driver.authority = denied_artificial_authority
    driver.original_common = forbidden
    for phase in ("declare", "preflight", "statistics"):
        try:
            getattr(driver, phase)()
        except FileNotFoundError as error:
            assert "root_" + phase + "_authorization.json" in str(error)
        else:
            raise AssertionError("missing NEWroot authority did not stop " + phase)
    checks_list.append(
        "import_no_input_reads_three_new_phase_authorities_deny_before_platform_or_allocation"
    )
    synthetic_bindings = {}
    for key, exp in (
        ("native_ref", "EX058_20261011"),
        ("old66_features", "EX066_20261011"),
        ("old66_labels", "EX066_20261011"),
        ("old69_features", "EX069_20261011"),
        ("warm69_prices", "EX069_20261011"),
        ("native73_prices", "EX073_20261011"),
    ):
        synthetic_bindings[key] = {
            "type": "EvidenceRef",
            "experiment": {"type": "ExperimentRef", "strategy_id": "S013", "experiment_id": exp},
            "sha256": "a" * 64,
            "evidence_id": "a" * 64 + (".json" if key == "native_ref" else ".csv"),
            "media_type": "application/json" if key == "native_ref" else "text/csv",
            "schema": "account_evaluation" if key == "native_ref" else None,
            "schema_version": 6 if key == "native_ref" else None,
        }
    assert driver.binding_schema(synthetic_bindings)
    for field, replacement in (
        (
            "experiment",
            {"type": "ExperimentRef", "strategy_id": "S014", "experiment_id": "EX069_20261011"},
        ),
        ("sha256", "malformed"),
        ("media_type", "application/json"),
        ("evidence_id", "elsewhere.csv"),
    ):
        fake = copy.deepcopy(synthetic_bindings)
        fake["old69_features"][field] = replacement
        try:
            driver.binding_schema(fake)
        except ValueError:
            refusals.append("binding_schema_" + field)
        else:
            raise AssertionError("malformed binding allowed")
    checks_list.append("pure_metadata_schema_fixed_S013_source_refs_native_v6_sha_media_no_resolve")

    tree = ast.parse(source.read_text(encoding="utf-8"))
    calls = []
    for node in tree.body:
        if isinstance(node, ast.If):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Expr)):
            continue
        calls.extend(n for n in ast.walk(node) if isinstance(n, ast.Call))
    assert not calls
    text = source.read_text(encoding="utf-8")
    assert "prepared=ed.prepared" in text and "common.context(1)" in text
    assert "allocation_attempt.json" in text and 'exp.experiment_id != "EX075_20261011"' in text
    checks_list.append(
        "ast_no_import_execution_prepared_only_no_provider_one_allocation_wrongid_stop"
    )
    sources = ["input_adapter_draft.py", "authorized_driver_draft.py", Path(__file__).name]
    return {
        "status": "PASS_ARTIFICIAL_INPUTS_AND_NO_AUTHORIZATION_DENIAL_ONLY",
        "checks": checks_list,
        "refusals": refusals,
        "source_sha256": {
            n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in sources
        },
        "real_data_reads": 0,
        "real_statistics": 0,
        "signals": 0,
        "accounts": 0,
        "allocate": 0,
        "publish": 0,
        "DEV": 0,
    }


if __name__ == "__main__":
    proof = check()
    Path(__file__).with_suffix(".json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(proof, ensure_ascii=False))
