"""Read-only source/API/authorization checks; no registration or delivery action."""

import ast
from hashlib import sha256
import importlib.util
import inspect
import json
from pathlib import Path

from czsc_trader.application import assemble_delivery, register_candidate, validate_delivery
from czsc_trader.research_tools import delivery as api
from czsc_trader.research_tools.evidence import EvidenceRef
from strategy_evaluator import AssessmentPanel

ROOT = Path.cwd().resolve()
WORK = ROOT / ".tmp/s013-pressure-early-exit"
HERE = WORK / "closeout"


def read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def references(value):
    if isinstance(value, dict):
        if value.get("type") == "EvidenceRef":
            yield EvidenceRef.from_dict(value)
        else:
            for item in value.values():
                yield from references(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from references(item)


assert not (HERE / "root_execution_authorization.json").exists()
assert not (WORK / "formal-closeout").exists()
assert not (ROOT / "research/registrations/S013/candidates/C9074.json").exists()
source = HERE / "postprocess.py"
tree = ast.parse(source.read_text("utf-8"))
assert not any(
    isinstance(node, ast.Call)
    and isinstance(node.func, ast.Attribute)
    and node.func.attr in ("prepare", "evaluate")
    for node in ast.walk(tree)
)
spec = importlib.util.spec_from_file_location("early_time_final_closeout_source", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert tuple(inspect.signature(register_candidate).parameters) == ("context", "request")
assert tuple(inspect.signature(assemble_delivery).parameters) == (
    "context",
    "definition",
    "content",
)
assert "scope" in inspect.signature(validate_delivery).parameters

protocol = ROOT / "research/S013/experiments/EX074_20261011/protocols"
reviewref = EvidenceRef.from_dict(
    read(protocol / "root_scientific_review_references.json")["root_scientific_review.json"]
)
review = read(reviewref.resolve(ROOT))
analysisref = EvidenceRef.from_dict(read(protocol / "analysis_reference.json"))
analysis = read(analysisref.resolve(ROOT))
assert reviewref.sha256 == "bc1c924843ca050812570c685d894649120facf7cd9f80d61ee2ed2f85348d7c"
assert analysisref.sha256 == "3442fe27127a19d92b8bc10c45d2e73df781688fa56a1a810a2f64ea9b079d57"
assert (
    review["analysis_reference"] == analysisref.to_dict()
    and review["analysis_sha256"] == analysisref.sha256
)
assert review["objective_achieved"] is False and review["eligible_centre_to_register"] == "C9074"
assert review["scientific_classification"] == "INEFFECTIVE_FOR_ABSOLUTE_ROBUSTNESS"
assert analysis["rows"]["N_PRESSURE_EARLY_EXIT"]["center"]["qualified"] is True
assert (
    analysis["counts"]["new_financial_total"] == 34
    and analysis["counts"]["all_native_accounts_including_reuse"] == 68
)
state = read(WORK / "perturbation_state.json")
assert state["status"] == "FINANCIAL34_COMPLETE" and set(state["accounts"]) == {
    *(f"P{i:02}" for i in range(32)),
    "FEE",
}
assert all(x["status"] == "AUDITED" for x in state["accounts"].values())
for row in analysis["fivechecks"].values():
    AssessmentPanel.from_dict(row["panel"]).validate()
predecessors = tuple(
    api.DeliveryReference.from_dict(
        read(ROOT / f"research/S013/assets/deliveries/{stage}/{revision}/receipt.json")["reference"]
    )
    for stage, revision in (("MANDATE", 6), ("CANDIDATES", 59), ("COMPONENTS", 10))
)
batch = predecessors[0].batch
definition = api.DeliveryDefinition(batch, api.DeliveryStage.CANDIDATES, 60, predecessors)
definition.validate()
previous = api.DeliveryContent.from_dict(
    read(ROOT / "research/S013/assets/deliveries/CANDIDATES/59/delivery.json")["content"]
).payload
public_refs = {}
for value in [review, analysis, *(read(q) for q in protocol.glob("*.json"))]:
    for ref in references(value):
        assert ref.experiment.strategy_id == "S013"
        ref.resolve(ROOT)
        public_refs[ref.repository_path] = ref.to_dict()

denials = []
try:
    module.run(reviewref, "0" * 64)
except ValueError as exc:
    assert str(exc) == "Root-reviewed closeout source drift"
    denials.append("incorrect_source_sha_refused_before_reads_or_actions")
else:
    raise AssertionError("Incorrect source hash accepted")
try:
    module.run(reviewref, digest(source))
except FileNotFoundError as exc:
    assert Path(exc.filename) == HERE / "root_execution_authorization.json"
    denials.append("missing_root_authority_refused_before_context_or_actions")
else:
    raise AssertionError("Missing closeout authority accepted")
original_read = module.read
module.read = lambda path: {
    "status": "WRONG_STATUS",
    "source_sha256": digest(source),
    "root_review_reference": reviewref.to_dict(),
}
try:
    module.run(reviewref, digest(source))
except ValueError as exc:
    assert str(exc) == "Exact root closeout authorization required"
    denials.append("wrong_authority_refused_before_context_or_actions")
else:
    raise AssertionError("Wrong closeout authority accepted")
finally:
    module.read = original_read
for name in ("freeze_v2.json", "standard/freeze.json"):
    frozen = read(WORK / name)
    assert all(digest(ROOT / p) == expected for p, expected in frozen["files"].items())

output = {
    "status": "PASS_SOURCE_ONLY_CLOSEOUT_GUARD_TYPED_API_MANIFEST",
    "source_sha256": digest(source),
    "guard_negative_checks": denials,
    "root_review_reference": reviewref.to_dict(),
    "analysis_reference": analysisref.to_dict(),
    "predecessors": [x.to_dict() for x in predecessors],
    "proposed_delivery_definition": definition.to_dict(),
    "counts": analysis["counts"],
    "search_evaluations": 68,
    "unique_strategy_parameter_configurations": 66,
    "cost_roles_do_not_add_parameter_configurations": True,
    "retained_previous_candidate_keys": [x.identity.key.to_dict() for x in previous.candidates],
    "retained_previous_handoff": [x.to_dict() for x in previous.handoff],
    "qualified_centre_to_register_after_separate_authority": "C9074",
    "root_scientific_objective_achieved": False,
    "public_evidence_references": list(public_refs.values()),
    "financial_source_and_standard_freezes_unchanged": True,
    "new_financial_runs": 0,
    "statistics_runs": 0,
    "provider_calls": 0,
    "registration": 0,
    "assemble": 0,
}
target = HERE / "source_checks.json"
assert not target.exists()
target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", "utf-8")
print(
    json.dumps(
        {
            k: output[k]
            for k in (
                "status",
                "source_sha256",
                "guard_negative_checks",
                "new_financial_runs",
                "registration",
                "assemble",
            )
        },
        ensure_ascii=False,
    )
)
