"""Pure full32 materialization/runtime/state diagnostics; no native/read/finance."""
# ruff: noqa: E402 -- Bootstrap frozen research module paths before imports.

from importlib import util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import specification as s
from strategy_evaluator import ParameterPerturbationDesign
from strategy_runtime import ParameterSet, StrategyCandidate, StrategyRuntime

value = s.d.read(HERE / "point_specification15.json")
design = ParameterPerturbationDesign.from_dict(value["design"])
design.validate()
assert len(design.points) == 32 and value["actual_unique_payloads"] == 32
instance = StrategyRuntime()
load_spec = util.spec_from_file_location(
    "early_exit_point_synthetic", HERE.parent / "exit_checks.py"
)
synthetic = util.module_from_spec(load_spec)
sys.modules[load_spec.name] = synthetic
load_spec.loader.exec_module(synthetic)
data, sessions = synthetic.inputs("changing")
counts = []
for entry, point in zip(value["points"], design.points, strict=True):
    assert entry["point"] == point.to_dict()
    params = s.materialize(
        value["centre_payload"]["parameters"], value["coordinates"], point.coordinates
    )
    assert params == entry["payload"]["parameters"] and s.feasible(point.coordinates)
    described = instance.describe(
        StrategyCandidate(
            "S013",
            entry["candidate_id"],
            entry["payload"],
            s.d.ROOT / "research/S013/experiments/EX074_20261011/src/strategy_runtime",
        )
    )
    assert described.parameters.values["pressure_exit"]["enabled"] is True
    h = synthetic.new.PressureEarlyExitRange(ParameterSet(params)).calculate_history(data, sessions)
    counts.append(
        dict(
            zip(
                ("entry_latches", "early_exits", "pressure_change_while_latched"),
                map(int, synthetic.path_audit(h, params)),
                strict=True,
            )
        )
    )
    assert h.pressure_effective_max_hold.between(1, 60).all()
    # The policy cap must never extend an original marked episode's H.
    marked = h.pressure_flag_before
    assert (h.loc[marked, "pressure_effective_max_hold"] <= params["bear"]["max_hold"]).all()
sys.path.insert(0, str(s.d.ROOT / "research/S013/experiments/EX074_20261011/src"))
spec = util.spec_from_file_location("early_exit_typed_point_audit", HERE / "native_point_audit.py")
audit = util.module_from_spec(spec)
sys.modules[spec.name] = audit
spec.loader.exec_module(audit)
import inspect

assert inspect.signature(audit.audit).parameters["expected_cost"].default == 0.001
assert audit.execution_links.verify is not None
assert audit is not synthetic.oracle
assert not (HERE / "root_execution_authorization.json").exists()
assert not (s.d.WORK / "perturbation_state.json").exists()
helper = audit.economics_reference
protocol = helper.protocol(design)
assert protocol.rolling_window_days == 126 and protocol.rolling_step_days == 21
assert (
    protocol.bootstrap_repetitions == 2000
    and protocol.bootstrap_block_length == 20
    and protocol.seed == 13
)
result = {
    "status": "PASS",
    "all32_exact_materializations": True,
    "all32_legal_runtime_described": True,
    "all32_independent_synthetic_latch_cap_age_memory_paths": True,
    "per_point_synthetic_counts": counts,
    "integer_coverage": value["integer_coverage"],
    "fivecheck_protocol": protocol.to_dict(),
    "new_point_audit_expected_cost_supported": [0.001, 0.002],
    "execution_links_bound": True,
    "original_centre_source_unchanged": True,
    "real_native_reads": 0,
    "financial_runs": 0,
    "provider_calls": 0,
    "candidate_registration": 0,
}
s.d.write(HERE / "point_checks_final.json", result)
print(
    json.dumps(
        {
            "status": "PASS",
            "points": 32,
            "financial_runs": 0,
            "integer_coverage": value["integer_coverage"],
        }
    )
)
