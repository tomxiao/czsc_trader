"""Freeze statistical method and static-review resolution before accounts."""
from hashlib import sha256
from pathlib import Path
import sys
WORK=Path(__file__).resolve().parent
sys.path.insert(0,str(WORK))
from run_compare import OUT, read, write, cache_read, ctx, material
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
method=read(WORK/'method.json')
source=(WORK/'assessment_helper.py').read_bytes()
assert sha256(source).hexdigest()==read(WORK/'focused.json')['source_sha256']
assert not (WORK/'S013-center.pkl.gz').exists() and not (WORK/'S003-center.pkl.gz').exists()
references={}
for family,experiment,*_ in cache_read(WORK/'prepared.pkl.gz'):
    context=ctx(family)
    refs={'statistical_method':material(context,experiment,'prospective-statistical-method',method).to_dict(),
        'cache_binding_resolution':material(context,experiment,'static-review-resolution',read(WORK/'driver_review_resolution.json')).to_dict()}
    refs['statistical_helper_source']=publish_evidence(context,MaterialEvidenceWrite(experiment,
        'statistical-helper-source',source,'text/x-python','py')).to_dict()
    references[family]=refs
write(OUT/'method_references.json',references)
write(OUT/'statistical_method.json',method)
print('METHOD_FIXED_BEFORE_ANY_ACCOUNT',flush=True)
