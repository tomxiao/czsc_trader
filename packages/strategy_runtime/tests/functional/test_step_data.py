# Risk ownership: SRT-23
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from dataflows import DataIdentity, Dataset, PreparedDataRef, canonical_frame_sha256
from strategy_runtime import ObservationAvailability, StepDataInput, StepDataWindow
from strategy_runtime.step_data import StepData


def reader(*, missing=False):
    declaration = StepDataInput('market', Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,
        '000300.SH', 'daily', 7, ObservationAvailability('Asia/Shanghai', '17:00'))
    frame = pd.DataFrame({'Date': pd.to_datetime(['2026-03-02', '2026-03-03']), 'Close': [1., 2.]})
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


def test_step_data_excludes_unpublished_rows_and_records_reproducible_slice():
    data, calls = reader()
    window = StepDataWindow('market', date(2026, 3, 2), date(2026, 3, 3))
    visible = data.fetch(window)
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
