"""Fixed S015 stage-four checks; original identities and public evidence APIs."""
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'

import argparse
from collections import Counter
from datetime import date
from dataclasses import replace
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd

from czsc_trader.application import (RepositoryContext, create_research_context, load_candidate,
    publish_evidence, open_research_execution, validate_delivery)
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, ExecutionResources,
    EvidenceRef, MaterialEvidenceWrite, EvaluationRequest, EvaluationWindow, EvaluationCost,
    EvaluationBenchmark, LimitBuyHold, EvaluationEvidenceWrite)
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from strategy_manager import CandidateKey
from strategy_runtime import StrategyRuntime
from strategy_evaluator import research_models as m
from strategy_evaluator import assess_candidates, compare_candidates, annualized_sharpe, effective_trial_count

ROOT = Path(__file__).resolve().parents[5]
EX = ExperimentRef('S015', 'EX063_20261024')
HOME = EX.resolve(ROOT)
OUT = HOME / 'others'
BATCH = ResearchBatchRef('S015')
VERSION = 'S015-EX063-stage4-v1'
FAMILY_EX = tuple(range(52, 57)) + tuple(range(58, 63))
CENTERS = ('C5806','C5901','C5902','C6015','C6016','C6017','C6018','C6101',
           'C6104','C6105','C6116','C6117','C6201','C6202','C6203','C6206')

def read(p):
    return json.loads(p.read_bytes())

def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')

def ctx(workers=4):
    return create_research_context(RepositoryContext.discover(ROOT), BATCH,
                                  resources=ExecutionResources(workers, 1, 13))

def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

def material(context, path, name=None):
    mime = {'.json':'application/json', '.py':'text/x-python', '.md':'text/markdown', '.csv':'text/csv'}
    return publish_evidence(context, MaterialEvidenceWrite(EX, name or path.stem,
        path.read_bytes(), mime[path.suffix], path.suffix[1:]))

def source_rows():
    return [row for number in FAMILY_EX for row in
            read(HOME.parent / f'EX{number:03d}_20261024/others/results.json')['rows']]

def protocol():
    return m.SelfCheckProtocol(version=VERSION, baseline_window='full', standard_scenario='standard',
        stress_scenario='fee_x2', rolling_window_days=252, rolling_step_days=21,
        quantile_method=m.QuantileMethod.LINEAR, minimum_perturbations=32,
        minimum_rolling_windows=1, bootstrap_repetitions=2000, bootstrap_block_length=10,
        seed=13, reconciliation_tolerance=1e-7, pbo_blocks=10,
        parameter_protocol=m.ParameterPerturbationProtocol(), frequency_min_closed_cycles=3)

def policy():
    metrics = (*m.BENCHMARK_METRICS, *m.WITHIN_LAYER_METRICS, m.ResearchMetric.FREQUENCY_MEDIAN)
    special = {m.ResearchMetric.PROFIT_CONCENTRATION:.01, m.ResearchMetric.FREQUENCY_MEDIAN:1.}
    bins = tuple(m.MetricBinSpec(x, special.get(x,.001), 0., m.BinRounding.FLOOR) for x in metrics)
    variants = (m.ComparisonVariant('bins_half', tuple(replace(x,resolution=x.resolution*.5) for x in bins)),
        m.ComparisonVariant('bins_double', tuple(replace(x,resolution=x.resolution*2) for x in bins)),
        *(m.ComparisonVariant(f'adjacent_swap_{i}',bins,i) for i in range(5)))
    return m.ComparisonPolicy(VERSION,bins,m.ParetoBasis.RAW,m.MissingEvidencePolicy.REQUIRE_COMPLETE,variants)

def predecessor(stage, revision, expected):
    folder = ROOT / f'research/S015/assets/deliveries/{stage}/{revision}'
    receipt = d.DeliveryReceipt.from_dict(read(folder/'receipt.json'))
    assert receipt.reference.content_sha256 == expected
    public = ROOT / f'research/S015/deliveries/{stage}/{revision}/receipt.json'
    assert public.read_bytes() == (folder/'receipt.json').read_bytes()
    return receipt.reference, read(folder/'delivery.json')['content']['payload']

def prepare():
    assert not (OUT/'protocol_refs.json').exists()
    context = ctx(1)
    cref, candidate_set = predecessor('CANDIDATES',6,'9e021c2a0ed2361ed7f06b916a0935ac4a08de73c9519fbeea7f477af0c2b9e1')
    mref, _ = predecessor('MANDATE',3,'5563c98c1a2ed876b6d75b775437f35ec2c31777818ad0f9b67e89c90d30d90a')
    assert {x['candidate_id'] for x in candidate_set['handoff']} == set(CENTERS)
    rows = [r for r in source_rows() if r['candidate_id'] in CENTERS]
    assert len(rows) == 16
    identities = {}
    for row in rows:
        c = load_candidate(RepositoryContext.discover(ROOT),CandidateKey('S015',row['candidate_id']))
        ident = StrategyRuntime().identify(c,dependencies=())
        assert ident.content_sha256 == row['identity']['content_sha256']
        identities[row['candidate_id']] = m.AssessmentCandidate(c.reference_id,ident.content_sha256)
    from parameter_geometry import build_geometry
    geometry = build_geometry(rows, identities)
    save(OUT/'centers.json', rows)
    save(OUT/'geometry.json', geometry)
    prospective = {
        'version':VERSION,'authorization':'用户：同意，请自主完成阶段四',
        'source_candidates':cref.to_dict(),'source_mandate':mref.to_dict(),
        'centers':list(CENTERS),'self_check':protocol().to_dict(),'comparison':policy().to_dict(),
        'new_account_plan':{'fee_x2':16,'serial_equivalence':1,'parameter':0},
        'parameter_disposition':'Fixed 5% sphere cannot supply32 distinct effective points; retain failed design. Do not execute or count partial points.',
        'stress':'Original registered identities, full434 days, EvaluationCost fee_x2=.002; public replay overrides capital fee and executed fee together. Same-cost LimitBuyHold.',
        'data':'Reuse approved S015 inputs, cutoff2026-10-21; full2025-01-02..2026-10-21; no new providers.',
        'diagnostics':'Reuse authenticated full standard accounts for252/21 rolling windows, closed-cycle concentration, bootstrap2000/block10/seed13; annual and final252 windows descriptive only.',
        'family':'All176 executable standard configurations EX052..056 and EX058..062, including failures and duplicate paths. Broader earlier S015 adaptive/feature selection remains outside this homogeneous matrix, not reset or claimed fully counted.',
        'discrete_sensitivity':'Reuse stage-three hold/lookback controls only; no substitute radius or unapproved discrete parameter acceptance.',
        'resources':{'workers':4,'native_threads':1,'seed':13},
        'stop':'Complete prescribed applicable checks and explicit gaps, no forced qualification; no stage5, freeze, PTE, platform edits or new search.'}
    save(HOME/'protocols/stage4.json',prospective)
    refs = {}
    for p in (Path(__file__),HOME/'src/parameter_geometry.py',OUT/'centers.json',OUT/'geometry.json',HOME/'protocols/stage4.json'):
        refs[p.relative_to(ROOT).as_posix()] = material(context,p).to_dict()
    save(OUT/'protocol_refs.json',refs)
    print('PROTOCOL_PUBLISHED',len(rows),flush=True)

def assert_protocol():
    for path, ref in read(OUT/'protocol_refs.json').items():
        assert EvidenceRef.from_dict(ref).resolve(ROOT).read_bytes() == (ROOT/path).read_bytes()

def stress_request(context, row):
    c = load_candidate(RepositoryContext.discover(ROOT),CandidateKey('S015',row['candidate_id']))
    return context.evaluation.prepare(EvaluationRequest(ROOT,EX.experiment_id,c,
        {'candidate_id':c.reference_id,'source_files':list(c.payload['runtime']['source_files']),
         'implementation_sha256':c.payload['runtime']['source_sha256']},'159326.SZ','etf',
        (EvaluationWindow('full',date(2025,1,2),date(2026,10,21)),),date(2026,10,21),100000.,
        (EvaluationCost('fee_x2',.002,'STRESS'),),benchmark=EvaluationBenchmark(LimitBuyHold(100,.01,.001,.1,1000000))))

def run_stress():
    assert_protocol()
    assert not (OUT/'stress_results.json').exists()
    context = ctx()
    rows = read(OUT/'centers.json')
    requests = [stress_request(context,row) for row in rows]
    first = ctx(1).evaluation.evaluate(requests[0])
    serial = publish_evidence(context,EvaluationEvidenceWrite(EX,'serial_fee_x2',requests[0],first))
    save(OUT/'serial_fee_x2.json',{'evidence':serial.to_dict(),'result_hash':first.result_hash})
    results = []
    with open_research_execution(context,experiment=EX) as session:
        for start in range(0,len(rows),4):
            block = requests[start:start+4]
            evaluated = context.evaluation.evaluate_many(tuple(block),execution=session)
            for i,(req,out) in enumerate(zip(block,evaluated,strict=True)):
                if out.status.value != 'SUCCEEDED':
                    save(OUT/'stress_failure.json',{'candidate_id':req.strategy.candidate_id,'error':str(out.error),'completed':len(results)})
                    raise RuntimeError(out.error)
                result = out.result
                if start+i == 0:
                    assert result.result_hash == first.result_hash
                    for name in ('account_daily','decisions','orders','fills','trades'):
                        pd.testing.assert_frame_equal(getattr(result.runs[0].execution,name),getattr(first.runs[0].execution,name))
                ref = publish_evidence(context,EvaluationEvidenceWrite(EX,req.strategy.candidate_id+'_fee_x2',req,result))
                result_row = {'candidate_id':req.strategy.candidate_id,'request_hash':result.request_hash,
                              'result_hash':result.result_hash,'evidence':ref.to_dict()}
                results.append(result_row)
                for name in ('account_daily','decisions','orders','fills','trades'):
                    getattr(result.runs[0].execution,name).to_csv(OUT/f'{req.strategy.candidate_id}_fee_x2_{name}.csv',index=False)
                save(OUT/'stress_progress.json',results)
                print('STRESS_COMPLETE',req.strategy.candidate_id,len(results),flush=True)
    save(OUT/'stress_results.json',results)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=('prepare','stress'))
    action = parser.parse_args().action
    {'prepare':prepare,'stress':run_stress}[action]()
