"""Preserve the complete2020-25 disclosure title universe without return comparisons."""
import csv
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TMP = ROOT / '.tmp/s014-year-drivers'
BASE = ROOT / 'research/S014/materials/20261019_year_driver_research/official'
EX = ROOT / 'research/S014/experiments/EX037_20261019'
BASE.mkdir(parents=True, exist_ok=True)


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path):
    return path.relative_to(ROOT).as_posix()


def save(path, data):
    assert not path.exists(), 'Preserve prior snapshot: ' + str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


copies = []


def copy(old, new):
    assert not new.exists()
    new.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(old, new)
    assert sha(old) == sha(new)
    copies.append({'from': rel(old), 'to': rel(new), 'sha256': sha(new)})


result = load(EX / 'others/result.json')
audit_path = EX / 'others/catalogue_audit_v3.json'
audit = load(audit_path)
assert sha(audit_path) == result['evidence'][rel(audit_path)]['sha256']
leaves = [leaf for leaf in audit['leaf_scopes'] if '2020-01-01' <= leaf['start'] <= '2025-12-31']
assert len(leaves) == 30 and all(leaf['complete'] for leaf in leaves)
query_by_name = {q['name']: q for q in audit['queries']}
requests = {}
for path in (EX / 'others/official/requests/catalogue').glob('*.request.json'):
    data = load(path)
    requests[data['name']] = (path, data)
proofs, entries = [], {}
for leaf in leaves:
    name = leaf['name']
    query = query_by_name[name]
    raw = ROOT / query['raw_path']
    ref = result['evidence'][rel(raw)]
    assert sha(raw) == ref['sha256'] == query['sha256']
    body = load(raw)
    records = body.get('announcements') or []
    assert not body['hasMore']
    assert body['totalAnnouncement'] == len(records) == leaf['rows'] == leaf['total']
    assert len({r['announcementId'] for r in records}) == len(records)
    request_path, request = requests[name]
    assert request['params']['category'] == request['params']['searchkey'] == ''
    assert request['params']['stock'] == '600722,gssh0600722'
    assert request['params']['seDate'] == leaf['start'] + '~' + leaf['end']
    request_ref = result['evidence'][rel(request_path)]
    assert sha(request_path) == request_ref['sha256']
    copy(raw, BASE / 'catalogues' / raw.name)
    copy(request_path, BASE / 'queries' / request_path.name)
    proof = {'name': name, 'start': leaf['start'], 'end': leaf['end'],
             'complete_within_current_source': True, 'rows': len(records),
             'total': body['totalAnnouncement'], 'has_more': body['hasMore'],
             'raw_original_path': rel(raw), 'raw_preserved_path': rel(BASE/'catalogues'/raw.name),
             'original_evidence_ref': ref, 'request_path': rel(BASE/'queries'/request_path.name),
             'request_original_evidence_ref': request_ref,
             'query_params': request['params']}
    proofs.append(proof)
    for record in records:
        assert record['secCode'] == '600722'
        doc, date = record['announcementId'], record['adjunctUrl'].split('/')[1]
        assert leaf['start'] <= date <= leaf['end']
        assert doc not in entries
        entries[doc] = {'doc_id': doc, 'title': record['announcementTitle'],
                        'publication_date': date,
                        'url': 'https://static.cninfo.com.cn/' + record['adjunctUrl'],
                        'leaf_proof_name': name, 'catalogue_evidence_ref': ref}

# Preserve original new-source request/PDF/text bytes; no further network requests.
for path in sorted((TMP/'official_pdfs').iterdir()):
    if path.suffix == '.pdf':
        dest = BASE / 'pdfs' / path.name
    elif path.name.endswith('.texts.json'):
        dest = BASE / 'texts' / path.name
    else:
        dest = BASE / 'retrieval_receipts' / path.name
    copy(path, dest)

original_facts = load(TMP/'official_driver_facts.json')
facts = json.loads(json.dumps(original_facts))


def rewrite_source(source):
    for key in ['pdf_path', 'text_path']:
        if source.get(key, '').startswith('.tmp/s014-year-drivers/official_pdfs/'):
            old = ROOT / source[key]
            new = BASE / ('pdfs' if key == 'pdf_path' else 'texts') / old.name
            source['original_' + key] = source[key]
            source[key] = rel(new)
            expected = source['sha256' if key == 'pdf_path' else 'text_sha256']
            assert sha(new) == expected


for source in facts['fact_sources'].values():
    rewrite_source(source)
    source.setdefault('title', next((r['title'] for r in audit['all_issuer_records']
                                     if r['doc_id'] == source['doc_id']), 'UNKNOWN_TITLE'))
for event in facts['risk_event_inventory']:
    rewrite_source(event['source'])
facts['catalogue']['evaluation_subset_2020_2025_complete'] = True
facts['catalogue']['risk_flag_effect_eligible'] = 'SOURCE_COMPLETENESS_ONLY_FOR2020_2025; any effect analysis requires root prelocked design'
facts['next_step'] = 'Source-only inventory complete2020-2025,2026 remains incomplete. Root may lock its one announced-disclosure-state contrast; this pack does not compute flags or outcomes.'
save(BASE/'official_driver_facts.json', facts)
copy(TMP/'official_driver_facts.json', BASE/'official_driver_facts.original.json')

events = []
for record in sorted(entries.values(), key=lambda x: (x['publication_date'], x['doc_id'])):
    title = record['title']
    if '\u80a1\u7968\u4ea4\u6613' not in title:
        continue
    if not ('\u5f02\u5e38\u6ce2\u52a8' in title or '\u98ce\u9669\u63d0\u793a' in title):
        continue
    if '\u56de\u590d' in title:
        continue
    prior = next(x for x in facts['risk_event_inventory'] if x['doc_id'] == record['doc_id'])
    record['availability'] = prior['availability']
    record['original_body'] = prior['source']
    record['event_semantics'] = 'Disclosure of abnormal trading or trading-risk warning; not uniformly negative news; no alpha or reversal claim'
    events.append(record)
assert len(events) == 14
counts = {str(year): sum(r['publication_date'][:4] == str(year) for r in events)
          for year in range(2020, 2026)}
assert counts == {'2020': 0, '2021': 8, '2022': 1, '2023': 0, '2024': 2, '2025': 3}
save(BASE/'events_2020_2025.json', {'status': 'SOURCE_INVENTORY_COMPLETE_WITHIN_CURRENT_OFFICIAL_SOURCE',
                                  'period': ['2020-01-01', '2025-12-31'],
                                  'selection_rule': 'issuer title contains stock-trading and abnormal-fluctuation or risk-warning; exclude inquiry replies; deduplicate official ID; no return selection',
                                  'by_year_counts': counts, 'events': events,
                                  '2026_included_in_effect_population': False,
                                  'not_independent_shocks': 'Adjacent documents may describe the same multi-session episode',
                                  'new_effect_flags_or_returns_computed': False})
with (BASE/'events_2020_2025.csv').open('x', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['doc_id', 'title', 'publication_date', 'decision_date_15_00',
                                         'earliest_execution_date', 'url', 'leaf_proof_name', 'pdf_sha256'])
    writer.writeheader()
    for r in events:
        writer.writerow({k: r[k] for k in ['doc_id','title','publication_date','url','leaf_proof_name']} |
                        {k: r['availability'][k] for k in ['decision_date_15_00','earliest_execution_date']} |
                        {'pdf_sha256': r['original_body']['sha256']})
save(BASE/'catalogue_coverage.json', {'status': 'COMPLETE_CURRENT_SOURCE_2020_2025_PARTIAL_2026',
                                    'original_audit_path': rel(audit_path),
                                    'original_audit_evidence_ref': result['evidence'][rel(audit_path)],
                                    'complete_2020_2025_leaf_count': len(leaves),
                                    'issuer_records_in_complete_2020_2025_leaves': len(entries),
                                    'all_query_categories_and_keywords_empty': True,
                                    'scope_is_all_issuer_announcement_classes': True,
                                    'leaf_proofs': proofs,
                                    '2026_known_gap': {'start': '2026-04-01', 'end': '2026-04-23',
                                                       'returned': 30, 'expected': 35,
                                                       'cannot_infer_missing_titles_or_dates': True},
                                    'limit': 'Completeness is within current source date-query contents. No certification of historical replacement/deletion/first timestamp or vendor arrival. Title absence is not absence of market risk.'})
copy(Path(__file__), BASE/'preserve_official_inventory.py')
manifest_files = [p for p in BASE.rglob('*') if p.is_file()]
save(BASE/'source_manifest.json', {'status': 'PASS', 'copied_original_bytes': copies,
                                  'files': [{'path': rel(p), 'sha256': sha(p)} for p in sorted(manifest_files)],
                                  'original_preserved': True, 'new_network_requests_during_preservation': 0,
                                  'new_returns_or_effect_flags': 0})
print(json.dumps({'status': 'PASS', 'events': len(events), 'counts': counts,
                  'leaves': len(leaves), 'issuer_records': len(entries),
                  'files': len(manifest_files)+1, 'path': rel(BASE),
                  'events_sha256': sha(BASE/'events_2020_2025.json')}))
