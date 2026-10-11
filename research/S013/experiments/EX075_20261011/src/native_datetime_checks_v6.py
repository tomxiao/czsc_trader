"""Artificial timestamp metadata audit; no cached data or real input reads."""

from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from native_datetime_exact_v6 import assert_native_exact


def run():
    work = Path(__file__).resolve().parent
    freeze = json.loads((work / "source_freeze_v5.json").read_text(encoding="utf-8"))
    assert all(
        sha256((work / name).read_bytes()).hexdigest() == digest
        for name, digest in freeze["source_files"].items()
    )
    ns = pd.DataFrame(
        {
            "dt": pd.to_datetime(["2020-01-02 10:00:00", "2020-01-02 10:30:00"]).as_unit("ns"),
            "open": [100.0, 101.0],
            "close": [101.0, 102.0],
            "vol": [1000.0, 1100.0],
        },
        index=pd.Index([7, 8], name="original"),
    )
    us = ns.copy()
    us.dt = us.dt.dt.as_unit("us")
    proof = assert_native_exact(ns, us)
    assert proof["left"]["original_unit"] == "ns"
    assert proof["right"]["original_unit"] == "us"
    assert str(ns.dt.dtype) == "datetime64[ns]"
    assert str(us.dt.dtype) == "datetime64[us]"
    checks = [
        "prior51_exact",
        "same_timestamps_us_ns_lossless_roundtrip_fullframe_exact_inputs_unchanged",
    ]
    refused = []
    altered_time = us.copy()
    altered_time.loc[7, "dt"] += pd.Timedelta(microseconds=1)
    altered_price = us.copy()
    altered_price.loc[7, "open"] += 0.0000000001
    altered_volume = us.copy()
    altered_volume.loc[7, "vol"] += 1
    for name, bad in (
        ("one_us_timestamp_difference", altered_time),
        ("price_difference", altered_price),
        ("volume_difference", altered_volume),
        ("row_order", us.iloc[::-1]),
        ("missing_schema", us.drop(columns="dt")),
        ("column_order", us[["close", "dt", "open", "vol"]]),
        ("numeric_dtype", us.astype({"vol": "int64"})),
        ("index_name", us.rename_axis("changed")),
    ):
        try:
            assert_native_exact(ns, bad)
        except (ValueError, AssertionError):
            refused.append(name)
        else:
            raise AssertionError("expected exact refusal: " + name)
    text = (work / "authorized_driver_draft_v6.py").read_text(encoding="utf-8")
    assert "check_dtype=False" not in text and "create_experiment" not in text
    assert "%.17g" in text and "import input_adapter_draft_v2 as adapter" in text
    assert "from prepared_schema_v5 import numerical" in text
    assert "native_datetime_checks = assert_native_exact(left, right)" in text
    checks.append(
        "only_dt_precision_canonicalization_original_adapter_numeric_exact_and17digits_preserved"
    )
    return dict(
        status="PASS",
        source_only=True,
        checks=checks,
        refusals=refused,
        actual_inputs_read=0,
        statistics_runs=0,
        accounts=0,
        provider_calls=0,
        timestamp_proof=proof,
        source_sha256={
            name: sha256((work / name).read_bytes()).hexdigest()
            for name in (
                "authorized_driver_draft_v6.py",
                "native_datetime_exact_v6.py",
                "native_datetime_checks_v6.py",
            )
        },
        original_freeze_sha256=sha256((work / "source_freeze_v5.json").read_bytes()).hexdigest(),
    )


if __name__ == "__main__":
    result = run()
    with (
        Path(__file__)
        .with_name("native_datetime_checks_v6.json")
        .open("x", encoding="utf-8") as out
    ):
        json.dump(result, out, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(result, ensure_ascii=False))
