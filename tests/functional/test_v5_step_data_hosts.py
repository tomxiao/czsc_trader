from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from czsc_trader.research_tools.equity_replay import pinned_step_data
from czsc_trader.application._frozen_materials import candidate_install_files
from dataflows import (AssetClass, BarFrequency, Dataflows, DataSpace, Dataset, InstrumentId, MarketId,
                       PreparePolicy, ProviderBinding, ProviderConfig, SourceRef)
from dataflows.equity_contracts import EquityProduct, ProviderKey, TimeInterval, TradingSession
from dataflows.equity_data import equity_metadata
from dataflows.local_strategy_data import fetch_strategy_feature_evidence
from paper_trading_engine.data_space import AccountDataflows
from paper_trading_engine.formal_v4_advice import FormalV4AdviceClient
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, CnEquitySpec, EquityStrategyCandidate, EquityStrategyDefinition,
                              ExecutionPolicy, FeatureGraph, FrozenDataAsset, ObservationAvailability,
                              ResearchExecutionSpec, StepDataInput, StepDataWindow, StrategyComputation,
                              StrategyStateSchema, equity_source_hash)
from strategy_runtime.step_data import StepData


def test_step_reads_use_isolated_research_and_account_spaces(tmp_path):
    day = date(2026, 11, 27)
    earlier = date(2026, 11, 25)
    first_bar_end = datetime(2026, 11, 27, 15, tzinfo=timezone.utc)
    daily, intraday = 'daily', '30m'
    us_zone = 'America/New_York'
    futu = SourceRef('futu', 'fixture-v1')
    soxx = InstrumentId(MarketId.US, AssetClass.ETF, 'SOXX')
    mu = InstrumentId(MarketId.US, AssetClass.STOCK, 'MU')
    source = tmp_path / 'candidate'
    source.mkdir()
    seed = b'Date,feature\n2026-11-25,1.0\n2026-11-26,2.0\n'
    (source / 'seed.csv').write_bytes(seed)
    shibor = StepDataInput('shibor', Dataset.SHIBOR_DAILY, None, daily, 7,
                            ObservationAvailability('Asia/Shanghai', '15:00'))
    chinext = StepDataInput('chinext', Dataset.INDEX_DAILY_BASIC, '399006.SZ', daily, 7, shibor.availability)
    shares = StepDataInput('shares', Dataset.ETF_SHARE_SIZE, '588080.SH', daily, 7, shibor.availability)
    frozen = StepDataInput('seed', Dataset.STRATEGY_FEATURE_EVIDENCE, 'S007-v1', daily, 7,
                            shibor.availability, asset=FrozenDataAsset('seed.csv', sha256(seed).hexdigest()))
    industry = StepDataInput('soxx_open', Dataset.EQUITY_BARS, soxx.symbol, intraday, 7,
                              ObservationAvailability(us_zone, '00:00'), instrument=soxx, source=futu)
    stock = StepDataInput('mu_daily', Dataset.EQUITY_BARS, mu.symbol, daily, 7,
                           industry.availability, instrument=mu, source=futu)
    declarations = (shibor, chinext, shares, frozen, industry, stock)
    grants = tuple(StepDataWindow(item.name, earlier, day if item is industry else earlier)
                   for item in declarations)
    reads = tuple(StepDataWindow(item.name, day, day) if item is industry else grant
                  for item, grant in zip(declarations, grants, strict=True))

    def equity(request):
        query = request.parameters.query
        sessions = tuple(TradingSession(
            stamp, us_zone, (TimeInterval(datetime(stamp.year, stamp.month, stamp.day, 14, 30,
                                                   tzinfo=timezone.utc),
                                          datetime(stamp.year, stamp.month, stamp.day, close,
                                                   tzinfo=timezone.utc)),))
            for stamp, close in ((earlier, 21), (day, 18)) if query.start <= stamp <= query.end)
        bars = [bar for session in sessions for bar in session.bars(query.frequency)
                if query.completed_through is None or bar.end <= query.completed_through]
        result = pd.DataFrame({'Date': [bar.end for bar in bars], 'AvailableDate': [bar.end for bar in bars],
            'BarStart': [bar.start for bar in bars], 'Open': 1., 'High': 1., 'Low': 1., 'Close': 1.,
            'Volume': 100., 'Amount': 100.})
        metadata = equity_metadata(request, sessions, availability_basis='FIXTURE_BAR_CLOSE')
        return result, {**metadata, 'acquisition_method': 'PROVIDER_ADJUSTED'}

    tables = {
        Dataset.SHIBOR_DAILY: (None, 'OvernightRate'),
        Dataset.INDEX_DAILY_BASIC: ('399006.SZ', 'TurnoverRateFreeFloat'),
        Dataset.ETF_SHARE_SIZE: ('588080.SH', 'TotalShare'),
    }

    def table(request):
        symbol, column = tables[request.dataset]
        assert request.symbol == symbol
        return pd.DataFrame({'Date': [pd.Timestamp(earlier)], column: [2.]}), {}

    config = ProviderConfig(bindings={
        **{dataset: ProviderBinding('fixture', 'v1', table) for dataset in tables},
        Dataset.STRATEGY_FEATURE_EVIDENCE: ProviderBinding('repository', 'v1', fetch_strategy_feature_evidence),
    }, equity_bindings={ProviderKey(EquityProduct.BARS, MarketId.US, futu): ProviderBinding('futu', 'fixture-v1', equity)})
    study = Dataflows(base_dir=tmp_path, space=DataSpace(Path('study')), providers=config)
    prepared = study.prepare(tuple(item.request(window, source_root=source)
        for item, window in zip(declarations, grants, strict=True)), policy=PreparePolicy.REUSE)
    assert prepared.ready, [item.error for item in prepared.items if not item.ready]

    accounts = AccountDataflows(tmp_path, DataSpace(Path('paper')), config)
    client = SimpleNamespace(inspection_permit=None, account_dataflows=accounts)
    candidate = SimpleNamespace(definition=SimpleNamespace(step_data_inputs=declarations))

    def run(load):
        data = StepData(declarations, as_of=first_bar_end, observed_through=first_bar_end,
                        load=load, source_root=source)
        for window in reads:
            assert len(data.fetch(window)) == 1
        receipts = data.receipts()
        data.close()
        return receipts

    historical = run(pinned_step_data(study, prepared.reference, grants))
    online = run(FormalV4AdviceClient._step_loader(client, 'account', candidate, None, None))
    replayed = run(FormalV4AdviceClient._step_loader(client, 'account', candidate,
        tuple(row.to_dict() for row in online), None))
    assert replayed == online
    assert {row.prepared.space_id for row in historical} == {study.binding.space_id}
    assert {row.prepared.space_id for row in online} == {accounts.for_account('account').binding.space_id}
    assert [row.visible_slice_sha256 for row in historical] == [row.visible_slice_sha256 for row in online]
    assert next(row.last for row in online if row.window.name == industry.name) == first_bar_end.isoformat()
    with pytest.raises(ValueError, match='SPACE_MISMATCH'):
        run(FormalV4AdviceClient._step_loader(client, 'different-account', candidate,
            tuple(row.to_dict() for row in online), None))


def test_step_seed_is_included_in_candidate_package(tmp_path):
    source = ('def step(ctx, state):\n'
              '    raise RuntimeError("package fixture")\n')
    (tmp_path / 'strategy.py').write_text(source, encoding='utf-8')
    content = b'Date,feature\n2026-11-25,1.0\n'
    seed = tmp_path / 'seed.csv'
    seed.write_bytes(content)
    asset = FrozenDataAsset('seed.csv', sha256(content).hexdigest())
    step = StepDataInput('seed', Dataset.STRATEGY_FEATURE_EVIDENCE, 'S007-v1', 'daily', 400,
        ObservationAvailability('Asia/Shanghai', '15:00'), asset=asset)
    definition = EquityStrategyDefinition(
        InstrumentId(MarketId.CN, AssetClass.ETF, '588080.SH'),
        ResearchExecutionSpec(CnEquitySpec(), BarFrequency.DAILY,
                              AccountPolicy('CNY', CashAvailabilityPolicy.IMMEDIATE_RESEARCH),
                              100, .001, 0., 0.),
        1, 'strategy:step', ('strategy.py',), equity_source_hash(tmp_path, ('strategy.py',)),
        contract_version=5, computation=StrategyComputation.STATEFUL_STEP,
        feature_graph=FeatureGraph((), ()), state_schema=StrategyStateSchema(),
        execution_policy=ExecutionPolicy('TARGET_POSITION', {'capital_mode': 'full_available_cash'}),
        step_data_inputs=(step,))
    candidate = EquityStrategyCandidate('S007', 'C9999', definition, tmp_path)
    assert candidate_install_files(candidate) == ('strategy.py', 'seed.csv')
    seed.write_bytes(content + b'2026-11-26,2.0\n')
    with pytest.raises(ValueError, match='frozen data content differs'):
        candidate.verify()
