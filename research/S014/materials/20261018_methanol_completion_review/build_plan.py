"""Derive a bounded acquisition proposal from existing evidence; no network."""
from hashlib import sha256
import json
from pathlib import Path
import socket

import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
PRIOR = ROOT / 'research/S014/materials/20261018_methanol_feasibility'


def main():
    def no_network(*args, **kwargs):
        raise AssertionError('Planning must not access the network')
    socket.socket.connect = no_network
    socket.create_connection = no_network
    target = OUT / 'request_plan.json'
    assert not target.exists(), 'Preserve published planning results'
    publication = json.loads((PRIOR / 'publication.json').read_text(encoding='utf-8'))
    sources = []

    def frame(number):
        relative = f'responses/call_{number:02d}.json'
        path = PRIOR / relative
        data = path.read_bytes()
        assert sha256(data).hexdigest() == publication['evidence'][relative]['sha256']
        sources.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(data).hexdigest()})
        obj = json.loads(data)
        return pd.DataFrame(obj['items'], columns=obj['fields'])

    directory = frame(1).set_index('ts_code')
    mapping = frame(2).sort_values('trade_date')
    calendar = frame(4)
    opens = sorted(calendar.loc[calendar.is_open.eq(1), 'cal_date'])
    assert len(opens) == len(set(opens)) == 1642
    assert mapping.trade_date.tolist() == opens
    known = {}
    for number in [5, 6, 7, 8]:
        raw = frame(number)
        assert raw.ts_code.nunique() == 1 and not raw.trade_date.duplicated().any()
        known[raw.ts_code.iloc[0]] = set(raw.trade_date)
    selected = mapping.loc[mapping.trade_date.le(opens[-2])]
    previous = dict(zip(opens[1:], opens[:-1]))
    requests = []
    for contract, group in selected.groupby('mapping_ts_code', sort=False):
        if contract in known:
            continue
        first, last = group.trade_date.min(), group.trade_date.max()
        start = previous[first]
        dates = [day for day in opens if start <= day <= last]
        item = directory.loc[contract]
        assert item.list_date <= start <= last <= item.delist_date
        assert item.exchange == 'CZCE' and item.fut_code == 'MA'
        assert dates[1:] == group.trade_date.tolist(), 'Unexpected disjoint main-contract periods'
        assert len(dates) < 2000
        requests.append({
            'request_number': len(requests) + 1, 'api': 'fut_daily',
            'params': {'ts_code': contract, 'start_date': start, 'end_date': last},
            'fields': 'ts_code,trade_date,close,settle,vol,amount,oi',
            'first_required_main_date': first, 'last_required_main_date': last,
            'mapped_dates': len(group), 'expected_rows': len(dates), 'expected_dates': dates,
            'list_date': item.list_date, 'delist_date': item.delist_date,
            'extra_pre_main_dates': [start], 'purpose': 'Exact P/Q endpoints of the same mapped contract',
        })
    expected_remaining = json.loads((PRIOR / 'others/analysis.json').read_text(encoding='utf-8'))['raw_contract_coverage']['remaining_contracts']
    assert {r['params']['ts_code'] for r in requests} == set(expected_remaining)
    assert len(requests) == 18 and sum(r['expected_rows'] for r in requests) == 1478
    planned = {r['params']['ts_code']: set(r['expected_dates']) for r in requests}
    mapped_by_date = dict(zip(mapping.trade_date, mapping.mapping_ts_code))
    needed_keys = set()
    known_pairs = 0
    proposed_pairs = 0
    for index, decision in enumerate(opens[2:], start=2):
        p, q = opens[index - 1], opens[index - 2]
        contract = mapped_by_date[p]
        available = known.get(contract, planned.get(contract))
        assert p in available and q in available, (decision, contract, p, q)
        needed_keys.update([(contract, p), (contract, q)])
        known_pairs += int(contract in known)
        proposed_pairs += int(contract in planned)
    assert known_pairs + proposed_pairs == 1640
    plan = {
        'status': 'PROPOSED_NOT_AUTHORIZED_FOR_ACQUISITION',
        'research_window': ['2020-01-01', '2026-10-15'],
        'decision_count': 1642, 'initial_feature_unready_dates': opens[:2],
        'first_potentially_usable_decision': opens[2], 'last_decision': opens[-1],
        'last_needed_source_date': opens[-2],
        'required_endpoint_keys': len(needed_keys),
        'existing_contracts': sorted(known), 'new_contracts': 18,
        'existing_endpoint_pairs': known_pairs, 'proposed_endpoint_pairs': proposed_pairs,
        'conditional_complete_pairs': 1640,
        'coverage_is_structural_only': 'Actual returned rows, trading volume, price quality and temporal rules must still pass; no signal efficacy claim',
        'expected_calls': 18, 'proposed_call_cap': 20, 'controlled_retry_slots': 2,
        'max_retries_per_contract': 1, 'automatic_retries': False, 'automatic_redirects': False,
        'retry_scope': 'Identical request only after transient transport failure, HTTP 429/5xx, or explicit temporary rate limit; never permission/data-quality failures',
        'stop_conditions': ['cap exhausted', 'permission denied', 'two consecutive equivalent transport/service failures',
                            'scope or pagination needed', 'source identity/coverage/quality discrepancy'],
        'counting': 'Reserve and persist one slot immediately before each HTTP dispatch attempt; transport, timeout, interruption, non-JSON, vendor errors, empty/truncated/invalid data all count. Never reclaim an uncertain reserved slot.',
        'zero_cost_local_actions': ['planning', 'hash verification', 'offline DFLS prepare/fetch', 'pre-dispatch local validation failure without reserved HTTP attempt'],
        'no_additional_requests': ['fut_basic', 'fut_mapping', 'trade_cal', 'continuous futures prices', 'existing four contract prices', '2019 warmup', 'post-window data'],
        'actual_new_calls': 0, 'actual_new_models': 0, 'actual_new_accounts': 0,
        'prior_methanol_calls_used': 8, 'currently_authorized_remaining_calls': 0,
        'proposed_max_cumulative_methanol_calls': 28,
        'requests': requests,
        'source_manifest': sources,
        'build_script_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    target.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: plan[k] for k in ['new_contracts', 'expected_calls', 'proposed_call_cap',
        'required_endpoint_keys', 'existing_endpoint_pairs', 'proposed_endpoint_pairs', 'conditional_complete_pairs']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
