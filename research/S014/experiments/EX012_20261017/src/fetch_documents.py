"""Fetch only selected official original PDFs; keep failures explicit."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[5]
EXPERIMENT=Path(__file__).resolve().parents[1]
RAW=ROOT/'research/S014/assets/runs/EX012_20261017/originals'


def main():
    target=EXPERIMENT/'others/document_requests.json'
    if target.exists():
        raise RuntimeError('No implicit repeat')
    selected=json.loads((EXPERIMENT/'protocols/document_selection.json').read_text(encoding='utf-8'))
    rows=[]
    try:
        for document in selected['documents']:
            if not document['selected_for_body']:
                continue
            receipt={'doc_id':document['doc_id'],'url':document['url'],
                'retrieved_at_utc':datetime.now(timezone.utc).isoformat()}
            rows.append(receipt)
            try:
                response=requests.get(document['url'],headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.sse.com.cn/'},timeout=35)
                receipt.update(http_status=response.status_code,bytes=len(response.content))
                if response.status_code==200 and response.content.startswith(b'%PDF'):
                    path=RAW/(document['doc_id']+'.pdf');path.write_bytes(response.content)
                    receipt.update(status='PDF_RECEIVED',path=path.relative_to(ROOT).as_posix(),sha256=sha256(response.content).hexdigest())
                else:
                    receipt['status']='NOT_PDF_OR_HTTP_FAILURE'
            except requests.RequestException as error:
                receipt.update(status='TRANSPORT_FAILURE',error_type=type(error).__name__)
    finally:
        target.write_text(json.dumps({'source_calls_tushare':0,'requests':rows},ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'attempts':len(rows),'pdf_received':sum(r['status']=='PDF_RECEIVED' for r in rows),
        'failures':[r for r in rows if r['status']!='PDF_RECEIVED']},ensure_ascii=False))


if __name__=='__main__':
    main()
