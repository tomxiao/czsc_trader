"""One fixed candidate and shared buyhold through the current public TDR path."""
from pathlib import Path
import os
import sys
import json
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[5]
EXP_ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT/'.tmp/s018-target'
TMP.mkdir(parents=True, exist_ok=True)
os.environ.update(TEMP=str(TMP), TMP=str(TMP), PYTHONDONTWRITEBYTECODE='1',
                  OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
sys.dont_write_bytecode = True

from czsc_trader.application import RepositoryContext, publish_evidence
from czsc_trader.research_tools import (ExperimentRef, ResearchExecutionSession,
    EquityEvaluationRequest, EvaluationBenchmark, EquityBuyHold, EvaluationEvidenceWrite)
from dataflows import TimeInterval
from candidate import build_candidate
from data_inputs import build_data_context, FIRST


def save(name, value):
    path = EXP_ROOT/'others'/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8')


def main():
    candidate = build_candidate()
    experiment = ExperimentRef('S018', EXP_ROOT.name)
    repo = RepositoryContext.discover(ROOT)
    context, sources, provenance = build_data_context(repo, candidate.definition.execution_spec)
    save('data_provenance.json', provenance)
    save('candidate_definition.json', candidate.definition.to_dict())
    zone = ZoneInfo('America/New_York')
    request = EquityEvaluationRequest(experiment, candidate,
        TimeInterval(datetime(2023,1,3,9,30,tzinfo=zone), datetime(2026,10,30,16,tzinfo=zone)),
        FIRST, sources,100000.,.001,
        benchmark=EvaluationBenchmark(EquityBuyHold(candidate.definition.execution_spec)),
        drawdown_basis='BAR_CLOSE', concentration_basis='MAX_SINGLE')
    try:
        with ResearchExecutionSession(context, experiment=experiment) as execution:
            prepared = context.evaluation.prepare(request, execution=execution)
            save('prepared_binding.json', prepared.request.input_binding.to_dict())
            outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
            if outcome.result is None:
                save('replay_outcome.json', {'status':outcome.status.value, 'error':str(outcome.error),
                     'candidate_id':candidate.candidate_id, 'full_account_completed':False})
                print('REPLAY', outcome.status.value, outcome.error)
                return 1
            reference = publish_evidence(context, EvaluationEvidenceWrite(experiment, 'target-weight-account',
                                        prepared, outcome.result), execution=execution)
            save('account_reference.json', reference.to_dict())
            save('replay_outcome.json', {'status':'SUCCEEDED','result_hash':outcome.result.result_hash,
                 'candidate_id':candidate.candidate_id,'full_account_completed':True,
                 'reference':reference.to_dict()})
            print('REPLAY SUCCEEDED', outcome.result.result_hash)
            return 0
    except Exception as exc:
        save('replay_outcome.json', {'status':'FAILED', 'error_type':type(exc).__name__,
             'error':str(exc),'traceback':traceback.format_exc(),'full_account_completed':False})
        print(traceback.format_exc())
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
