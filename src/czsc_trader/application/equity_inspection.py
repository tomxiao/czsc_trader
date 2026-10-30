"""Equity adapters for the existing inspection report, package and freeze lifecycle."""
from dataclasses import asdict, replace
from datetime import datetime
import json
from pathlib import Path
import shutil
import time
from uuid import uuid4

import pandas as pd
from dataflows import Dataflows, DataSpace, ProviderConfig, ProviderKey, ProviderBinding, PreparePolicy, EquityProduct
from dataflows.equity_data import sessions_from_metadata
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition, StrategyRuntime, canonical_sha256
from strategy_runtime.inspection import InspectionRuntimePermit, InspectionStage
from strategy_runtime.deployment import validate_release_package
from strategy_manager import StrategyRegistry, freeze_contracts as f
from .candidate_service import load_candidate
from .inspection_execution import Controller, Interrupted, equivalence_jobs, goal
from .inspection_contracts import InspectionPublicationError


def _json(value):
    def encode(x):
        if isinstance(x, datetime):
            return x.isoformat()
        raise TypeError(type(x).__name__)
    return json.loads(json.dumps(value, default=encode, allow_nan=False))


def replay_identity(replay):
    return {'runtime_kind': 'US_EQUITY', 'coordinate': replay.coordinate.to_dict(),
        'input_binding': _json(replay.input_binding.to_dict()),
        'window': _json(asdict(replay.window)), 'initial_cash': replay.initial_cash,
        'one_way_cost': replay.one_way_cost, 'baseline': None if replay.baseline is None else replay.baseline.to_dict()}


def _products(flows, replay):
    expected = replay.input_binding.expected_identities
    products, identities, calendars = {}, {}, {}
    for query in replay.requests:
        name = replay.input_binding.request_key(query)
        result = flows.fetch(query, prepared=replay.input_binding.prepared)
        if name in products or not result.ready or result.identity.content_sha256 != expected[name]:
            raise ValueError('inspection prepared input identity differs')
        role = name.rsplit(':', 1)[0] if name.startswith('auxiliary:') else 'primary'
        calendar = result.identity.metadata['sessions']
        if role in calendars and calendars[role] != calendar:
            raise ValueError('inspection input calendars differ')
        calendars[role] = calendar
        products[name] = result.dataframe
        identities[name] = {'content_sha256': result.identity.content_sha256, 'metadata': dict(result.identity.metadata)}
    if set(products) != set(expected):
        raise ValueError('inspection product coverage differs')
    return products, identities


def _records(frame):
    return json.loads(frame.to_json(orient='records', date_format='iso', date_unit='us'))


def replay_account(candidate, flows, replay):
    from trading_execution_engine.frozen_equity import _FrozenEquityExecutor
    from strategy_evaluator.frozen_equity import _audit_frozen_equity_account
    products, identities = _products(flows, replay)
    if candidate.execution_spec_hash != replay.input_binding.specification_hash or candidate.instrument != replay.input_binding.instrument:
        raise ValueError('technical replay market contract differs')
    if candidate.warmup_bars != replay.input_binding.warmup_bars:
        raise ValueError('technical replay warmup differs')
    if candidate.definition.auxiliary_inputs != tuple(x.input for x in replay.input_binding.auxiliary_inputs):
        raise ValueError('technical replay auxiliary contract differs')
    specification = candidate.definition.execution_spec
    executor = _FrozenEquityExecutor(specification=specification, initial_cash=replay.initial_cash,
                                        fee_rate=replay.one_way_cost, actions=products['actions'])
    account = StrategyRuntime(execution_spec=specification).create(candidate).run_window(
        products['bars'], products['constraints'], executor, start=replay.window.start,
        end=replay.window.end, fee_rate=replay.one_way_cost,
        auxiliary_histories={x.name: products[x.data_key(EquityProduct.BARS)] for x in candidate.definition.auxiliary_inputs},
        sessions=products['sessions'] if candidate.definition.session_context else None,
        trading_sessions=sessions_from_metadata(identities['sessions']['metadata']) if candidate.definition.session_context else ())
    facts = {name: _records(getattr(account, attr)) for name, attr in (
        ('decisions','decisions'), ('orders','orders'), ('fills','fills'), ('actions','corporate_action_entries'),
        ('account_points','account_points'), ('account_daily','account_daily'), ('trades','trades'))}
    source = {name: _records(frame) for name, frame in products.items()}
    audit = _audit_frozen_equity_account(initial_cash=replay.initial_cash, specification=asdict(specification),
        bars=source['bars'], action_facts=source['actions'], constraints=source['constraints'],
        fee_rate=replay.one_way_cost, decision_contract="FORMAL_V2",
        **{k: facts[k] for k in ('decisions','orders','fills','actions','account_points','trades')})
    return _json({'facts': facts, 'metrics': asdict(audit), 'source': source, 'data': identities,
                  'definition': candidate.definition.to_dict(), 'content_sha256': candidate.content_identity.content_sha256,
                  'input': replay_identity(replay)})


def compute_equity(base, space, candidate, verified, replay):
    flows = Dataflows(base_dir=base, space=space, providers=ProviderConfig(bindings={}))
    frozen = EquityStrategyCandidate(candidate.strategy_id, candidate.candidate_id,
        EquityStrategyDefinition.from_dict(dict(verified.release.payload['equity_definition'])), verified.source_root)
    if frozen.content_identity != candidate.content_identity:
        raise ValueError('frozen equity source identity differs')
    left, right = replay_account(candidate, flows, replay), replay_account(frozen, flows, replay)
    return {'runtime_kind': 'US_EQUITY', 'candidate': left, 'release': right,
            'release_hash': verified.release.release_hash, 'package_hash': verified.package_sha256,
            'passed': left == right, 'baseline': {'status': 'NOT_REQUESTED'}}


def _pte_compute(connection, payload):
    import pickle
    from paper_trading_engine.equity_inspection import inspect_equity_release
    try:
        candidate, binding, replay, permit, protocol = pickle.loads(payload)
        flows = Dataflows(base_dir=binding.base_dir, space=binding.space, providers=ProviderConfig(bindings={}))
        result = inspect_equity_release(candidate=candidate, dataflows=flows, binding=replay.input_binding,
            requests=replay.requests, initial_cash=replay.initial_cash, fee_rate=replay.one_way_cost,
            permit=permit, protocol=protocol)
        connection.send((True, result))
    except BaseException as exc:
        connection.send((False, {'type': type(exc).__name__, 'message': str(exc)}))
    finally:
        connection.close()


def _pte_job(candidate, flows, replay, permit, protocol, controller):
    import multiprocessing
    from ..research_tools._evaluation_workers import pack
    from .inspection_execution import _stop_worker
    context = multiprocessing.get_context('spawn')
    receive, send = context.Pipe(duplex=False)
    worker = context.Process(target=_pte_compute, args=(send, pack((candidate, flows.binding, replay, permit, protocol))))
    worker.start()
    send.close()
    try:
        while not receive.poll(.05):
            controller.tick()
            if not worker.is_alive():
                raise ValueError('equity PTE worker exited without confirmed result')
        ok, result = receive.recv()
        if not ok:
            raise ValueError('equity PTE worker failed: ' + result['message'])
        return result
    finally:
        _stop_worker(worker)
        receive.close()


def _baseline_matches(payload, replay, account, content_hash, candidate_key):
    from ..research_tools.equity_assessment import build_equity_assessment_payload
    evidence = build_equity_assessment_payload(payload)
    if replay.baseline.evaluation_ids and set(replay.baseline.evaluation_ids) != {x.evaluation_id for x in evidence}:
        raise ValueError('baseline evaluation coordinates differ')
    request = payload['request']
    if (request.get('implementation_hash') != content_hash or request['candidate_id'] != candidate_key.candidate_id
            or request['experiment']['strategy_id'] != candidate_key.strategy_id
            or request['window'] != _json(asdict(replay.window))
            or request['initial_cash'] != replay.initial_cash or request['fee_rate'] != replay.one_way_cost
            or request['specification_hash'] != replay.input_binding.specification_hash
            or any(payload['data'][k]['content_sha256'] != v for k, v in replay.input_binding.expected_identities.items())):
        raise ValueError('baseline technical identity differs')
    return all(payload['runs']['candidate'][k] == account['facts'][k] for k in account['facts'])


def _copy_inputs(flows, replay, workspace):
    products, identities = _products(flows, replay)
    # DFLS normalizes subclasses to DataRequest before invoking a provider;
    # EquityParameters retains the complete instrument/source/bounded query.
    requests = {q.parameters: replay.input_binding.request_key(q) for q in replay.requests}
    def fetch(request):
        if request.parameters not in requests:
            raise ValueError('isolated equity request differs from authenticated input')
        name = requests[request.parameters]
        return products[name].copy(deep=True), dict(identities[name]['metadata'])
    bindings = {ProviderKey(q.parameters.query.product, q.parameters.instrument.market, q.parameters.source):
                ProviderBinding(q.parameters.source.provider, q.parameters.source.revision, fetch) for q in replay.requests}
    target = Dataflows(base_dir=workspace, space=DataSpace(Path('inputs/equity/data')),
                      providers=ProviderConfig(equity_bindings=bindings))
    prepared = target.prepare(replay.requests, policy=PreparePolicy.REFRESH)
    if not prepared.ready:
        raise ValueError('isolated equity preparation failed: ' + '; '.join(
            item.error.message for item in prepared.items if not item.ready))
    copied = replace(replay, input_binding=replace(replay.input_binding, prepared=prepared.reference))
    _products(target, copied)
    return target, copied


def inspect_equity_candidate(context, request, control, registration, selection):
    from .inspection_service import _EvidenceStore, _copy_plan, _package, describe_inspection_environment
    owner = f.ResearchEvidenceOwner(request.candidate.strategy_id, request.experiment.experiment_id)
    store = _EvidenceStore(context, owner)
    run_id = 'inspection-' + uuid4().hex
    workspace = context.root / '.tmp' / 'strategy-inspection' / run_id
    workspace.mkdir(parents=True)
    controller = Controller(run_id, control, workspace)
    origin = f.CandidateOrigin(registration.key, registration.content_sha256, store.put_json(registration.to_dict()))
    protocol = store.put_json(_json(request.protocol.to_dict()))
    normalized = {'schema_version': 2, 'runtime_kind': 'US_EQUITY', 'candidate': request.candidate.to_dict(),
        'selection': request.selection.to_dict(), 'experiment': request.experiment.to_dict(), 'target': request.target.to_dict(),
        'protocol_sha256': protocol.sha256, 'replays': [replay_identity(x) for x in request.replays],
        'additional_files': [x.to_dict() for x in request.additional_files], 'remaining_risks': list(request.remaining_risks),
        'data_kind': request.data_kind.value}
    request_ref = store.put_json(normalized)
    environment_ref = plan = release = None
    behavior, pte = [], []
    quiescent = True
    try:
        controller.tick(force=True)
        environment = describe_inspection_environment(context)
        environment_ref = store.put_json(environment.to_dict())
        if request.protocol.pte.environment != environment:
            raise ValueError('equity inspection environment differs')
        candidate = load_candidate(context, request.candidate)
        if type(candidate) is not EquityStrategyCandidate:
            raise ValueError('equity inspection requires formal equity candidate')
        for replay in request.replays:
            if pd.Timestamp(replay.window.end).tz_convert(candidate.instrument.timezone).date() > request.target.selection_data_cutoff:
                raise ValueError('equity replay exceeds selection cutoff')
            if any(q.parameters.query.end > request.target.selection_data_cutoff for q in replay.requests):
                raise ValueError('equity technical inputs exceed selection cutoff')
            _products(request.research.data, replay)
        plan = _copy_plan(context, request, registration, store, origin)
        release, verified = _package(context, plan, store, workspace / 'repository', selection.subject)
        controller.stage = InspectionStage.EQUIVALENCE
        jobs = equivalence_jobs(request, candidate, verified, workspace, controller)
        for index, ok, facts in jobs.completed:
            replay = request.replays[index]
            if ok and replay.baseline is not None:
                _, data = replay.baseline.evidence._read_verified(context.root)
                baseline = json.loads(data)
                matches = _baseline_matches(baseline, replay, facts['candidate'], registration.content_sha256, registration.key)
                facts['baseline'] = {'status': 'PASS' if matches else 'FAIL', 'evidence': store.put(data).to_dict()}
                facts['passed'] = facts['passed'] and matches
            passed = ok and facts.get('passed') is True
            behavior.append(f.InspectionCaseResult('replay-' + str(index),
                f.InspectionStatus.PASS if passed else f.InspectionStatus.FAIL,
                f.InspectionReason.OK if passed else f.InspectionReason.BEHAVIOR_DIFFERENCE,
                'authenticated candidate/frozen equity account comparison', (store.put_json(facts),)))
        if jobs.interruption:
            raise jobs.interruption
        controller.stage = InspectionStage.PTE
        controller.tick(force=True)
        flows, replay = _copy_inputs(request.research.data, request.replays[0], workspace)
        frozen = EquityStrategyCandidate(candidate.strategy_id, candidate.candidate_id,
            EquityStrategyDefinition.from_dict(dict(verified.release.payload['equity_definition'])), verified.source_root)
        permit = InspectionRuntimePermit(run_id, verified.release.release_id, release.release_sha256,
            release.package_sha256, canonical_sha256(request.protocol.pte.to_dict()), workspace / 'repository', workspace)
        outcome = _pte_job(frozen, flows, replay, permit, request.protocol.pte, controller)
        coverage = store.put_json(_json(outcome))
        for case in outcome['scenarios']:
            status = f.InspectionStatus(case['status'])
            pte.append(f.InspectionCaseResult(case['case_id'], status,
                f.InspectionReason.OK if status is f.InspectionStatus.PASS else f.InspectionReason.PTE_FAILURE,
                case['summary'], (coverage,)))
        status = f.InspectionStatus(outcome['status'])
        pte.append(f.InspectionCaseResult('pte-coverage', status,
            f.InspectionReason.OK if status is f.InspectionStatus.PASS else f.InspectionReason.COVERAGE_MISSING,
            'normal PTE business path capability coverage', (coverage,)))
        controller.stage = InspectionStage.FINALIZE
        controller.tick(force=True)
        if load_candidate(context, request.candidate).content_identity != candidate.content_identity:
            raise ValueError('candidate changed during inspection')
        final = validate_release_package(workspace / 'repository/strategies', verified.release.release_id)
        if final.package_sha256 != release.package_sha256 or describe_inspection_environment(context) != environment:
            raise ValueError('package or environment changed during inspection')
        if StrategyRegistry(context.research_registry_root).get_candidate_registration(request.candidate) != registration:
            raise ValueError('registration changed during inspection')
    except InspectionPublicationError:
        raise
    except Exception as exc:
        quiescent = getattr(exc, 'quiescent', True)
        reason = exc.reason if isinstance(exc, Interrupted) else f.InspectionReason.EXECUTION_ERROR
        status = f.InspectionStatus.INCOMPLETE if reason in (f.InspectionReason.CANCELLED, f.InspectionReason.RESOURCE_LIMIT) else f.InspectionStatus.FAIL
        target = pte if controller.stage in (InspectionStage.PTE, InspectionStage.FINALIZE) else behavior
        target.append(f.InspectionCaseResult('execution-' + controller.stage.value.lower(), status, reason,
            str(exc), (store.put_json({'type': type(exc).__name__, 'message': str(exc)}),)))
    measurements = store.put_json({'run_id': run_id, 'elapsed_seconds': time.monotonic() - controller.started,
                                   'max_workers': control.max_workers, 'timeout_seconds': control.timeout_seconds})
    report = f.CandidateInspectionReport(run_id, owner, origin, request.selection, request_ref, protocol,
        environment_ref, plan, release, goal(behavior), goal(pte), measurements, request.remaining_risks)
    store.put_json(report.to_dict())
    if quiescent:
        shutil.rmtree(workspace)
    return report


def validate_pass_facts(root, report, normalized, protocol):
    from .research_evidence import _read
    from strategy_evaluator.frozen_equity import _audit_frozen_equity_account
    from paper_trading_engine.equity_inspection import verify_equity_inspection_facts
    if len(report.behavior_equivalence.cases) != len(normalized['replays']):
        raise ValueError('equity replay coverage differs')
    for index, (case, replay) in enumerate(zip(report.behavior_equivalence.cases, normalized['replays'], strict=True)):
        if case.case_id != 'replay-' + str(index):
            raise ValueError('equity replay case identity differs')
        facts = _read(case.evidence[0].resolve(root))
        left, right = facts['candidate'], facts['release']
        if not facts['passed'] or left != right or left['input'] != replay:
            raise ValueError('equity equivalent facts differ')
        if facts['release_hash'] != report.release.release_sha256 or facts['package_hash'] != report.release.package_sha256:
            raise ValueError('equity replay release identity differs')
        definition = EquityStrategyDefinition.from_dict(left['definition'])
        if definition.content_identity.content_sha256 != report.origin.content_sha256 or left['content_sha256'] != report.origin.content_sha256:
            raise ValueError('equity replay content differs')
        ledger, source = left['facts'], left['source']
        audit = _audit_frozen_equity_account(initial_cash=replay['initial_cash'], specification=asdict(definition.execution_spec),
            bars=source['bars'], action_facts=source['actions'], constraints=source['constraints'],
            fee_rate=replay['one_way_cost'], decision_contract="FORMAL_V2",
            **{k: ledger[k] for k in ('decisions','orders','fills','actions','account_points','trades')})
        if _json(asdict(audit)) != left['metrics']:
            raise ValueError('equity replay audit differs')
        expected_times = [x['Date'] for x in source['bars'] if pd.Timestamp(x['BarStart']) >= pd.Timestamp(replay['window']['start'])
                          and pd.Timestamp(x['Date']) <= pd.Timestamp(replay['window']['end'])]
        if [x['time'] for x in ledger['account_points']] != expected_times:
            raise ValueError('equity replay account coverage differs')
        daily = {}
        for point in ledger['account_points']:
            daily[point['session']] = point
        if list(daily.values()) != ledger['account_daily']:
            raise ValueError('equity replay daily observations differ')
        if replay['baseline'] is None:
            if facts['baseline'] != {'status': 'NOT_REQUESTED'}:
                raise ValueError('unexpected equity baseline')
        else:
            from types import SimpleNamespace
            from dataflows import TimeInterval
            from strategy_runtime import EquityInputBinding
            base_ref = f.ResearchEvidenceRef.from_dict(facts['baseline']['evidence'])
            if base_ref.sha256 != replay['baseline']['evidence']['sha256'] or facts['baseline']['status'] != 'PASS':
                raise ValueError('equity baseline source identity differs')
            request = SimpleNamespace(baseline=SimpleNamespace(evaluation_ids=replay['baseline']['evaluation_ids']),
                window=TimeInterval(datetime.fromisoformat(replay['window']['start']), datetime.fromisoformat(replay['window']['end'])),
                input_binding=EquityInputBinding.from_dict(replay['input_binding']), initial_cash=replay['initial_cash'],
                one_way_cost=replay['one_way_cost'])
            if not _baseline_matches(_read(base_ref.resolve(root)), request, left, report.origin.content_sha256, report.origin.candidate):
                raise ValueError('equity baseline account differs')
    coverage = [x for x in report.pte_runtime.cases if x.case_id == 'pte-coverage']
    if len(coverage) != 1:
        raise ValueError('equity PTE coverage absent')
    outcome = _read(coverage[0].evidence[0].resolve(root))
    verify_equity_inspection_facts(outcome, protocol['pte'])
