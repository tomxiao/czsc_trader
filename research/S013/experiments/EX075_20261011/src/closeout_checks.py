"""Artificial typed boundaries only; no real inputs or delivery API calls."""

import ast
from copy import deepcopy
from hashlib import sha256
import inspect
import json
from pathlib import Path

from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evidence import EvidenceRef
from postprocess import EXPERIMENT, LABELS, MANDATE_SHA, build_payload, report_links


def main():
    here = Path(__file__).resolve().parent
    fixture = EvidenceRef.from_dict(
        {
            "type": "EvidenceRef",
            "experiment": EXPERIMENT.to_dict(),
            "evidence_id": "a" * 64 + ".json",
            "sha256": "a" * 64,
            "media_type": "application/json",
            "name": "artificial-only",
            "schema": None,
            "schema_version": None,
        }
    )
    refs = {
        name: fixture.to_dict()
        for name in (
            "plan.json",
            "statistics.json",
            "verification.json",
            "root_review.json",
            "component_draft.py",
        )
    }
    review = {
        "objective_achieved": False,
        "new_accounts": 0,
        "original_four_hard_gates_changed": False,
        "judgment": "人工边界测试，非真实研究结论",
        "roles": {
            LABELS[0]: {"status": "INEFFECTIVE", "judgment": "人工收益负面fixture"},
            LABELS[1]: {"status": "INSUFFICIENT_DATA", "judgment": "人工风险不足fixture"},
        },
    }
    panel = build_payload(review, refs)
    assert len(panel.components) == 1 and len(panel.components[0].tests) == 2
    assert [t.status.value for t in panel.components[0].tests] == [
        "INEFFECTIVE",
        "INSUFFICIENT_DATA",
    ]
    assert d.ComponentPanel.from_dict(panel.to_dict()) == panel
    definition = d.DeliveryDefinition(
        d.ResearchBatchRef("S013"),
        d.DeliveryStage.COMPONENTS,
        11,
        (d.DeliveryReference(d.ResearchBatchRef("S013"), d.DeliveryStage.MANDATE, 6, MANDATE_SHA),),
    )
    assert d.DeliveryDefinition.from_dict(definition.to_dict()) == definition
    assert f"]({fixture.path})" in report_links(refs)
    assert "../../../" not in report_links(refs)
    refused = 0
    for key, value in (
        ("objective_achieved", True),
        ("new_accounts", 1),
        ("original_four_hard_gates_changed", True),
    ):
        invalid = deepcopy(review)
        invalid[key] = value
        try:
            build_payload(invalid, refs)
        except ValueError:
            refused += 1
        else:
            raise AssertionError(key)
    for roles in (
        {},
        {LABELS[0]: review["roles"][LABELS[0]]},
        {**review["roles"], "rescued_h2": review["roles"][LABELS[0]]},
    ):
        invalid = {**review, "roles": roles}
        try:
            build_payload(invalid, refs)
        except ValueError:
            refused += 1
        else:
            raise AssertionError("independent role count")
    for invalid_status in (None, "PENDING", "PASS"):
        invalid = deepcopy(review)
        invalid["roles"][LABELS[0]]["status"] = invalid_status
        try:
            build_payload(invalid, refs)
        except ValueError:
            refused += 1
        else:
            raise AssertionError("unknown status must not default")
    assert next(iter(inspect.signature(assemble_delivery).parameters)) == "context"
    assert next(iter(inspect.signature(validate_delivery).parameters)) == "context"
    tree = ast.parse((here / "postprocess.py").read_text("utf-8"))
    forbidden = {"register_candidate", "evaluate", "run_backtest", "fetch", "analyze", "statistics"}
    assert not any(
        isinstance(n, ast.Call)
        and (
            isinstance(n.func, ast.Name)
            and n.func.id in forbidden
            or isinstance(n.func, ast.Attribute)
            and n.func.attr in forbidden
        )
        for n in ast.walk(tree)
    )
    result = {
        "status": "PASS",
        "checks": 7,
        "refusals": refused,
        "artificial_fixture_only": True,
        "accounts": 0,
        "statistics": 0,
        "provider": 0,
        "publication": 0,
        "registration": 0,
        "assembly": 0,
        "validation": 0,
        "source_files": {
            name: sha256((here / name).read_bytes()).hexdigest()
            for name in ("postprocess.py", "checks.py")
        },
    }
    (here / "checks.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    print(result)


if __name__ == "__main__":
    main()
