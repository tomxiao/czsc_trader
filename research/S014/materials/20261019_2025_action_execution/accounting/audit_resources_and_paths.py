"""Reconcile dispatched resources (including missing receipts) and common CSV paths."""
from collections import Counter
import csv
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT=Path.cwd()
OUT=Path(__file__).resolve().parent

def read(path):
    return json.loads(path.read_bytes())

def main():
    records=[]
    provenance={}
    for ex in ['EX040_20261019','EX041_20261019','EX042_20261019']:
        base=ROOT/'research/S014/experiments'/ex
        ref=EvidenceRef.from_dict(read(base/'others/accounts_index_ref.json'))
        raw=ref.resolve(ROOT).read_bytes()
        assert sha256(raw).hexdigest()==ref.sha256
        assert raw==(base/'others/accounts_index.json').read_bytes()
        index=json.loads(raw)
        rows={r['index']:r for r in index['records']}
        assert len(rows)==len(index['records'])
        dispatched={read(p)['index']:p for p in (base/'others/dispatches').glob('*.json')}
        assert set(rows).issubset(dispatched),'index contains undispatched record'
        for i in sorted(dispatched):
            row=rows.get(i)
            if row is None:
                row={'index':i,'status':'UNKNOWN_MISSING_RECEIPT','mode':read(dispatched[i]).get('mode'),'evidence':None}
            else:
                assert row==read(base/f'others/accounts/run-{i:03d}.json')
            if row['status']=='SUCCEEDED':
                assert row['evidence'] is not None and row['result_hash'] is not None
                evidence=EvidenceRef.from_dict(row['evidence'])
                saved=evidence.resolve(ROOT).read_bytes()
                assert sha256(saved).hexdigest()==evidence.sha256 and json.loads(saved)['result_hash']==row['result_hash']
            records.append({'experiment':ex,'index':i,'mode':row['mode'],'status':row['status'],'candidate':row.get('candidate'),
                            'result_hash':row.get('result_hash'),'source_sha256':row.get('published_source_ref',{}).get('sha256'),
                            'payload_sha256':row.get('payload_sha256'),'runtime_sha256':row.get('runtime_sha256'),
                            'dispatch_path':str(dispatched[i].relative_to(ROOT)), 'dispatch_sha256':sha256(dispatched[i].read_bytes()).hexdigest(),
                            'failure_error':row.get('error')})
        provenance[ex]={'index_ref':ref.to_dict(),'dispatched_files':len(dispatched),'receipt_records':len(rows)}
    paths=['daily_2025_equity.csv','daily_2025_early_cycle_equity.csv','daily_2025_joint_equity.csv']
    tables={}
    for path in paths:
        with (OUT/path).open(encoding='utf-8',newline='') as stream:
            rows=list(csv.DictReader(stream))
        assert len(rows)==243 and len({r['date'] for r in rows})==243
        assert all(Decimal(r['ORIGINAL_R'])==Decimal(r['NOOP']) for r in rows)
        tables[path]=rows
    base=tables[paths[0]]
    for name,rows in tables.items():
        assert [r['date'] for r in rows]==[r['date'] for r in base]
        assert all(Decimal(r['ORIGINAL_R'])==Decimal(b['ORIGINAL_R']) and Decimal(r['NOOP'])==Decimal(b['NOOP']) for r,b in zip(rows,base,strict=True)),name
    statuses=dict(Counter(row['status'] for row in records))
    assert len(records)==8 and statuses=={'FAILED':1,'SUCCEEDED':7}
    build=ROOT/'research/S014/experiments/EX040_20261019/others/build_failure_v2_package_name.json'
    erratum=ROOT/'research/S014/experiments/EX040_20261019/others/manifest_alias_erratum_ref.json'
    alias=EvidenceRef.from_dict(read(erratum))
    assert sha256(alias.resolve(ROOT).read_bytes()).hexdigest()==alias.sha256
    result={'status':'PASS_DISPATCH_RESOURCES_AND_THREE_WAVE_CSV_COMMON_PATHS','dispatched_total_including_FAILED_UNKNOWN':len(records),
            'status_counts':statuses,'records':records,'index_provenance':provenance,
            'technical_build_failure_not_account_dispatch':{'path':str(build.relative_to(ROOT)),'sha256':sha256(build.read_bytes()).hexdigest(),'account_dispatched':False},
            'EX040_alias_erratum':alias.to_dict(),'csv_rows_each':243,'all_original_R_and_NOOP_values_exact_across_three_waves':True,
            'csv_sha256':{name:sha256((OUT/name).read_bytes()).hexdigest() for name in paths},
            'original_2025_opening_equity':278758.90799999965,'first_daily_close_not_used_as_opening':True,
            'new_dispatches_by_auditor':0,'new_market_data_calls':0,'new_fits':0,'source_sha256':sha256(Path(__file__).read_bytes()).hexdigest()}
    with (OUT/'resource_and_path_review.json').open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    print(json.dumps({'status':result['status'],'dispatched':len(records),'statuses':statuses,'review_sha256':sha256((OUT/'resource_and_path_review.json').read_bytes()).hexdigest()}))

if __name__=='__main__':
    main()
