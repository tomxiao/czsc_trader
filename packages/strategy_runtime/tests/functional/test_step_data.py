# Risk ownership: SRT-23
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from dataflows import (AssetClass, Dataflows, DataIdentity, DataSpace, Dataset, InstrumentId, MarketId,
                       PreparedDataRef, PreparePolicy, ProviderConfig, SourceRef, canonical_frame_sha256)
from strategy_runtime import FrozenDataAsset, ObservationAvailability, StepDataInput, StepDataWindow
from strategy_runtime.step_data import StepData


def reader(*, missing=False, text_dates=False):
    declaration = StepDataInput('market', Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,
        '000300.SH', 'daily', 7, ObservationAvailability('Asia/Shanghai', '17:00'))
    frame = pd.DataFrame({'Date': pd.to_datetime(['2026-03-02', '2026-03-03']), 'Close': [1., 2.]})
    if text_dates:
        frame['Date'] = frame.Date.dt.strftime('%Y-%m-%d')
    cutoff = datetime(2026, 3, 3, 8, tzinfo=timezone.utc)
    observed = datetime(2026, 3, 3, 7, tzinfo=timezone.utc)
    identity = DataIdentity(declaration.dataset.value, 'fixture', declaration.symbol,
        '2026-03-02', '2026-03-03', canonical_frame_sha256(frame),
        {'source_time_field': 'Date', 'availability_time_field': 'Date', 'source_calendar': 'SSE',
         'available_at': '17:00 Asia/Shanghai', 'request_range_policy': 'EXACT'})
    reference = PreparedDataRef(uuid4(), uuid4(), 'a' * 64)
    calls = []

    def load(window, request):
        calls.append((window, request))
        if missing:
            return reference, SimpleNamespace(ready=False, error='missing fixture')
        return reference, SimpleNamespace(ready=True, dataframe=frame, identity=identity)

    return StepData((declaration,), as_of=cutoff, observed_through=observed, load=load), calls


@pytest.mark.parametrize('text_dates', [False, True], ids=['timestamps', 'provider-date-strings'])
def test_step_data_excludes_unpublished_rows_and_records_reproducible_slice(text_dates):
    data, calls = reader(text_dates=text_dates)
    window = StepDataWindow('market', date(2026, 3, 2), date(2026, 3, 3))
    visible = data.fetch(window)
    assert visible.Date.dt.date.tolist() == [date(2026, 3, 2)]
    assert visible.Close.tolist() == [1.]
    read, = data.receipts()
    assert read.rows == 1
    assert read.visible_slice_sha256 == canonical_frame_sha256(visible)
    assert read.prepared_slice_sha256 != read.visible_slice_sha256
    visible.loc[0, 'Close'] = 9.
    assert data.fetch(window).Close.tolist() == [1.]
    assert len(calls) == 1
    data.close()
    with pytest.raises(RuntimeError, match='expired'):
        data.fetch(window)


@pytest.mark.parametrize('window', [
    StepDataWindow('market', date(2026, 3, 3), date(2026, 3, 4)),
    StepDataWindow('market', date(2026, 2, 24), date(2026, 2, 24)),
    StepDataWindow('undeclared', date(2026, 3, 3), date(2026, 3, 3)),
])
def test_step_data_rejects_invalid_read_before_host_access(window):
    data, calls = reader()
    with pytest.raises(ValueError):
        data.fetch(window)
    assert not calls
    with pytest.raises(ValueError, match='invalid or unavailable'):
        data.receipts()


def test_step_data_failure_blocks_the_proposal_even_if_caught_by_strategy():
    data, calls = reader(missing=True)
    window = StepDataWindow('market', date(2026, 3, 2), date(2026, 3, 2))
    with pytest.raises(ValueError, match='STRATEGY_DATA_UNAVAILABLE'):
        data.fetch(window)
    assert len(calls) == 1
    with pytest.raises(ValueError, match='invalid or unavailable'):
        data.receipts()


@pytest.mark.parametrize('dataset,symbol', [
    (Dataset.SHIBOR_DAILY, None),
    (Dataset.INDEX_DAILY_BASIC, '399006.SZ'),
    (Dataset.ETF_SHARE_SIZE, '588080.SH'),
])
def test_s007_source_declarations_build_typed_daily_requests(dataset, symbol):
    item = StepDataInput('input', dataset, symbol, 'daily', 40, ObservationAvailability('Asia/Shanghai', '15:00'))
    round_trip = StepDataInput.from_dict(item.to_dict())
    req = round_trip.request(StepDataWindow('input', date(2026, 9, 1), date(2026, 9, 3)))
    assert (req.dataset, req.symbol, req.start, req.end) == (dataset, symbol, '2026-09-01', '2026-09-03')
    if dataset is Dataset.SHIBOR_DAILY:
        with pytest.raises(ValueError, match='requires no symbol'):
            StepDataInput('input', dataset, 'SHIBOR', 'daily', 40, item.availability)


def test_frozen_seed_uses_pinned_bytes_in_candidate_and_frozen_copy(tmp_path):
    candidate = tmp_path / 'source'
    frozen = tmp_path / 'release'
    content = b'Date,feature\n2026-09-01,1.0\n2026-09-02,2.0\n2026-09-03,3.0\n'
    for root in (candidate, frozen):
        root.mkdir()
        (root / 'seed.csv').write_bytes(content)
    asset = FrozenDataAsset('seed.csv', sha256(content).hexdigest())
    item = StepDataInput('seed', Dataset.STRATEGY_FEATURE_EVIDENCE, 'S007-v1', 'daily', 400,
                         ObservationAvailability('Asia/Shanghai', '15:00'), asset=asset)
    assert StepDataInput.from_dict(item.to_dict()) == item
    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path('dfls')), providers=ProviderConfig())
    start, end = date(2026, 9, 1), date(2026, 9, 3)
    grant = item.request(StepDataWindow('seed', start, end), source_root=candidate)
    prepared = flows.prepare((grant,), policy=PreparePolicy.REUSE)
    assert prepared.ready, prepared.items[0].error
    day = date(2026, 9, 2)
    cutoff = datetime(2026, 9, 2, 7, tzinfo=timezone.utc)
    data = StepData((item,), as_of=cutoff, observed_through=cutoff, source_root=frozen,
        load=lambda _, req: (prepared.reference, flows.fetch(req, prepared=prepared.reference)))
    window = StepDataWindow('seed', day, day)
    assert data.fetch(window).feature.tolist() == [2.0]
    assert data.receipts()[0].prepared == prepared.reference
    wrong = StepDataInput('seed', item.dataset, item.symbol, 'daily', 400, item.availability,
                          asset=FrozenDataAsset('seed.csv', 'f' * 64))
    invalid = flows.fetch(wrong.request(window, source_root=frozen), prepared=prepared.reference)
    assert invalid.error.code == 'REQUEST_NOT_PREPARED'


def test_us_source_and_closed_bar_cutoff_are_explicit():
    instrument = InstrumentId(MarketId.US, AssetClass.ETF, 'SOXX')
    source = SourceRef('futu', 's019-source')
    item = StepDataInput('soxx', Dataset.EQUITY_BARS, instrument.symbol, '30m', 100,
                         ObservationAvailability(instrument.timezone, '00:00'),
                         instrument=instrument, source=source)
    assert StepDataInput.from_dict(item.to_dict()) == item
    day = date(2026, 11, 27)
    cutoff = datetime(2026, 11, 27, 15, tzinfo=timezone.utc)
    req = item.request(StepDataWindow('soxx', day, day), observed_through=cutoff)
    assert req.parameters.source == source
    assert req.parameters.instrument == instrument
    assert req.parameters.query.completed_through == cutoff
    assert req.parameters.query.adjustment.value == 'hfq'
