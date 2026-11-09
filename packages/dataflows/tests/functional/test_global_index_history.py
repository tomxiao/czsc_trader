"""SPX publications must reject the historical hole that blocked PTE decisions."""

from pathlib import Path

import pandas as pd
import pytest

from dataflows import (
    Dataflows, DataRequest, DataSpace, DataStatus, Dataset, PreparePolicy,
    ProviderBinding, ProviderConfig,
)
from dataflows.errors import IncompleteDataError
from dataflows.tushare_strategy_data import fetch_global_index_daily


@pytest.fixture
def global_index_root(tmp_path, empty_space_factory):
    # Initialization/concurrency are covered by test_data_space.
    empty_space_factory("market")
    return tmp_path


class GlobalPro:
    def __init__(self, *, empty_year=None, missing_start=None, missing_end=None):
        self.empty_year = empty_year
        self.missing_start = missing_start
        self.missing_end = missing_end
        self.calls = []

    def index_global(self, **kwargs):
        self.calls.append(kwargs)
        dates = pd.bdate_range(kwargs['start_date'], kwargs['end_date'])
        dates = dates[~dates.strftime('%m%d').isin(['0101'])]
        if kwargs['start_date'].startswith(str(self.empty_year)):
            dates = dates[:0]
        if self.missing_start is not None:
            dates = dates[~dates.to_series().between(
                self.missing_start, self.missing_end).to_numpy()]
        return pd.DataFrame({'trade_date': dates.strftime('%Y%m%d'), 'pct_chg': 1.5})






def test_DFLS_34_C02_nonempty_spx_year_with_internal_hole_is_rejected():
    with pytest.raises(IncompleteDataError, match='SPX history has an internal gap') as exc:
        fetch_global_index_daily('SPX', '2025-01-02', '2025-02-10',
                                 pro=GlobalPro(missing_start='2025-01-06',
                                               missing_end='2025-01-31'))
    assert exc.value.context['maximum_gap_days'] == 10
    assert exc.value.context['annual_requests'][0]['row_count'] > 0




def test_DFLS_36_C02_old_ready_spx_hole_is_rejected_on_fetch_and_reuse_then_explicitly_refreshed(
    global_index_root, monkeypatch,
):
    from dataflows import facade

    frame = pd.DataFrame({'Date': pd.to_datetime([
        '2024-12-30', '2024-12-31', '2026-01-02', '2026-01-05',
    ]), 'PercentChange': [0.01] * 4})
    calls = []

    def provider(request):
        calls.append(request)
        return frame, {'vendor': 'synthetic'}

    flows = Dataflows(base_dir=global_index_root, space=DataSpace(Path('market')),
        providers=ProviderConfig({Dataset.GLOBAL_INDEX_DAILY:
            ProviderBinding('fixture', '1', provider)}))
    request = DataRequest(Dataset.GLOBAL_INDEX_DAILY, 'SPX', '2024-12-30',
                          '2026-01-05', '2026-01-05')
    # Fault injection recreates a legacy publication without rewriting its bytes/hashes.
    with monkeypatch.context() as legacy:
        legacy.setattr(facade, 'validate_global_index_history', lambda *_: None, raising=False)
        original = flows.prepare((request,), policy=PreparePolicy.REUSE)
        assert original.ready
    fetched = flows.fetch(request, prepared=original.reference)
    assert fetched.status is DataStatus.INCOMPLETE
    assert fetched.error.code == 'INCOMPLETE_DATA'
    reused = flows.prepare((request,), policy=PreparePolicy.REUSE)
    assert not reused.ready and reused.reference is None
    assert reused.items[0].status is DataStatus.INCOMPLETE
    assert reused.items[0].error.code == 'INCOMPLETE_DATA'
    assert len(calls) == 1  # Rejection must not trigger a hidden network fallback.
    frame = pd.DataFrame({'Date': pd.bdate_range(request.start, request.end),
                          'PercentChange': 0.01})
    refreshed = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    assert refreshed.ready and refreshed.reference != original.reference
    assert len(calls) == 2
    assert flows.fetch(request, prepared=refreshed.reference).ready
    assert flows.fetch(request, prepared=original.reference).status is DataStatus.INCOMPLETE
