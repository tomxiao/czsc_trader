"""Rebind historical synthetic PTE cases without changing financial expectations."""
from pathlib import Path
from dataclasses import replace
from hashlib import sha256
import json
import sys
import cloudpickle

from czsc_trader.application import RepositoryContext, create_research_context, describe_inspection_environment, InspectionProtocol
from czsc_trader.research_tools import ResearchBatchRef, ExecutionResources
from dataflows import ProviderConfig
from strategy_runtime import StrategyCandidate, StrategyRuntime, StrategyInit, StrategyInputBinding, implementation_sha256
from paper_trading_engine.inspection import PteEnvironmentRequirement

ROOT = Path(__file__).resolve().parents[5]
HOME = Path(__file__).resolve().parents[1]
FAMILY = HOME.parent.parent.name
REFERENCE = FAMILY + "-v1"


def write_once(path, value):
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def run():
    sys.dont_write_bytecode = True
    repo = RepositoryContext.discover(ROOT)
    ctx = create_research_context(repo, ResearchBatchRef(FAMILY), resources=ExecutionResources(1,1,42), providers=ProviderConfig(bindings={}))
    prior_name = ("EX083_20261022/protocols/inspection.json" if FAMILY == "S011" else "EX084_20261025/protocols/inspection_v2.json")
    prior_path = ROOT / "research" / FAMILY / "experiments" / prior_name
    prior = InspectionProtocol.from_dict(json.loads(prior_path.read_bytes())["protocol"]).pte
    note = {
        "status":"DESIGNED_BEFORE_PREPARATION", "source_protocol":prior_path.relative_to(ROOT).as_posix(),
        "source_sha256":sha256(prior_path.read_bytes()).hexdigest(),
        "changes":["Candidate identity and definition hashes rebound to C9950", "Environment rebound to current platform source identity"],
        "unchanged":["Decision dates and clocks", "All channel events and amounts", "All checkpoints including health", "Restart, coverage and failure cases"],
        "normal_unfilled_review":"S011 zero-fill cancellation at 10:01 has no ENGINE planned_deadline cancellation provenance. S015 cancellation follows a partial fill. Neither qualifies for NORMAL_UNFILLED; BLOCKED remains the correct expectation.",
        "verification":"Authenticated fetch of every original prepared request. Input plan changes only strategy identity. No providers are configured; no network access.",
        "production_writes":0,
    }
    write_once(HOME / "others/pte_protocol_design.json", note)
    baseline = cloudpickle.loads((ROOT / ".tmp/observation-v4-upgrade" / (REFERENCE+"-baseline.pkl")).read_bytes())
    original = json.loads((ROOT / "strategies" / FAMILY / "versions/v1.json").read_bytes())
    source = HOME / "src" / REFERENCE / "strategy_runtime"
    payload = original["strategy_payload"]
    payload["runtime"]["source_files"].append("strategies/observation_explanation.py")
    payload["runtime"]["source_sha256"] = implementation_sha256(tuple(payload["runtime"]["source_files"]),source_root=source)
    child = StrategyCandidate(FAMILY,"C9950",payload,source)
    cache = ROOT / ".tmp/observation-v4-upgrade" / (REFERENCE+"-pte-bindings")
    scenarios, proofs = [], []
    for scenario in prior.scenarios:
        decisions = []
        for decision in scenario.decisions:
            old = decision.binding
            results = {name:ctx.data.fetch(request,prepared=old.prepared) for name,request in old.plan.requests.items()}
            assert all(result.ready for result in results.values()), {k: str(v.error) for k,v in results.items() if not v.ready}
            instance = StrategyRuntime(repo.strategy_root,dataflows=ctx.data).create(StrategyInit(child,old.plan.tradable_window,cache/scenario.scenario_id/decision.step_id,pricing=baseline.execution_data.pricing))
            kwargs = {}
            if "__trading_status" in results:
                kwargs = {"trading_status":results["__trading_status"],"status_request":old.plan.requests["__trading_status"]}
            plan = instance.plan_inputs(results[old.plan.calendar_name],**kwargs)
            before, after = old.plan.to_dict(), plan.to_dict()
            before.pop("strategy"); after.pop("strategy")
            assert before == after, (scenario.scenario_id,decision.step_id,"nonidentity plan changed")
            binding = StrategyInputBinding(plan,old.prepared)
            instance.prepare_data(binding=binding)
            decisions.append(replace(decision,binding=binding))
            proofs.append({"scenario_id":scenario.scenario_id,"step_id":decision.step_id,
                "prepared":binding.to_dict()["prepared"],"plan_equal_except_strategy":True,
                "input_content_sha256":{k:v.identity.content_sha256 for k,v in results.items()}})
        changed = replace(scenario,decisions=tuple(decisions))
        left,right=scenario.to_dict(),changed.to_dict()
        left.pop("decisions");right.pop("decisions")
        assert left==right
        scenarios.append(changed)
    environment=describe_inspection_environment(repo)
    requirement=PteEnvironmentRequirement(environment.platform_build_sha256,environment.pte_contract_version,environment.srt_contract_version)
    protocol=replace(prior,scenarios=tuple(scenarios),environment=requirement)
    write_once(HOME/"others/pte_protocol.json",protocol.to_dict())
    write_once(HOME/"others/pte_protocol_preparation.json",{"status":"PREPARED_NOT_INSPECTED","candidate":child.reference_id,"source_sha256":payload["runtime"]["source_sha256"],"environment":environment.to_dict(),"bindings":proofs,"scenarios":len(scenarios),"monetary_and_health_expectations_unchanged":True})
    print(REFERENCE,"PTE_PREPARED",len(scenarios),len(proofs),environment.platform_build_sha256)


if __name__ == "__main__":
    run()
