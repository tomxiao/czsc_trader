"""One independent input/statistic verification of the existing EX078 outputs."""

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import pandas as pd
from czsc_trader.research_tools.context import ExperimentRef

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
WORK = ROOT / ".tmp/s013-vol-concentration-result"
AUDIT = ROOT / ".tmp/s013-vol-concentration-audit"
spec = importlib.util.spec_from_file_location(
    "s013_vol_root_driver", ROOT / ".tmp/s013_vol_research.py"
)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


plan = driver.read(WORK / "plan.json")
driver.check(plan)
freeze = driver.read(AUDIT / "freeze.json")
proof = driver.read(AUDIT / "synthetic.json")
if proof["status"] != "PASS" or proof["real_inputs"] != 0 or proof["new_accounts"] != 0:
    raise ValueError("Source-only independent synthetic PASS required")
if (
    sha256((AUDIT / "freeze.json").read_bytes()).hexdigest()
    != "118b9e339c4436066881255b604bf994373190acd5423e240e45ef6ab3f066eb"
):
    raise ValueError("Exact frozen independent source identity required")
for name, expected in freeze["files"].items():
    if sha256((AUDIT / name).read_bytes()).hexdigest() != expected:
        raise ValueError("Independent audit source drift")
for name, expected in proof["production_sources"].items():
    if sha256((driver.WORK / name).read_bytes()).hexdigest() != expected:
        raise ValueError("Synthetic main source drift")
exp = ExperimentRef.from_dict(plan["experiment"])
protocols = exp.resolve(ROOT) / "protocols"
refs = driver.read(protocols / "result_references.json")
for name, ref in refs.items():
    if (WORK / name).read_bytes() != driver.public(ref).read_bytes():
        raise ValueError("Original actual result output drift")
driver.write(
    WORK / "audit_attempt.json",
    {
        "status": "STARTED",
        "new_accounts": 0,
        "new_main_statistics": 0,
        "audit_source_sha256": sha256((AUDIT / "audit.py").read_bytes()).hexdigest(),
    },
)
bound, result = driver.common.cache_read(ROOT / ".tmp/s013-mechanism-EX058/N0.pkl.gz")
if driver.serialize_evaluation_evidence(bound, result) != driver.read(
    driver.public(plan["input_references"]["native"])
):
    raise ValueError("Original native serialization mismatch")
old = driver.frame(driver.public(plan["input_references"]["old_features"]))
warm = driver.frame(driver.public(plan["input_references"]["warm_prices"]))
features, labels, scopes, state, prices = [
    driver.frame(WORK / name)
    for name in ("features.csv", "labels.csv", "scopes.csv", "known_state.csv", "prices.csv")
]
native_prices = bound.execution_data.execution_daily.set_index("dt")[["open", "close"]].rename(
    columns={"open": "Open", "close": "Close"}
)
native_prices.index = pd.to_datetime(native_prices.index).as_unit("ns")
native_prices.attrs = {}
pd.testing.assert_frame_equal(prices, native_prices, check_exact=True, check_names=False)
for name in labels:
    if name.startswith("label_end_"):
        labels[name] = pd.to_datetime(labels[name], errors="raise").dt.as_unit("ns")
state["entry_session"] = pd.to_datetime(state["entry_session"], errors="raise").dt.as_unit("ns")
audit = load("s013_vol_independent_audit", AUDIT / "audit.py")
execution = result.runs[0].execution
inputs = audit.verify_inputs(
    old,
    warm.Close,
    prices,
    execution.account_daily,
    execution.fills,
    execution.decisions,
    dict(features=features, labels=labels, scope=scopes, state=state),
)
statistics = audit.verify_statistics(
    features, labels, scopes, driver.read(WORK / "statistics.json")
)
if driver.common.SOURCE_CALLS:
    raise ValueError("Provider invocation forbidden")
verification = {
    "status": "PASS",
    "input_audit": inputs,
    "statistics_audit": statistics,
    "native_exact": True,
    "component_table": "independent direct-loop formula compared to original actual feature columns; no additional main component calculation; scopes/labels/state independently rebuilt from original native pair",
    "source_freeze": freeze,
    "source_proof": proof,
    "actual_evidence_references": refs,
    "input_references": plan["input_references"],
    "new_accounts": 0,
    "new_main_statistics": 0,
    "provider_calls": 0,
}
driver.write(WORK / "verification.json", verification)
ctx = driver.common.context(1)
audit_refs = {"verification.json": driver.put(ctx, exp, WORK / "verification.json")}
for name in ("audit.py", "synthetic.py", "synthetic.json", "freeze.json"):
    audit_refs["audit_" + name] = driver.put(ctx, exp, AUDIT / name)
for path in (Path(__file__), ROOT / ".tmp/s013_vol_plan.py"):
    audit_refs[path.name] = driver.put(ctx, exp, path)
    (exp.resolve(ROOT) / "src" / path.name).write_bytes(path.read_bytes())
for name in ("audit.py", "synthetic.py"):
    (exp.resolve(ROOT) / "src" / ("independent_" + name)).write_bytes((AUDIT / name).read_bytes())
driver.write(protocols / "audit_references.json", audit_refs)
print(
    json.dumps(
        {
            "status": "PASS",
            "input_audit": inputs,
            "statistics_audit": statistics,
            "new_accounts": 0,
        },
        ensure_ascii=False,
    ),
    flush=True,
)
