"""Public subwindow reads of a fixed, already authorized S013 preparation."""
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from dataflows import Dataflows, DataSpace, PreparedDataRef, ProviderConfig, Dataset

ROOT = Path(__file__).resolve().parents[5]
PINNED = PreparedDataRef(
    UUID('24bb58bb-7fea-4e5f-8bd4-ac23474ced6a'),
    UUID('bd5c9b30-98fb-455f-958a-04383bd8cacd'),
    '2f124ba9a35c2900a31a74605bf8371920b625e23ed093ba8baccf1b3eaf9400',
)


@lru_cache(maxsize=1)
def reader():
    return Dataflows(base_dir=ROOT, space=DataSpace(Path('research/S013/assets/data')),
                     providers=ProviderConfig(bindings={}))


def supplier(request):
    if not ((request.dataset == Dataset.TRADING_CALENDAR and request.symbol == 'SSE')
            or (request.dataset == Dataset.ETF_OHLCV and request.symbol == '510500.SH'
                and request.frequency == 'daily')):
        raise ValueError('Pinned supplier only serves original S013 calendar and HFQ daily inputs')
    result = reader().fetch(request, prepared=PINNED)
    if not result.ready:
        raise RuntimeError(result.error)
    return result.dataframe.copy(deep=True), dict(result.identity.metadata)


def main():
    from dataflows import DataRequest
    from dataflows.ohlcv_quality import validate_quality_metadata
    from aligned_common import runs, write, material, fingerprint
    checks = []
    for dataset, symbol, start, end in (
        (Dataset.TRADING_CALENDAR, 'SSE', '2018-08-28', '2026-09-30'),
        (Dataset.ETF_OHLCV, '510500.SH', '2018-12-27', '2026-09-29'),
    ):
        request = DataRequest(dataset, symbol, start, end, end, 'daily')
        result = reader().fetch(request, prepared=PINNED)
        assert result.ready, result.error
        quality = (validate_quality_metadata(dict(result.identity.metadata), request,
                                            result.dataframe)
                   if dataset == Dataset.ETF_OHLCV else None)
        checks.append({'dataset': str(dataset), 'symbol': symbol, 'start': start, 'end': end,
                       'rows': len(result.dataframe), 'content_sha256': result.identity.content_sha256,
                       'quality': quality})
    proof = {'status': 'PASS', 'fixed_preparation': {'space_id': str(PINNED.space_id),
        'preparation_id': str(PINNED.preparation_id), 'manifest_sha256': PINNED.manifest_sha256},
        'source': fingerprint(Path(__file__)), 'coverage_checks': checks,
        'decision': 'Explicit fixed-ref provider for new exact request selectors. Public fetch only; '
                    'no acquisition, automatic repair, manual input binding or quality resigning. '
                    'Return actual metadata; public prepare authenticates child subwindows. '
                    'Previously authenticated execution requests remain unchanged.'}
    path = runs('S013')/'pinned_source_check.json'
    write(path, proof)
    write(runs('S013')/'pinned_source_check_reference.json',
          material('aligned-fixed-native-source-check', path, 'S013').to_dict())
    print({'status': proof['status'], 'checks': checks})


if __name__ == '__main__':
    main()
