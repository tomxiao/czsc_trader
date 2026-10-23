"""Explicit technical binding correction; frozen account design unchanged."""
import argparse
from datetime import date
import accounts as a
def request(ctx,ex,cid,p):
    c=a.candidate(cid,p)
    return ctx.evaluation.prepare(a.EvaluationRequest(a.ROOT,ex.experiment_id,c,{'candidate_id':c.reference_id,'source_files':a.FILES,'implementation_sha256':c.payload['runtime']['source_sha256']},'159326.SZ','etf',(a.EvaluationWindow('full',date(2025,1,2),date(2026,10,21)),a.EvaluationWindow('s011_common',date(2025,2,6),date(2026,10,21))),date(2026,10,21),100000.,(a.EvaluationCost('standard',.001),),benchmark=a.EvaluationBenchmark(a.LimitBuyHold(100,.01,.001,.1,1000000))))
if __name__=='__main__':
    for key,ref in a.read(a.HERE/'others/binding_correction_refs.json').items():assert a.EvidenceRef.from_dict(ref).resolve(a.ROOT).read_bytes()==(a.HERE/key).read_bytes()
    p=argparse.ArgumentParser();p.add_argument('--experiment',default=a.HERE.name);p.add_argument('--precheck',action='store_true');args=p.parse_args();a.request=request;a.run(args.experiment,args.precheck)
