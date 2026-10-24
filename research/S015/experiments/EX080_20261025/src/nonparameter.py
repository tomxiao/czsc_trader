"""Explicit partial selfcheck: retain parameter-design gaps, never qualify candidates."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
from pathlib import Path
import json
from strategy_evaluator import assess_candidates
from strategy_evaluator import research_models as m
from strategy_evaluator.parameter_neighborhood import ParameterNeighborhoodProtocol
H=Path(__file__).resolve().parents[1];ROOT=H.parents[3];OUT=H/'others';CACHE=ROOT/'.tmp/s015-ex080'
def read(p):return json.loads(p.read_bytes())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def main():
 assert not (OUT/'nonparameter_panel.json').exists();allitems=[m.AssessmentEvidence.from_dict(x) for x in read(CACHE/'retained_accounts.json')];family=m.FamilyReturnEvidence.from_dict(read(CACHE/'family_returns.json'));keep=set(family.candidates);items=tuple(x for x in allitems if x.scenario_id=='fee_x2' or x.candidate in keep);byid={x.candidate.candidate_id.removeprefix('S015-'):x for x in items if x.scenario_id=='standard'};centers=tuple(byid[r['candidate_id']].candidate for r in read(OUT/'centers.json'));assert len(items)==635 and len(centers)==29
 protocol=m.NeighborhoodSelfCheckProtocol(version='S015-EX080-price-repair-stage4-v1',baseline_window='full',standard_scenario='standard',stress_scenario='fee_x2',rolling_window_days=252,rolling_step_days=21,quantile_method=m.QuantileMethod.LINEAR,minimum_rolling_windows=1,bootstrap_repetitions=2000,bootstrap_block_length=10,seed=13,reconciliation_tolerance=1e-7,parameter_protocol=ParameterNeighborhoodProtocol(),pbo_blocks=10,frequency_min_closed_cycles=3)
 request=m.CandidateAssessmentRequest(centers,protocol,(),items,family_returns=family,parameter_designs=());save(CACHE/'nonparameter_request.json',request.to_dict());print('ASSESS_NONPARAMETER',29,flush=True);panel=assess_candidates(request);save(OUT/'nonparameter_panel.json',panel.to_dict());assert len(panel.rows)==29
 summary={'status':'PARTIAL_PARAMETER_DESIGN_BLOCKED','full_qualification':'NOT_DETERMINED','source_request_sha256':request.sha256,'rows':[{'candidate_id':x.candidate.candidate_id,'coverage_gaps':list(x.coverage_gaps),'diagnostics':[v.to_dict() for v in x.diagnostics],'uncertainty':x.uncertainty.to_dict()} for x in panel.rows],'family_diagnostics':[x.to_dict() for x in panel.family_diagnostics],'limit':'No parameter design or neighborhood supplied while platform endpoint defect is unresolved. Missing is neither NOT_APPLICABLE nor PASSED. No comparison/ranking or qualification issued.'};save(OUT/'nonparameter_summary.json',summary);print('NONPARAMETER_COMPLETE_PARAMETER_REMAINS_MISSING',flush=True)
if __name__=='__main__':main()
