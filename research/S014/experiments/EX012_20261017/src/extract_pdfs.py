"""Extract original disclosure pages with bundled pypdf, preserving page IDs."""
from hashlib import sha256
import json
from pathlib import Path
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[5]
EXPERIMENT=Path(__file__).resolve().parents[1]
OUT=ROOT/'research/S014/assets/runs/EX012_20261017/texts'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    requests=json.loads((EXPERIMENT/'others/cninfo_requests.json').read_text(encoding='utf-8'))
    records=[]
    for item in requests['downloads']:
        if item['status']!='PDF_RECEIVED':continue
        source=ROOT/item['path'];assert sha256(source.read_bytes()).hexdigest()==item['sha256']
        pdf=PdfReader(source)
        pages=[{'page':i+1,'text':p.extract_text() or ''} for i,p in enumerate(pdf.pages)]
        path=OUT/(item['doc_id']+'.json')
        path.write_text(json.dumps({'doc_id':item['doc_id'],'pdf_sha256':item['sha256'],'pages':pages},ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        records.append({'doc_id':item['doc_id'],'pages':len(pages),'characters':sum(len(p['text']) for p in pages),
            'path':path.relative_to(ROOT).as_posix(),'sha256':sha256(path.read_bytes()).hexdigest()})
    (EXPERIMENT/'others/extraction.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps([{k:r[k] for k in ('doc_id','pages','characters')} for r in records]))


if __name__=='__main__':main()
