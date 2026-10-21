"""S015 stage-four identities and public evaluation requests."""
import json
import os
from pathlib import Path
from datetime import date
from collections.abc import Mapping

for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'

from czsc_trader.application import RepositoryContext,create_research_context,load_candidate  # noqa: E402
from czsc_trader.research_tools import (ResearchBatchRef,ExperimentRef,EvaluationResources,  # noqa: E402
    EvaluationRequest,EvaluationWindow,EvaluationCost,EvaluationBenchmark,LimitBuyHold,EvidenceRef)
from strategy_manager import CandidateKey  # noqa: E402

ROOT=Path(__file__).resolve().parents[5]
EXPERIMENT=ExperimentRef('S015','EX005_20261022')
EROOT=EXPERIMENT.resolve(ROOT)
WORK=ROOT/'research/S015/assets/runs/EX005_20261022/assessment'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path,data):
    def plain(x):
        if isinstance(x,Mapping):
            return {k:plain(v) for k,v in x.items()}
        if isinstance(x,(list,tuple)):
            return [plain(v) for v in x]
        return x
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(plain(data),ensure_ascii=False,indent=2,default=str),encoding='utf-8',newline='\n')


def context():
    return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=EvaluationResources(8,1,13))


def family_rows():
    old=ROOT/'research/S015/assets/runs/EX003_20261021/strategy_study'
    new=ROOT/'research/S015/assets/runs/EX004_20261022/range_weights'
    return read(old/'grid_results.json')+read(old/'extension_results.json')+sum((read(new/f'{p}_results.json') for p in ('initial','followup','boundary')),[])


def account(row):
    return read(EvidenceRef.from_dict(row['evidence']).resolve(ROOT))


def request(row):
    c=load_candidate(RepositoryContext.discover(ROOT),CandidateKey('S015',row['candidate_id']))
    return EvaluationRequest(ROOT,row['evidence']['experiment']['experiment_id'],c,{
        'candidate_id':c.reference_id,'source_files':list(c.payload['runtime']['source_files']),
        'implementation_sha256':c.payload['runtime']['source_sha256']},'159326.SZ','etf',
        (EvaluationWindow('full',date(2025,1,2),date(2026,10,21)),),date(2026,10,21),100000.,
        (EvaluationCost('standard',.001),),benchmark=EvaluationBenchmark(LimitBuyHold(100,.01,.001,.1,1000000)))
