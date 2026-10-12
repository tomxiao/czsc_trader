"""Focused pause-artifact/links/immutable-file check, no research execution."""
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
MAT=ROOT/'research/S013/materials'
def read(path):
    return json.loads(path.read_text('utf-8-sig'))
def digest(path):
    return sha256(path.read_bytes()).hexdigest()
state=read(MAT/'research_pause_20261012.json')
proof=read(MAT/'research_pause_provenance_20261012.json')
copy=read(MAT/'research_pause_report_copy_v2_20261012.json')
validation=read(MAT/'research_pause_validation_v2_20261012.json')
assert state['state']=='PAUSED' and not state['research_objective_achieved']
assert validation['status']=='PASS' and validation['scope']=='FULL'
assert state['last_authorized_quota']['remaining']==0
assert (ROOT/copy['formal']).read_bytes()==(ROOT/copy['copy']).read_bytes()
assert digest(ROOT/copy['formal'])==copy['formal_sha256']==copy['copy_sha256']
assert (ROOT/copy['formal']).stat().st_size==copy['formal_bytes']==copy['copy_bytes']
for relative,expected in proof['existing_research_files_before'].items():
    assert digest(ROOT/relative)==expected,relative
for relative,expected in proof['protected_user_document_sha256'].items():
    assert digest(ROOT/relative)==expected,relative
handoff=ROOT/'research/S013/HANDOFF.md'
new=handoff.read_text('utf-8').split('## 历史接手记录')[0]
assert '当前状态：PAUSED' in new
links=0
for text,base in ((new,handoff.parent),((ROOT/copy['copy']).read_text('utf-8'),ROOT),
                  ((MAT/'research_evidence_index_20261012.md').read_text('utf-8'),ROOT)):
    for target in re.findall(r'\]\(([^)]+)\)',text):
        target=target.split('#')[0]
        assert not Path(target).is_absolute(),target
        resolved=(base/target).resolve()
        assert resolved.is_relative_to(ROOT.resolve()) and resolved.exists(),target
        links+=1
assert not (ROOT/'research/S013/experiments/EX099_20261012').exists()
correction=read(MAT/'research_pause_navigation_correction_20261012.json')
assert digest(ROOT/correction['original_report'])==correction['original_sha256']
old_copy=read(MAT/'research_pause_report_copy_20261012.json')
assert (ROOT/old_copy['formal']).read_bytes()==(ROOT/old_copy['copy']).read_bytes()
print({'status':'PASS','pause':'PAUSED','closeout':'COMPLETE','objective_achieved':False,
    'old_files_unchanged':len(proof['existing_research_files_before']),'relative_links':links,
    'report_copy':'EXACT','protected_user_docs':'UNCHANGED','no_EX099':True})
