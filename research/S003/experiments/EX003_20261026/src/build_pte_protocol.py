"""Read-only capability audit: S003 cannot satisfy current PTE inspection coverage."""

from pathlib import Path
import json
from hashlib import sha256
from paper_trading_engine.inspection import (
    PteCoverageRequirement,
    PteInspectionCapability,
    CoverageRequirement,
)

ROOT = Path(__file__).resolve().parents[5]
HOME = Path(__file__).resolve().parents[1]
runner = ROOT / "packages/paper_trading_engine/src/paper_trading_engine/inspection_runner.py"
contract = ROOT / "packages/paper_trading_engine/src/paper_trading_engine/inspection_contracts.py"
execution = ROOT / "packages/strategy_runtime/src/strategy_runtime/execution_rules.py"
assert 'final["position_quantity"] == 0' in runner.read_text(encoding="utf-8")
try:
    PteCoverageRequirement(
        PteInspectionCapability.ENTER_HOLD_EXIT,
        CoverageRequirement.NOT_APPLICABLE,
        (),
        "S003 retains a permanent core position and exits only the intraday enhancement.",
    )
except ValueError as exc:
    rejection = str(exc)
else:
    raise AssertionError("Review the platform: mandatory coverage behavior changed")
result = {
    "reference": "S003-v1",
    "status": "BLOCKED_PLATFORM_CAPABILITY",
    "production_writes": 0,
    "mandatory_coverage_conflict": {
        "capability": "ENTER_HOLD_EXIT",
        "required_fact": "final account quantity == 0",
        "actual_strategy": "INTRADAY_OVERLAY maintains core_quantity; rotation exits enhancement only, returning to core, not zero.",
        "inapplicable_declaration_rejected": rejection,
    },
    "checkpoint_limitation": {
        "strategy": "OPEN entry and 11:30_CLOSE dependent exit are separate execution windows",
        "protocol": "PteDecisionInput provides one submit_at per decision; no independent submit/checkpoint action is declared.",
        "status": "Requires explicit platform design review; do not encode separate economic decisions merely to invoke submission twice.",
    },
    "source_sha256": {
        str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p.read_bytes()).hexdigest()
        for p in (runner, contract, execution)
    },
    "completed": "Observation-only source and semantic validation were completed separately.",
    "next_step": "DEV must define coverage for permanent-core intraday rotation and execution checkpoint scheduling before a valid complete inspection protocol can be emitted.",
}
(HOME / "others/pte_protocol_blocker.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    "S003-v1 BLOCKED_PLATFORM_CAPABILITY: mandatory final-zero holding coverage incompatible with permanent core"
)
