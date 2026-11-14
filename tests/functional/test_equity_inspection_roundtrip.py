# Risk ownership: TDR-20
"""Inspection contract boundaries and assertions shared by the real US closure."""
from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4
import pytest
from strategy_manager import CandidateEvidence, CandidateRegistration, CandidateRegistrationOrigin, freeze_contracts as f
from strategy_manager import StrategyRegistry
from strategy_runtime import InspectionControl
from strategy_runtime.deployment import validate_release_package
from czsc_trader.application import (inspect_candidate, freeze_candidate, assemble_delivery, validate_delivery)
from czsc_trader.application.research_evidence import validate_inspection
from czsc_trader.application import run_backtest
from czsc_trader.research_tools import delivery as d


def seed_registered_frozen_candidate(research,evaluation):
    """Install an existing V2 registration through SM, not a retired research API."""
    candidate=evaluation.candidate
    identity=candidate.content_identity
    root=research.repository.research_root/candidate.strategy_id
    prefix=f'assets/candidates/{candidate.candidate_id}'
    source_root=f'{prefix}/source/strategy_runtime'
    def write(relative,content):
        path=root/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(content)
        return CandidateEvidence(relative,sha256(content).hexdigest())
    payload=write(f'{prefix}/payload.json',json.dumps(candidate.payload,sort_keys=True,separators=(',',':')).encode())
    from czsc_trader.application._frozen_materials import candidate_install_files
    sources=tuple(write(f'{source_root}/{name}',(candidate.source_root/name).read_bytes())
        for name in candidate_install_files(candidate))
    record=CandidateRegistration(candidate.key,identity.content_sha256,identity.source_sha256,
        identity.dependency_sha256,payload,sources,source_root,
        tuple((item.name,item.version) for item in candidate.definition.dependencies),
        CandidateRegistrationOrigin(evaluation.experiment.experiment_id,()))
    StrategyRegistry(research.repository.research_registry_root).register_candidate(record,evidence_root=root)


def test_TDR_20_C03_equity_inspection_rejects_legacy_auxiliary_binding():
    from dataflows import (AssetClass, BarFrequency, EquityDataRequest, EquityProduct, EquityQuery,
        InstrumentId, MarketId, PreparedDataRef, PriceAdjustment, SourceRef, TimeInterval)
    from strategy_runtime import EquityAuxiliaryBinding, EquityAuxiliaryInput, EquityInputBinding, InputBindingScope
    from paper_trading_engine.execution_reference import ExecutionReferenceBinding
    from czsc_trader.application import EquityInspectionReplay

    # Use an authenticated binding shape from the older strategy contract.
    instrument = InstrumentId(MarketId.US, AssetClass.STOCK, 'MU')
    source = SourceRef('contract-fixture', 'v1')
    day = date(2026, 10, 12)
    primary = tuple(EquityDataRequest(instrument, source, EquityQuery(product, day, day,
        BarFrequency.M30, PriceAdjustment.BACKWARD if product is EquityProduct.BARS else PriceAdjustment.NONE))
        for product in (EquityProduct.BARS, EquityProduct.SESSIONS))
    auxiliary = EquityAuxiliaryInput('sector', InstrumentId(MarketId.US, AssetClass.ETF, 'SOXX'),
        source, BarFrequency.M30, 1, 86400, 'HFQ')
    requests = primary + auxiliary.requests(day, day)
    prepared = PreparedDataRef(uuid4(), uuid4(), 'a' * 64)
    binding = EquityInputBinding(prepared, instrument, 'b' * 64,
        (('bars', 'c' * 64), ('sessions', 'd' * 64)), 1,
        (EquityAuxiliaryBinding(auxiliary, 'e' * 64, 'f' * 64),), scope=InputBindingScope.OBSERVATION,
        request_bindings=tuple((key, request.parameters) for key, request in zip(
            ('bars', 'sessions', auxiliary.data_key(EquityProduct.BARS), auxiliary.data_key(EquityProduct.SESSIONS)), requests)))
    raw = replace(primary[0].parameters, query=replace(primary[0].parameters.query, adjustment=PriceAdjustment.NONE))
    with pytest.raises(ValueError, match='V5 inspection strategy data requires step_data_windows'):
        EquityInspectionReplay(f.InspectionCoordinate('main', 'standard'), binding, requests,
            TimeInterval(datetime(2026, 10, 12, 14, tzinfo=timezone.utc), datetime(2026, 10, 12, 15, tzinfo=timezone.utc)),
            10000., .001, execution_reference=ExecutionReferenceBinding(raw, prepared, '1' * 64))


def assert_cancelled_inspection_cannot_freeze(context, request):
    """Check cancellation before the US main chain, without a second successful inspection."""
    cancelled = inspect_candidate(context, request, control=InspectionControl(max_workers=1, cancelled=lambda: True))
    assert cancelled.status is f.InspectionStatus.INCOMPLETE
    assert validate_inspection(context.root, cancelled.reference) == cancelled
    blocked = f.FreezeCandidateRequest(f.FreezeRequestId('S999', 'cancelled-fixture'), cancelled.reference, request.selection)
    with pytest.raises(ValueError):
        freeze_candidate(context, blocked)


def assert_frozen_us_delivery(research, evaluation, report, operation, receipt, selection):
    """Exercise post-freeze risks on the package produced by the US main chain."""
    context = research.repository
    package = validate_release_package(context.strategy_root, 'S999-v1')
    assert package.package_sha256 == report.release.package_sha256
    version = StrategyRegistry(context.strategy_root).get_version('S999', 'v1')
    with pytest.raises(TypeError, match='ResearchExecutionSession'):
        run_backtest(research, version, evaluation)
    source_file = package.source_root / evaluation.candidate.definition.source_files[0]
    original = source_file.read_bytes()
    try:
        source_file.write_bytes(original + b'\n# unexpected frozen source change\n')
        with pytest.raises(Exception, match='differs|hash|source'):
            validate_release_package(context.strategy_root, 'S999-v1')
    finally:
        source_file.write_bytes(original)
    delivery = assemble_delivery(context, d.DeliveryDefinition(research.batch, d.DeliveryStage.INSPECTION, 1,
        schema_version=9),
        d.DeliveryContent(d.CandidateInspectionDelivery(report.reference, (selection, operation.approval), receipt, ()),
            d.DeliveryStatus.COMPLETE, (), (),
            report='Synthetic US technical inspection and exact-package freeze; no economic acceptance claim.'))
    assert delivery.validation.status is d.ValidationStatus.PASS
    assert validate_delivery(context, delivery.receipt.reference).status is d.ValidationStatus.PASS
    return report, receipt, delivery.receipt
