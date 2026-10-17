"""Bounded official SSE catalogue queries for locked case windows."""
from datetime import datetime,timezone
import json
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[5]
EXPERIMENT=Path(__file__).resolve().parents[1]
RAW=ROOT/'research/S014/assets/runs/EX012_20261017/originals'


def main():
    target=EXPERIMENT/'others/catalogue_requests.json'
    if target.exists():
        raise RuntimeError('Preserve retrieval attempts')
    cases=json.loads((EXPERIMENT/'others/blinded_cases.json').read_text(encoding='utf-8'))
    ranges=sorted((r['lookback_start'],r['exit_date']) for r in cases)
    merged=[]
    for start,end in ranges:
        if merged and start<=merged[-1][1]:
            merged[-1][1]=max(end,merged[-1][1])
        else:
            merged.append([start,end])
    assert len(merged)<=15
    RAW.mkdir(parents=True,exist_ok=True)
    receipts=[]
    try:
        for i,(start,end) in enumerate(merged):
            params={'isPagination':'true','productId':'600722','keyWord':'','securityType':'0101',
                'reportType2':'','reportType':'ALL','beginDate':start,'endDate':end,
                'pageHelp.pageSize':100,'pageHelp.pageNo':1,'pageHelp.beginPage':1,'pageHelp.endPage':1}
            receipt={'source':'SSE','url':'https://query.sse.com.cn/security/stock/queryCompanyBulletin.do',
                'params':params,'retrieved_at_utc':datetime.now(timezone.utc).isoformat()}
            receipts.append(receipt)
            try:
                response=requests.get(receipt['url'],params=params,headers={
                    'Referer':'https://www.sse.com.cn/','User-Agent':'Mozilla/5.0'},timeout=35)
                receipt.update(http_status=response.status_code,bytes=len(response.content))
                name=f'sse_catalogue_{i+1}.json'
                (RAW/name).write_bytes(response.content)
                receipt['raw_path']=(RAW/name).relative_to(ROOT).as_posix()
                if response.status_code!=200:
                    receipt['status']='HTTP_FAILED';continue
                body=response.json()
                page=body.get('pageHelp',{})
                rows=page.get('data') or body.get('result') or []
                receipt.update(status='RECEIVED',rows=len(rows),total=page.get('total'),
                    page_count=page.get('pageCount'),response_keys=list(body))
            except (requests.RequestException,ValueError) as error:
                receipt.update(status='FAILED',error_type=type(error).__name__)
    finally:
        target.write_text(json.dumps({'source_calls_tushare':0,'merged_ranges':merged,'requests':receipts},ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(receipts,ensure_ascii=False))


if __name__=='__main__':
    main()
