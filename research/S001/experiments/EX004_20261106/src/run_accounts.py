"""Run the two corrected S001 native accounts through the public research API."""
from pathlib import Path
from datetime import date
import json
import sys
import time

from czsc_trader.application import create_experiment, ExperimentRequest, publish_evidence
from czsc_trader.research_tools import ExperimentRef, ResearchExecutionSession, EvaluationEvidenceWrite
from czsc_trader.research_tools.equity_replay import materialize_equity
from s001_context import build_context, build_request

ROOT = Path.cwd()
OUT = ROOT/'.tmp/s001-v4-correction/accounts'
OUT.mkdir(exist_ok=True)


def save(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')


def main():
    work = []
    for version in ('v1','v2'):
        context,candidate = build_context(version)
        path = OUT/f'{version}-experiment.json'
        if path.exists():
            exp = ExperimentRef.from_dict(json.loads(path.read_text(encoding='utf-8')))
        else:
            exp = create_experiment(context,ExperimentRequest(f'S001-{version} 已完成周线纠偏与原生V4升级',
                '按原设计只读取已完成周线；原公式完整周输入与原生V4账户是否一致，并完成同版本升级技术检验？',date(2026,11,6)))
            save(path,exp.to_dict())
        save(OUT/f'{version}-candidate.json',candidate.payload)
        work.append((version,context,candidate,exp))
        print('PREPARED_EXPERIMENT',version,json.dumps(exp.to_dict()),candidate.content_identity.content_sha256,flush=True)
    if '--create-only' in sys.argv:
        return
    for version,context,candidate,exp in work:
        if len(sys.argv)>1 and sys.argv[1] in ('v1','v2') and sys.argv[1]!=version:
            continue
        before=time.monotonic()
        with ResearchExecutionSession(context,experiment=exp) as execution:
            prepared=context.evaluation.prepare(build_request(context,candidate,exp),execution=execution)
            save(OUT/f'{version}-binding.json',prepared.request.input_binding.to_dict())
            print('EVALUATING',version,'elapsed',time.monotonic()-before,flush=True)
            outcome,=context.evaluation.evaluate_many((prepared,),execution=execution)
            if outcome.result is None:
                raise RuntimeError(str(outcome.error))
            result=outcome.result
            materialized=materialize_equity(result).payload
            save(OUT/f'{version}-native-account.json',materialized)
            reference=publish_evidence(context,EvaluationEvidenceWrite(exp,'corrected-native-forward',prepared,result),execution=execution)
            save(OUT/f'{version}-native-reference.json',reference.to_dict())
        run=materialized['runs']['candidate']
        summary={'version':version,'candidate_id':candidate.candidate_id,'content_sha256':candidate.content_identity.content_sha256,
            'experiment':exp.to_dict(),'evidence':reference.to_dict(),'days':len(run['account_daily']),
            'fills':len(run['fills']),'orders':len(run['orders']),'elapsed_seconds':time.monotonic()-before}
        save(OUT/f'{version}-native-summary.json',summary)
        print('ACCOUNT_COMPLETE',json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
