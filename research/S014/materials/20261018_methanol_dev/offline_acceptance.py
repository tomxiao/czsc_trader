"""Replay already published source evidence through DFLS; no research experiment."""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import socket

from dataflows import DataRequest, Dataset, EvidenceParameters, PreparePolicy, ProviderConfig
from dataflows.methanol_evidence import methanol_evidence_bindings
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EvidenceRef, ResearchBatchRef


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
PRIOR = ROOT / 'research/S014/materials/20261018_methanol_feasibility'


def reject_network(*args, **kwargs):
    raise AssertionError('Offline acceptance must not access the network')


def main():
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    result_path = OUT / 'acceptance.json'
    if result_path.exists():
        raise FileExistsError('Preserve completed acceptance; use a new evidence directory for a revision')
    publication = json.loads((PRIOR / 'publication.json').read_text(encoding='utf-8'))
    refs = publication['evidence']
    sources = {}
    for number in [1, 2, 4, 5, 6, 7, 8]:
        key = f'attempts/call_{number:02d}.json'
        reference = EvidenceRef.from_dict(refs[key])
        receipt_path = reference.resolve(ROOT)
        sources[number] = EvidenceParameters(ROOT, receipt_path.relative_to(ROOT).as_posix(), reference.sha256)
        response_reference = EvidenceRef.from_dict(refs[f'responses/call_{number:02d}.json'])
        response_reference.resolve(ROOT)
    bindings = methanol_evidence_bindings(directory=sources[1], calendar=sources[4], mapping=sources[2],
                                          daily=tuple(sources[i] for i in [5, 6, 7, 8]))
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'),
                                      providers=ProviderConfig(bindings=bindings))
    requests = (
        DataRequest(Dataset.TRADING_CALENDAR, 'CZCE', '2020-01-01', '2026-10-15', '2026-10-15'),
        DataRequest(Dataset.FUTURES_CZCE_METHANOL_MAPPING, 'MA.ZCE', '2020-01-01', '2026-10-14', '2026-10-14'),
        DataRequest(Dataset.FUTURES_CZCE_METHANOL_DAILY, 'MA2005.ZCE', '2020-01-02', '2020-05-19', '2020-05-19'),
        DataRequest(Dataset.FUTURES_CZCE_METHANOL_DAILY, 'MA2305.ZCE', '2022-05-19', '2023-05-17', '2023-05-17'),
        DataRequest(Dataset.FUTURES_CZCE_METHANOL_DAILY, 'MA2611.ZCE', '2025-11-17', '2026-10-14', '2026-10-14'),
        DataRequest(Dataset.FUTURES_CZCE_METHANOL_DAILY, 'MA2610.ZCE', '2025-10-23', '2026-10-14', '2026-10-14'),
    )
    prepared = context.data.prepare(requests, policy=PreparePolicy.REFRESH)
    if not prepared.ready:
        print(json.dumps([{'symbol': item.request.symbol, 'status': str(item.status),
                          'error': None if item.error is None else {'code': item.error.code,
                              'message': item.error.message, 'context': dict(item.error.context)}}
                         for item in prepared.items], ensure_ascii=False, default=str))
        raise AssertionError('Offline source acceptance was not READY')
    rows = []
    results = []
    for request in requests:
        result = context.data.fetch(request, prepared=prepared.reference)
        assert result.ready, result.error
        results.append(result)
        metadata = result.identity.metadata
        rows.append({'dataset': str(request.dataset), 'symbol': request.symbol,
                     'start': request.start, 'end': request.end, 'rows': len(result.dataframe),
                     'content_sha256': result.identity.content_sha256,
                     'provider_binding': metadata['provider_binding'],
                     'provider_revision': metadata['provider_revision'],
                     'source_evidence': metadata['source_evidence']})
    cal = results[0].dataframe
    patched = cal.loc[cal.Date.eq('2022-12-31')].iloc[0]
    assert patched.IsOpen == 0 and str(patched.PreviousTradingDate.date()) == '2022-12-30'
    assert len(cal) == 2480 and int(cal.IsOpen.sum()) == 1642
    assert len(results[1].dataframe) == 1641
    # Compare selected mapped OHLC-independent source values, never calculate a
    # return signal, label, model, or strategy/account performance here.
    mapping = results[1].dataframe
    paired_rows = 0
    raw_tables = {}
    for index, call in enumerate([5, 6, 7, 8], start=2):
        original = json.loads((PRIOR / f'responses/call_{call:02d}.json').read_text(encoding='utf-8'))
        columns = original['fields']
        raw_tables[requests[index].symbol] = {r[columns.index('trade_date')]: dict(zip(columns, r))
                                             for r in original['items']}
        for row in results[index].dataframe.itertuples():
            original_row = raw_tables[row.Contract][row.Date.strftime('%Y%m%d')]
            assert row.Close == original_row['close'] and row.Settle == original_row['settle']
            assert row.Volume == original_row['vol']
            paired_rows += int(((mapping.Date == row.Date) & (mapping.Contract == row.Contract)).any())
    reused = context.data.prepare(requests, policy=PreparePolicy.REUSE)
    assert reused.ready and reused.reference == prepared.reference
    artifact = {
        'status': 'PASS_OFFLINE_DATA_ACCEPTANCE',
        'scope': 'Existing evidence only; no feature, label, model or account computation',
        'prepared': asdict(prepared.reference), 'assets': rows,
        'calendar': {'natural_days': len(cal), 'open_days': int(cal.IsOpen.sum()),
                     'patched_date': '2022-12-31', 'is_open': 0, 'previous_trading_date': '2022-12-30'},
        'raw_contracts_prepared': 4, 'mapped_source_dates_paired': paired_rows,
        'remaining_raw_contracts_unavailable': 18,
        'source_end_reason': 'Last necessary source session is 2026-10-14 for the 2026-10-15 decision',
        'new_tushare_calls': 0, 'new_models': 0, 'new_accounts': 0,
        'fees_execution_annual_targets': 'UNCHANGED',
        'new_data_call_budget': 0, 'historical_publication_verified': False,
        'historical_revision_history_verified': False,
        'reuse_same_reference': True,
        'source_hashes': {key: refs[key]['sha256'] for key in refs
                          if key.startswith(('attempts/', 'responses/')) and key.endswith('.json')},
        'acceptance_script_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    result_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    print(json.dumps({key: artifact[key] for key in ['status', 'calendar', 'raw_contracts_prepared',
                                                  'mapped_source_dates_paired', 'new_tushare_calls']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
