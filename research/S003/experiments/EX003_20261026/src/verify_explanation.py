from pathlib import Path
import ast
import importlib.util
import json
import numpy as np
import pandas as pd
from strategy_runtime import StrategyCandidate, implementation_sha256, RuntimeContractError
from strategy_runtime.signal_panel import materialize_signal_panel
from czsc_trader.application import RepositoryContext, validate_frozen_observation_upgrade
from strategy_manager.freeze_contracts import FrozenVersionReference

ROOT = Path(__file__).resolve().parents[5]
HOME = Path(__file__).resolve().parents[1]
FAMILY = HOME.parents[1].name
REF = f"{FAMILY}-v1"
SOURCE = HOME / "src" / REF / "strategy_runtime"
VERSION = json.loads(
    (ROOT / "strategies" / FAMILY / "versions/v1.json").read_text(encoding="utf-8")
)
MANIFEST = json.loads(
    (ROOT / "strategies" / FAMILY / "releases/v1/release_manifest.json").read_text(encoding="utf-8")
)
module_path = SOURCE / "strategies/observation_explanation_v4.py"
spec = importlib.util.spec_from_file_location(f"{FAMILY}_display", module_path)
display = importlib.util.module_from_spec(spec)
spec.loader.exec_module(display)
params = VERSION["strategy_payload"]["parameters"]["rule"]
settings = params["feature" if FAMILY == "S003" else "score"]
definition = display.observation_definition(settings)
payload = VERSION["strategy_payload"]
payload["runtime"]["source_files"].append("strategies/observation_explanation_v4.py")
payload["runtime"]["source_sha256"] = implementation_sha256(
    tuple(payload["runtime"]["source_files"]), source_root=SOURCE
)
candidate = StrategyCandidate(FAMILY, "C9950", payload, SOURCE)
validated = validate_frozen_observation_upgrade(
    RepositoryContext.discover(ROOT),
    FrozenVersionReference(FAMILY, "v1", VERSION["release_hash"], MANIFEST["package_hash"]),
    candidate,
)
assert validated.observation == definition
assert definition.to_dict()["contract_version"] == "strategy_observation.v4"
core = ast.parse((SOURCE / "strategies" / f"{FAMILY.lower()}_v1.py").read_text(encoding="utf-8"))
checks = []


def materialize(history):
    before = history.copy(deep=True)
    fields = display.observation_history(history, settings)
    assert history.equals(before)
    return [
        materialize_signal_panel(definition.signal_panel, row.to_dict())
        for _, row in fields.iterrows()
    ]


if FAMILY == "S003":
    helper = next(
        n for n in core.body if isinstance(n, ast.FunctionDef) and n.name == "_decision_history"
    )
    namespace = {"pd": pd, "Mapping": dict, "Any": object}
    exec(
        compile(ast.Module(body=[helper], type_ignores=[]), "<actual-frozen-helper>", "exec"),
        namespace,
    )
    length = settings["threshold_lookback_sessions"]
    dates = pd.date_range("2026-01-01", periods=length + 3)
    history = pd.DataFrame(
        {"moneyflow_breadth": [0.5] * length + [0.5, 0.4, 0.6], "observed_weight_ratio": 1.0},
        index=dates,
    )
    history = namespace["_decision_history"](history, settings)
    view = materialize(history.iloc[-3:])
    assert [v.explanation.case_key for v in view] == ["active", "inactive", "active"]
    assert history.iloc[-3]["moneyflow_breadth"] == history.iloc[-3]["threshold"]
    assert "50.00%" in view[0].explanation.basis[0].text
    checks += [
        "actual frozen GREATER_THAN_OR_EQUAL boundary: equality active, below inactive, above active",
        "dynamic threshold and observed coverage quoted from trading evidence",
        "signal does not imply clearing core inventory or confirmed fill",
    ]
    try:
        materialize(history.iloc[:1])
    except RuntimeContractError:
        checks.append("warmup threshold unavailable is rejected, not fabricated as inactive")
    else:
        raise AssertionError("warmup must be unavailable")
    broken = history.iloc[-1:].copy()
    broken["signal_active"] = None
    try:
        materialize(broken)
    except RuntimeContractError:
        checks.append("missing actual signal rejected")
    else:
        raise AssertionError("missing signal accepted")
else:
    helper = next(
        n
        for n in core.body
        if isinstance(n, ast.FunctionDef) and n.name == "calculate_s007_history"
    )
    # Isolate the unchanged frozen decision loop: feed controlled normalized scores.
    namespace = {
        "pd": pd,
        "np": np,
        "Mapping": dict,
        "Any": object,
        "_object": lambda value, name: value,
        "causal_percentile": lambda values, *args: values,
    }
    exec(
        compile(
            ast.Module(body=[helper], type_ignores=[]), "<actual-frozen-decision-loop>", "exec"
        ),
        namespace,
    )
    entry = settings["entry_threshold"]
    exit = settings["exit_threshold"]
    confirm = settings["confirmation_threshold"]
    controlled = pd.DataFrame(
        {
            "base": [entry - 1e-8, entry, exit + 1e-8, exit, entry, entry],
            "confirmation": [confirm, confirm, confirm - 1.0, confirm, confirm - 1e-8, confirm],
        }
    )
    isolated = {
        **settings,
        "orientations": {"base": 1, "confirmation": 1},
        "base_weights": {"base": 1.0},
        "confirmation_weights": {"confirmation": 1.0},
    }
    history = namespace["calculate_s007_history"](
        controlled, {"lookback_sessions": 1, "minimum_observations": 1}, isolated
    )
    assert history.action.tolist() == [
        "HOLD_CASH",
        "ENTER",
        "HOLD_POSITION",
        "EXIT",
        "HOLD_CASH",
        "ENTER",
    ]
    view = materialize(history)
    assert [v.explanation.case_key for v in view] == [
        "hold_cash",
        "enter",
        "hold_position",
        "exit",
        "hold_cash",
        "enter",
    ]
    checks += [
        "isolated unchanged trading loop: entry equality, confirmation equality, below-entry, below-confirmation, hold above exit, exit equality",
        "confirmation falling does not trigger exit",
        "all four actual action states map to matching narratives",
    ]
    broken = history.iloc[[2]].copy()
    broken["confirmation_score"] = float("nan")
    assert materialize(broken)[0].explanation.case_key == "hold_position"
    checks.append("unused confirmation unavailable does not change active-branch explanation")
    broken = history.iloc[[0]].copy()
    broken["base_score"] = float("nan")
    try:
        materialize(broken)
    except RuntimeContractError:
        checks.append("selected basis unavailable rejects whole explanation")
    else:
        raise AssertionError("missing base accepted")
    broken = history.iloc[[0]].copy()
    broken["action"] = "UNKNOWN"
    try:
        materialize(broken)
    except RuntimeContractError:
        checks.append("unknown actual action rejected")
    else:
        raise AssertionError("unknown action accepted")
    changed = {**settings, "entry_threshold": entry + 0.1}
    changed_definition = display.observation_definition(changed)
    fields = display.observation_history(history.iloc[[1]], changed).iloc[0].to_dict()
    changed_snapshot = materialize_signal_panel(changed_definition.signal_panel, fields)
    assert f"{entry + 0.1:.4f}" in changed_snapshot.explanation.basis[0].text
    checks.append("display threshold references effective parameters rather than copied literals")
result = {
    "reference": REF,
    "status": "PASS",
    "source_files_added": ["strategies/observation_explanation_v4.py"],
    "public_observation_upgrade_validation": "PASS",
    "checks": checks,
    "scope": "Synthetic semantic and isolated frozen decision-loop checks; full historical equivalence is performed separately by the parent task.",
    "snapshots": [x.to_dict() for x in view],
}
out = HOME / "others/explanation_semantics.json"
out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
print(REF, "PASS", len(checks), flush=True)
