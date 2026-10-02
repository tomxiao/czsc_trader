"""S011 technical registration adaptation; no market evaluation or search."""
from datetime import date
from hashlib import sha256
from pathlib import Path
import ast
import importlib.util
import json

import numpy as np
import pandas as pd
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentStage, ExperimentProtocol, ExperimentDependency, ExperimentCapabilities,
    ExperimentCapability, ExperimentResult, ExperimentOutcome, ExperimentPrecheckResult,
    ExperimentPreflightCheck, ExperimentPreflightStatus,
)
from strategy_runtime import StrategyCandidate, StrategyRuntime, ImplementationDependency
from strategy_manager import CandidateKey, CandidateEvidence, CandidateRegistrationOrigin
from czsc_trader.application import RepositoryContext, CandidateRegistrationRequest, register_candidate, load_candidate

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
INPUTS = json.loads((ROOT / 'inputs.json').read_text(encoding='utf-8'))
DEPS = tuple(ImplementationDependency(**item) for item in INPUTS['dependencies'])


def candidate(spec):
    return StrategyCandidate('S011', spec['candidate_id'], spec['payload'], ROOT / spec['runtime_root'])


def verify_sources():
    modules = {}
    additions = {'ObservationDefinition', 'ObservationSeries', 'ObservationFact', 'ConstantGuide',
                 'ObservationValueType', 'ObservationFormat'}
    for source in INPUTS['sources'].values():
        old = ast.parse((REPO / source['old_source']).read_text(encoding='utf-8'))
        path = ROOT / source['runtime_root'] / 'strategies/s011_reversal.py'
        new = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(new):
            if isinstance(node, ast.ImportFrom) and node.module == 'strategy_runtime':
                node.names = [item for item in node.names if item.name not in additions]
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'RuntimeDefinition':
                node.keywords = [item for item in node.keywords if item.arg != 'observation']
                for item in node.keywords:
                    if item.arg == 'schema_version':
                        assert item.value.value == 3
                        item.value.value = 2
        assert ast.dump(new) == ast.dump(old), 'Changes exceed runtime schema and observation declaration'
        spec = importlib.util.spec_from_file_location('s011_' + source['source_sha256'], path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[source['runtime_root']] = module
    return modules


def synthetic_validation():
    modules = verify_sources()
    sessions = pd.bdate_range('2025-01-01', periods=280)
    t = np.arange(len(sessions))
    panel = pd.DataFrame({'tail': np.sin(t / 5), 'market': np.cos(t / 7),
                          'spx': np.sin(t / 9), 'risk5': 0.02}, index=sessions)
    runtime = StrategyRuntime()
    for spec in INPUTS['candidates']:
        current = candidate(spec)
        definition = runtime.describe(current)
        previous_root = REPO / 'experiments/S011' / spec['previous_experiment_id']
        previous_file = previous_root / spec['previous_payload']['path']
        assert sha256(previous_file.read_bytes()).hexdigest() == spec['previous_payload']['sha256']
        previous = json.loads(previous_file.read_text(encoding='utf-8'))
        assert dict(definition.parameters.values) == previous['parameters']
        assert definition.schema_version == 3 and definition.execution.settings['instrument']['lot_size'] == 100
        assert runtime.identify(current, dependencies=DEPS).schema_version == 2
        frame = modules[spec['runtime_root']].policy(panel, previous['parameters'], sessions[-40:])
        assert len(frame) == 40 and set(frame.target_position) <= {0, 1}
        declaration = definition.observation
        assert declaration.series[0].guides[0].value == previous['parameters']['entry']
        assert declaration.series[0].guides[1].value == previous['parameters']['exit']
        row = frame.iloc[-1].to_dict()
        for fact in declaration.facts:
            fact.validate_value(row[fact.value_field])
        assert np.isfinite(frame.score).all()
    return {'candidate_count': 612, 'source_closures': 2, 'synthetic_rows_per_candidate': 40,
            'real_market_evaluations': 0, 'evaluation_status': 'NOT_EVALUATED'}


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2, experiment_id=ROOT.name, strategy_id='S011',
            mode=ExperimentMode.DISCOVERY, data_scope=ExperimentDataScope.DEVELOPMENT,
            development_cutoff=date(2026, 9, 28), random_seed=38,
            research_question='Can current S011 candidates load under the current platform contract without changing trading logic?',
            hypothesis='Only IDs, runtime schema and typed observation declarations change.',
            falsification_conditions=('Any trading logic or parameter changes', 'Any historical evaluation is relabeled as current evidence'),
            allowed_datasets=('etf.ohlcv',), subjects=('159326.SZ',),
            dependencies=tuple(ExperimentDependency(**item) for item in INPUTS['dependencies']),
            capabilities=ExperimentCapabilities(creates_candidate=True),
            protocol=ExperimentProtocol(
                ExperimentStage.CANDIDATE, ('Runtime identity is separate from research certification',),
                ('Historical source and parameters -> current runtime -> explicit registration',),
                ('Adapt 612 fixed candidates without evaluation or parameter search',),
                ('Loadability, source AST invariance, typed synthetic observations',),
                ('Engineering adaptation only; historical sources are byte-checked inputs, not certified predecessor research results',),
            ),
        )

    def synthetic_precheck(self):
        facts = synthetic_validation()
        return ExperimentPrecheckResult(
            (ExperimentPreflightCheck('TECHNICAL_ADAPTATION', ExperimentPreflightStatus.PASS,
                                      '612 fixed candidates pass source, parameter and synthetic observation checks'),),
            ExperimentResult(ExperimentOutcome.PASS, facts, {'research_evidence': False}),
        )

    def execute(self, context):
        context.require_capability(ExperimentCapability.CREATE_CANDIDATE)
        repository = RepositoryContext.discover(REPO)
        preflight = ROOT / 'preflight.json'
        origin = CandidateRegistrationOrigin(
            ROOT.name, self.definition.sha256, sha256((ROOT / 'experiment_binding.json').read_bytes()).hexdigest(),
            CandidateEvidence(preflight.relative_to(REPO).as_posix(), sha256(preflight.read_bytes()).hexdigest()),
        )
        entries = []
        for number, spec in enumerate(INPUTS['candidates'], 1):
            record = register_candidate(repository, CandidateRegistrationRequest(candidate(spec), origin, DEPS))
            loaded = load_candidate(repository, CandidateKey('S011', spec['candidate_id']))
            assert StrategyRuntime().identify(loaded, dependencies=DEPS).content_sha256 == record.content_sha256
            entries.append({
                'candidate_id': spec['candidate_id'], 'reference_id': loaded.reference_id,
                'content_sha256': record.content_sha256, 'source_sha256': record.source_sha256,
                'registration_sha256': record.record_sha256,
                'parent_candidate_id': spec['parent_candidate_id'],
                'previous_candidate_id': spec['previous_candidate_id'],
                'previous_content_sha256': spec['previous_content_sha256'],
                'historical_derivation': spec['historical_derivation'],
                'historical_evidence_experiment_id': spec['previous_experiment_id'],
                'evaluation_status': 'NOT_EVALUATED',
                'derivation_certification': 'PENDING_CURRENT_PARENT_EVALUATION' if spec['parent_candidate_id'] else 'NOT_APPLICABLE',
            })
            if number % 100 == 0:
                print(f'Registered and loaded {number}/612', flush=True)
        result = {'schema_version': 1, 'strategy_id': 'S011', 'experiment_id': ROOT.name,
                  'kind': 'TECHNICAL_ADAPTATION', 'evaluation_status': 'NOT_EVALUATED',
                  'real_market_evaluations': 0, 'parameter_searches': 0, 'candidates': entries}
        context.workspace.path('candidates.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n',
        )
        artifact = context.workspace.register_artifact('candidates.json', 'technical_candidate_index')
        return ExperimentResult(ExperimentOutcome.PASS,
            {'registered': len(entries), 'centers': 36, 'perturbations': 576, 'evaluation_status': 'NOT_EVALUATED'},
            {'research_evidence': False, 'historical_derivations_not_certified_for_current_identity': 576},
            (artifact,),
        )
