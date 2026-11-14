# Risk ownership: E2E-03
"""Native V5 final packages and dual-market inspection, on synthetic data only."""
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import shutil
from uuid import uuid4

import pytest
from dataflows import MarketId, EquityProduct, TimeInterval
from strategy_runtime import InspectionControl, StrategyComputation, equity_source_hash
from strategy_runtime.deployment import validate_release_package
from strategy_manager import CandidateEvidence, StrategyRegistry, freeze_contracts as f
from czsc_trader.application import (CandidateInspectionRequest, EquityInspectionReplay,
    EquityInspectionProtocol, FreezeTarget, InspectionDataKind, inspect_candidate,
    freeze_candidate, get_freeze_result, record_research_decision, describe_inspection_environment)
from czsc_trader.application.equity_inspection import replay_account
from czsc_trader.application.research_evidence import validate_inspection
from czsc_trader.research_tools import ResearchExecutionSession
from paper_trading_engine.equity_inspection import (EquityPteDecision, EquityPteReport,
    EquityPteRestart, EquityPteReconcile, EquityPteScenario, EquityPteInspectionProtocol)
from adjusted_observation_support import setup_adjusted
from test_equity_inspection_roundtrip import (
    assert_cancelled_inspection_cannot_freeze, assert_frozen_us_delivery, seed_registered_frozen_candidate,
)


_PREPARED_SEEDS = {}
pytestmark = pytest.mark.usefixtures('pinned_inspection_environment')


def native_fixture(tmp_path, market, computation=StrategyComputation.STATEFUL_STEP, *, initial_state=False,
                   etf=False):
    key = (market, computation, initial_state, etf)
    saved = _PREPARED_SEEDS.get(key)
    if saved is not None:
        seed, prepared_request, reference = saved
        shutil.copytree(seed, tmp_path, dirs_exist_ok=True)
    context, request, products, _, _ = setup_adjusted(tmp_path, market, computation, etf=etf,
        existing_experiment=None if saved is None else prepared_request.experiment)
    if initial_state:
        from dataflows import Dataset, ProviderBinding
        from dataflows.local_strategy_data import fetch_strategy_feature_evidence
        from strategy_runtime import FrozenDataAsset, ObservationAvailability, StateRecord, StepDataInput, StepDataWindow
        from strategy_runtime.equity_replay import StrategyStateSchema, StateField, StateValueType
        source = request.candidate.source_root / 'strategy.py'
        source.write_text(
            "from datetime import timedelta\n"
            "from zoneinfo import ZoneInfo\n"
            "from strategy_runtime import AccountDecision, AccountStepResult, StateRecord, StepDataWindow\n"
            "def step(ctx, state):\n"
            f"    day = ctx.point.observed_through.astimezone(ZoneInfo({request.candidate.instrument.timezone!r})).date()\n"
            "    rows = ctx.dfls.fetch(StepDataWindow('seed', day - timedelta(days=1), day))\n"
            "    assert len(rows) == 2\n"
            "    row = rows.iloc[-1]\n"
            "    decision = AccountDecision.from_facts(1, 'hold', facts={'seed': row.score}, next_watch='next session')\n"
            "    return AccountStepResult(decision, account=state.account, cycle_values=StateRecord())\n",
            encoding='utf-8')
        seed = b'Date,score\n2026-10-11,0\n2026-10-12,1\n2026-10-13,2\n2026-10-14,3\n'
        (source.parent / 'seed.csv').write_bytes(seed)
        step_input = StepDataInput('seed', Dataset.STRATEGY_FEATURE_EVIDENCE, 'S999-v1', 'daily', 2,
            ObservationAvailability(request.candidate.instrument.timezone, '00:00'),
            asset=FrozenDataAsset('seed.csv', sha256(seed).hexdigest()))
        context.data._providers[Dataset.STRATEGY_FEATURE_EVIDENCE.value] = ProviderBinding(
            'repository', 'v1', fetch_strategy_feature_evidence)
        initial = StateRecord((('locked', -1), ('held', False), ('since', request.window.start)))
        schema = StrategyStateSchema((StateField('locked', StateValueType.INT),
            StateField('held', StateValueType.BOOL), StateField('since', StateValueType.DATETIME)))
        definition = replace(request.candidate.definition, initial_account=initial, state_schema=schema,
            source_sha256=equity_source_hash(source.parent, ('strategy.py',)), step_data_inputs=(step_input,))
        request = replace(request, candidate=replace(request.candidate, definition=definition),
            step_data_windows=(StepDataWindow('seed', date(2026, 10, 11), date(2026, 10, 14)),))
    if saved is None:
        with ResearchExecutionSession(context, experiment=request.experiment) as execution:
            request = context.evaluation.prepare(request, execution=execution).request
        reference = prepare_raw_reference(context, request)
        # A private immutable snapshot, created before any consumer can mutate it.
        # All mutable providers/frames are reconstructed above for each consumer.
        seed = tmp_path.parent / ('native-seed-' + uuid4().hex)
        shutil.copytree(tmp_path, seed)
        _PREPARED_SEEDS[key] = (seed, request, reference)
    else:
        request = replace(prepared_request, candidate=request.candidate)
    replay = EquityInspectionReplay(f.InspectionCoordinate('main', 'standard'), request.input_binding,
        request.requests(context.execution_spec), request.window, request.initial_cash, request.fee_rate,
        execution_reference=reference, step_data_windows=request.step_data_windows)
    return context, request, products, replay


def prepare_raw_reference(context, request):
    from dataflows import EquityDataRequest, PriceAdjustment, PreparePolicy
    from paper_trading_engine.execution_reference import ExecutionReferenceBinding
    hfq = dict(request.request_items(context.execution_spec))["bars"]
    raw_request = EquityDataRequest(hfq.parameters.instrument, hfq.parameters.source, replace(hfq.parameters.query, adjustment=PriceAdjustment.NONE))
    raw_prepared = context.data.prepare((raw_request,), policy=PreparePolicy.REUSE)
    assert raw_prepared.ready
    raw = context.data.fetch(raw_request, prepared=raw_prepared.reference)
    return ExecutionReferenceBinding(raw_request.parameters, raw_prepared.reference, raw.identity.content_sha256)


def native_protocol(context, request, products):
    row = products[EquityProduct.BARS].loc[lambda x: x.BarStart == request.window.start].iloc[0]
    interval = TimeInterval(row.BarStart.to_pydatetime(), row.Date.to_pydatetime())
    quantity = 900 if request.candidate.instrument.market is MarketId.CN else 989
    partial_quantity = context.execution_spec.quantity_step
    cash = Decimal(str(request.initial_cash))
    fee = Decimal(str(request.fee_rate))
    price = Decimal('10')
    partial = EquityPteReport(0, partial_quantity, price, interval.start + timedelta(minutes=1), 'FILLED_PART')
    complete = EquityPteReport(0, quantity, price, interval.start + timedelta(minutes=2), 'FILLED_ALL')
    reconcile = EquityPteReconcile(cash, 0)
    scenarios = [EquityPteScenario('partial-duplicate-restart',
        (reconcile, EquityPteDecision(interval, interval.start), partial, partial, EquityPteRestart(), complete),
        cash - quantity * price * (1 + fee), quantity, Decimal(0))]
    reserved = quantity * Decimal('10.10') * (1 + fee)
    for code, outcome, at in [('REJECTED', 'REJECTED', interval.start),
                              ('UNKNOWN', 'UNKNOWN', interval.start), ('EXPIRED', 'ACCEPTED', interval.end)]:
        scenarios.append(EquityPteScenario(code,
            (reconcile, EquityPteDecision(interval, at, outcome, code)),
            cash if code in ('REJECTED', 'EXPIRED') else cash - reserved, 0, Decimal(0)))
    scenarios.append(EquityPteScenario('reconciliation-blocked',
        (EquityPteReconcile(cash-1, 0), EquityPteDecision(interval, interval.start, expected='RECONCILIATION_BLOCKED')),
        cash, 0, Decimal(0)))
    return EquityInspectionProtocol('candidate-inspection-v5', 'ECONOMIC_V1', 0.,
        EquityPteInspectionProtocol(describe_inspection_environment(context.repository), tuple(scenarios)))


def test_legacy_equity_contract_is_rejected_before_data_access(tmp_path):
    context, request, products, replay = native_fixture(tmp_path, MarketId.US)
    legacy = replace(request.candidate, definition=replace(request.candidate.definition, contract_version=4))
    with pytest.raises(TypeError, match='V5 DFLS step contract'):
        replace(request, candidate=legacy)
    with pytest.raises(ValueError, match='V5 DFLS step contract'):
        replay_account(legacy, None, replay)
    with pytest.raises(ValueError, match='candidate-inspection-v5'):
        replace(native_protocol(context, request, products), method_version='candidate-inspection-v4')


def native_inspection_request(tmp_path, context, request, products, replay):
    """Prepare real synthetic admission inputs without running another test."""
    seed_registered_frozen_candidate(context, request)
    repository = context.repository
    registration = StrategyRegistry(repository.research_registry_root).get_candidate_registration(request.candidate.key)
    confirmation = tmp_path / '.tmp/engineering-approval.json'
    confirmation.parent.mkdir(exist_ok=True)
    confirmation.write_text('{"scope":"synthetic engineering fixture only"}', encoding='utf-8')
    source = CandidateEvidence(confirmation.relative_to(tmp_path).as_posix(), sha256(confirmation.read_bytes()).hexdigest())
    selection = record_research_decision(repository, f.ResearchDecision('native-selection', 'S999', f.DecisionAction.APPROVE,
        f.CandidateSelectionSubject(registration.key, registration.content_sha256, registration.record_sha256), source, 'fixture selection'))
    protocol = native_protocol(context, request, products)
    inspection = CandidateInspectionRequest(registration.key, selection, context, request.experiment,
        FreezeTarget('v1', None, 'native V5 synthetic package', date(2026,10,15), date(2026,10,16)),
        protocol, (replay,), InspectionDataKind.SYNTHETIC)
    return inspection, source


def freeze_native_inspection(repository, inspection, source, *, version='v1'):
    """Run the real inspection and commit once; callers own lifecycle assertions."""
    version_path = repository.strategy_root / inspection.candidate.strategy_id / 'versions' / (version + '.json')
    assert not version_path.exists()
    report = inspect_candidate(repository, inspection, control=InspectionControl(max_workers=1, timeout_seconds=90))
    assert report.status is f.InspectionStatus.PASS, '\n'.join(x.case_id + ': ' + x.summary for g in (report.behavior_equivalence, report.pte_runtime) for x in g.cases if x.status is not f.InspectionStatus.PASS)
    assert not version_path.exists(), 'technical inspection must precede the freeze approval'
    inspected_bytes = report.release.version_record.resolve(repository.root).read_bytes()
    facts = json.loads(report.pte_runtime.cases[0].evidence[0].resolve(repository.root).read_text(encoding='utf-8'))
    assert facts['runtime'] == {'advice': 'EquityRuntimeAdviceClient', 'execution': 'ChannelExecution',
        'account_engine': 'AccountEngine', 'store': 'PaperStore', 'admission': 'INSPECTION'}
    for case in facts['scenarios']:
        for step in case['facts']['observed']:
            if step['kind'] == 'DECISION' and step['outcome'] in ('REJECTED', 'EXPIRED'):
                assert step['account_health'] == 'OK'
            if step['kind'] == 'DECISION' and step['outcome'] == 'UNKNOWN':
                assert step['account_health'] == 'BLOCKED'
    suffix = '' if version == 'v1' else '-' + version
    approval = record_research_decision(repository, f.ResearchDecision('native-freeze' + suffix, 'S999', f.DecisionAction.APPROVE,
        f.FreezeSubject(report.origin.candidate, report.origin.content_sha256, report.reference, report.plan.sha256, version), source, 'approve exact synthetic package'))
    operation = f.FreezeCandidateRequest(f.FreezeRequestId('S999','native-fixture' + suffix), report.reference, approval)
    receipt = freeze_candidate(repository, operation)
    assert receipt.status is f.FreezeStatus.COMMITTED
    assert version_path.read_bytes() == inspected_bytes
    package_root = repository.strategy_root / inspection.candidate.strategy_id / 'releases' / version
    assert (package_root / 'release_manifest.json').read_bytes() == report.release.manifest.resolve(repository.root).read_bytes()
    for item in report.release.files:
        assert (package_root / item.path).read_bytes() == item.source.resolve(repository.root).read_bytes()
    return report, operation, receipt


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_native_dual_market_inspection_freezes_exact_v5_package(tmp_path, market):
    context, request, products, replay = native_fixture(tmp_path, market, initial_state=True)
    repository = context.repository
    inspection, source = native_inspection_request(tmp_path, context, request, products, replay)
    if market is MarketId.US:
        assert_cancelled_inspection_cannot_freeze(repository, inspection)
    report, operation, receipt = freeze_native_inspection(repository, inspection, source)
    assert validate_inspection(tmp_path, report.reference) == report
    facts = json.loads(report.behavior_equivalence.cases[0].evidence[0].resolve(tmp_path).read_bytes())
    reads = [read for step in facts['candidate']['strategy_data_reads'] for read in step['reads']]
    assert reads and all(read['rows'] == 2 and read['window']['name'] == 'seed' for read in reads)
    assert reads[0]['window']['start'] < request.history_start.isoformat()
    assert facts['candidate']['strategy_data_reads'] == facts['release']['strategy_data_reads']
    chart, = [case for case in report.pte_runtime.cases if case.case_id == 'pte-forward-chart']
    assert chart.status is f.InspectionStatus.PASS
    manifest, *html_files = [ref.resolve(tmp_path) for ref in chart.evidence]
    metadata = json.loads(manifest.read_text(encoding='utf-8'))['forward_chart']
    assert metadata['scenarios']['partial-duplicate-restart']['decision_count'] == 1
    assert 'reconciliation-blocked' not in metadata['scenarios']
    assert html_files and all('id="forward-context"' in path.read_text(encoding='utf-8') for path in html_files)
    assert get_freeze_result(repository, operation.request_id) == receipt == freeze_candidate(repository, operation)
    package = validate_release_package(repository.strategy_root, 'S999-v1')
    assert package.package_sha256 == report.release.package_sha256
    assert package.release.payload['runtime']['kind'] == 'ACCOUNT_REPLAY'
    assert package.release.payload['runtime']['contract_version'] == 5
    from strategy_runtime import EquityStrategyDefinition
    restored = EquityStrategyDefinition.from_dict(package.release.payload['equity_definition'])
    assert restored.initial_account == request.candidate.definition.initial_account
    assert restored.content_identity == request.candidate.definition.content_identity
    assert json.loads((package.source_root.parent.parent/'runtime_binding.json').read_text())['observation_sha256']
    if market is MarketId.US:
        assert_frozen_us_delivery(context, request, report, operation, receipt, inspection.selection)


@pytest.mark.parametrize('boundary', ['repository', 'data_dir', 'store'],
                         ids=['PTE30-C01', 'PTE30-C02', 'PTE30-C03'])
def test_formal_inspection_permit_cannot_reach_normal_store_or_paths(tmp_path, boundary):
    from paper_trading_engine.equity_runtime import EquityRuntimeAdviceClient
    from paper_trading_engine.ec_boundary import execution_permit
    from execution_channels.futu.store import PaperStore
    from strategy_runtime.inspection import InspectionRuntimePermit
    from strategy_runtime.errors import RuntimeCompatibilityError
    workspace = tmp_path / '.tmp' / 'strategy-inspection' / 'permit-test'
    repository = workspace / 'repository'
    permit = InspectionRuntimePermit('permit-test', 'S999-v1', 'a'*64, 'b'*64, 'c'*64,
                                     repository, workspace)
    ordinary = PaperStore(workspace / 'ordinary.db')
    isolated = PaperStore(workspace / 'isolated.db', inspection_permit=execution_permit(permit))
    try:
        kwargs = dict(repo_root=repository, dataflows=None, data_dir=workspace / 'data', inspection_permit=permit)
        if boundary == 'repository':
            with pytest.raises(ValueError, match='repository differs'):
                EquityRuntimeAdviceClient(store=isolated, **{**kwargs, 'repo_root': tmp_path})
        elif boundary == 'data_dir':
            with pytest.raises(RuntimeCompatibilityError, match='escapes'):
                EquityRuntimeAdviceClient(store=isolated, **{**kwargs, 'data_dir': tmp_path / 'outside'})
        else:
            with pytest.raises(ValueError, match='store differs'):
                EquityRuntimeAdviceClient(store=ordinary, **kwargs)
            client = EquityRuntimeAdviceClient(store=isolated, **kwargs)
            assert client.inspection_permit == permit
            with pytest.raises(RuntimeCompatibilityError):
                client.load_release('S999', 'v1')  # Permission does not replace package authentication.
    finally:
        isolated.close()
        ordinary.close()
