"""Current public SE assessment of available immutable center facts only."""
from pathlib import Path
import json
from hashlib import sha256
from czsc_trader.research_tools import EvidenceRef
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
    assert not (OUT/'available_assessment_panel.json').exists(),'preserve completed assessment'
    item=read(OUT/'result_C9810_full.json')
    ref=EvidenceRef.from_dict(item['reference']);path=ref.resolve(ROOT);content=path.read_bytes()
    assert sha256(content).hexdigest()==ref.sha256
    standard,=build_equity_assessment(content,lambda r:(path.parent/(r['sha256']+'.json')).read_bytes())
    assert standard.equity.concentration_basis=='TOP_DECILE'
    assert standard.parent is None and standard.parameter_point is None
    protocol=m.NeighborhoodSelfCheckProtocol(version='S015-EX090-existing-stage-four-objectives',
        baseline_window='full',standard_scenario='STANDARD',stress_scenario='FEE_X2',
        rolling_window_days=252,rolling_step_days=21,quantile_method=m.QuantileMethod.LINEAR,
        minimum_rolling_windows=1,bootstrap_repetitions=2000,bootstrap_block_length=10,seed=13,
        reconciliation_tolerance=1e-7,parameter_protocol=ParameterNeighborhoodProtocol(),
        pbo_blocks=10,frequency_min_closed_cycles=3)
    request=m.CandidateAssessmentRequest(centers=(standard.candidate,),protocol=protocol,
        perturbations=(),evidence=(standard,),family_returns=None,parameter_designs=())
    save(OUT/'available_assessment_request.json',request.to_dict())
    panel=assess_candidates(request)
    save(OUT/'available_assessment_panel.json',panel.to_dict())
    old=m.CandidateComparisonRequest.from_dict(read(ROOT/'research/S015/experiments/EX080_20261025/others/comparison_request_v2.json'))
    comparison_request=m.CandidateComparisonRequest((standard.candidate,),old.targets,panel,old.policy)
    save(OUT/'available_comparison_request.json',comparison_request.to_dict())
    comparison=compare_candidates(comparison_request)
    save(OUT/'available_comparison.json',comparison.to_dict())
    summary={'source':ref.to_dict(),'formula_version':panel.formula_version,
        'scope':'Center only; parameter lineage missing and pressure not requested. Not complete stage-four acceptance.',
        'diagnostics':[x.to_dict() for x in panel.rows[0].diagnostics],
        'uncertainty':panel.rows[0].uncertainty.to_dict(),
        'family_limitation':'family_returns=None; PBO/DSR not calculated; missing-data labels preserved',
        'parameter_binding_blocker':'Published request.lineage is None. Current public plan creation accepts session-owned prepared handles and binding must exist in evaluation request. No public post-hoc rebinding of saved account evidence.',
        'targets_reused_from':'EX080_20261025/others/comparison_request_v2.json'}
    save(OUT/'available_assessment_summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
