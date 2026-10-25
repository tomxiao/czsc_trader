"""Authorized date-boundary adaptation with exact historical economic proof."""
from __future__ import annotations

# ruff: noqa: E402 -- constrain native threads before numerical imports
import argparse
from collections.abc import Mapping
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
sys.dont_write_bytecode = True
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import cloudpickle
from czsc_trader.application import (
    RepositoryContext, create_research_context, load_candidate, publish_evidence,
    CandidateRegistrationRequest, register_candidate, record_research_decision,
)
from czsc_trader.research_tools import (
    ResearchBatchRef, ExperimentRef, ExecutionResources, MaterialEvidenceWrite, EvidenceRef,
    EvaluationRequest, EvaluationWindow, EvaluationCost, EvaluationBenchmark, LimitBuyHold,
    EvaluationEvidenceWrite, EvaluationLineage,
)
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from strategy_runtime import (
    StrategyCandidate, StrategyRuntime, StrategyInit, StrategyInputBinding, implementation_sha256,
)
from strategy_manager import CandidateKey, CandidateEvidence, CandidateDerivation, CandidateDerivationKind
from strategy_manager import freeze_contracts as f
from strategy_evaluator import (
    ReplayEvidence, compare_ledgers, LedgerComparisonRequest, LedgerComparisonMode, LedgerComparisonStatus,
)

ROOT = Path(__file__).resolve().parents[5]
EX = ExperimentRef('S015', 'EX082_20261025')
HOME = EX.resolve(ROOT)
OUT = HOME / 'others'
CACHE = ROOT / '.tmp/s015-ex082'
SOURCE = HOME / 'src/strategy_runtime'
KEY = CandidateKey('S015', 'C9700')
PARENT = CandidateKey('S015', 'C9304')
PARENT_CONTENT = 'abf26e331cac4cd030c30aa5f84269e0471d3a4c31b36f5e9f8a0dbf687beda1'
PREVIOUS = HOME.parent / 'EX081_20261025'
sys.path.insert(0, str(PREVIOUS / 'src'))
import run_inspection as original


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def plain(value):
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def context():
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'),
                                   resources=ExecutionResources(4, 1, 13))


def material(ctx, path):
    media = {'.json': 'application/json', '.py': 'text/x-python', '.md': 'text/markdown',
             '.pkl': 'application/octet-stream'}[path.suffix]
    return publish_evidence(ctx, MaterialEvidenceWrite(EX, path.stem, path.read_bytes(), media, path.suffix[1:]))


def candidate(ctx):
    parent = load_candidate(ctx.repository, PARENT)
    assert StrategyRuntime().identify(parent, dependencies=()).content_sha256 == PARENT_CONTENT
    payload = plain(parent.payload)
    payload['runtime']['source_sha256'] = implementation_sha256(payload['runtime']['source_files'], source_root=SOURCE)
    return StrategyCandidate('S015', KEY.candidate_id, payload, SOURCE)


def old_replays():
    return original.replays()


def rebind(ctx, child, old_binding, execution_data, tag):
    """Re-derive the new candidate plan from existing authenticated data, offline."""
    old = old_binding.plan
    instance = StrategyRuntime(ctx.repository.strategy_root, dataflows=ctx.data).create(StrategyInit(
        child, old.tradable_window, CACHE / 'bindings' / tag, pricing=execution_data.pricing))
    calendar = ctx.data.fetch(old.requests[old.calendar_name], prepared=old_binding.prepared)
    kwargs = {}
    if '__trading_status' in old.requests:
        kwargs = {'trading_status': ctx.data.fetch(old.requests['__trading_status'], prepared=old_binding.prepared),
                  'status_request': old.requests['__trading_status']}
    plan = instance.plan_inputs(calendar, **kwargs)
    before, after = old.to_dict(), plan.to_dict()
    before.pop('strategy')
    after.pop('strategy')
    assert before == after, 'Non-identity input plan changed'
    binding = StrategyInputBinding(plan, old_binding.prepared)
    instance.prepare_data(binding=binding)
    assert instance.input_binding == binding
    return binding


def prepare():
    assert not (OUT / 'prepared.json').exists()
    ctx = context()
    child = candidate(ctx)
    identity = StrategyRuntime().identify(child, dependencies=())
    assert identity.content_sha256 != PARENT_CONTENT
    assert (OUT / 'source_change.json').exists() and (OUT / 'calendar_boundary.json').exists()
    auth = {'verbatim': '批准', 'source': 'human reply to the quoted minimum-scope proposal in this conversation',
        'approved_proposal': '只解除研究日期上界，保持金融逻辑、参数及资金规则不变，生成新内容身份后复验历史等价和阶段五。',
        'parent': PARENT.to_dict(), 'parent_content_sha256': PARENT_CONTENT,
        'successor': KEY.to_dict(), 'successor_content_sha256': identity.content_sha256,
        'scope': 'Technical date-boundary adaptation and inspection; no freeze or deployment authorization.'}
    save(OUT / 'user_approval.json', auth)
    protocol = {'candidate': KEY.to_dict(), 'content_sha256': identity.content_sha256,
        'parent': PARENT.to_dict(), 'parent_content_sha256': PARENT_CONTENT,
        'change': 'Remove LAST constant and only the end > LAST calendar guard; preserve every other source byte and all parameters.',
        'evaluation': 'Two new technical baseline accounts, full434, standard .001 and fee_x2 .002; same old prepared datasets and execution data, no future market fetch.',
        'acceptance': 'Public ECONOMIC five-ledger comparison with original C9304 at zero tolerance; exact signals/dtypes/window and buyhold. Stop on any difference.',
        'counting': 'One implementation-derived identity, no financial configuration search or new independent selection trial.',
        'boundary': 'Before FIRST still rejected, original cutoff and later request dates accepted without fetching data.',
        'resources': {'max_workers': 4, 'native_threads': 1},
        'stop': 'Do not freeze, deploy, change platform, alter tolerance or conceal differences.'}
    proto = HOME / 'protocols/adaptation.json'
    save(proto, protocol)
    protoref = material(ctx, proto)
    requests, refs = [], []
    for old in old_replays():
        scenario = old.coordinate.scenario_id
        derivation = CandidateDerivation(PARENT, PARENT_CONTENT, KEY, identity.content_sha256,
            CandidateDerivationKind.IMPLEMENTATION, {'calendar_request.end_upper_bound': 'removed research-only LAST'},
            protoref.sha256, CandidateEvidence(old.baseline.evidence.repository_path, old.baseline.evidence.sha256))
        binding = rebind(ctx, child, old.input_binding, old.execution_data, 'full-' + scenario)
        request = ctx.evaluation.prepare(EvaluationRequest(ROOT, EX.experiment_id, child,
            {'candidate_id': child.reference_id, 'source_files': list(child.payload['runtime']['source_files']),
             'implementation_sha256': child.payload['runtime']['source_sha256']},
            '159326.SZ', 'etf', (EvaluationWindow('full', date(2025, 1, 2), date(2026, 10, 21)),),
            date(2026, 10, 21), old.initial_cash,
            (EvaluationCost(scenario, old.one_way_cost, 'STRESS' if scenario == 'fee_x2' else 'FORMAL'),),
            execution_data=old.execution_data, benchmark=EvaluationBenchmark(LimitBuyHold(100, .01, .001, .1, 1000000)),
            lineage=EvaluationLineage(derivation), input_bindings={'full': binding}))
        assert request.execution_data.fingerprint == old.execution_data.fingerprint
        requests.append(request)
        refs.append({'scenario_id': scenario, 'old_baseline': old.baseline.to_dict(),
                     'new_input_binding': binding.to_dict(), 'execution_fingerprint': request.execution_data.fingerprint})
    CACHE.mkdir(parents=True, exist_ok=True)
    snapshot = CACHE / 'requests.pkl'
    snapshot.write_bytes(cloudpickle.dumps(tuple(requests)))
    save(OUT / 'identity.json', {'candidate': KEY.to_dict(), 'content_sha256': identity.content_sha256,
        'source_sha256': identity.source_sha256, 'parent_content_sha256': PARENT_CONTENT,
        'parameters': plain(child.payload['parameters'])})
    save(OUT / 'input_identity.json', refs)
    paths = [proto, OUT / 'user_approval.json', OUT / 'identity.json', OUT / 'input_identity.json',
             OUT / 'source_change.json', OUT / 'calendar_boundary.json', Path(__file__),
             HOME / 'src/source_check.py', *[SOURCE / x for x in child.payload['runtime']['source_files']]]
    references = {p.relative_to(ROOT).as_posix(): material(ctx, p).to_dict() for p in paths}
    save(OUT / 'prepared.json', {'references': references, 'requests': material(ctx, snapshot).to_dict(),
        'source_hashes': {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in paths}})
    print('ADAPTATION_PREPARED', identity.content_sha256, flush=True)


def run():
    assert not (OUT / 'results.json').exists()
    saved = read(OUT / 'prepared.json')
    for path, digest in saved['source_hashes'].items():
        assert sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    snapshot = EvidenceRef.from_dict(saved['requests'])
    requests = cloudpickle.loads(snapshot.resolve(ROOT).read_bytes())
    ctx = context()
    rows = []
    for req, old in zip(requests, old_replays(), strict=True):
        result = ctx.evaluation.evaluate(req)
        ref = publish_evidence(ctx, EvaluationEvidenceWrite(EX, req.costs[0].scenario_id, req, result))
        left_raw, right_raw = read(old.baseline.evidence.resolve(ROOT)), read(ref.resolve(ROOT))
        validate_evaluation_evidence(left_raw)
        validate_evaluation_evidence(right_raw)
        left, = left_raw['runs']
        right, = right_raw['runs']
        assert left['identity']['candidate'] == PARENT.to_dict() and right['identity']['candidate'] == KEY.to_dict()
        comparison = compare_ledgers(LedgerComparisonRequest(ReplayEvidence.from_dict(left['replay_evidence']),
            ReplayEvidence.from_dict(right['replay_evidence']), LedgerComparisonMode.ECONOMIC, 0.0))
        row = {'scenario_id': old.coordinate.scenario_id, 'evidence': ref.to_dict(),
            'old_baseline': old.baseline.to_dict(), 'comparison': comparison.to_dict(),
            'signals_equal': all(left[k] == right[k] for k in ('signals', 'signal_dtypes', 'signal_window')),
            'buyhold_equal': left['buyhold'] == right['buyhold'], 'request_hash': result.request_hash,
            'result_hash': result.result_hash}
        rows.append(row)
        save(OUT / ('comparison_' + old.coordinate.scenario_id + '.json'), row)
        assert comparison.status is LedgerComparisonStatus.EQUIVALENT and comparison.economic_sha256
        assert row['signals_equal'] and row['buyhold_equal']
        print('HISTORICAL_EQUIVALENCE_PASS', old.coordinate.scenario_id, flush=True)
    save(OUT / 'results.json', {'status': 'PASS', 'rows': rows, 'new_baseline_accounts': 2, 'new_search_trials': 0})


def register():
    ctx = context()
    result = read(OUT / 'results.json')
    assert result['status'] == 'PASS' and len(result['rows']) == 2
    saved = read(OUT / 'prepared.json')
    for path, digest in saved['source_hashes'].items():
        assert sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    requests = cloudpickle.loads(EvidenceRef.from_dict(saved['requests']).resolve(ROOT).read_bytes())
    child = candidate(ctx)
    registration = register_candidate(ctx.repository, CandidateRegistrationRequest(child, EX,
        tuple(EvidenceRef.from_dict(x['evidence']) for x in result['rows']), (), requests[0].lineage.derivation))
    loaded = load_candidate(ctx.repository, KEY)
    assert StrategyRuntime().identify(loaded, dependencies=()).content_sha256 == registration.content_sha256
    save(OUT / 'registration.json', registration.to_dict())
    approval = material(ctx, OUT / 'user_approval.json')
    selection = record_research_decision(ctx.repository, f.ResearchDecision('S015-select-C9700-adaptation-20261025',
        'S015', f.DecisionAction.APPROVE, f.CandidateSelectionSubject(KEY, registration.content_sha256, registration.record_sha256),
        CandidateEvidence(approval.repository_path, approval.sha256),
        '用户批准C9304最小日期适配并以新身份复验阶段五；C9700仅作该适配，历史完全等价已证，不批准冻结或部署。'))
    save(OUT / 'selection_ref.json', selection.to_dict())
    print('SUCCESSOR_REGISTERED_AND_SELECTED', KEY.candidate_id, registration.content_sha256, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'run', 'register'))
    {'prepare': prepare, 'run': run, 'register': register}[parser.parse_args().mode]()
