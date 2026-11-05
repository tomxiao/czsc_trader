"""Current public SE assessment of available immutable center facts only."""
from pathlib import Path
import json
from hashlib import sha256
from czsc_trader.research_tools import EvidenceRef,ParameterEvaluationPlan
from czsc_trader.research_tools.equity_replay import build_equity_assessment
from strategy_evaluator import assess_candidates,compare_candidates
from strategy_evaluator import research_models as m
from strategy_evaluator.parameter_neighborhood import ParameterNeighborhoodProtocol
ROOT=Path(__file__).resolve().parents[5]
HOME=Path(__file__).resolve().parents[1]
OUT=HOME/'others'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def main():
    assert not (OUT/'bound_assessment_panel.json').exists(),'preserve completed assessment'
    item=read(OUT/'result_C9820_full_STANDARD.json')
    ref=EvidenceRef.from_dict(item['reference']);path=ref.resolve(ROOT);content=path.read_bytes()
    assert sha256(content).hexdigest()==ref.sha256
    standard,=build_equity_assessment(content,lambda r:(path.parent/(r['sha256']+'.json')).read_bytes())
    assert standard.equity.concentration_basis=='TOP_DECILE'
    assert standard.parent is None and standard.parameter_point is None
    protocol=m.NeighborhoodSelfCheckProtocol(version='S015-EX092-existing-stage-four-objectives',
        baseline_window='full',standard_scenario='STANDARD',stress_scenario='FEE_X2',
        rolling_window_days=252,rolling_step_days=21,quantile_method=m.QuantileMethod.LINEAR,
        minimum_rolling_windows=1,bootstrap_repetitions=2000,bootstrap_block_length=10,seed=13,
        reconciliation_tolerance=1e-7,parameter_protocol=ParameterNeighborhoodProtocol(),
        pbo_blocks=10,frequency_min_closed_cycles=3)
    plan=ParameterEvaluationPlan.from_dict(read(OUT/'formal_parameter_plan.json'))
    children=[]
    for row in read(OUT/'bound_results.json')['accounts']:
        childref=EvidenceRef.from_dict(row['reference']); childpath=childref.resolve(ROOT)
        child,=build_equity_assessment(childpath.read_bytes(),lambda r:(childpath.parent/(r['sha256']+'.json')).read_bytes())
        assert child.parent==standard.candidate and child.parameter_point is not None
        children.append(child)
    stressref=EvidenceRef.from_dict(read(OUT/'result_C9820_full_FEE_X2.json')['reference']); stresspath=stressref.resolve(ROOT)
    stress,=build_equity_assessment(stresspath.read_bytes(),lambda r:(stresspath.parent/(r['sha256']+'.json')).read_bytes())
    assert stress.candidate==standard.candidate
    links=tuple(m.PerturbationLink(x.parent,x.candidate,1.,x.derivation_sha256,x.parameter_point) for x in children)
    request=m.CandidateAssessmentRequest(centers=(standard.candidate,),protocol=protocol,
        perturbations=links,evidence=(standard,stress,*children),family_returns=None,parameter_designs=(plan.design,))
    save(OUT/'bound_assessment_request.json',request.to_dict())
    panel=assess_candidates(request)
    save(OUT/'bound_assessment_panel.json',panel.to_dict())
    old=m.CandidateComparisonRequest.from_dict(read(ROOT/'research/S015/experiments/EX080_20261025/others/comparison_request_v2.json'))
    comparison_request=m.CandidateComparisonRequest((standard.candidate,),old.targets,panel,old.policy)
    save(OUT/'bound_comparison_request.json',comparison_request.to_dict())
    comparison=compare_candidates(comparison_request)
    save(OUT/'bound_comparison.json',comparison.to_dict())
    summary={'source':ref.to_dict(),'formula_version':panel.formula_version,
        'scope':'Center, same-candidate fee stress, and five formally bound parameter points; selection stability remains separate.',
        'diagnostics':[x.to_dict() for x in panel.rows[0].diagnostics],
        'uncertainty':panel.rows[0].uncertainty.to_dict(),
        'family_limitation':'family_returns=None; PBO/DSR not calculated; missing-data labels preserved',
        'parameter_binding':'Prospective schema-4 plan published before five new evaluations; original unbound source references preserved.',
        'targets_reused_from':'EX080_20261025/others/comparison_request_v2.json'}
    save(OUT/'bound_assessment_summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
