"""Focused source, temporal, sample and immutable-evidence verification."""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from analyze import calculate

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]


def main():
    target=EX/'others/audit.json'
    if target.exists():raise RuntimeError('Preserve audit receipt')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    checks=[]
    def check(name,condition):
        assert condition,name
        checks.append({'name':name,'status':'PASS'})
    annotation=read(EX/'protocols/annotations.json')
    docs=annotation['documents']; by_id={d['doc_id']:d for d in docs}
    cn=read(EX/'others/cninfo_requests.json')
    sse=read(EX/'others/catalogue_requests.json')
    extraction=read(EX/'others/extraction.json')
    analysis=read(EX/'others/analysis.json')
    check('62 unique documents, 32 reviewed, 30 explicitly unknown',len(by_id)==62 and sum(d['body_review']=='KEY_PAGES' for d in docs)==32 and sum(d['category']=='UNKNOWN' for d in docs)==30)
    check('5 complete CNInfo pages',len(cn['catalogue_requests'])==5 and all(r['rows']==r['total'] and not r['has_more'] for r in cn['catalogue_requests']))
    check('62 unique title/date matches',len(cn['matches'])==62 and all(m['unique'] and len(m['matches'])==1 and m['matches'][0]['title']==by_id[m['doc_id']]['title'] and m['matches'][0]['date']==by_id[m['doc_id']]['date'] for m in cn['matches']))
    raw_files={}
    for r in cn['catalogue_requests']:
        p=ROOT/r['raw_path'];raw_files[p]=r['sha256'];raw=read(p)
        check('CNInfo raw identity '+r['params']['seDate'],len(raw['announcements'])==raw['totalAnnouncement']==r['rows'] and all(x['secCode']=='600722' and x['orgId']=='gssh0600722' for x in raw['announcements']))
    selection=read(EX/'protocols/document_selection.json')
    for r in selection['checks']:
        p=ROOT/r['raw_path'];raw_files[p]=r['sha256'];raw=read(p)
        check('SSE complete original page '+r['start'],raw['productId']=='600722' and len(raw['result'])==r['total']==r['rows'] and r['page_count']==1)
    for r in cn['downloads']:
        p=ROOT/r['path'];raw_files[p]=r['sha256']
        assert p.read_bytes().startswith(b'%PDF-') and r['status']=='PDF_RECEIVED'
    check('32 original PDF identities',len(cn['downloads'])==32 and {x['doc_id'] for x in cn['downloads']}=={d['doc_id'] for d in docs if d['selected_for_body']})
    pdf_hash={x['doc_id']:x['sha256'] for x in cn['downloads']}
    for r in extraction:
        p=ROOT/r['path'];raw_files[p]=r['sha256'];raw=read(p)
        assert raw['pdf_sha256']==pdf_hash[r['doc_id']] and len(raw['pages'])==r['pages']
        assert all(1<=page<=r['pages'] for page in by_id[r['doc_id']]['examined_pages'])
    check('32 text/PDF relationships and examined page bounds',len(extraction)==32)
    check('all 74 original/text checksums',len(raw_files)==74 and all(sha256(p.read_bytes()).hexdigest()==h for p,h in raw_files.items()))
    for name in ('published_design','published_sample','published_documents','published_annotations'):
        for ref_dict in read(EX/f'protocols/{name}.json').values():
            ref=EvidenceRef.from_dict(ref_dict)
            assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest()==ref.sha256
    check('all prepublished evidence identities',True)
    check('annotation lock precedes first unmask',datetime.fromisoformat(read(EX/'protocols/annotation_lock.json')['locked_at_utc'])<datetime.fromisoformat(analysis['unmasked_at_utc']))
    sealed=read(EX/'others/sealed_outcomes.json');ref=EvidenceRef.from_dict(sealed['source']);p=ref.resolve(ROOT)
    check('original EX010 source identity',sha256(p.read_bytes()).hexdigest()==ref.sha256)
    frame=pd.read_csv(p);rows=frame.loc[frame.horizon.eq(1)&frame.status.eq('CLOSED')].copy();rows['date']=pd.to_datetime(rows.signal_date)
    for c in sealed['cases']:
        anchor=pd.Timestamp(c['anchor']);pool=rows.loc[rows.year.eq(anchor.year)].copy()
        pool['distance']=(pool.date-anchor).abs().dt.days
        pool=pool.loc[pool.distance.le(30)].sort_values(['distance','date'])
        mask=pool.gap_down_repair.eq(0) if c['group']=='ordinary' else pool.gap_down_repair.eq(1)&(pool.net_return.gt(0) if c['group']=='repair_positive' else pool.net_return.le(0))
        r=pool.loc[mask].iloc[0]
        assert int(r.signal)==c['signal']
        for k in ('net_return','prediction_ridge_stock','prediction_ridge_market','gap','intraday','ret5','ret20','range','volume_ratio'):
            assert float(r[k])==c[k],(c['case_id'],k)
    check('15 nearest fixed-anchor samples and original numeric labels',len(sealed['cases'])==15 and not sealed['missing_groups'])
    for c in annotation['cases']:
        assert all(c['lookback_start']<=by_id[d]['date']<c['signal_date'] for d in c['date_before_t'])
        assert all(by_id[d]['date']==c['signal_date'] for d in c['same_day_time_unknown'])
        assert all(c['signal_date']<by_id[d]['date']<=c['exit_date'] for d in c['post_decision'])
        assert set(c['usable_reviewed']).isdisjoint(c['same_day_time_unknown']+c['post_decision'])
        assert c['last_observed_report'] is None or by_id[c['last_observed_report']]['date']<c['signal_date']
    check('all case timing and carry-forward exclusions',True)
    computed=calculate()
    check('full descriptive contrast reproducibility',all(analysis[k]==v for k,v in computed.items()))
    check('Tushare budget unchanged',cn['source_calls_tushare']==sse['source_calls_tushare']==read(EX/'others/document_requests.json')['source_calls_tushare']==0)
    check('SSE HTML failures not recorded as PDFs',len(read(EX/'others/document_requests.json')['requests'])==32 and all(x['status']=='NOT_PDF_OR_HTTP_FAILURE' for x in read(EX/'others/document_requests.json')['requests']))
    check('three shared-report pairs; five same-day cases',analysis['counts']['same_observed_report_pairs']==3 and analysis['counts']['cases_with_same_day_time_unknown']==5)
    files=set(raw_files)|{p for folder in ('protocols','src','others') for p in (EX/folder).glob('*') if p.is_file() and p.name not in ('audit.json','result.json','report_copy_verification.json')}
    manifest=[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha256(p.read_bytes()).hexdigest()} for p in sorted(files)]
    target.write_text(json.dumps({'status':'PASS','checks':checks,'manifest':manifest,'verification_scope':'离线来源/语义边界/计算，不是历史真实分钟、全部正文、公告Alpha或账户验收'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'status':'PASS','checks':len(checks),'files':len(manifest)}))


if __name__=='__main__':main()
