"""Source-bound migration replay; no parameter proposal or candidate selection."""
from copy import deepcopy
from datetime import date
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path

import pandas as pd
from dataflows import Dataset
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentStage, ExperimentProtocol, ExperimentDependency, ExperimentCapabilities,
    ExperimentResult, ExperimentOutcome, ExperimentPrecheckResult,
    ExperimentPreflightCheck, ExperimentPreflightStatus,
)
from strategy_runtime import StrategyCandidate, StrategyRuntime, ImplementationDependency, canonical_sha256
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from czsc_trader.research_tools import EvaluationRequest, EvaluationWindow, EvaluationCost, EvaluationLineage, EvaluationBenchmark
from czsc_trader.application import RepositoryContext, load_candidate, register_candidate, CandidateRegistrationRequest
from strategy_manager import CandidateRegistrationOrigin
from research_experiment import load_experiment
from czsc_trader.backtesting.execution_data import prepare_backtest_execution_data

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
ID = ROOT.name
START, CUTOFF = date(2025, 2, 6), date(2026, 9, 28)
INPUTS = json.loads((ROOT / 'inputs.json').read_text(encoding='utf-8'))
BENCHMARK = EvaluationBenchmark.from_dict(INPUTS['benchmark'])
DEPS = tuple(ImplementationDependency(**x) for x in INPUTS['dependencies'])
LEDGERS = ('decisions', 'orders', 'fills', 'account_daily', 'trades')

def candidate(item, parent=None):
    spec = item if parent is None else parent
    payload = deepcopy(spec['definition'])
    if parent is not None:
        payload['parameters'] = item['parameters']
    return StrategyCandidate('S011', item['candidate_id'], payload, ROOT / spec['migrated_source_root'])

def normalized(frames):
    maps = {k: {} for k in ('decision_id', 'order_id', 'fill_id', 'cycle_id')}
    output = {}
    for name, frame in frames.items():
        frame = frame.copy()
        for key, mapping in maps.items():
            if key in frame:
                def value(v):
                    if pd.isna(v):
                        return v
                    if v not in mapping:
                        mapping[v] = f'{key}:{len(mapping)}'
                    return mapping[v]
                frame[key] = frame[key].map(value)
        output[name] = frame
    return output

def compare_history(run, historical):
    current = normalized({n: pd.read_csv(StringIO(getattr(run.execution, n).to_csv(index=False))) for n in LEDGERS})
    previous = normalized({n: pd.read_csv(REPO / historical / (n+'.csv.gz')) for n in LEDGERS})
    for name in LEDGERS:
        pd.testing.assert_frame_equal(current[name], previous[name], check_dtype=False, rtol=1e-12, atol=1e-8)
    return {'status': 'EQUIVALENT', 'ledgers': list(LEDGERS), 'historical': historical,
            'absolute_tolerance': 1e-8, 'relative_tolerance': 1e-12,
            'normalization': 'bijective decision/order/fill/cycle identifiers only'}

class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2, experiment_id=ID, strategy_id='S011', mode=ExperimentMode.FORMAL,
            data_scope=ExperimentDataScope.DEVELOPMENT,
            research_question='Can current managed identities reproduce the approved historical S011 accounts?',
            hypothesis='Explicit limit BuyHold and unchanged strategies reproduce historical standard and stress accounts.',
            falsification_conditions=('Any economic ledger differs beyond serialization tolerance', 'A historical source hash changes'),
            development_cutoff=CUTOFF, random_seed=20261001,
            allowed_datasets=tuple(x.value for x in (Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY,
                Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY, Dataset.GLOBAL_INDEX_DAILY, Dataset.TRADING_CALENDAR)),
            subjects=('159326.SZ',), dependencies=tuple(ExperimentDependency(**x) for x in INPUTS['dependencies']),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            protocol=ExperimentProtocol(ExperimentStage.ROBUSTNESS,
                ('Identity migration must preserve historical economic meaning and missing evidence',),
                ('DFLS current retrieval -> unchanged SRT implementation -> managed TDR full account -> historical ledger comparison',),
                ('36 standard and 35 existing stress accounts, plus 64 already-designed standard perturbation accounts',),
                ('Strategy and benchmark five-ledger equivalence', 'Authenticated candidate/evaluation and benchmark identities'),
                ('Single formal context; sequential requests; explicit runtime lot_size=100; no search or retry',
                 '403 development sessions, 1e6 cash, standard 10bp and stress 20bp per side',
                 'Stop on first mismatch, retain failure; no extra coverage or independent evidence claimed'),
                tuple(INPUTS['predecessors'])))

    def synthetic_precheck(self):
        centers = {x['config_id']: x for x in INPUTS['centers']}
        assert len(centers) == 36 and len(INPUTS['neighbors']) == 64
        assert sum(bool(x['pressure_evidence']) for x in centers.values()) == 35
        runtime = StrategyRuntime()
        for spec in centers.values():
            runtime.describe(candidate(spec))
        for spec in INPUTS['neighbors']:
            runtime.describe(candidate(spec, centers[spec['center_config_id']]))
            assert spec['parameters']['max_days'] == 2
        for center in {x['center_config_id'] for x in INPUTS['neighbors']}:
            points = [x for x in INPUTS['neighbors'] if x['center_config_id'] == center]
            assert len(points) == len({canonical_sha256(x['parameters']) for x in points}) == 16
        a = normalized({'fills': pd.DataFrame({'fill_id':['a','b'], 'cycle_id':['x','x'], 'price':[1.,2.]})})
        b = normalized({'fills': pd.DataFrame({'fill_id':['c','d'], 'cycle_id':['y','y'], 'price':[1.,2.]})})
        pd.testing.assert_frame_equal(a['fills'], b['fills'])
        return ExperimentPrecheckResult((ExperimentPreflightCheck('MIGRATION_SCOPE', ExperimentPreflightStatus.PASS,
            '36 centers, 64 unique within-parent points and identifier normalization validated'),),
            ExperimentResult(ExperimentOutcome.PASS, {'synthetic_only': True}, {}))

    def execute(self, context):
        for name, digest in INPUTS['historical_source_hashes'].items():
            assert sha256((REPO/name).read_bytes()).hexdigest() == digest, name
        data = prepare_backtest_execution_data(srt_data_root=REPO/'.tmp/s011-formal-migration/execution',
            symbol='159326.SZ', asset_type='etf', start=START, end=CUTOFF, dataflows=context.data)
        assert len(data.evaluation_sessions) == 403
        artifacts, results, parent_records = [], [], {}
        def save(name, value):
            context.workspace.path(name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
                encoding='utf-8', newline='\n')
            artifacts.append(context.workspace.register_artifact(name, 'S011-migration-evidence'))
        def evaluate(spec, parent=None):
            repository = RepositoryContext.discover(REPO)
            item = load_candidate(repository, CandidateKey('S011', spec['candidate_id'])) if parent is None else candidate(spec, parent)
            relation = None
            if parent is not None:
                record = parent_records[parent['config_id']]
                proof = context.workspace.path(f'evaluations/{record.attempt_id}/record.json')
                relation = CandidateDerivation(CandidateKey('S011', parent['candidate_id']), record.content_sha256,
                    CandidateKey('S011', item.candidate_id), StrategyRuntime().identify(item, dependencies=DEPS).content_sha256,
                    CandidateDerivationKind.PARAMETERS,
                    {k: {'before': parent['definition']['parameters'][k], 'after': v}
                     for k,v in spec['parameters'].items() if parent['definition']['parameters'][k] != v},
                    sha256((ROOT/'02_design.md').read_bytes()).hexdigest(),
                    CandidateEvidence(proof.relative_to(REPO).as_posix(), sha256(proof.read_bytes()).hexdigest()))
                origin = CandidateRegistrationOrigin(ID, self.definition.sha256,
                    sha256((ROOT/'experiment_binding.json').read_bytes()).hexdigest(),
                    CandidateEvidence((ROOT/'preflight.json').relative_to(REPO).as_posix(),
                                      sha256((ROOT/'preflight.json').read_bytes()).hexdigest()))
                registered = register_candidate(repository, CandidateRegistrationRequest(item, origin, DEPS, relation))
                save(f'registrations/{item.candidate_id}.json', registered.to_dict())
                item = load_candidate(repository, registered.key)
            costs = (EvaluationCost('standard', .001, 'FORMAL'),)
            if parent is None and spec['pressure_evidence']:
                costs += (EvaluationCost('fee_20bp', .002, 'STRESS'),)
            request = EvaluationRequest(repository_root=REPO, experiment_id=ID, strategy=item,
                runtime_binding={'candidate_id': item.reference_id, 'source_files': list(item.payload['runtime']['source_files']),
                    'implementation_sha256': item.payload['runtime']['source_sha256']},
                symbol='159326.SZ', asset_type='etf', windows=(EvaluationWindow('full', START, CUTOFF),),
                data_cutoff=CUTOFF, initial_cash=1e6, costs=costs, execution_data=data, workers=1,
                frequency_window_days=60, dependencies=DEPS, benchmark=BENCHMARK,
                lineage=None if relation is None else EvaluationLineage(relation))
            result = context.evaluation.evaluate(request)
            checks=[]
            for run in result.runs:
                history = (spec['standard_evidence'] if run.scenario_id=='standard' else spec['pressure_evidence']) if parent is None else (
                    f'experiments/S011/20260930_S011_EX28/artifacts/trials/T{spec["design_id"]:03}/standard')
                check=compare_history(run, history)
                benchmark_root = (REPO/'experiments/S011/20260930_S011_EX16/artifacts' if run.scenario_id=='standard'
                    else REPO/'experiments/S011/20260930_S011_EX26/artifacts/accounts/EX16BH/fee_20bp')
                current_benchmark = normalized({n: pd.read_csv(StringIO(getattr(run.buyhold.execution,n).to_csv(index=False))) for n in LEDGERS})
                prefix = 'benchmark_' if run.scenario_id == 'standard' else ''
                old_benchmark = normalized({n: pd.read_csv(benchmark_root/(prefix+n+'.csv.gz')) for n in LEDGERS})
                for name in LEDGERS:
                    pd.testing.assert_frame_equal(current_benchmark[name], old_benchmark[name], check_dtype=False, rtol=1e-12, atol=1e-8)
                check['benchmark'] = {'status':'EQUIVALENT','contract':BENCHMARK.to_dict(),
                    'contract_sha256':BENCHMARK.fingerprint,'ledgers':list(LEDGERS),
                    'historical':benchmark_root.relative_to(REPO).as_posix(),
                    'quantity':int(run.buyhold.execution.fills.iloc[0]['quantity']),
                    'end_equity':float(run.buyhold.account_daily.iloc[-1]['equity'])}
                check.update(candidate_id=item.reference_id, scenario=run.scenario_id, evaluation_id=run.identity.evaluation_id)
                checks.append(check)
            save(f'comparison/{item.candidate_id}.json', checks)
            if relation is not None:
                save(f'derivations/{item.candidate_id}.json', relation.to_dict())
            else:
                parent_records[spec['config_id']] = next(x for x in context.trace.evaluations if x.attempt_id==result.attempt_id)
            results.append({'candidate_id': item.reference_id, 'attempt_id': result.attempt_id,
                'evaluation_ids': [x.identity.evaluation_id for x in result.runs],
                'content_sha256': result.runs[0].identity.content_sha256,
                'historical_config': spec.get('config_id'), 'parent': None if parent is None else parent['config_id'],
                'checks': checks})
            print(json.dumps({'complete':len(results),'candidate':item.reference_id,'accounts':len(result.runs),'equivalence':'PASS'}), flush=True)
        centers = {x['config_id']: x for x in INPUTS['centers']}
        ordered = sorted(centers.values(), key=lambda x: (x['config_id']!='S011-CFG-000621', x['config_id']))
        for spec in ordered:
            evaluate(spec)
        for spec in INPUTS['neighbors']:
            evaluate(spec, centers[spec['center_config_id']])
        save('migration_results.json', results)
        save('input_contract.json', {'execution_data_fingerprint':data.fingerprint,'sessions':403,'lot_size':100,
            'standard_accounts':36,'stress_accounts':35,'perturbation_accounts':64,'independent_evidence':False,'benchmark':BENCHMARK.to_dict()})
        return ExperimentResult(ExperimentOutcome.PASS, {'candidate_calls':100,'accounts':135,'ledger_equivalence':'PASS','benchmark_ledger_equivalence':'PASS'},
            {'development_only':True,'new_parameter_search':False,'historical_limitations_preserved':True}, tuple(artifacts))
