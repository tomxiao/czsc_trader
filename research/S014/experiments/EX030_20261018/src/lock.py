"""Publish the fixed diagnostic design and implementation before new labels."""
from hashlib import sha256
from pathlib import Path
import json
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,MaterialEvidenceWrite
ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]
def main():
    target=EX/'protocols/published_design.json'
    if target.exists():raise RuntimeError('Do not overwrite published design')
    assert not (EX/'others/analysis.json').exists()
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'));exp=ExperimentRef('S014',EX.name)
    files=[]
    for p in [EX/'protocols/design.json',EX/'src/study.py',EX/'others/precheck.json',Path(__file__)]:
        mime='application/json' if p.suffix=='.json' else 'text/x-python'
        ref=publish_evidence(ctx,MaterialEvidenceWrite(exp,'lock-'+p.stem,p.read_bytes(),mime,p.suffix[1:]))
        files.append(dict(path=p.relative_to(ROOT).as_posix(),sha256=sha256(p.read_bytes()).hexdigest(),evidence=ref.to_dict()))
    target.write_text(json.dumps(dict(status='LOCKED_BEFORE_NEW_LABELS',files=files),ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('DESIGN_PUBLISHED',len(files))
if __name__=='__main__':main()
