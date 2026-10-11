"""Pure closeout helper/typed-reference checks; no assemble or new statistics."""

import ast
from hashlib import sha256
from pathlib import Path
import json
from finish import typed_status, report_links
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef

HERE = Path(__file__).parent
ROOT = next(p for p in HERE.resolve().parents if (p / "pyproject.toml").exists())


def main():
    plan = json.loads((HERE / "plan.json").read_text("utf-8"))
    exp = ExperimentRef.from_dict(json.loads((HERE / "experiment.json").read_text("utf-8")))
    refs = json.loads(
        (exp.resolve(ROOT) / "protocols/complete_result_references.json").read_text("utf-8")
    )
    fixture = {"component_status": "LIMITED_SUPPORT_FOR_FIXED_HOLDING_TEST"}
    assert typed_status(fixture) is d.ComponentTestStatus.SUPPORTED
    refused = 0
    for invalid in ("SUPPORTED", "INEFFECTIVE", "OTHER"):
        try:
            typed_status({"component_status": invalid})
        except ValueError:
            refused += 1
        else:
            raise AssertionError(invalid)
    links = report_links(refs)
    local = report_links(refs, "../../../assets/deliveries/COMPONENTS/10/")
    for name, ref in refs.items():
        path = str(EvidenceRef.from_dict(ref).path)
        assert f"[{name}]({path})" in links
        assert f"[{name}](../../../assets/deliveries/COMPONENTS/10/{path})" in local
    assert "driver_pricefix.py" in refs and "price_technical_amendment.json" in refs
    assert "execution_receipt.json" in refs and "C8880_original_native" in refs
    definition = d.DeliveryDefinition(
        d.ResearchBatchRef("S013"),
        d.DeliveryStage.COMPONENTS,
        10,
        (d.DeliveryReference.from_dict(plan["delivery_lineage"]["permitted_stage_predecessor"]),),
    )
    assert len(definition.predecessors) == 1
    test = d.ComponentTestResult(
        "SYNTHETIC-CLOSEOUT-HELPER",
        exp.experiment_id,
        EvidenceRef.from_dict(refs["plan.json"]),
        typed_status(fixture),
        "有限，仅支持固定账户反证；非跨年/策略稳健证实",
        (
            EvidenceRef.from_dict(refs["statistics.json"]),
            EvidenceRef.from_dict(refs["verification.json"]),
        ),
    )
    assert test.status is d.ComponentTestStatus.SUPPORTED
    tree = ast.parse((HERE / "finish.py").read_text("utf-8"))
    assert not any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in ("fetch", "evaluate", "run_backtest")
        for n in ast.walk(tree)
    )
    original = {n: sha256((HERE / n).read_bytes()).hexdigest() for n in plan["source_files"]}
    assert original == plan["source_files"]
    out = {
        "status": "PASS",
        "checks": 8,
        "refusals": refused,
        "source_hashes": {
            n: sha256((HERE / n).read_bytes()).hexdigest()
            for n in ("finish.py", "closeout_checks.py")
        },
        "original_scientific_source_hashes_unchanged": original,
        "assemble_calls": 0,
        "actual_statistics_runs": 0,
        "accounts": 0,
        "provider": 0,
    }
    path = HERE / "closeout_checks.json"
    assert not path.exists()
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print({k: out[k] for k in ("status", "checks", "refusals", "source_hashes", "assemble_calls")})


if __name__ == "__main__":
    main()
