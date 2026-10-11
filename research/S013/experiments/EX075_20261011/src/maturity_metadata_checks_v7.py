"""Artificial execution of the exact inline v7 maturity authentication block."""

import ast
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd


def run():
    work = Path(__file__).resolve().parent
    freeze = json.loads((work / "source_freeze_v6.json").read_text(encoding="utf-8"))
    assert all(
        sha256((work / name).read_bytes()).hexdigest() == digest
        for name, digest in freeze["source_files"].items()
    )
    source = (work / "authorized_driver_draft_v7.py").read_text(encoding="utf-8")
    body = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "preflight"
    ).body
    first = next(
        p
        for p, node in enumerate(body)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "parsed_old" for t in node.targets)
    )
    last = next(
        p
        for p in range(first + 1, len(body))
        if ast.unparse(body[p]).startswith("pd.testing.assert_series_equal(labels.label_end4")
    )
    compiled = compile(
        ast.Module(body=body[first : last + 1], type_ignores=[]), "inline_v7_maturity", "exec"
    )
    axis = pd.DatetimeIndex(["2020-01-02", "2020-01-03", "2020-01-06"], name="signal_date").as_unit(
        "ns"
    )
    new = pd.Series(pd.to_datetime(["2020-01-09", "2020-01-10", None]).as_unit("ns"), index=axis)
    checks = ["original58_exact"]
    for unit in ("ns", "us"):
        labels = pd.DataFrame({"label_end4": new}, index=axis)
        oldlabels = pd.DataFrame({"label_end_return_4": new.dt.as_unit(unit)}, index=axis)
        scope = {"pd": pd, "np": np, "labels": labels, "oldlabels": oldlabels}
        exec(compiled, scope)
        assert scope["originalunit"] == unit
        assert labels.label_end4.equals(new)
        assert str(oldlabels.label_end_return_4.dtype) == "datetime64[" + unit + "]"
    checks.append("exact_inline_ns_us_same_dates_and_NaT_roundtrip_no_mutation")
    refused = []
    wrong_day = new.dt.as_unit("us").copy()
    wrong_day.iloc[0] += pd.Timedelta(days=1)
    wrong_nat = new.dt.as_unit("us").copy()
    wrong_nat.iloc[0] = pd.NaT
    wrong_nat.iloc[2] = pd.Timestamp("2020-01-09")
    for name, bad in (("wrong_maturity_day", wrong_day), ("changed_NaT_position", wrong_nat)):
        scope = {
            "pd": pd,
            "np": np,
            "labels": pd.DataFrame({"label_end4": new}, index=axis),
            "oldlabels": pd.DataFrame({"label_end_return_4": bad}, index=axis),
        }
        try:
            exec(compiled, scope)
        except AssertionError:
            refused.append(name)
        else:
            raise AssertionError("maturity discrepancy not rejected")
    assert "check_dtype=False" not in source and "create_experiment" not in source
    assert 'float_format="%.17g"' in source
    assert "labels.label_end4" in ast.unparse(body[last])
    checks.append("only_old_series_metadata_canonicalization_original_output17digits_and_math")
    return dict(
        status="PASS",
        source_only=True,
        checks=checks,
        refusals=refused,
        actual_inputs_read=0,
        statistics_runs=0,
        accounts=0,
        provider_calls=0,
        source_sha256={
            name: sha256((work / name).read_bytes()).hexdigest()
            for name in ("authorized_driver_draft_v7.py", "maturity_metadata_checks_v7.py")
        },
        original_freeze_sha256=sha256((work / "source_freeze_v6.json").read_bytes()).hexdigest(),
    )


if __name__ == "__main__":
    result = run()
    with (
        Path(__file__)
        .with_name("maturity_metadata_checks_v7.json")
        .open("x", encoding="utf-8") as out
    ):
        json.dump(result, out, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(result, ensure_ascii=False))
