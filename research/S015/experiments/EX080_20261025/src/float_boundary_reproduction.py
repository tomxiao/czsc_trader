"""Read-only public-contract reproduction; no strategy account or platform writes."""
from pathlib import Path
from fractions import Fraction
import json,math
from strategy_evaluator.parameter_neighborhood import ParameterAxis,RealDomain,BoundedLocalStep,RelativeChangeLimit
H=Path(__file__).resolve().parents[1]
def main():
 rows=json.loads((H/'others/centers.json').read_bytes());result=[]
 for r in rows:
  c=r['parameters']['minimum_repair_space']
  if c==0:continue
  maximum=Fraction(str(c))*Fraction('0.05');directions=[]
  for sign in (-1,1):
   exact=Fraction(str(c))+sign*maximum;value=float(exact);actual=abs(Fraction(str(value))-Fraction(str(c)));inner=math.nextafter(value,c) if actual>maximum else value
   directions.append({'direction':sign,'exact_endpoint':str(exact),'float_endpoint':value,'actual_change':str(actual),'maximum_change':str(maximum),'incorrectly_over_limit':actual>maximum,'nearest_inward_float':inner,'inward_change_within_limit':abs(Fraction(str(inner))-Fraction(str(c)))<=maximum})
  try:
   ParameterAxis('minimum_repair_space',c,RealDomain(0.,.05),BoundedLocalStep(RelativeChangeLimit(.05)),('minimum_repair_space',),'price_ratio');status='CONSTRUCTION_ACCEPTED'
  except ValueError as error:status=str(error)
  result.append({'candidate':r['candidate_id'],'center':c,'public_api_status':status,'directions':directions})
 out={'status':'PLATFORM_FLOAT_BOUNDARY_DEFECT_REPRODUCED','new_accounts':0,'rows':result,'affected_centers':sum(any(x['incorrectly_over_limit'] for x in r['directions']) for r in result),'blocked_centers':sum(all(x['incorrectly_over_limit'] for x in r['directions']) for r in result),'proposal':{'scope':'DEV minimal fix in parameter_neighborhood continuous bounded endpoint conversion only; no economic threshold, discrete step, source candidate or historical evidence changes.','algorithm':'Compute exact rational endpoint as today. If nearest float is farther from center than allowed, select next representable float toward center and verify it is distinct, legal and within original exact limit. Keep exact-domain rejection before conversion.','contracts_and_api':'Existing types and public API signatures unchanged; preserve historical designs and manifests. New designs record actual representable endpoints and unchanged maximum.','focused_tests':['Non-round fee anchor both directions retained.','A tiny overshoot is moved one ULP inward; real discrete over-limit still rejected.','Zero/absolute limit, one-sided domain bounds, integer and ordinal behavior unchanged.','Serialized design round-trip and TDR parameter plan binding retain exact values.'],'authorization_required':'RSCH cannot edit platform. Need user approval to switch DEV for this bounded repair, then resume RSCH.'}}
 p=H/'others/float_boundary_reproduction.json';assert not p.exists();p.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print({k:out[k] for k in ('status','affected_centers','blocked_centers')})
if __name__=='__main__':main()
