"""Catalogue normalization and bounded document selection, labels unopened."""
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[5]
EXPERIMENT=Path(__file__).resolve().parents[1]


def main():
    raw=json.loads((EXPERIMENT/'others/catalogue_requests.json').read_text(encoding='utf-8'))
    documents=[];checks=[]
    for request in raw['requests']:
        body=json.loads((ROOT/request['raw_path']).read_text(encoding='utf-8'))
        rows=body['pageHelp']['data'];start=request['params']['beginDate'];end=request['params']['endDate']
        assert len(rows)==request['total'] and request['page_count']==1
        assert all(r['SECURITY_CODE']=='600722' and start<=r['SSEDATE']<=end for r in rows)
        checks.append({'start':start,'end':end,'rows':len(rows),'total':request['total'],'page_count':1,
            'raw_path':request['raw_path'],'sha256':sha256((ROOT/request['raw_path']).read_bytes()).hexdigest()})
        for r in rows:
            title=r['TITLE'].strip()
            full_report=(r['BULLETIN_TYPE'] in ('年报','半年报'))
            peripheral=bool(re.search('独立董事.*(述职|声明|承诺)|提名人声明|候选人声明|独立性的核查|履职|工作细则|议事规则|独立董事制度|公司章程$|对外捐赠管理办法|环境、社会|内部控制评价|股东大会资料|审计报告|非经营性资金占用',title))
            selected=not(full_report or peripheral)
            documents.append({'title':title,'date':r['SSEDATE'],'adddate_unverified':r.get('ADDDATE'),
                'url':'https://www.sse.com.cn'+r['URL'],'catalogue_type':r['BULLETIN_TYPE'],
                'selected_for_body':selected,'selection_reason': 'Substantive/summary/board/other announcement'
                    if selected else 'Full report paired with summary' if full_report else 'Peripheral title; body unreviewed, not presumed immaterial',
                'raw_source':request['raw_path']})
    documents=sorted(documents,key=lambda r:(r['date'],r['url']))
    assert len({r['url'] for r in documents})==len(documents)
    for i,r in enumerate(documents):
        r['doc_id']=f'D{i+1:02d}'
    assert sum(r['selected_for_body'] for r in documents)<=40
    result={'catalogue_rows':len(documents),'selected_pdf_count':sum(r['selected_for_body'] for r in documents),
        'coverage':'Returned SSE totals reconciled only for requested windows; no historical-version completeness guarantee.',
        'selection_timing':'After viewing catalogue titles, before bodies or unblinding outcomes; prioritizes substantive and summary disclosures within40PDFcap.',
        'checks':checks,'documents':documents}
    (EXPERIMENT/'protocols/document_selection.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'rows':len(documents),'selected':result['selected_pdf_count'],
        'documents':[{k:r[k] for k in ('doc_id','date','title','selected_for_body')} for r in documents]},ensure_ascii=False))


if __name__=='__main__':
    main()
