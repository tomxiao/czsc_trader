"""Cross-match locked SSE records with official CNInfo originals."""
from datetime import datetime,timezone,timedelta
from hashlib import sha256
import json,re
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[5]
EXPERIMENT=Path(__file__).resolve().parents[1]
RAW=ROOT/'research/S014/assets/runs/EX012_20261017/originals'


def main():
    target=EXPERIMENT/'others/cninfo_requests.json'
    if target.exists():
        raise RuntimeError('Preserve official requests')
    selection=json.loads((EXPERIMENT/'protocols/document_selection.json').read_text(encoding='utf-8'))
    ranges=json.loads((EXPERIMENT/'others/catalogue_requests.json').read_text(encoding='utf-8'))['merged_ranges']
    url='https://www.cninfo.com.cn/new/hisAnnouncement/query'
    headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.cninfo.com.cn/new/disclosure/stock?stockCode=600722&orgId=gssh0600722',
        'Accept':'application/json, text/javascript, */*; q=0.01','X-Requested-With':'XMLHttpRequest'}
    receipts=[];catalogue=[];matches=[];downloads=[]
    try:
        for i,(start,end) in enumerate(ranges):
            params={'pageNum':1,'pageSize':100,'column':'sse','tabName':'fulltext','stock':'600722,gssh0600722',
                'searchkey':'','secid':'','plate':'sh','category':'','trade':'','seDate':start+'~'+end,
                'sortName':'time','sortType':'asc','isHLtitle':'true'}
            receipt={'url':url,'params':params,'retrieved_at_utc':datetime.now(timezone.utc).isoformat()}
            receipts.append(receipt)
            if start=='2025-04-07':
                path=RAW/'cninfo_probe.json';receipt.update(reused_probe=True,http_status=200)
            else:
                response=requests.post(url,data=params,headers=headers,timeout=30)
                path=RAW/f'cninfo_catalogue_{i+1}.json';path.write_bytes(response.content)
                receipt.update(reused_probe=False,http_status=response.status_code)
                response.raise_for_status()
            body=json.loads(path.read_text(encoding='utf-8'))
            rows=body.get('announcements') or []
            receipt.update(raw_path=path.relative_to(ROOT).as_posix(),rows=len(rows),total=body['totalAnnouncement'],
                has_more=body.get('hasMore'),sha256=sha256(path.read_bytes()).hexdigest())
            assert len(rows)==body['totalAnnouncement'] and not body.get('hasMore')
            for r in rows:
                assert r['secCode']=='600722' and r['orgId']=='gssh0600722'
                date=datetime.fromtimestamp(r['announcementTime']/1000,timezone(timedelta(hours=8))).strftime('%Y-%m-%d')
                assert start<=date<=end
                catalogue.append({'title':r['announcementTitle'].strip(),'date':date,'epoch_ms':r['announcementTime'],
                    'org_id':r['orgId'],'announcement_id':r['announcementId'],'url':'https://static.cninfo.com.cn/'+r['adjunctUrl']})
        normalize=lambda s:re.sub(r'\s+','',s)
        for document in selection['documents']:
            found=[r for r in catalogue if normalize(r['title'])==normalize(document['title']) and r['date']==document['date']]
            match={'doc_id':document['doc_id'],'matches':found,'unique':len(found)==1,'selected_for_body':document['selected_for_body']}
            matches.append(match)
            if not document['selected_for_body'] or len(found)!=1:
                continue
            record={'doc_id':document['doc_id'],'url':found[0]['url'],'retrieved_at_utc':datetime.now(timezone.utc).isoformat()}
            downloads.append(record)
            try:
                response=requests.get(record['url'],headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.cninfo.com.cn/'},timeout=30)
                record.update(http_status=response.status_code,bytes=len(response.content))
                if response.status_code==200 and response.content.startswith(b'%PDF'):
                    path=RAW/(document['doc_id']+'.pdf');path.write_bytes(response.content)
                    record.update(status='PDF_RECEIVED',path=path.relative_to(ROOT).as_posix(),sha256=sha256(response.content).hexdigest())
                else:
                    record['status']='NOT_PDF_OR_HTTP_FAILURE'
            except requests.RequestException as error:
                record.update(status='TRANSPORT_FAILURE',error_type=type(error).__name__)
    finally:
        target.write_text(json.dumps({'source_calls_tushare':0,'catalogue_requests':receipts,'catalogue':catalogue,
            'matches':matches,'downloads':downloads},ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'catalogue_rows':len(catalogue),'matched':sum(m['unique'] for m in matches),'downloaded':sum(r.get('status')=='PDF_RECEIVED' for r in downloads),
        'unmatched':[m for m in matches if not m['unique']],'failed':[r for r in downloads if r.get('status')!='PDF_RECEIVED']},ensure_ascii=False))


if __name__=='__main__':
    main()
