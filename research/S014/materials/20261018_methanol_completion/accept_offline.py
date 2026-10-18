"""Validate complete contract-date coverage through DFLS; never compute returns."""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import socket

import pandas as pd

from dataflows import DataRequest, Dataset, EvidenceParameters, PreparePolicy, ProviderConfig
from dataflows.methanol_evidence import methanol_evidence_bindings
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EvidenceRef, ResearchBatchRef

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
PRIOR = ROOT / 'research/S014/materials/20261018_methanol_feasibility'
PLAN = ROOT / 'research/S014/materials/20261018_methanol_completion_review/request_plan.json'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


def main():
    def no_network(*args, **kwargs):
        raise AssertionError('Offline acceptance must make zero network calls')
    socket.socket.connect = no_network
    socket.create_connection = no_network
    assert not (OUT / 'acceptance.json').exists(), 'Preserve completed acceptance'
    plan = read(PLAN)
    plan_hash = sha256(PLAN.read_bytes()).hexdigest()
    assert plan_hash == read(OUT / 'authorization.json')['plan_sha256']
    old_refs = read(PRIOR / 'publication.json')['evidence']
    new_refs = read(OUT / 'source_publication.json')['evidence']

    def source(ref):
        evidence = EvidenceRef.from_dict(ref)
        path = evidence.resolve(ROOT)
        return EvidenceParameters(ROOT, path.relative_to(ROOT).as_posix(), evidence.sha256)

    previous = {number: source(old_refs[f'attempts/call_{number:02d}.json']) for number in [1, 2, 4, 5, 6, 7, 8]}
    attempts = [read(p) for p in sorted((OUT / 'attempts').glob('call_*.json'))]
    assert all(r['plan_sha256'] == plan_hash for r in attempts)
    assert len(attempts) <= 20 and sum(r['is_retry'] for r in attempts) <= 2
    successful = {r['request_number']: r for r in attempts if r['status'] == 'RECEIVED'}
    assert set(successful) == set(range(1, 19))
    added = [source(new_refs[f"attempts/call_{successful[i]['call']:02d}.json"]) for i in range(1, 19)]
    bindings = methanol_evidence_bindings(directory=previous[1], calendar=previous[4], mapping=previous[2],
        daily=tuple(previous[i] for i in [5, 6, 7, 8]) + tuple(added))
    repository = RepositoryContext.discover(ROOT)
    context = create_research_context(repository, ResearchBatchRef('S014'), providers=ProviderConfig(bindings=bindings))
    requests = [
        DataRequest(Dataset.TRADING_CALENDAR, 'CZCE', '2020-01-01', '2026-10-15', '2026-10-15'),
        DataRequest(Dataset.FUTURES_CZCE_METHANOL_MAPPING, 'MA.ZCE', '2020-01-01', '2026-10-14', '2026-10-14'),
    ]
    previous_ranges = [('MA2005.ZCE', '2020-01-02', '2020-05-19'),
        ('MA2305.ZCE', '2022-05-19', '2023-05-17'), ('MA2611.ZCE', '2025-11-17', '2026-10-14'),
        ('MA2610.ZCE', '2025-10-23', '2026-10-14')]
    for symbol, start, end in previous_ranges:
        requests.append(DataRequest(Dataset.FUTURES_CZCE_METHANOL_DAILY, symbol, start, end, end))
    for spec in plan['requests']:
        params = spec['params']
        start, end = [pd.Timestamp(params[key]).date().isoformat() for key in ['start_date', 'end_date']]
        requests.append(DataRequest(Dataset.FUTURES_CZCE_METHANOL_DAILY, params['ts_code'], start, end, end))
    requests = tuple(requests)
    prepared = context.data.prepare(requests, policy=PreparePolicy.REFRESH)
    assert prepared.ready, [(item.request.symbol, str(item.status), item.error) for item in prepared.items]
    results = [context.data.fetch(request, prepared=prepared.reference) for request in requests]
    assert all(result.ready for result in results)
    calendar, mapping = results[0].dataframe, results[1].dataframe
    assert len(calendar) == 2480 and int(calendar.IsOpen.sum()) == 1642 and len(mapping) == 1641
    assert calendar.loc[calendar.Date.eq('2022-12-31'), 'IsOpen'].tolist() == [0]
    original = read(PRIOR / 'responses/call_04.json')
    old_calendar = pd.DataFrame(original['items'], columns=original['fields'])
    old_open = sorted(old_calendar.loc[old_calendar.is_open.eq(1), 'cal_date'])
    opens = calendar.loc[calendar.IsOpen.eq(1), 'Date'].tolist()
    assert [date.strftime('%Y%m%d') for date in opens] == old_open
    assets = []
    tables = {}
    for request, result in zip(requests, results):
        assets.append({'dataset': str(request.dataset), 'symbol': request.symbol,
            'start': request.start, 'end': request.end, 'rows': len(result.dataframe),
            'content_sha256': result.identity.content_sha256,
            'provider_binding': result.identity.metadata['provider_binding'],
            'provider_revision': result.identity.metadata['provider_revision']})
        if request.dataset is Dataset.FUTURES_CZCE_METHANOL_DAILY:
            tables[request.symbol] = result.dataframe.set_index('Date')
    assert len(tables) == 22
    for spec in plan['requests']:
        table = tables[spec['params']['ts_code']]
        assert table.index.strftime('%Y%m%d').tolist() == spec['expected_dates']
        receipt = successful[spec['request_number']]
        original = read(ROOT / receipt['response_path'])
        assert sha256((ROOT / receipt['response_path']).read_bytes()).hexdigest() == receipt['response_sha256']
        raw = pd.DataFrame(original['items'], columns=original['fields']).set_index('trade_date')
        for row in table.itertuples():
            supplied = raw.loc[row.Index.strftime('%Y%m%d')]
            for published_field, raw_field in [('Close', 'close'), ('Settle', 'settle'), ('Volume', 'vol'), ('Amount', 'amount'), ('OpenInterest', 'oi')]:
                assert getattr(row, published_field) == supplied[raw_field]
    map_table = mapping.set_index('Date')
    endpoint_checks = []
    needed = set()
    for index in range(2, len(opens)):
        decision, p, q = opens[index], opens[index - 1], opens[index - 2]
        mapped = map_table.loc[p]
        contract = mapped.Contract
        p_row, q_row = tables[contract].loc[p], tables[contract].loc[q]
        cutoff = decision + pd.Timedelta(hours=15)
        assert max(mapped.AvailableDate, p_row.AvailableDate, q_row.AvailableDate) <= cutoff
        assert p_row.AvailableDate == cutoff
        needed.update([(contract, p), (contract, q)])
        endpoint_checks.append({'decision_date': str(decision.date()), 'contract': contract,
            'p': str(p.date()), 'q': str(q.date()), 'dates_present': True, 'availability_pass': True,
            'positive_volume_both': bool(p_row.Volume > 0 and q_row.Volume > 0)})
    assert len(endpoint_checks) == 1640 and len(needed) == 1662
    zero_endpoints = [row for row in endpoint_checks if not row['positive_volume_both']]
    reused = context.data.prepare(requests, policy=PreparePolicy.REUSE)
    assert reused.ready and reused.reference == prepared.reference
    # Prepared reads remain network-free even without any configured provider.
    reopened = create_research_context(repository, ResearchBatchRef('S014'), providers=ProviderConfig(bindings={}))
    assert all(reopened.data.fetch(request, prepared=prepared.reference).ready for request in requests)
    write(OUT / 'endpoint_checks.json', endpoint_checks)
    write(OUT / 'acceptance.json', {
        'status': 'PASS_OFFLINE_COVERAGE_ACCEPTANCE', 'scope': 'Data identity, coverage, price preservation and availability only; no return, signal, model or account',
        'prepared': asdict(prepared.reference), 'assets': assets,
        'actual_calls': len(attempts), 'failed_calls': sum(r['status'] != 'RECEIVED' for r in attempts),
        'controlled_retries': sum(r['is_retry'] for r in attempts), 'call_cap': 20, 'unused_slots': 20-len(attempts),
        'new_contracts': 18, 'new_rows': sum(len(tables[s['params']['ts_code']]) for s in plan['requests']),
        'all_contracts_prepared': 22, 'all_raw_rows_prepared': sum(len(t) for t in tables.values()),
        'mapping_rows': len(mapping), 'calendar_days': len(calendar), 'open_days': len(opens),
        'endpoint_pairs_checked': len(endpoint_checks), 'distinct_required_contract_dates': len(needed),
        'positive_volume_pairs': len(endpoint_checks)-len(zero_endpoints), 'zero_volume_endpoint_pairs': zero_endpoints,
        'initial_unready_dates': [str(date.date()) for date in opens[:2]],
        'first_potentially_usable_decision': str(opens[2].date()), 'last_decision': str(opens[-1].date()),
        'reuse_pass': True, 'reopen_without_provider_pass': True,
        'new_models': 0, 'new_accounts': 0, 'fees_execution_annual_targets': 'UNCHANGED',
        'historical_publication_verified': False, 'historical_revision_history_verified': False,
        'script_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'endpoint_checks_sha256': sha256((OUT/'endpoint_checks.json').read_bytes()).hexdigest(),
    })
    print(json.dumps({k: read(OUT/'acceptance.json')[k] for k in ['status', 'actual_calls', 'failed_calls',
        'controlled_retries', 'new_rows', 'all_contracts_prepared', 'all_raw_rows_prepared',
        'endpoint_pairs_checked', 'positive_volume_pairs', 'unused_slots']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
