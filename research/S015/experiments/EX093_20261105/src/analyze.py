"""Project saved native V4 accounts; never replay a selection window."""
from pathlib import Path
import json
from time import perf_counter
from czsc_trader.application import RepositoryContext,project_selection_window_facts
from czsc_trader.research_tools import (EvidenceRef,SelectionWindowSource,SelectionProjectionBudget,
    SelectionWindowFactsRequest,SelectionStabilityEvidence)
from strategy_evaluator import assess_selection_stability
from strategy_evaluator.research_models import AssessmentCandidate
from strategy_evaluator.selection_models import SelectionWindowPlan,SelectionRule

ROOT=Path(__file__).resolve().parents[5]
HOME=Path(__file__).resolve().parents[1]
OUT=HOME/'others'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def save(name,value):(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def main():
    assert not (OUT/'selection_stability.json').exists()
    rows=read(OUT/'results.json')['accounts']
    assert len(rows)==164 and len({r['content_sha256'] for r in rows})==164
    plan=SelectionWindowPlan.from_dict(read(HOME/'protocols/plan.json'))
    rule=SelectionRule.from_dict(read(HOME/'protocols/rule.json'))
    request=SelectionWindowFactsRequest(tuple(SelectionWindowSource(
        AssessmentCandidate('S015-'+r['proposed_candidate_id'],r['content_sha256']),EvidenceRef.from_dict(r['reference']))
        for r in rows),plan,60,3,SelectionProjectionBudget(990,2000000000,256000000))
    save('projection_request.json',request.to_dict())
    started=perf_counter()
    projection=project_selection_window_facts(RepositoryContext.discover(ROOT),request)
    save('projection.json',projection.to_dict())
    print('PROJECTION',projection.status.value,projection.stats.to_dict(),flush=True)
    analysis=projection.analysis_request(rule,observation_targets=rule.targets)
    result=assess_selection_stability(analysis)
    evidence=SelectionStabilityEvidence(projection,analysis,result,plan.limitations)
    save('selection_request.json',analysis.to_dict())
    save('selection_result.json',result.to_dict())
    save('selection_stability.json',evidence.to_dict())
    save('analysis_runtime.json',{'total_seconds':perf_counter()-started,'accounts_replayed':0})
    print('ANALYSIS',json.dumps({'status':result.status.value,'planned_windows':result.planned_windows,
        'selected_windows':result.selected_windows,'no_eligible_windows':result.no_eligible_windows,
        'passed_observations':result.passed_observations,'failed_observations':result.failed_observations,
        'selected':[[c.candidate_id for c in d.selected] for d in result.decisions]},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
