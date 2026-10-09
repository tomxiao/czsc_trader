"""Add an exact request binding to an authenticated existing S013 raw asset."""
from uuid import UUID
import pandas as pd
from dataflows import (Dataflows, DataRequest, DataCoverageRequirement, Dataset, PreparedDataRef,
                       ProviderBinding, ProviderConfig, PreparePolicy)
from common import ROOT, RUNS, context, read, write


def main():
    mapping = read(ROOT / 'research/S013/assets/runs/EX004_20261007/contract_migration/prepared_reference_mapping.json')
    matches = [(row, item) for row in mapping for item in row['requests']
               if item['dataset'] == 'etf.unadjusted_daily' and item['start'] == '2019-10-09'
               and item['end'] == '2026-09-30']
    if not matches:
        raise RuntimeError('existing authenticated raw warmup is unavailable')
    row, item = matches[0]
    original = DataRequest(Dataset(item['dataset']), item['symbol'], item['start'], item['end'],
        item['required_cutoff'], frequency=item['frequency'],
        coverage=DataCoverageRequirement(**item['coverage']) if item['coverage'] else None)
    old_ref = PreparedDataRef(UUID(row['new']['space_id']), UUID(row['new']['preparation_id']), row['new']['manifest_sha256'])
    research = context(1)
    source = research.data.fetch(original, prepared=old_ref)
    target = DataRequest(Dataset.ETF_UNADJUSTED_DAILY, '510500.SH', '2019-10-09', '2026-09-29', None)
    calls = []

    def exact_existing_source(request):
        if request != target:
            raise AssertionError('only the declared existing-asset request is allowed')
        calls.append(request)
        metadata = dict(source.identity.metadata)
        metadata['existing_asset_scope_origin'] = {'request': item, 'prepared': row['new'],
            'source_content_sha256': source.identity.content_sha256, 'external_acquisition': False}
        frame = source.dataframe.loc[pd.to_datetime(source.dataframe.Date) <= pd.Timestamp(target.end)].copy(deep=True)
        return frame, metadata

    binding = research.data.binding
    offline = Dataflows(base_dir=ROOT, space=binding.space, providers=ProviderConfig(bindings={
        Dataset.ETF_UNADJUSTED_DAILY: ProviderBinding('etf.unadjusted_daily',
            'S013-offline-contract-migration-v1', exact_existing_source)}))
    receipt = offline.prepare((target,), policy=PreparePolicy.REUSE)
    if not receipt.ready:
        raise RuntimeError(receipt)
    actual = research.data.fetch(target, prepared=receipt.reference)
    expected = source.dataframe.loc[pd.to_datetime(source.dataframe.Date) <= pd.Timestamp(target.end)].reset_index(drop=True)
    pd.testing.assert_frame_equal(actual.dataframe.reset_index(drop=True), expected, check_exact=True)
    write(RUNS / 'raw_volume_scope_preparation.json', {'status': 'PASS', 'source_request': item,
        'source_prepared': row['new'], 'source_content_sha256': source.identity.content_sha256,
        'new_prepared': {'space_id': str(receipt.reference.space_id), 'preparation_id': str(receipt.reference.preparation_id),
                         'manifest_sha256': receipt.reference.manifest_sha256},
        'new_request': {'dataset': 'etf.unadjusted_daily', 'symbol': target.symbol,
                        'start': target.start, 'end': target.end, 'required_cutoff': None},
        'subset_frame': 'EXACT_EQUAL', 'rows': len(actual.dataframe),
        'existing_asset_adapter_calls': len(calls), 'external_data_acquisition': False})
    print({'status': 'PASS', 'exact_existing_raw_rows': len(actual.dataframe), 'external_data_acquisition': False}, flush=True)


if __name__ == '__main__':
    main()
