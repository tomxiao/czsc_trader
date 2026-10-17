"""Lock adaptive followup before observing its outcomes."""
import json
from pathlib import Path
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,MaterialEvidenceWrite
ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]
target=EX/'protocols/published_annual.json'
if target.exists():raise RuntimeError('Preserve lock')
ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'));exp=ExperimentRef('S014',EX.name);refs={}
for rel in ['protocols/annual_followup.json','src/annual_followup.py','src/lock_annual.py']:
    p=EX/rel;refs[rel]=publish_evidence(ctx,MaterialEvidenceWrite(exp,'annual-'+p.stem,p.read_bytes(),'application/json' if p.suffix=='.json' else 'text/x-python',p.suffix[1:])).to_dict()
target.write_text(json.dumps(refs,indent=2)+'\n',encoding='utf-8',newline='\n')
print('LOCKED',len(refs))
