"""Only artificial prepared-frame schema and source/guard checks."""

import ast
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

import authorized_driver_draft_v5 as driver
from prepared_schema_v5 import MAPPING, numerical


def run():
    work = Path(__file__).resolve().parent
    original = json.loads((work / "source_freeze_v4.json").read_text(encoding="utf-8"))
    assert all(
        sha256((work / name).read_bytes()).hexdigest() == digest
        for name, digest in original["source_files"].items()
    )
    checks = ["original44_source_and_v4_plan_unmodified"]
    frame = pd.DataFrame(
        {
            "Date": ["2020-01-02", "2020-01-03"],
            "Open": ["100", "101"],
            "High": [102, 103],
            "Low": [99, 100],
            "Close": [101, 102],
            "Volume": [1000, 1100],
            "Amount": [100000, 110000],
        }
    )
    frame.attrs["not_pricing_input"] = "artificial"
    actual = numerical(frame)
    assert list(actual.columns) == list(MAPPING.values())
    assert str(actual.dt.dtype) == "datetime64[ns]" and not actual.attrs
    for old, new in MAPPING.items():
        if old != "Date":
            np.testing.assert_array_equal(actual[new].to_numpy(float), pd.to_numeric(frame[old]))
    assert "Date" in frame and frame.attrs
    checks.append("exact7_column_mapping_ns_six_numeric_no_input_mutation")
    bars = frame.copy()
    bars.Date = ["2020-01-02 10:00:00", "2020-01-02 10:30:00"]
    assert numerical(bars).dt.dt.strftime("%H:%M").tolist() == ["10:00", "10:30"]
    checks.append("daily_and_intraday_same_explicit_raw_contract_clock_preserved")
    refused = []
    for name, bad in (
        ("already_lowercase_dt", frame.rename(columns=MAPPING)),
        ("missing_Amount", frame.drop(columns="Amount")),
        ("mixed_dt", frame.assign(dt=frame.Date)),
        ("duplicate_Open", pd.concat([frame, frame[["Open"]]], axis=1)),
        ("nonnumeric_Volume", frame.assign(Volume=["bad", "1"])),
        ("bad_Date", frame.assign(Date=["bad", "2020-01-03"])),
        ("missing_Date", frame.assign(Date=[None, "2020-01-03"])),
        ("timezone_Date", frame.assign(Date=pd.date_range("2020-01-02", periods=2, tz="UTC"))),
        ("infinite_Amount", frame.assign(Amount=[np.inf, 1])),
    ):
        try:
            numerical(bad)
        except (ValueError, TypeError):
            refused.append(name)
        else:
            raise AssertionError("missing schema refusal: " + name)
    for phase in ("declare", "statistics"):
        try:
            driver.authority(phase)
        except ValueError:
            refused.append("v5_no_" + phase)
        else:
            raise AssertionError("v5 forbidden phase accepted")
    try:
        driver.authority("preflight")
    except FileNotFoundError:
        refused.append("missing_NEW_root_preflight_v5_authority")
    else:
        raise AssertionError("synthetic stage must not already have live v5 authority")
    tree = ast.parse((work / "authorized_driver_draft_v5.py").read_text(encoding="utf-8"))
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert "declare" not in functions and "statistics" not in functions
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "create_experiment" not in calls
    checks.append("v5_no_allocate_or_statistics_entrypoint_separate_guard_failure_chain")
    return dict(
        status="PASS",
        source_only=True,
        checks=checks,
        refusals=refused,
        real_input_reads=0,
        statistics_runs=0,
        accounts=0,
        publications=0,
        source_sha256={
            name: sha256((work / name).read_bytes()).hexdigest()
            for name in (
                "authorized_driver_draft_v5.py",
                "prepared_schema_v5.py",
                "prepared_schema_checks_v5.py",
            )
        },
        original_freeze_sha256=sha256((work / "source_freeze_v4.json").read_bytes()).hexdigest(),
    )


if __name__ == "__main__":
    result = run()
    with (
        Path(__file__)
        .with_name("prepared_schema_checks_v5.json")
        .open("x", encoding="utf-8") as out
    ):
        json.dump(result, out, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(result, ensure_ascii=False))
