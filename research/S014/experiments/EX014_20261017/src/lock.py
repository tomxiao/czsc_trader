"""Publish preregistered design/source bytes before computation."""
import json
from pathlib import Path
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,MaterialEvidenceWrite
ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]
def main():
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'))
    exp=ExperimentRef('S014',EX.name); refs={}
    target=EX/'protocols/published_design.json'
    if target.exists():raise RuntimeError('Preserve published design')
    for p in [EX/'protocols/design.json',EX/'src/study.py',Path(__file__)]:
        name=p.stem+'-'+p.suffix[1:]
        ref=publish_evidence(ctx,MaterialEvidenceWrite(exp,name,p.read_bytes(),'application/json' if p.suffix=='.json' else 'text/x-python',p.suffix[1:]))
        refs[name]=ref.to_dict()
    target.write_text(json.dumps(refs,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('LOCKED',list(refs))
if __name__=='__main__':main()
